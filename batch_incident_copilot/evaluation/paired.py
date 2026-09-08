from __future__ import annotations

from typing import Any


def _accuracy(rows: list[dict[str, Any]], version: str, field: str) -> float:
    if not rows:
        return 0.0
    hits = sum(
        1
        for row in rows
        if row.get("run_status") == "success"
        and bool((row.get(version) or {}).get(field))
    )
    return hits / len(rows)


def aggregate_paired_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [row for row in rows if row.get("run_status") == "success"]
    transitions = {
        "incorrect_to_correct": 0,
        "correct_to_incorrect": 0,
        "correct_to_correct": 0,
        "incorrect_to_incorrect": 0,
    }
    for row in successful:
        v2_correct = bool((row.get("v2") or {}).get("final_diagnosis_correct"))
        v3_correct = bool((row.get("v3") or {}).get("final_diagnosis_correct"))
        if not v2_correct and v3_correct:
            transitions["incorrect_to_correct"] += 1
        elif v2_correct and not v3_correct:
            transitions["correct_to_incorrect"] += 1
        elif v2_correct and v3_correct:
            transitions["correct_to_correct"] += 1
        else:
            transitions["incorrect_to_incorrect"] += 1

    requests = [
        row for row in successful if row.get("critic_verdict") == "REVISE"
    ]
    applied = [row for row in successful if row.get("cause_changed") is True]
    corrected_applied = [
        row
        for row in applied
        if bool((row.get("v3") or {}).get("final_diagnosis_correct"))
    ]
    blocked = [row for row in requests if row.get("guard_allowed") is not True]

    return {
        "total_cases": len(rows),
        "evaluated_cases": len(successful),
        "failed_runs": len(rows) - len(successful),
        "v2": {
            "final_diagnosis_accuracy": _accuracy(
                rows, "v2", "final_diagnosis_correct"
            ),
            "diagnosis_level_accuracy": _accuracy(
                rows, "v2", "diagnosis_level_correct"
            ),
            "owner_accuracy": _accuracy(rows, "v2", "owner_correct"),
            "hypothesis_recall": _accuracy(
                rows, "v2", "hypothesis_recall_hit"
            ),
        },
        "v3": {
            "final_diagnosis_accuracy": _accuracy(
                rows, "v3", "final_diagnosis_correct"
            ),
            "diagnosis_level_accuracy": _accuracy(
                rows, "v3", "diagnosis_level_correct"
            ),
            "owner_accuracy": _accuracy(rows, "v3", "owner_correct"),
            "hypothesis_recall": _accuracy(
                rows, "v3", "hypothesis_recall_hit"
            ),
        },
        "v2_to_v3": transitions,
        "v3_effect": {
            "cause_change_requests": len(requests),
            "applied_cause_changes": len(applied),
            "guard_blocked_revisions": len(blocked),
            "applied_revision_precision": (
                len(corrected_applied) / len(applied) if applied else None
            ),
            "net_corrected_cases": (
                transitions["incorrect_to_correct"]
                - transitions["correct_to_incorrect"]
            ),
        },
        "cases": rows,
    }
