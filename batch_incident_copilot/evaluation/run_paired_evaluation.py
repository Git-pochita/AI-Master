from __future__ import annotations

import json
import signal
import sys
import time
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import llm_client
from app.critic import cause_revision_allowed
from app.planning import diagnose_v2
from app.v3 import diagnose_v3
from config import settings
from evaluation.evaluator import evaluate_payload, load_ground_truth
from evaluation.paired import aggregate_paired_results
from evaluation.report import write_json
from evaluation.run_evaluation import REQUEST_TIMEOUT_SECONDS, _create_evaluation_client
from main import save_result


ARTIFACT_LABEL = "challenge33_paired"


def _run_once(fn: Callable):
    previous_handler = signal.getsignal(signal.SIGALRM)

    def _raise_timeout(_signum, _frame):
        raise TimeoutError(
            f"paired evaluation request exceeded {REQUEST_TIMEOUT_SECONDS} seconds"
        )

    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.alarm(REQUEST_TIMEOUT_SECONDS)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def evaluate_paired_case(
    case_id: str,
    ground_truth: dict,
    log_text: str,
    *,
    v2_fn=diagnose_v2,
    v3_fn=diagnose_v3,
) -> tuple[dict, object, object]:
    started = time.perf_counter()
    v2_result = _run_once(lambda: v2_fn(log_text, case_id=case_id))
    v3_result = _run_once(
        lambda: v3_fn(log_text, case_id=case_id, v2_result=v2_result)
    )
    v2_payload = v2_result.model_dump()
    v3_payload = v3_result.model_dump()
    v2_metrics = evaluate_payload(v2_payload, ground_truth)
    v3_metrics = evaluate_payload(v3_payload, ground_truth)
    critic = v3_result.critic_result
    guard_allowed = False
    if critic.verdict == "REVISE":
        guard_allowed = cause_revision_allowed(
            critic,
            current_cause=v2_result.final_cause_code,
            log_text=log_text,
            extracted_info=v2_result.extracted_info,
            tool_results=v2_result.tool_results,
        )
    cause_changed = v3_result.final_cause_code != v2_result.final_cause_code
    row = {
        "case_id": case_id,
        "run_status": "success",
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "actual_cause_code": ground_truth.get("actual_cause_code"),
        "v2": v2_metrics,
        "v3": v3_metrics,
        "v2_cause_code": v2_result.final_cause_code,
        "v2_diagnosis_level": v2_result.diagnosis_level,
        "critic_verdict": critic.verdict,
        "critic_recommended_cause_code": critic.recommended_cause_code,
        "guard_allowed": guard_allowed,
        "guard_decision": (
            "ALLOW"
            if guard_allowed
            else "BLOCK"
            if critic.verdict == "REVISE"
            else "NOT_APPLICABLE"
        ),
        "v3_cause_code": v3_result.final_cause_code,
        "v3_diagnosis_level": v3_result.diagnosis_level,
        "cause_changed": cause_changed,
        "diagnosis_level_changed": (
            v3_result.diagnosis_level != v2_result.diagnosis_level
        ),
        "owner_changed": v3_result.owner != v2_result.owner,
        "correctness_transition": (
            f"{'correct' if v2_metrics['final_diagnosis_correct'] else 'incorrect'}"
            f"_to_{'correct' if v3_metrics['final_diagnosis_correct'] else 'incorrect'}"
        ),
    }
    return row, v2_result, v3_result


def main() -> int:
    llm_client.create_client = _create_evaluation_client
    ground_truth = load_ground_truth()
    reports_dir = settings.REPORTS_DIR / ARTIFACT_LABEL
    results_dir = settings.PROJECT_ROOT / "results" / "evaluation_runs" / ARTIFACT_LABEL
    rows: list[dict] = []
    for case_id, gt in ground_truth.items():
        print(f"[paired] {case_id}", flush=True)
        log_path = settings.SAMPLE_LOGS_DIR / f"{case_id}.log"
        try:
            log_text = log_path.read_text(encoding="utf-8")
            row, v2_result, v3_result = evaluate_paired_case(
                case_id, gt, log_text
            )
            save_result(case_id, v2_result.model_dump(), results_dir / "v2")
            save_result(case_id, v3_result.model_dump(), results_dir / "v3")
            write_json(results_dir / "paired_cases" / f"{case_id}.json", row)
            rows.append(row)
        except Exception as exc:
            rows.append(
                {
                    "case_id": case_id,
                    "run_status": "failed",
                    "actual_cause_code": gt.get("actual_cause_code"),
                    "error": str(exc),
                }
            )
    summary = aggregate_paired_results(rows)
    summary["model"] = settings.AZURE_OPENAI_MODEL
    summary["pairing"] = (
        "각 case의 V2 Producer를 1회 실행하고 같은 v2_result를 V3에 주입했습니다."
    )
    write_json(reports_dir / "paired_summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "cases"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
