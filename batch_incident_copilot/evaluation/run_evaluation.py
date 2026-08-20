import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ui_service import public_error_message
from config import settings
from evaluation.evaluator import evaluate_payload, load_ground_truth
from evaluation.metrics import aggregate_case_metrics
from evaluation.report import render_comparison_markdown, write_json
from main import run_diagnosis, save_result

RETRY_ATTEMPTS = 3


def sample_log_path(case_id: str) -> Path:
    return settings.SAMPLE_LOGS_DIR / f"{case_id}.log"


def _retry_diagnosis(version: str, log_text: str, case_id: str):
    last_error: Exception | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return run_diagnosis(version, log_text, case_id)
        except Exception as exc:
            last_error = exc
            if attempt >= RETRY_ATTEMPTS:
                break
            time.sleep(2 ** (attempt - 1))
    assert last_error is not None
    raise last_error


def evaluate_one_case(version: str, case_id: str, ground_truth: dict) -> dict:
    log_path = sample_log_path(case_id)
    started = time.perf_counter()
    if not log_path.is_file():
        return {
            "case_id": case_id,
            "run_status": "failed",
            "error": f"sample log가 없습니다: {log_path}",
            "actual_cause_code": ground_truth.get("actual_cause_code"),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    try:
        log_text = log_path.read_text(encoding="utf-8")
        result = _retry_diagnosis(version, log_text, case_id)
        payload = result.model_dump()
        results_dir = settings.V1_RESULTS_DIR if version == "v1" else settings.V0_RESULTS_DIR
        save_result(case_id, payload, results_dir)
        metrics = evaluate_payload(payload, ground_truth)
        metrics["case_id"] = case_id
        metrics["run_status"] = "success"
        metrics["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        metrics["incident_domain"] = ground_truth.get("incident_domain")
        return metrics
    except Exception as exc:
        return {
            "case_id": case_id,
            "run_status": "failed",
            "error": public_error_message(exc),
            "actual_cause_code": ground_truth.get("actual_cause_code"),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "incident_domain": ground_truth.get("incident_domain"),
        }


def run_version(version: str, ground_truth: dict, case_ids: list[str]) -> dict:
    rows = []
    for case_id in case_ids:
        print(f"[{version}] {case_id}", flush=True)
        rows.append(evaluate_one_case(version, case_id, ground_truth[case_id]))
    summary = aggregate_case_metrics(version, rows)
    elapsed = [row.get("elapsed_seconds") or 0 for row in rows]
    summary["average_elapsed_seconds"] = round(sum(elapsed) / len(elapsed), 3) if elapsed else 0.0
    summary["timing_note"] = "local/mock PoC 측정값이며 운영 장애 분석 시간 절감을 의미하지 않습니다."
    summary["model"] = settings.AZURE_OPENAI_MODEL
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Ground Truth 전체 케이스 V0/V1 일괄 평가")
    parser.add_argument(
        "--versions",
        nargs="+",
        default=["v0", "v1"],
        choices=["v0", "v1"],
        help="실행할 버전",
    )
    parser.add_argument(
        "--case-id",
        nargs="*",
        default=None,
        help="지정하면 해당 case만 실행합니다.",
    )
    args = parser.parse_args()

    ground_truth = load_ground_truth()
    case_ids = list(args.case_id or ground_truth.keys())
    missing = [case_id for case_id in case_ids if case_id not in ground_truth]
    if missing:
        print(f"ground_truth.json에 없는 case_id: {missing}", file=sys.stderr)
        return 1

    reports_dir = settings.REPORTS_DIR
    summaries: dict[str, dict] = {}
    for version in args.versions:
        summary = run_version(version, ground_truth, case_ids)
        summaries[version] = summary
        out_path = write_json(reports_dir / f"{version}_summary.json", summary)
        print(f"saved: {out_path}", flush=True)
        print(json.dumps({k: v for k, v in summary.items() if k != "cases"}, ensure_ascii=False, indent=2))

    markdown = render_comparison_markdown(
        v0=summaries.get("v0"),
        v1=summaries.get("v1"),
        ground_truth={case_id: ground_truth[case_id] for case_id in case_ids},
        model=settings.AZURE_OPENAI_MODEL,
        notes=[],
    )
    md_path = reports_dir / "v0_vs_v1.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")
    print(f"saved: {md_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
