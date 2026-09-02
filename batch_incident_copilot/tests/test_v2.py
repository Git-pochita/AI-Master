import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.planning import (
    MAX_PLANNING_ROUNDS,
    MAX_TOOL_CALLS,
    complete_v2_arguments,
    diagnose_v2,
    tool_fingerprint,
)
from app.schemas import (
    Hypothesis,
    HypothesisState,
    PlannerDecision,
    StopReason,
    ToolResult,
    V2DiagnosisResult,
)
from app.tool_use import MAX_TOOL_CALLS as V1_MAX_TOOL_CALLS
from app.tools.evidence import filter_evidence, supporting_tool_results
from main import run_diagnosis


F05_LOG = (PROJECT_ROOT / "data" / "sample_logs" / "F-05.log").read_text(encoding="utf-8")


def _hyp(*codes: str) -> list[Hypothesis]:
    items = []
    for code in codes:
        items.append(
            Hypothesis(
                cause_code=code,
                cause_name=code,
                evidence=["log"],
            )
        )
    return items


def _v0_result(codes=("FILE_NOT_RECEIVED", "INVALID_FILE_PATH"), extracted=None):
    hyps = _hyp(*codes)
    return SimpleNamespace(
        case_id="unit",
        extracted_info=extracted or {
            "job_name": "DAILY_SALES_LOAD",
            "business_date": "20260831",
            "input_path": "/data/in/sales_20260831.csv",
        },
        hypotheses=hyps,
    )


def _final_payload(cause="FILE_NOT_RECEIVED", evidence=None, level="확인됨"):
    return {
        "summary": "unit",
        "final_cause_code": cause,
        "final_cause_name": cause,
        "diagnosis_level": level,
        "owner": "BATCH_OPERATION",
        "evidence": evidence or ["success evidence"],
        "limitations": ["mock"],
        "recommended_actions": [],
    }


def _plan(tool=None, arguments=None, sufficient=False, stop=None, states=None, goal="점검"):
    return PlannerDecision(
        investigation_plan=[
            {
                "goal": goal,
                "candidate_tool": tool,
                "arguments": arguments or {},
                "argument_status": "READY" if tool else "MISSING_ARGUMENTS",
                "related_cause_codes": [],
                "status": "pending",
            }
        ],
        hypothesis_states=states or [],
        unresolved_questions=["원인 미확정"] if not sufficient else [],
        evidence_sufficient=sufficient,
        selected_tool=tool,
        arguments=arguments or {},
        reason=goal,
        stop_reason=stop,
    )


def test_v2_schema_and_frozen_initial_hypotheses():
    result = V2DiagnosisResult(
        case_id="unit",
        summary="s",
        initial_hypotheses=_hyp("FILE_NOT_RECEIVED"),
        working_hypotheses=[
            HypothesisState(
                cause_code="INVALID_BUSINESS_DATE",
                origin="planner",
                status="adopted",
            )
        ],
        stop_reason=StopReason.EVIDENCE_SUFFICIENT,
        final_cause_code="INVALID_BUSINESS_DATE",
        final_cause_name="실행일자 파라미터 오류",
        diagnosis_level="확인됨",
        owner="BATCH_OPERATION",
        evidence=["is_valid=false"],
        limitations=[],
    )
    dumped = result.model_dump()
    assert dumped["version"] == "v2"
    assert dumped["initial_hypotheses"][0]["cause_code"] == "FILE_NOT_RECEIVED"
    assert dumped["working_hypotheses"][0]["cause_code"] == "INVALID_BUSINESS_DATE"
    assert dumped["stop_reason"] == "EVIDENCE_SUFFICIENT"


def test_v2_schema_rejects_bad_cause():
    with pytest.raises(ValidationError):
        V2DiagnosisResult(
            initial_hypotheses=_hyp("FILE_NOT_RECEIVED"),
            stop_reason=StopReason.EVIDENCE_SUFFICIENT,
            final_cause_code="NOT_A_CODE",
            final_cause_name="x",
            diagnosis_level="추정",
            owner="BATCH_OPERATION",
            evidence=["x"],
            limitations=[],
        )


def test_fingerprint_ignores_blank_and_key_order():
    left = tool_fingerprint("check_file_status", {"path": "/a", "unused": ""})
    right = tool_fingerprint("check_file_status", {"unused": None, "path": "/a"})
    assert left == right
    other = tool_fingerprint("check_file_status", {"path": "/b"})
    assert left != other


def test_success_tool_then_stop(monkeypatch):
    monkeypatch.setattr("app.planning.diagnose", lambda *_a, **_k: _v0_result())
    calls = {"n": 0}

    def planner(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _plan(
                "check_file_status",
                {"path": "/data/in/sales_20260831.csv"},
                goal="파일 존재 확인",
            )
        return _plan(sufficient=True, goal="근거 충분")

    result = diagnose_v2(
        "log",
        case_id="unit",
        plan_fn=planner,
        finalize_fn=lambda *_a, **_k: _final_payload(),
    )
    assert len(result.selected_tools) == 1
    assert result.selected_tools[0].selected_tool == "check_file_status"
    assert result.tool_results[0].status == "SUCCESS"
    assert result.stop_reason == StopReason.EVIDENCE_SUFFICIENT
    assert result.planning_trace[0].tool_result is not None
    assert result.planning_trace[1].evidence_sufficient is True


def test_tool_then_replan_second_tool(monkeypatch):
    monkeypatch.setattr("app.planning.diagnose", lambda *_a, **_k: _v0_result())
    calls = {"n": 0}

    def planner(**kwargs):
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
    tools = [item.selected_tool for item in result.selected_tools]
    assert tools == ["check_file_status", "validate_parameter"]
    assert result.planning_trace[1].replanned is True
    assert any(item.cause_code == "INVALID_BUSINESS_DATE" for item in result.working_hypotheses)
    assert result.initial_hypotheses[0].cause_code == "FILE_NOT_RECEIVED"
    assert "INVALID_BUSINESS_DATE" not in {h.cause_code for h in result.initial_hypotheses}
    assert result.tool_results[1].status == "SUCCESS"
    assert result.tool_results[1].data["is_valid"] is False


def test_duplicate_tool_and_args_blocked(monkeypatch):
    monkeypatch.setattr("app.planning.diagnose", lambda *_a, **_k: _v0_result())

    def planner(**_kwargs):
        return _plan(
            "check_file_status",
            {"path": "/data/in/sales_20260831.csv"},
            goal="같은 점검 반복",
        )

    result = diagnose_v2(
        "log",
        case_id="unit",
        plan_fn=planner,
        finalize_fn=lambda *_a, **_k: _final_payload(),
    )
    assert len(result.tool_results) == 1
    assert result.stop_reason == StopReason.DUPLICATE_TOOL_CALL_BLOCKED


def test_max_planning_rounds(monkeypatch):
    monkeypatch.setattr("app.planning.diagnose", lambda *_a, **_k: _v0_result())
    monkeypatch.setattr("app.planning.MAX_PLANNING_ROUNDS", 2)
    monkeypatch.setattr("app.planning.MAX_TOOL_CALLS", 5)
    calls = {"n": 0}
    paths = [
        "/data/in/sales_20260831.csv",
        "/data/in/orders/orders_20260901.csv",
        "/data/in/ledger_20260901.csv",
    ]

    def planner(**_kwargs):
        calls["n"] += 1
        path = paths[min(calls["n"] - 1, len(paths) - 1)]
        return _plan("check_file_status", {"path": path}, goal="추가 점검")

    result = diagnose_v2(
        "log",
        case_id="unit",
        plan_fn=planner,
        finalize_fn=lambda *_a, **_k: _final_payload(),
    )
    assert result.current_round == 2
    assert result.stop_reason == StopReason.MAX_PLANNING_ROUNDS
    assert len(result.tool_results) == 2


def test_max_tool_calls(monkeypatch):
    monkeypatch.setattr("app.planning.diagnose", lambda *_a, **_k: _v0_result())
    monkeypatch.setattr("app.planning.MAX_PLANNING_ROUNDS", 3)
    monkeypatch.setattr("app.planning.MAX_TOOL_CALLS", 1)

    def planner(**_kwargs):
        return _plan(
            "check_file_status",
            {"path": "/data/in/sales_20260831.csv"},
            goal="반복 시도",
        )

    result = diagnose_v2(
        "log",
        case_id="unit",
        plan_fn=planner,
        finalize_fn=lambda *_a, **_k: _final_payload(),
    )
    assert len(result.tool_results) == 1
    assert result.stop_reason in {
        StopReason.MAX_TOOL_CALLS,
        StopReason.DUPLICATE_TOOL_CALL_BLOCKED,
    }


def test_failed_tool_not_in_final_evidence(monkeypatch):
    monkeypatch.setattr("app.planning.diagnose", lambda *_a, **_k: _v0_result())
    seen = {}

    def planner(**_kwargs):
        if seen.get("n"):
            return _plan(sufficient=True, goal="종료")
        seen["n"] = 1
        return _plan(
            "check_file_status",
            {"path": "/missing/not-in-catalog.csv"},
            goal="없는 경로",
        )

    def finalize(_log, _initial, tool_results):
        usable = supporting_tool_results(tool_results)
        evidence = [
            f"{item.tool}: {item.data}" for item in usable
        ]
        filtered = filter_evidence(
            evidence + [item.error for item in tool_results if item.error],
            tool_results,
        )
        return _final_payload(evidence=filtered or ["log only"], level="추정")

    result = diagnose_v2(
        "log",
        case_id="unit",
        plan_fn=planner,
        finalize_fn=finalize,
    )
    assert result.tool_results[0].status == "FAILED"
    assert result.planning_trace[0].tool_result.status == "FAILED"
    joined = " ".join(result.evidence)
    assert result.tool_results[0].error not in joined
    assert supporting_tool_results(result.tool_results) == []


def test_missing_required_arguments_stops(monkeypatch):
    monkeypatch.setattr(
        "app.planning.diagnose",
        lambda *_a, **_k: _v0_result(
            extracted={"connection_name": "SALES_DB"},
        ),
    )

    def planner(**_kwargs):
        return _plan("check_db_status", {"connection_name": "SALES_DB"}, goal="DB 확인")

    result = diagnose_v2(
        "log",
        case_id="unit",
        plan_fn=planner,
        finalize_fn=lambda *_a, **_k: _final_payload(level="추정"),
    )
    assert result.tool_results == []
    assert result.stop_reason == StopReason.MISSING_REQUIRED_ARGUMENTS


def test_v1_max_tool_calls_unchanged():
    assert V1_MAX_TOOL_CALLS == 2
    assert MAX_PLANNING_ROUNDS == 3
    assert MAX_TOOL_CALLS == 3


def test_v2_run_diagnosis_entry(monkeypatch):
    fake = V2DiagnosisResult(
        case_id="unit",
        summary="s",
        initial_hypotheses=_hyp("FILE_NOT_RECEIVED"),
        stop_reason=StopReason.EVIDENCE_SUFFICIENT,
        selected_tools=[],
        tool_results=[],
        final_cause_code="FILE_NOT_RECEIVED",
        final_cause_name="파일 미수신",
        diagnosis_level="추정",
        owner="BATCH_OPERATION",
        evidence=["log"],
        limitations=[],
    )
    monkeypatch.setattr("app.planning.diagnose_v2", lambda *_a, **_k: fake)
    result = run_diagnosis("v2", "log", "unit")
    assert isinstance(result, V2DiagnosisResult)
    assert result.version == "v2"


def test_planning_source_has_no_case_specialization():
    source = (PROJECT_ROOT / "app" / "planning.py").read_text(encoding="utf-8")
    prompt = (PROJECT_ROOT / "prompts" / "v2_planning_prompt.txt").read_text(encoding="utf-8")
    for snippet in ("F-05", "F-04", "F-01", "INVALID_BUSINESS_DATE가 정답"):
        assert snippet not in source
        assert snippet not in prompt
    assert "case_id:" not in prompt
    assert "f\"case_id:" not in source


def test_v2_analyze_builds_planning_events(monkeypatch):
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
                            "data": {"exists": False},
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
    assert outcome.ok is True
    assert outcome.trace["version"] == "v2"
    assert outcome.trace["planning_trace"][0]["round_index"] == 1
    assert outcome.trace["stop_reason"] == "EVIDENCE_SUFFICIENT"
    assert outcome.result["selected_tools"][0]["selected_tool"] == "check_file_status"


def test_complete_v2_arguments_uses_extracted_aliases():
    args = complete_v2_arguments(
        "check_file_status",
        {},
        {"input_path": "/data/in/sales_20260831.csv"},
        [],
    )
    assert args["path"] == "/data/in/sales_20260831.csv"
    param_args = complete_v2_arguments(
        "validate_parameter",
        {"job_name": "DAILY_SALES_LOAD"},
        {"business_date": "20260831"},
        [],
    )
    assert param_args["parameter_name"] == "business_date"
    assert param_args["parameter_value"] == "20260831"
