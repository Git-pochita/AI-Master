import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent_events import (
    ALLOWED_COMPONENTS,
    build_agent_event_views,
    build_agent_events,
    event_contains_private_cot,
)
from app.planning import diagnose_v2
from app.schemas import AgentEvent, Hypothesis, HypothesisState, V1DiagnosisResult
from app.tools.check_file_status import check_file_status
from app.trace import build_execution_trace
from tests.test_v2 import F05_LOG, _final_payload, _plan, _v0_result


ISO_UTC = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z$"


def _v0_payload() -> dict:
    return {
        "summary": "LLM private prose must not leak",
        "extracted_info": {
            "job_name": "DAILY_SALES_LOAD",
            "business_date": "20260831",
            "input_path": "/data/in/sales_20260831.csv",
            "return_code": "12",
            "error_messages": ["FileNotFoundError"],
        },
        "hypotheses": [
            Hypothesis(
                cause_code="FILE_NOT_RECEIVED",
                cause_name="파일 미수신",
                evidence=["FileNotFoundError"],
            ).model_dump(),
            Hypothesis(
                cause_code="INVALID_FILE_PATH",
                cause_name="파일 경로 오류",
                evidence=["path"],
            ).model_dump(),
        ],
        "final_cause_code": "FILE_NOT_RECEIVED",
        "final_cause_name": "파일 미수신",
        "diagnosis_level": "추정",
        "owner": "BATCH_OPERATION",
        "evidence": ["FileNotFoundError"],
        "recommended_actions": ["파일 수신 확인"],
        "limitations": ["로그만 사용"],
    }


def _v1_success_payload() -> dict:
    file_result = check_file_status(path="/data/in/sales_20260831.csv")
    assert file_result.status == "SUCCESS"
    return V1DiagnosisResult(
        case_id="file_case_001",
        summary="unused-llm-prose",
        extracted_info={
            "job_name": "DAILY_SALES_LOAD",
            "business_date": "20260831",
            "input_path": "/data/in/sales_20260831.csv",
            "return_code": "12",
        },
        initial_hypotheses=[
            Hypothesis(
                cause_code="FILE_NOT_RECEIVED",
                cause_name="파일 미수신",
                evidence=["FileNotFoundError"],
            ),
            Hypothesis(
                cause_code="INVALID_BUSINESS_DATE",
                cause_name="실행일자 파라미터 오류",
                evidence=["business_date=20260831"],
            ),
        ],
        selected_tools=[
            {
                "selected_tool": "check_file_status",
                "reason": "숨기면 안 되는 CoT처럼 보이는 긴 문장",
                "arguments": {"path": "/data/in/sales_20260831.csv"},
            }
        ],
        tool_results=[file_result],
        final_cause_code="FILE_NOT_RECEIVED",
        final_cause_name="파일 미수신",
        diagnosis_level="확인됨",
        owner="BATCH_OPERATION",
        evidence=["exists=false"],
        limitations=["mock"],
        recommended_actions=[],
    ).model_dump()


def _steps(events: list[AgentEvent]) -> list[tuple[str, str]]:
    return [(item.component, item.step) for item in events]


def test_agent_event_schema_and_timestamp():
    event = AgentEvent(
        component="Perception",
        step="log_analysis",
        summary="로그에서 오류 코드와 주요 실행 정보를 추출했습니다.",
    )
    assert event.timestamp
    assert event.detail == ""
    assert event.metadata == {}
    dumped = event.model_dump()
    assert dumped["component"] == "Perception"
    assert dumped["timestamp"]
    import re

    assert re.match(ISO_UTC, event.timestamp)


def test_agent_event_rejects_unknown_component():
    with pytest.raises(ValidationError):
        AgentEvent(component="Planner", step="x", summary="y")


def test_agent_event_has_no_private_cot_fields():
    fields = set(AgentEvent.model_fields)
    for forbidden in (
        "reason",
        "thinking",
        "chain_of_thought",
        "private_reasoning",
        "cot",
        "hidden_reasoning",
    ):
        assert forbidden not in fields
    event = AgentEvent(component="Reasoning", step="stop", summary="근거가 충분하여 조사를 종료합니다.")
    assert event_contains_private_cot(event) is False


def test_v0_result_to_agent_events():
    events = build_agent_events("v0", _v0_payload())
    assert _steps(events) == [
        ("Perception", "log_analysis"),
        ("Reasoning", "initial_hypotheses"),
        ("Reasoning", "final_diagnosis"),
    ]
    assert all(item.source == "v0" for item in events)
    assert events[0].metadata["job_name"] == "DAILY_SALES_LOAD"
    assert events[0].metadata["return_code"] == "12"
    assert events[1].metadata["cause_codes"] == ["FILE_NOT_RECEIVED", "INVALID_FILE_PATH"]
    assert "FILE_NOT_RECEIVED" in events[2].summary
    assert not any(item.component == "Action" for item in events)
    blob = str([item.model_dump() for item in events])
    assert "LLM private prose must not leak" not in blob


def test_v1_success_tool_events_are_action():
    payload = _v1_success_payload()
    events = build_agent_events("v1", payload)
    assert _steps(events)[:5] == [
        ("Perception", "log_analysis"),
        ("Reasoning", "initial_hypotheses"),
        ("Reasoning", "tool_selection"),
        ("Action", "tool_call"),
        ("Action", "tool_result"),
    ]
    assert events[-1].step == "final_diagnosis"
    call = next(item for item in events if item.step == "tool_call")
    result = next(item for item in events if item.step == "tool_result")
    assert call.component == "Action"
    assert call.metadata["tool"] == "check_file_status"
    assert result.component == "Action"
    assert result.metadata["status"] == "SUCCESS"
    assert result.metadata["exists"] is False
    assert result.metadata["received"] is False
    assert any(item.step == "evidence_update" for item in events)
    blob = str([item.model_dump() for item in events])
    assert "숨기면 안 되는 CoT" not in blob
    assert "unused-llm-prose" not in blob


def test_failed_tool_is_governance_and_excluded():
    failed = check_file_status(path="/data/in/not_in_catalog.csv")
    assert failed.status == "FAILED"
    payload = {
        "extracted_info": {"job_name": "DAILY_SALES_LOAD"},
        "initial_hypotheses": [
            Hypothesis(
                cause_code="FILE_NOT_RECEIVED",
                cause_name="파일 미수신",
                evidence=["FileNotFoundError"],
            ).model_dump()
        ],
        "selected_tools": [
            {
                "selected_tool": "check_file_status",
                "reason": "should-not-appear",
                "arguments": {"path": "/data/in/not_in_catalog.csv"},
            }
        ],
        "tool_results": [failed.model_dump()],
        "final_cause_code": "FILE_NOT_RECEIVED",
        "final_cause_name": "파일 미수신",
        "diagnosis_level": "추정",
        "owner": "BATCH_OPERATION",
        "evidence": ["FileNotFoundError"],
        "recommended_actions": [],
    }
    events = build_agent_events("v1", payload)
    failure = next(item for item in events if item.step == "tool_failure")
    assert failure.component == "Governance"
    assert failure.metadata["excluded_from_final_evidence"] is True
    assert failure.metadata["tool"] == "check_file_status"
    assert failure.metadata.get("error")
    assert not any(
        item.step == "tool_result" and item.component == "Action" for item in events
    )
    blob = str([item.model_dump() for item in events])
    assert "should-not-appear" not in blob


@pytest.mark.parametrize(
    ("stop_reason", "component", "step"),
    [
        ("EVIDENCE_SUFFICIENT", "Reasoning", "stop"),
        ("NO_ACTIONABLE_TOOL", "Reasoning", "stop"),
        ("MISSING_REQUIRED_ARGUMENTS", "Governance", "missing_arguments"),
        ("MAX_PLANNING_ROUNDS", "Governance", "planning_limit"),
        ("MAX_TOOL_CALLS", "Governance", "tool_call_limit"),
        ("DUPLICATE_TOOL_CALL_BLOCKED", "Governance", "duplicate_tool_blocked"),
    ],
)
def test_stop_reason_maps_to_component_and_step(stop_reason, component, step):
    payload = {
        "extracted_info": {"job_name": "DAILY_SALES_LOAD"},
        "initial_hypotheses": [
            {
                "cause_code": "FILE_NOT_RECEIVED",
                "cause_name": "파일 미수신",
                "evidence": ["x"],
            }
        ],
        "planning_trace": [],
        "stop_reason": stop_reason,
        "final_cause_code": "FILE_NOT_RECEIVED",
        "final_cause_name": "파일 미수신",
        "diagnosis_level": "추정",
        "owner": "BATCH_OPERATION",
    }
    events = build_agent_events("v2", payload)
    mapped = [item for item in events if item.metadata.get("stop_reason") == stop_reason]
    assert len(mapped) == 1
    assert mapped[0].component == component
    assert mapped[0].step == step


def test_v2_f05_like_event_flow(monkeypatch):
    monkeypatch.setattr("app.planning.diagnose", lambda *_a, **_k: _v0_result())
    calls = {"n": 0}

    def planner(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _plan(
                "check_file_status",
                {"path": "/data/in/sales_20260831.csv"},
                goal="파일 확인",
            )
        if calls["n"] == 2:
            return _plan(
                "validate_parameter",
                {
                    "job_name": "DAILY_SALES_LOAD",
                    "parameter_name": "business_date",
                    "parameter_value": "20260831",
                },
                states=[
                    HypothesisState(
                        cause_code="INVALID_BUSINESS_DATE",
                        origin="planner",
                        status="adopted",
                        signals=["business_date in log"],
                    )
                ],
                goal="실행일자 검증",
            )
        return _plan(sufficient=True, goal="충분")

    result = diagnose_v2(
        F05_LOG,
        case_id="unit",
        plan_fn=planner,
        finalize_fn=lambda *_a, **_k: _final_payload("INVALID_BUSINESS_DATE"),
    )
    payload = result.model_dump()
    events = build_agent_events("v2", payload)
    assert _steps(events) == [
        ("Perception", "log_analysis"),
        ("Reasoning", "initial_hypotheses"),
        ("Reasoning", "planning"),
        ("Action", "tool_call"),
        ("Action", "tool_result"),
        ("Reasoning", "sufficiency_check"),
        ("Reasoning", "replan"),
        ("Action", "tool_call"),
        ("Action", "tool_result"),
        ("Reasoning", "hypothesis_update"),
        ("Reasoning", "stop"),
        ("Reasoning", "final_diagnosis"),
    ]
    tools = [
        item.metadata.get("tool")
        for item in events
        if item.step in {"tool_call", "tool_result"}
    ]
    assert tools == [
        "check_file_status",
        "check_file_status",
        "validate_parameter",
        "validate_parameter",
    ]
    sufficiency = next(item for item in events if item.step == "sufficiency_check")
    assert sufficiency.metadata["evidence_sufficient"] is False
    stop = next(item for item in events if item.step == "stop")
    assert stop.metadata["stop_reason"] == "EVIDENCE_SUFFICIENT"
    update = next(item for item in events if item.step == "hypothesis_update")
    assert "INVALID_BUSINESS_DATE" in update.summary
    blob = str([item.model_dump() for item in events])
    assert "파일 확인" not in blob
    assert "실행일자 검증" not in blob


def test_execution_trace_regression_still_holds():
    payload = _v1_success_payload()
    trace = build_execution_trace("v1", payload)
    dumped = trace.model_dump()
    assert dumped["version"] == "v1"
    assert dumped["tool_rounds"][0]["tool"] == "check_file_status"
    assert dumped["tool_rounds"][0]["status"] == "SUCCESS"
    assert "agent_events" not in dumped
    v0 = build_execution_trace("v0", _v0_payload())
    assert v0.tool_rounds == []
    events = build_agent_events("v1", payload)
    assert events[0].component == "Perception"
    assert trace.tool_rounds[0].tool == "check_file_status"


def test_streamlit_view_conversion():
    events = build_agent_events("v0", _v0_payload())
    views = build_agent_event_views(events)
    assert views[0]["title"].startswith("👁️ [Perception] Log Analysis — ")
    assert views[1]["title"].startswith("🧠 [Reasoning] Initial Hypotheses — ")
    assert views[-1]["component"] == "Reasoning"
    assert views[-1]["step"] == "final_diagnosis"
    assert "metadata" in views[0]
    assert views[0]["timestamp"] == events[0].timestamp
    failed_views = build_agent_event_views(
        [
            AgentEvent(
                component="Governance",
                step="tool_failure",
                summary="check_file_status 실행에 실패했습니다.",
                metadata={"excluded_from_final_evidence": True},
            )
        ]
    )
    assert failed_views[0]["title"].startswith("🛡️ [Governance] Tool Failure — ")


def test_analyze_attaches_agent_events_without_breaking_v2_trace(monkeypatch):
    from app.ui_service import analyze

    class FakeV2:
        def model_dump(self):
            return {
                "version": "v2",
                "case_id": "unit",
                "extracted_info": {"job_name": "DAILY_SALES_LOAD"},
                "initial_hypotheses": [
                    {
                        "cause_code": "FILE_NOT_RECEIVED",
                        "cause_name": "파일 미수신",
                        "evidence": ["FileNotFoundError"],
                    }
                ],
                "working_hypotheses": [],
                "selected_tools": [
                    {
                        "selected_tool": "check_file_status",
                        "reason": "파일 확인",
                        "arguments": {"path": "/data/in/sales_20260831.csv"},
                    }
                ],
                "tool_results": [
                    {
                        "tool": "check_file_status",
                        "status": "SUCCESS",
                        "data": {"exists": False, "received": False},
                        "error": None,
                    }
                ],
                "planning_trace": [
                    {
                        "round_index": 1,
                        "goal": "파일 확인",
                        "investigation_plan": [],
                        "hypothesis_states": [],
                        "unresolved_questions": ["날짜 검증 필요"],
                        "evidence_sufficient": False,
                        "selected_tool": "check_file_status",
                        "arguments": {"path": "/data/in/sales_20260831.csv"},
                        "reason": "파일 존재 여부",
                        "evidence_summary": {"exists": False, "status": "SUCCESS"},
                        "replanned": False,
                        "stop_reason": None,
                        "tool_result": {
                            "tool": "check_file_status",
                            "status": "SUCCESS",
                            "data": {"exists": False, "received": False},
                            "error": None,
                        },
                    }
                ],
                "stop_reason": "EVIDENCE_SUFFICIENT",
                "current_round": 1,
                "final_cause_code": "FILE_NOT_RECEIVED",
                "final_cause_name": "파일 미수신",
                "diagnosis_level": "확인됨",
                "owner": "BATCH_OPERATION",
                "evidence": ["exists=false"],
                "limitations": [],
                "recommended_actions": [],
            }

    monkeypatch.setattr("app.ui_service.run_backend", lambda *a, **k: FakeV2())
    outcome = analyze("v2", F05_LOG, case_id="unit")
    assert outcome.trace["planning_trace"][0]["round_index"] == 1
    assert outcome.trace["stop_reason"] == "EVIDENCE_SUFFICIENT"
    assert outcome.trace["agent_events"]
    assert outcome.trace["agent_events"][0]["component"] == "Perception"
    joined = str(outcome.trace["agent_events"])
    assert "파일 존재 여부" not in joined
    assert "agent_events" not in (outcome.result or {})


def test_adapter_does_not_touch_v2_behavior_modules():
    source = (PROJECT_ROOT / "app" / "agent_events.py").read_text(encoding="utf-8")
    assert "diagnose_v2" not in source
    assert "has_parameter_anomaly_signal" not in source
    assert "v2_planning_prompt" not in source
    for name in ALLOWED_COMPONENTS:
        AgentEvent(component=name, step="placeholder", summary="enum 허용 확인")
