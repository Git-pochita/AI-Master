from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent_events import build_agent_events
from app.cause_codes import CAUSE_CODE_NAMES
from app.critic import (
    CRITIC_ALLOWED_KEYS,
    CRITIC_DENIED_KEYS,
    CriticLLMDraft,
    build_critic_input,
    cause_revision_allowed,
    run_critic,
)
from app.schemas import (
    CriticIssue,
    CriticIssueType,
    CriticResult,
    StopReason,
    V2DiagnosisResult,
    V3DiagnosisResult,
)
from app.v3 import (
    MAX_CRITIC_CALLS,
    MAX_REVISION_CALLS,
    RevisionDraft,
    diagnose_v3,
)
from main import run_diagnosis


V2_DIR = PROJECT_ROOT / "results" / "v2_planning"
LOG_DIR = PROJECT_ROOT / "data" / "sample_logs"
FAILED_CATALOG = "카탈로그에 경로가 없습니다"


def _load_v2(case_id: str) -> V2DiagnosisResult:
    payload = json.loads((V2_DIR / f"{case_id}.json").read_text(encoding="utf-8"))
    return V2DiagnosisResult.model_validate(payload)


def _load_log(case_id: str) -> str:
    return (LOG_DIR / f"{case_id}.log").read_text(encoding="utf-8")


def _pass_draft(*_args, **_kwargs) -> CriticLLMDraft:
    return CriticLLMDraft()


def _issue(issue_type: CriticIssueType, related: list[str] | None = None) -> CriticIssue:
    return CriticIssue(
        issue_type=issue_type,
        description=issue_type.value,
        related_evidence=list(related or []),
        blocking=True,
    )


def _conflict_better_draft(token: str) -> CriticLLMDraft:
    return CriticLLMDraft(
        evidence_consistent=False,
        issues=[
            _issue(CriticIssueType.EVIDENCE_CONFLICT, [token]),
            _issue(CriticIssueType.BETTER_SUPPORTED_CAUSE, [token]),
        ],
        recommended_cause_code="INVALID_FILE_PATH",
    )


def _revision_draft(v2: V2DiagnosisResult, cause: str, **overrides) -> RevisionDraft:
    payload = {
        "summary": "revision",
        "final_cause_code": cause,
        "final_cause_name": CAUSE_CODE_NAMES.get(cause, cause),
        "diagnosis_level": v2.diagnosis_level,
        "owner": v2.owner,
        "evidence": list(v2.evidence),
        "limitations": list(v2.limitations),
        "recommended_actions": list(v2.recommended_actions),
    }
    payload.update(overrides)
    return RevisionDraft.model_validate(payload)


def _run(
    case_id: str,
    critic_fn,
    revise_fn=None,
    v2: V2DiagnosisResult | None = None,
) -> V3DiagnosisResult:
    result_v2 = v2 or _load_v2(case_id)
    return diagnose_v3(
        _load_log(case_id),
        case_id=case_id,
        v2_result=result_v2,
        critic_fn=critic_fn,
        revise_fn=revise_fn,
        diagnose_v2_fn=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("diagnose_v2 should not run when v2_result is provided")
        ),
    )


def test_critic_result_schema_defaults():
    result = CriticResult(
        verdict="PASS",
        evidence_consistent=True,
        diagnosis_level_appropriate=True,
        owner_consistent=True,
    )
    assert result.issues == []
    assert result.recommended_cause_code is None
    assert result.recommended_owner is None
    assert result.revision_reason == ""


def test_critic_result_rejects_invalid_canonical_recommendation():
    with pytest.raises(ValidationError):
        CriticResult(
            verdict="REVISE",
            evidence_consistent=False,
            diagnosis_level_appropriate=True,
            owner_consistent=True,
            recommended_cause_code="NOT_A_CODE",
        )


def test_run_critic_sanitizes_invalid_llm_recommendation():
    v2 = _load_v2("F-01")
    draft = CriticLLMDraft(recommended_cause_code="NOT_A_CODE")
    result = run_critic(_load_log("F-01"), v2, critic_fn=lambda *_a, **_k: draft)
    assert result.recommended_cause_code is None


def test_pass_recommended_cause_is_null():
    v2 = _load_v2("F-01")
    result = run_critic(_load_log("F-01"), v2, critic_fn=_pass_draft)
    assert result.verdict == "PASS"
    assert result.recommended_cause_code is None


def test_evidence_conflict_only_does_not_change_cause():
    v2 = _load_v2("F-02")
    log = _load_log("F-02")

    def critic_fn(*_a, **_k):
        return CriticLLMDraft(
            evidence_consistent=False,
            issues=[_issue(CriticIssueType.EVIDENCE_CONFLICT, ["sales_20260901.csv"])],
            recommended_cause_code="INVALID_FILE_PATH",
        )

    critic = run_critic(log, v2, critic_fn=critic_fn)
    assert critic.verdict == "REVISE"
    assert cause_revision_allowed(
        critic,
        current_cause=v2.final_cause_code,
        log_text=log,
        extracted_info=v2.extracted_info,
        tool_results=v2.tool_results,
    ) is False

    result = _run(
        "F-02",
        critic_fn,
        revise_fn=lambda _log, producer, _critic: _revision_draft(
            producer, "INVALID_FILE_PATH"
        ),
    )
    assert result.final_cause_code == "FILE_NOT_RECEIVED"
    assert result.original_v2_cause_code == "FILE_NOT_RECEIVED"


def test_better_supported_only_does_not_change_cause():
    v2 = _load_v2("F-02")
    revise_calls = {"n": 0}

    def critic_fn(*_a, **_k):
        return CriticLLMDraft(
            evidence_consistent=True,
            issues=[
                _issue(CriticIssueType.BETTER_SUPPORTED_CAUSE, ["sales_20260901.csv"])
            ],
            recommended_cause_code="INVALID_FILE_PATH",
        )

    def revise_fn(*_a, **_k):
        revise_calls["n"] += 1
        return _revision_draft(v2, "INVALID_FILE_PATH")

    result = _run("F-02", critic_fn, revise_fn=revise_fn)
    assert result.critic_result.verdict == "PASS"
    assert result.final_cause_code == "FILE_NOT_RECEIVED"
    assert result.revised is False
    assert revise_calls["n"] == 0


def test_both_blocking_issues_allow_cause_revision():
    token = "sales_20260901.csv"
    result = _run(
        "F-02",
        lambda *_a, **_k: _conflict_better_draft(token),
        revise_fn=lambda _log, producer, _critic: _revision_draft(
            producer, "INVALID_FILE_PATH"
        ),
    )
    assert result.critic_result.verdict == "REVISE"
    assert result.final_cause_code == "INVALID_FILE_PATH"
    assert result.revised is True


def test_ambiguous_defaults_to_pass():
    result = _run("F-01", _pass_draft)
    assert result.critic_result.verdict == "PASS"
    assert result.final_cause_code == "FILE_NOT_RECEIVED"
    assert result.revised is False


def test_failed_evidence_stripped_after_revision():
    v2 = _load_v2("F-06")
    error = v2.tool_results[0].error
    assert error
    tainted = v2.model_copy(update={"evidence": list(v2.evidence) + [error]})

    def revise_fn(_log, producer, _critic):
        return _revision_draft(
            producer,
            producer.final_cause_code,
            evidence=list(producer.evidence) + [error],
            owner="FILE_OPS",
        )

    result = _run("F-06", _pass_draft, revise_fn=revise_fn, v2=tainted)
    assert result.critic_result.verdict == "REVISE"
    assert any(
        item.issue_type == CriticIssueType.FAILED_EVIDENCE_USED
        for item in result.critic_result.issues
    )
    assert error not in result.evidence
    assert FAILED_CATALOG not in "\n".join(result.evidence)
    assert result.owner == "BATCH_OPERATION"
    assert result.final_cause_code == "FILE_NOT_RECEIVED"


def test_diagnosis_level_capped_without_success_tools():
    v2 = _load_v2("F-06").model_copy(update={"diagnosis_level": "확인됨"})

    def revise_fn(_log, producer, _critic):
        return _revision_draft(producer, producer.final_cause_code, diagnosis_level="확인됨")

    result = _run("F-06", _pass_draft, revise_fn=revise_fn, v2=v2)
    assert any(
        item.issue_type == CriticIssueType.DIAGNOSIS_LEVEL_TOO_HIGH
        for item in result.critic_result.issues
    )
    assert result.diagnosis_level == "추정"
    assert result.final_cause_code == "FILE_NOT_RECEIVED"


def test_owner_not_changed_unnecessarily():
    token = "sales_20260901.csv"
    result = _run(
        "F-02",
        lambda *_a, **_k: _conflict_better_draft(token),
        revise_fn=lambda _log, producer, _critic: _revision_draft(
            producer, "INVALID_FILE_PATH", owner="FILE_OPS"
        ),
    )
    assert result.owner == "BATCH_OPERATION"
    assert result.original_v2_owner == "BATCH_OPERATION"


def test_critic_called_once_revision_at_most_once():
    critic_calls = {"n": 0}
    revise_calls = {"n": 0}
    v2 = _load_v2("F-02")

    def critic_fn(*_a, **_k):
        critic_calls["n"] += 1
        return _conflict_better_draft("sales_20260901.csv")

    def revise_fn(*_a, **_k):
        revise_calls["n"] += 1
        return _revision_draft(v2, "INVALID_FILE_PATH")

    result = _run("F-02", critic_fn, revise_fn=revise_fn)
    assert critic_calls["n"] == 1
    assert revise_calls["n"] == 1
    assert result.final_cause_code == "INVALID_FILE_PATH"
    assert MAX_CRITIC_CALLS == 1
    assert MAX_REVISION_CALLS == 1


def test_pass_does_not_call_revision():
    revise_calls = {"n": 0}

    def revise_fn(*_a, **_k):
        revise_calls["n"] += 1
        raise AssertionError("PASS must not revise")

    _run("F-01", _pass_draft, revise_fn=revise_fn)
    assert revise_calls["n"] == 0


def test_no_additional_tool_execution_in_v3_modules():
    critic_src = (PROJECT_ROOT / "app" / "critic.py").read_text(encoding="utf-8")
    v3_src = (PROJECT_ROOT / "app" / "v3.py").read_text(encoding="utf-8")
    assert "execute_tool" not in critic_src
    assert "execute_tool" not in v3_src


def test_v2_result_is_not_mutated():
    original = _load_v2("F-01")
    before = original.model_dump()
    result = _run("F-01", _pass_draft, v2=original)
    assert original.model_dump() == before
    assert original.version == "v2"
    assert result.version == "v3"


def test_f01_pass_keeps_file_not_received():
    result = _run("F-01", _pass_draft)
    assert result.critic_result.verdict == "PASS"
    assert result.final_cause_code == "FILE_NOT_RECEIVED"
    assert result.revised is False


def test_f02_revise_candidate_invalid_file_path():
    result = _run(
        "F-02",
        lambda *_a, **_k: _conflict_better_draft("sales_20260901.csv"),
        revise_fn=lambda _log, producer, _critic: _revision_draft(
            producer, "INVALID_FILE_PATH"
        ),
    )
    assert result.critic_result.verdict == "REVISE"
    assert result.final_cause_code == "INVALID_FILE_PATH"
    assert result.original_v2_cause_code == "FILE_NOT_RECEIVED"


def test_f03_pass_keeps_file_not_received():
    result = _run("F-03", _pass_draft)
    assert result.critic_result.verdict == "PASS"
    assert result.final_cause_code == "FILE_NOT_RECEIVED"


def test_f04_revise_candidate_invalid_file_path():
    result = _run(
        "F-04",
        lambda *_a, **_k: _conflict_better_draft("partner_20260901.csv"),
        revise_fn=lambda _log, producer, _critic: _revision_draft(
            producer, "INVALID_FILE_PATH"
        ),
    )
    assert result.critic_result.verdict == "REVISE"
    assert result.final_cause_code == "INVALID_FILE_PATH"
    assert result.original_v2_cause_code == "FILE_NOT_RECEIVED"


def test_f05_pass_keeps_invalid_business_date():
    result = _run("F-05", _pass_draft)
    assert result.critic_result.verdict == "PASS"
    assert result.final_cause_code == "INVALID_BUSINESS_DATE"


def test_f06_failed_tool_error_not_used_as_evidence():
    result = _run("F-06", _pass_draft)
    joined = "\n".join(result.evidence)
    assert FAILED_CATALOG not in joined
    assert result.diagnosis_level != "확인됨"
    assert result.diagnosis_level == "추정"
    assert result.critic_result.verdict == "PASS"


@pytest.mark.parametrize("case_id", ["P-05", "D-01", "C-06"])
def test_regression_pass_keeps_v2_cause(case_id: str):
    v2 = _load_v2(case_id)
    result = _run(case_id, _pass_draft)
    assert result.critic_result.verdict == "PASS"
    assert result.final_cause_code == v2.final_cause_code
    assert result.revised is False


def test_critic_input_allowlist_excludes_gt_and_planner_rationale():
    v2 = _load_v2("F-02")
    payload = build_critic_input(_load_log("F-02"), v2)
    assert set(payload) == set(CRITIC_ALLOWED_KEYS)
    for key in CRITIC_DENIED_KEYS:
        assert key not in payload
    blob = json.dumps(payload, ensure_ascii=False)
    assert "actual_cause_code" not in blob
    assert "ground_truth" not in blob
    for item in v2.selected_tools:
        if item.reason:
            assert item.reason not in blob
    for item in v2.planning_trace:
        if item.reason:
            assert item.reason not in blob
    assert "INVALID_FILE_PATH가 정답" not in blob


def test_v3_schema_includes_investigation_and_critic_fields():
    result = _run("F-01", _pass_draft)
    dumped = result.model_dump()
    assert dumped["version"] == "v3"
    for key in (
        "extracted_info",
        "initial_hypotheses",
        "working_hypotheses",
        "investigation_plan",
        "unresolved_questions",
        "planning_trace",
        "selected_tools",
        "tool_results",
        "stop_reason",
        "critic_result",
        "revised",
        "original_v2_cause_code",
        "original_v2_diagnosis_level",
        "original_v2_owner",
        "final_cause_code",
        "final_cause_name",
        "diagnosis_level",
        "owner",
        "evidence",
        "limitations",
        "recommended_actions",
    ):
        assert key in dumped
    V3DiagnosisResult.model_validate(dumped)


def test_agent_events_pass_has_no_reflection():
    payload = _run("F-01", _pass_draft).model_dump()
    events = build_agent_events("v3", payload)
    steps = [item.step for item in events]
    assert "critic_check" in steps
    assert "evidence_consistency" in steps
    assert "revision_requested" not in steps
    assert "reflection" not in steps
    assert "final_revision" not in steps
    for event in events:
        assert "revision_reason" not in event.metadata
        assert event.source == "v3"


def test_agent_events_revise_and_final_revision():
    payload = _run(
        "F-02",
        lambda *_a, **_k: _conflict_better_draft("sales_20260901.csv"),
        revise_fn=lambda _log, producer, _critic: _revision_draft(
            producer, "INVALID_FILE_PATH"
        ),
    ).model_dump()
    events = build_agent_events("v3", payload)
    steps = [item.step for item in events]
    assert steps.count("critic_check") == 1
    assert "evidence_consistency" in steps
    assert "revision_requested" in steps
    assert "reflection" in steps
    assert "final_revision" in steps
    consistency = next(item for item in events if item.step == "evidence_consistency")
    assert consistency.metadata["verdict"] == "REVISE"
    assert "issue_count" in consistency.metadata
    assert "evidence_consistent" in consistency.metadata
    joined = json.dumps([item.model_dump() for item in events], ensure_ascii=False)
    assert "chain_of_thought" not in joined
    assert "private_reasoning" not in joined


def test_v3_run_diagnosis_dispatch(monkeypatch):
    fake = _run("F-01", _pass_draft)
    monkeypatch.setattr("app.v3.diagnose_v3", lambda *_a, **_k: fake)
    result = run_diagnosis("v3", "log", "unit")
    assert result.version == "v3"


def test_v3_prompts_have_no_case_specific_answers():
    critic = (PROJECT_ROOT / "prompts" / "v3_critic_prompt.txt").read_text(
        encoding="utf-8"
    )
    revision = (PROJECT_ROOT / "prompts" / "v3_revision_prompt.txt").read_text(
        encoding="utf-8"
    )
    for text in (critic, revision):
        assert "F-02" not in text
        assert "F-04" not in text
        assert "F-01" not in text
        assert "sale_20260901.csv" not in text
        assert "partnr_20260901.csv" not in text


def test_v3_modules_have_no_case_id_hardcoding():
    for rel in ("app/critic.py", "app/v3.py"):
        source = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        assert "if case_id" not in source
        assert "F-02" not in source
        assert "F-04" not in source


def test_v2_planning_frozen():
    planning = (PROJECT_ROOT / "app" / "planning.py").read_text(encoding="utf-8")
    prompt = (PROJECT_ROOT / "prompts" / "v2_planning_prompt.txt").read_text(
        encoding="utf-8"
    )
    assert "diagnose_v3" not in planning
    assert "Critic" not in planning
    assert "critic" not in planning
    assert "v3" not in planning
    assert "critic" not in prompt


def test_streamlit_exposes_v3_without_revision_reason():
    source = (PROJECT_ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "V3 Critic / Reflection" in source
    assert "revision_reason" not in source


def test_cli_and_eval_accept_v3():
    main_src = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    eval_src = (PROJECT_ROOT / "evaluation" / "run_evaluation.py").read_text(
        encoding="utf-8"
    )
    assert '"v3"' in main_src
    assert '"v3"' in eval_src
    assert "v2_refined_summary.json" in eval_src
    assert "v1_vs_v2_refined.md" in eval_src


def test_evaluate_payload_adds_v3_fields_without_changing_core_metrics():
    from evaluation.evaluator import evaluate_payload, load_ground_truth

    gt = load_ground_truth()["F-02"]
    payload = {
        "version": "v3",
        "case_id": "F-02",
        "initial_hypotheses": [
            {
                "cause_code": "FILE_NOT_RECEIVED",
                "cause_name": "파일 미수신",
                "evidence": ["log"],
            }
        ],
        "selected_tools": [{"selected_tool": "check_file_status"}],
        "tool_results": [],
        "final_cause_code": "INVALID_FILE_PATH",
        "diagnosis_level": "확인됨",
        "owner": "BATCH_OPERATION",
        "revised": True,
        "original_v2_cause_code": "FILE_NOT_RECEIVED",
        "original_v2_diagnosis_level": "확인됨",
        "original_v2_owner": "BATCH_OPERATION",
        "critic_result": {"verdict": "REVISE", "issues": []},
    }
    metrics = evaluate_payload(payload, gt)
    assert metrics["final_diagnosis_correct"] is True
    assert metrics["revised"] is True
    assert metrics["original_v2_cause_code"] == "FILE_NOT_RECEIVED"
    assert metrics["critic_verdict"] == "REVISE"
    assert metrics["required_tool_recall"] == 1.0
