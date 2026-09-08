import json
from pathlib import Path

from app.critic import CriticLLMDraft
from app.schemas import V2DiagnosisResult
from app.v3 import diagnose_v3
from evaluation.evaluator import load_ground_truth
from evaluation.paired import aggregate_paired_results
from evaluation.run_paired_evaluation import evaluate_paired_case


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _row(
    case_id: str,
    *,
    v2_correct: bool,
    v3_correct: bool,
    verdict: str = "PASS",
    cause_changed: bool = False,
    guard_allowed: bool = False,
) -> dict:
    return {
        "case_id": case_id,
        "run_status": "success",
        "v2": {
            "final_diagnosis_correct": v2_correct,
            "diagnosis_level_correct": True,
            "owner_correct": True,
            "hypothesis_recall_hit": True,
        },
        "v3": {
            "final_diagnosis_correct": v3_correct,
            "diagnosis_level_correct": True,
            "owner_correct": True,
            "hypothesis_recall_hit": True,
        },
        "critic_verdict": verdict,
        "guard_allowed": guard_allowed,
        "cause_changed": cause_changed,
    }


def test_paired_aggregate_counts_transitions_and_applied_precision():
    summary = aggregate_paired_results(
        [
            _row("fixed", v2_correct=False, v3_correct=True, verdict="REVISE", cause_changed=True, guard_allowed=True),
            _row("regressed", v2_correct=True, v3_correct=False, verdict="REVISE", cause_changed=True, guard_allowed=True),
            _row("protected", v2_correct=True, v3_correct=True, verdict="REVISE"),
            _row("still-wrong", v2_correct=False, v3_correct=False),
        ]
    )

    assert summary["v2_to_v3"]["incorrect_to_correct"] == 1
    assert summary["v2_to_v3"]["correct_to_incorrect"] == 1
    assert summary["v2_to_v3"]["correct_to_correct"] == 1
    assert summary["v2_to_v3"]["incorrect_to_incorrect"] == 1
    assert summary["v3_effect"]["cause_change_requests"] == 3
    assert summary["v3_effect"]["applied_cause_changes"] == 2
    assert summary["v3_effect"]["guard_blocked_revisions"] == 1
    assert summary["v3_effect"]["applied_revision_precision"] == 0.5
    assert summary["v3_effect"]["net_corrected_cases"] == 0


def test_applied_precision_is_none_when_no_cause_change_is_applied():
    summary = aggregate_paired_results(
        [_row("protected", v2_correct=True, v3_correct=True, verdict="REVISE")]
    )

    assert summary["v3_effect"]["applied_cause_changes"] == 0
    assert summary["v3_effect"]["applied_revision_precision"] is None
    assert summary["v3_effect"]["guard_blocked_revisions"] == 1


def test_paired_case_runs_v2_once_and_passes_same_result_to_v3():
    fixture = json.loads(
        (PROJECT_ROOT / "tests" / "fixtures" / "v2_planning" / "F-01.json").read_text(
            encoding="utf-8"
        )
    )
    shared_v2 = V2DiagnosisResult.model_validate(fixture)
    calls = {"v2": 0, "v3": 0}

    def v2_fn(_log_text, *, case_id):
        calls["v2"] += 1
        assert case_id == "F-01"
        return shared_v2

    def v3_fn(log_text, *, case_id, v2_result):
        calls["v3"] += 1
        assert case_id == "F-01"
        assert v2_result is shared_v2
        return diagnose_v3(
            log_text,
            case_id=case_id,
            v2_result=v2_result,
            critic_fn=lambda *_args, **_kwargs: CriticLLMDraft(),
        )

    row, returned_v2, _v3 = evaluate_paired_case(
        "F-01",
        load_ground_truth()["F-01"],
        (PROJECT_ROOT / "data" / "sample_logs" / "F-01.log").read_text(
            encoding="utf-8"
        ),
        v2_fn=v2_fn,
        v3_fn=v3_fn,
    )

    assert calls == {"v2": 1, "v3": 1}
    assert returned_v2 is shared_v2
    assert row["v2_cause_code"] == row["v3_cause_code"]
