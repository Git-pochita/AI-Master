import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.progress import (
    STEP_CRITIC,
    STEP_EVIDENCE,
    STEP_HYPOTHESES,
    STEP_LOG_ANALYSIS,
    STEP_PLANNING,
    STEP_REFLECTION,
    STEP_REPLAN,
    STEP_TOOL,
    STEP_VALIDATION,
    ProgressEvent,
    contains_private_cot,
    emit_critic,
    emit_validation,
)
from app.planning import diagnose_v2
from app.schemas import (
    CriticIssue,
    CriticIssueType,
    CriticResult,
    HypothesisState,
    ValidationDecision,
    ValidationResult,
)
from app.tool_use import diagnose_v1
from app.ui_service import analyze
from app.v3 import diagnose_v3
from tests.test_v2 import F05_LOG, _final_payload, _plan, _v0_result

STREAMLIT_SRC = (PROJECT_ROOT / "streamlit_app.py").read_text(encoding="utf-8")
PROGRESS_SRC = (PROJECT_ROOT / "app" / "progress.py").read_text(encoding="utf-8")
PLANNING_SRC = (PROJECT_ROOT / "app" / "planning.py").read_text(encoding="utf-8")
TOOL_USE_SRC = (PROJECT_ROOT / "app" / "tool_use.py").read_text(encoding="utf-8")
V3_SRC = (PROJECT_ROOT / "app" / "v3.py").read_text(encoding="utf-8")

SAMPLE = """2026-09-01 02:00:00 INFO  JOB=DAILY_SALES_LOAD START
2026-09-01 02:00:03 ERROR FileNotFoundError: /data/in/sales_20260831.csv
2026-09-01 02:00:03 ERROR job failed with return_code=12
"""


def _recorder():
    events: list[ProgressEvent] = []

    def progress_fn(event: ProgressEvent) -> None:
        events.append(event)

    return events, progress_fn


def _done_steps(events: list[ProgressEvent]) -> list[str]:
    return [item.step for item in events if item.status == "done"]


def test_progress_sources_do_not_fake_delay():
    for source in (STREAMLIT_SRC, PROGRESS_SRC, PLANNING_SRC, TOOL_USE_SRC, V3_SRC):
        assert "time.sleep" not in source


def test_streamlit_uses_live_progress_callback():
    assert "분석 진행 과정" in STREAMLIT_SRC
    assert "st.status" in STREAMLIT_SRC
    assert "progress_fn=on_progress" in STREAMLIT_SRC
    assert "_render_final(payload)" in STREAMLIT_SRC


def test_emit_validation_and_no_private_cot():
    events, progress_fn = _recorder()
    emit_validation(
        progress_fn,
        ValidationResult(decision=ValidationDecision.PROCEED, reasons=["배치 로그로 보입니다."]),
    )
    assert events[0].step == STEP_VALIDATION
    assert events[0].title == "입력 로그 검증 완료"
    assert all(not contains_private_cot(item) for item in events)


def test_v0_progress_omits_planning_tool_critic(monkeypatch):
    from app.schemas import DiagnosisResult, Hypothesis

    result = DiagnosisResult(
        summary="V0",
        extracted_info={
            "job_name": "DAILY_SALES_LOAD",
            "return_code": "12",
            "error_messages": ["FileNotFoundError"],
        },
        hypotheses=[
            Hypothesis(
                cause_code="FILE_NOT_RECEIVED",
                cause_name="파일 미수신",
                evidence=["FileNotFoundError"],
            )
        ],
        final_cause_code="FILE_NOT_RECEIVED",
        final_cause_name="파일 미수신",
        diagnosis_level="추정",
        owner="BATCH_OPERATION",
        recommended_actions=["확인"],
        limitations=["로그만 사용"],
    )
    monkeypatch.setattr("app.ui_service.diagnose", lambda *a, **k: result)
    events, progress_fn = _recorder()
    outcome = analyze("v0", SAMPLE, progress_fn=progress_fn)
    assert outcome.ok is True
    steps = _done_steps(events)
    assert steps == [STEP_VALIDATION, STEP_LOG_ANALYSIS, STEP_HYPOTHESES]
    assert STEP_PLANNING not in steps
    assert STEP_TOOL not in steps
    assert STEP_REPLAN not in steps
    assert STEP_CRITIC not in steps
    assert any("FILE_NOT_RECEIVED" in line for line in events[2].details)


def test_v1_progress_has_tools_but_not_planning(monkeypatch):
    from app.schemas import DiagnosisResult, Hypothesis, ToolSelection

    initial = DiagnosisResult(
        case_id="unit",
        summary="V0",
        extracted_info={
            "job_name": "DAILY_SALES_LOAD",
            "input_path": "/data/in/sales_20260831.csv",
            "error_messages": ["FileNotFoundError"],
        },
        hypotheses=[
            Hypothesis(
                cause_code="FILE_NOT_RECEIVED",
                cause_name="파일 미수신",
                evidence=["FileNotFoundError"],
            )
        ],
        final_cause_code="FILE_NOT_RECEIVED",
        final_cause_name="파일 미수신",
        diagnosis_level="추정",
        owner="BATCH_OPERATION",
        recommended_actions=["확인"],
        limitations=["로그만 사용"],
    )
    monkeypatch.setattr("app.tool_use.diagnose", lambda *a, **k: initial)

    def fake_select(_log, _initial, already_called, _results):
        if already_called:
            return ToolSelection(selected_tool=None, reason="done", arguments={})
        return ToolSelection(
            selected_tool="check_file_status",
            reason="파일 확인",
            arguments={"path": "/data/in/sales_20260831.csv"},
        )

    monkeypatch.setattr("app.tool_use.select_tool", fake_select)
    monkeypatch.setattr(
        "app.tool_use.finalize_diagnosis",
        lambda *_a, **_k: _final_payload(),
    )
    events, progress_fn = _recorder()
    result = diagnose_v1("log", case_id="unit", progress_fn=progress_fn)
    assert result.tool_results[0].tool == "check_file_status"
    steps = _done_steps(events)
    assert steps == [
        STEP_LOG_ANALYSIS,
        STEP_HYPOTHESES,
        STEP_TOOL,
        STEP_EVIDENCE,
    ]
    assert STEP_PLANNING not in steps
    assert STEP_REPLAN not in steps
    assert STEP_CRITIC not in steps
    tool_event = next(item for item in events if item.step == STEP_TOOL and item.status == "done")
    assert "`check_file_status`" in tool_event.details[0]
    assert any(line.startswith("exists=") for line in tool_event.details)
    assert "reason" not in " ".join(tool_event.details)


def test_v2_progress_shows_planning_tool_replan_evidence(monkeypatch):
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

    events, progress_fn = _recorder()
    result = diagnose_v2(
        F05_LOG,
        case_id="unit",
        plan_fn=planner,
        finalize_fn=lambda *_a, **_k: _final_payload("INVALID_BUSINESS_DATE"),
        progress_fn=progress_fn,
    )
    assert [item.selected_tool for item in result.selected_tools] == [
        "check_file_status",
        "validate_parameter",
    ]
    steps = _done_steps(events)
    assert steps == [
        STEP_LOG_ANALYSIS,
        STEP_HYPOTHESES,
        STEP_PLANNING,
        STEP_TOOL,
        STEP_REPLAN,
        STEP_TOOL,
        STEP_EVIDENCE,
    ]
    assert STEP_CRITIC not in steps
    planning = next(item for item in events if item.step == STEP_PLANNING and item.status == "done")
    assert any("check_file_status" in line for line in planning.details)
    replan = next(item for item in events if item.step == STEP_REPLAN and item.status == "done")
    assert "이전 점검만으로는 원인을 확정하기 부족합니다." in replan.details
    assert any("validate_parameter" in line for line in replan.details)
    assert "실행일자 검증" not in " ".join(replan.details)
    assert all(not contains_private_cot(item) for item in events)


def test_v2_without_second_tool_omits_replan(monkeypatch):
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

    events, progress_fn = _recorder()
    diagnose_v2(
        "log",
        case_id="unit",
        plan_fn=planner,
        finalize_fn=lambda *_a, **_k: _final_payload(),
        progress_fn=progress_fn,
    )
    steps = _done_steps(events)
    assert STEP_PLANNING in steps
    assert STEP_TOOL in steps
    assert STEP_REPLAN not in steps
    assert STEP_EVIDENCE in steps


def test_v3_progress_adds_critic(monkeypatch):
    from tests.test_v3 import _load_log, _load_v2, _pass_draft

    events, progress_fn = _recorder()
    result = diagnose_v3(
        _load_log("F-01"),
        case_id="F-01",
        v2_result=_load_v2("F-01"),
        critic_fn=_pass_draft,
        diagnose_v2_fn=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("diagnose_v2 should not run")
        ),
        progress_fn=progress_fn,
    )
    assert result.critic_result.verdict == "PASS"
    steps = _done_steps(events)
    assert steps == [STEP_CRITIC]
    assert "PASS" in events[-1].details[0]
    assert all("revision_reason" not in line for line in events[-1].details)


def test_v3_progress_emits_reflection_when_revised():
    from tests.test_v3 import _load_log, _load_v2, _conflict_better_draft, _revision_draft

    v2 = _load_v2("F-02")
    events, progress_fn = _recorder()
    result = diagnose_v3(
        _load_log("F-02"),
        case_id="F-02",
        v2_result=v2,
        critic_fn=lambda *_a, **_k: _conflict_better_draft("sales_20260901.csv"),
        revise_fn=lambda *_a, **_k: _revision_draft(v2, "INVALID_FILE_PATH"),
        diagnose_v2_fn=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("diagnose_v2 should not run")
        ),
        progress_fn=progress_fn,
    )
    steps = _done_steps(events)
    assert steps == [STEP_CRITIC, STEP_REFLECTION]
    assert result.revised is True
    reflection = events[-1]
    assert reflection.step == STEP_REFLECTION
    assert any("INVALID_FILE_PATH" in line for line in reflection.details)


def test_analyze_abort_emits_validation_only(monkeypatch):
    called = {"n": 0}

    def fake_backend(*_args, **_kwargs):
        called["n"] += 1
        raise AssertionError("ABORT이면 backend를 호출하면 안 됩니다.")

    monkeypatch.setattr("app.ui_service.run_backend", fake_backend)
    events, progress_fn = _recorder()
    outcome = analyze("v2", "", progress_fn=progress_fn)
    assert outcome.ok is False
    assert called["n"] == 0
    assert _done_steps(events) == [STEP_VALIDATION]
    assert events[0].title == "입력 로그 검증 실패"


def test_critic_event_skips_issue_descriptions():
    events, progress_fn = _recorder()
    emit_critic(
        progress_fn,
        CriticResult(
            verdict="REVISE",
            evidence_consistent=False,
            diagnosis_level_appropriate=True,
            owner_consistent=True,
            issues=[
                CriticIssue(
                    issue_type=CriticIssueType.EVIDENCE_CONFLICT,
                    description="이 문장은 시연 화면에 나오면 안 되는 장문 추론입니다.",
                    related_evidence=["x"],
                    blocking=True,
                )
            ],
            revision_reason="private critic prose",
        ),
    )
    blob = " ".join(events[0].details)
    assert "장문 추론" not in blob
    assert "private critic prose" not in blob
    assert "EVIDENCE_CONFLICT" in blob
    assert not contains_private_cot(events[0])
