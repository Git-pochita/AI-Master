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
    TITLE_CRITIC_RUNNING,
    TITLE_LOG_ANALYSIS_RUNNING,
    TITLE_REFLECTION_RUNNING,
    TITLE_REPLAN,
    ProgressEvent,
    contains_private_cot,
    emit_critic,
    emit_evidence,
    emit_hypotheses,
    emit_log_analysis,
    emit_planning,
    emit_reflection,
    emit_replan,
    emit_tool,
    emit_validation,
    evidence_details,
    highlight_tool_data,
    format_progress_markdown,
    running_label,
)
from app.progress_view import format_operator_progress, operator_running_label
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
    assert "st.empty" in STREAMLIT_SRC
    assert "_redraw_progress" in STREAMLIT_SRC
    assert "format_operator_progress" in STREAMLIT_SRC
    assert "progress_fn=on_progress" in STREAMLIT_SRC
    assert "result_slot = st.empty()" in STREAMLIT_SRC
    assert "_render_final(payload)" in STREAMLIT_SRC
    assert 'st.markdown(f"- ' not in STREAMLIT_SRC
    assert "slot.markdown(format_operator_progress" in STREAMLIT_SRC
    assert "st.markdown(format_progress_markdown(progress_events))" not in STREAMLIT_SRC
    assert STREAMLIT_SRC.count('st.subheader("분석 진행 과정")') == 1
    assert 'st.subheader("V3 Critic / Reflection")' not in STREAMLIT_SRC
    assert "**final_cause_code:**" not in STREAMLIT_SRC
    assert "**verdict:**" not in STREAMLIT_SRC
    status_block = STREAMLIT_SRC.split("with st.status", 1)[1].split(
        "if outcome.validation", 1
    )[0]
    assert "st.expander" not in status_block
    assert "_render_execution_trace" not in status_block
    assert "_render_final" not in status_block


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
    running = [item for item in events if item.status == "running"]
    assert running[0].step == STEP_LOG_ANALYSIS
    assert running[0].title == TITLE_LOG_ANALYSIS_RUNNING
    hypotheses = next(item for item in events if item.step == STEP_HYPOTHESES)
    assert hypotheses.details == ["FILE_NOT_RECEIVED"]
    log_event = next(
        item for item in events if item.step == STEP_LOG_ANALYSIS and item.status == "done"
    )
    assert any("FileNotFoundError" in line for line in log_event.details)
    assert "return_code=12" in log_event.details
    assert "job=DAILY_SALES_LOAD" in log_event.details


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
    assert "check_file_status" in tool_event.title
    assert any(line.startswith("exists=") for line in tool_event.details)
    assert any(line.startswith("path=") for line in tool_event.details)
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
    assert "파일 확인" not in " ".join(planning.details)
    replan = next(item for item in events if item.step == STEP_REPLAN and item.status == "done")
    assert "이전 점검만으로 원인 확정 부족" in replan.details
    assert any("validate_parameter" in line for line in replan.details)
    assert "실행일자 검증" not in " ".join(replan.details)
    running_replan = next(
        item
        for item in events
        if item.step == STEP_REPLAN and item.status == "running"
    )
    assert running_replan.title == TITLE_REPLAN
    assert all(not contains_private_cot(item) for item in events)
    evidence = next(item for item in events if item.step == STEP_EVIDENCE and item.status == "done")
    assert evidence.details
    assert all("몇 건" not in line for line in evidence.details)
    assert any("success evidence" in line or "exists=" in line for line in evidence.details)


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


def test_highlight_tool_data_keeps_only_key_fields():
    lines = highlight_tool_data(
        {
            "path": "/data/in/sales_20260831.csv",
            "exists": False,
            "received": False,
            "raw_payload": {"secret": "do-not-show"},
            "same_directory_files": [{"path": "/data/in/other.csv"}],
        }
    )
    blob = " ".join(lines)
    assert "exists=False" in blob
    assert "received=False" in blob
    assert "raw_payload" not in blob
    assert "secret" not in blob
    assert "same_directory_files" not in blob


def test_format_progress_markdown_is_live_panel_text():
    events, progress_fn = _recorder()
    emit_validation(
        progress_fn,
        ValidationResult(
            decision=ValidationDecision.PROCEED,
            reasons=["배치 로그로 보입니다."],
        ),
    )
    text = format_progress_markdown(events, running_title="핵심 오류 분석")
    assert "✓ **입력 로그 검증 완료**" in text
    assert "배치 로그로 보입니다." in text
    assert "진행 중: **핵심 오류 분석**" in text
    assert "\n- " not in text
    assert "\n* " not in text
    event = ProgressEvent(
        step=STEP_TOOL,
        title="Tool 실행",
        status="running",
        metadata={"tool": "check_file_status"},
    )
    assert running_label(event) == "Tool 실행 · check_file_status"


def test_emit_planning_lists_tools_not_planner_reason():
    events, progress_fn = _recorder()
    emit_planning(
        progress_fn,
        [
            {
                "candidate_tool": "check_file_status",
                "goal": "파일 존재 확인",
            }
        ],
        round_index=1,
    )
    assert events[0].step == STEP_PLANNING
    assert events[0].details == ["check_file_status"]
    assert "파일 존재 확인" not in " ".join(events[0].details)
    assert "planner" not in " ".join(events[0].details).lower()


def test_v3_producer_progress_then_critic(monkeypatch):
    from tests.test_v3 import _load_log, _load_v2, _pass_draft
    from app.progress import emit_evidence, emit_planning, emit_tool
    from app.schemas import ToolResult

    v2 = _load_v2("F-01")

    def fake_v2(log_text, case_id=None, progress_fn=None):
        emit_planning(
            progress_fn,
            [
                {"candidate_tool": "check_file_status", "goal": "파일 확인"},
                {"candidate_tool": "validate_parameter", "goal": "날짜 검증"},
            ],
            round_index=1,
        )
        emit_tool(
            progress_fn,
            "check_file_status",
            ToolResult(
                tool="check_file_status",
                status="SUCCESS",
                data={"path": "/data/in/sales_20260831.csv", "exists": False},
            ),
        )
        emit_evidence(
            progress_fn,
            evidence=["check_file_status: exists=False"],
        )
        return v2

    events, progress_fn = _recorder()
    result = diagnose_v3(
        _load_log("F-01"),
        case_id="F-01",
        critic_fn=_pass_draft,
        diagnose_v2_fn=fake_v2,
        progress_fn=progress_fn,
    )
    assert result.critic_result.verdict == "PASS"
    steps = _done_steps(events)
    assert steps == [STEP_PLANNING, STEP_TOOL, STEP_EVIDENCE, STEP_CRITIC]
    critic_running = next(
        item
        for item in events
        if item.step == STEP_CRITIC and item.status == "running"
    )
    assert critic_running.title == TITLE_CRITIC_RUNNING


def test_analyze_v3_1_routes_progress_like_v3(monkeypatch):
    from tests.test_v3 import _load_v2, _pass_draft

    v2 = _load_v2("F-01")
    captured = {}

    def fake_v3(log_text, case_id=None, progress_fn=None, **_kwargs):
        captured["progress_fn"] = progress_fn
        captured["log"] = log_text
        from app.progress import emit_critic

        emit_critic(
            progress_fn,
            {
                "verdict": "PASS",
                "evidence_consistent": True,
                "issues": [],
            },
        )
        from app.v3 import _pack_v3
        from app.schemas import CriticResult

        return _pack_v3(
            v2,
            CriticResult(
                verdict="PASS",
                evidence_consistent=True,
                diagnosis_level_appropriate=True,
                owner_consistent=True,
            ),
            summary=v2.summary,
            final_cause_code=v2.final_cause_code,
            final_cause_name=v2.final_cause_name,
            diagnosis_level=v2.diagnosis_level,
            owner=v2.owner,
            evidence=list(v2.evidence),
            limitations=list(v2.limitations),
            recommended_actions=list(v2.recommended_actions),
        )

    monkeypatch.setattr("app.v3.diagnose_v3", fake_v3)
    events, progress_fn = _recorder()
    outcome = analyze("v3_1", SAMPLE, progress_fn=progress_fn)
    assert outcome.ok is True
    assert captured["progress_fn"] is progress_fn
    assert _done_steps(events)[0] == STEP_VALIDATION
    assert STEP_CRITIC in _done_steps(events)


def test_v3_reflection_emits_running_before_revision():
    from tests.test_v3 import _load_log, _load_v2, _conflict_better_draft, _revision_draft

    v2 = _load_v2("F-02")
    events, progress_fn = _recorder()
    diagnose_v3(
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
    running_titles = [item.title for item in events if item.status == "running"]
    assert TITLE_CRITIC_RUNNING in running_titles
    assert TITLE_REFLECTION_RUNNING in running_titles
    assert running_titles.index(TITLE_CRITIC_RUNNING) < running_titles.index(
        TITLE_REFLECTION_RUNNING
    )


def test_log_and_hypothesis_details_are_actual_artifacts():
    events, progress_fn = _recorder()
    emit_log_analysis(
        progress_fn,
        {
            "error_messages": ["FileNotFoundError"],
            "return_code": "12",
            "job_name": "DAILY_SALES_LOAD",
            "input_path": "/data/in/sales_20260903.csv",
        },
    )
    emit_hypotheses(
        progress_fn,
        [
            {"cause_code": "FILE_NOT_RECEIVED", "cause_name": "파일 미수신"},
            {"cause_code": "INVALID_BUSINESS_DATE", "cause_name": "영업일자 불일치"},
        ],
    )
    log_event = events[0]
    assert log_event.details == [
        "FileNotFoundError",
        "return_code=12",
        "job=DAILY_SALES_LOAD",
        "path=/data/in/sales_20260903.csv",
    ]
    assert events[1].details == ["FILE_NOT_RECEIVED", "INVALID_BUSINESS_DATE"]
    assert all(not contains_private_cot(item) for item in events)


def test_planning_lists_candidate_tools_without_goals():
    events, progress_fn = _recorder()
    emit_planning(
        progress_fn,
        [
            {
                "candidate_tool": "check_file_status",
                "goal": "이 문장은 planner reason처럼 보이면 안 됩니다.",
            },
            {
                "candidate_tool": "validate_parameter",
                "goal": "날짜를 왜 점검하는지 장문 설명",
            },
        ],
    )
    assert events[0].details == ["check_file_status", "validate_parameter 후보"]
    blob = " ".join(events[0].details)
    assert "장문" not in blob
    assert "planner" not in blob.lower()


def test_replan_and_tool_details_are_observable_fields():
    from app.schemas import ToolResult

    events, progress_fn = _recorder()
    emit_replan(progress_fn, "validate_parameter", round_index=2)
    emit_tool(
        progress_fn,
        "validate_parameter",
        ToolResult(
            tool="validate_parameter",
            status="SUCCESS",
            data={
                "parameter_name": "business_date",
                "parameter_value": "20260903",
                "expected_value": "20260904",
                "is_valid": False,
                "raw_dump": {"secret": "nope"},
            },
        ),
        round_index=2,
    )
    assert events[0].details == [
        "이전 점검만으로 원인 확정 부족",
        "다음 점검: validate_parameter",
    ]
    tool_event = events[1]
    assert tool_event.title == "Tool 실행 · validate_parameter"
    assert "parameter_name=business_date" in tool_event.details
    assert "parameter_value=20260903" in tool_event.details
    assert "expected_value=20260904" in tool_event.details
    assert "is_valid=False" in tool_event.details
    assert "raw_dump" not in " ".join(tool_event.details)
    assert "secret" not in " ".join(tool_event.details)


def test_evidence_details_use_final_evidence_not_counts():
    from app.schemas import ToolResult

    lines = evidence_details(
        [
            "check_file_status: exists=False, received=False",
            "validate_parameter: is_valid=False",
            "chain_of_thought: do not show",
            '{"path": "/tmp/raw.json"}',
        ],
        [
            ToolResult(
                tool="check_file_status",
                status="SUCCESS",
                data={"path": "/data/in/sales_20260903.csv", "exists": False},
            )
        ],
    )
    assert 2 <= len(lines) <= 4
    assert "check_file_status: exists=False, received=False" in lines
    assert "validate_parameter: is_valid=False" in lines
    assert all("chain_of_thought" not in line.lower() for line in lines)
    assert all(not line.lstrip().startswith("{") for line in lines)
    assert all("몇 건" not in line for line in lines)

    events, progress_fn = _recorder()
    emit_evidence(
        progress_fn,
        evidence=['{"path": "/tmp/raw.json", "dump": true}'],
        tool_results=[
            ToolResult(
                tool="check_file_status",
                status="SUCCESS",
                data={
                    "path": "/data/in/sales_20260903.csv",
                    "exists": False,
                    "received": False,
                },
            )
        ],
    )
    blob = " ".join(events[0].details)
    assert "exists=False" in blob
    assert "received=False" in blob
    assert "/tmp/raw.json" not in blob
    assert "몇 건 확보" not in blob


def test_critic_and_reflection_details_stay_short():
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
                    description="내부 장문 reasoning",
                    related_evidence=["x"],
                    blocking=True,
                )
            ],
            revision_reason="private critic prose",
        ),
    )
    assert events[0].details[0] == "REVISE"
    assert events[0].details[1] == "issue type: EVIDENCE_CONFLICT"
    assert "evidence_consistent" not in " ".join(events[0].details)
    assert "장문" not in " ".join(events[0].details)
    emit_reflection(
        progress_fn,
        revised=True,
        original_cause="FILE_NOT_RECEIVED",
        final_cause="INVALID_BUSINESS_DATE",
    )
    assert events[1].details == ["FILE_NOT_RECEIVED → INVALID_BUSINESS_DATE"]
    assert all(not contains_private_cot(item) for item in events)


def test_format_operator_progress_groups_and_hides_raw_fields():
    from app.schemas import ToolResult

    events, progress_fn = _recorder()
    emit_validation(
        progress_fn,
        ValidationResult(
            decision=ValidationDecision.PROCEED,
            reasons=["배치 로그로 보입니다."],
        ),
    )
    emit_log_analysis(
        progress_fn,
        {
            "error_messages": ["FileNotFoundError"],
            "return_code": "12",
            "job_name": "DAILY_SALES_LOAD",
            "input_path": "/data/in/sales_20260903.csv",
        },
    )
    emit_hypotheses(
        progress_fn,
        [
            {"cause_code": "FILE_NOT_RECEIVED", "cause_name": "파일 미수신"},
            {"cause_code": "INVALID_FILE_PATH", "cause_name": "파일 경로 오류"},
        ],
    )
    emit_tool(
        progress_fn,
        "check_file_status",
        ToolResult(
            tool="check_file_status",
            status="SUCCESS",
            data={"path": "/data/in/sales_20260903.csv", "exists": False},
        ),
    )
    emit_tool(
        progress_fn,
        "validate_parameter",
        ToolResult(
            tool="validate_parameter",
            status="SUCCESS",
            data={
                "parameter_name": "business_date",
                "parameter_value": "20260903",
                "expected_value": "20260901",
                "is_valid": False,
            },
        ),
    )
    emit_evidence(
        progress_fn,
        evidence=[
            "validate_parameter: parameter_value=20260903, expected_value=20260901",
        ],
    )
    emit_critic(
        progress_fn,
        CriticResult(
            verdict="PASS",
            evidence_consistent=True,
            diagnosis_level_appropriate=True,
            owner_consistent=True,
        ),
    )
    text = format_operator_progress(events)
    assert "✓ **로그 분석**" in text
    assert "주요 오류: FileNotFoundError" in text
    assert "작업: DAILY_SALES_LOAD" in text
    assert "✓ **원인 후보**" in text
    assert "파일 미수신" in text
    assert "파일 경로 오류" in text
    assert "✓ **추가 점검**" in text
    assert "파일 상태 확인 → 실패" in text
    assert "실행일자 검증 → 불일치 확인" in text
    assert "✓ **근거 종합**" in text
    assert "business_date: 20260903" in text
    assert "expected: 20260901" in text
    assert "✓ **최종 검증**" in text
    assert "진단 근거 일관성 확인 완료" in text
    assert "\n- " not in text
    assert "\n* " not in text
    for hidden in (
        "final_cause_code",
        "verdict",
        "revised",
        "issue types",
        "evidence_consistent",
        "PASS",
        "False",
        "[]",
        "FILE_NOT_RECEIVED",
        "check_file_status",
        "validate_parameter",
    ):
        assert hidden not in text

    prose_events, prose_fn = _recorder()
    emit_tool(
        prose_fn,
        "validate_parameter",
        ToolResult(
            tool="validate_parameter",
            status="SUCCESS",
            data={
                "parameter_name": "business_date",
                "parameter_value": "20260831",
                "expected_value": "20260901",
                "is_valid": False,
            },
        ),
    )
    emit_evidence(
        prose_fn,
        evidence=["로그에서 FileNotFoundError가 확인됨"],
    )
    prose_text = format_operator_progress(prose_events)
    assert "business_date: 20260831" in prose_text
    assert "expected: 20260901" in prose_text
    assert "False" not in prose_text
    running = format_operator_progress(events, running_title="최종 검증")
    assert "진행 중: **최종 검증**" in running
    event = ProgressEvent(step=STEP_TOOL, title="Tool 실행", status="running")
    assert operator_running_label(event) == "추가 점검"
