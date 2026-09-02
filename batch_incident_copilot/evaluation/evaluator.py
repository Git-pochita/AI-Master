import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas import DiagnosisResult, Hypothesis
from config import settings
from evaluation.metrics import (
    required_tool_recall,
    selected_tool_names,
    tool_failure_count,
    unnecessary_tool_count,
    unnecessary_tool_rate,
)


def load_ground_truth() -> dict:
    return json.loads(settings.GROUND_TRUTH_PATH.read_text(encoding="utf-8"))


def _hypothesis_codes(items: list) -> set[str]:
    codes = set()
    for item in items:
        if isinstance(item, Hypothesis):
            codes.add(item.cause_code)
        elif isinstance(item, dict) and item.get("cause_code"):
            codes.add(item["cause_code"])
    return codes


def evaluate_metrics(
    *,
    case_id: str | None,
    predicted_codes: set[str],
    final_cause_code: str,
    diagnosis_level: str,
    owner: str,
    ground_truth: dict,
    expected_level_key: str,
    selected_tools: list[str] | None = None,
    tool_results: list | None = None,
) -> dict:
    actual_cause_code = ground_truth.get("actual_cause_code")
    expected_codes = set(ground_truth.get("expected_hypothesis_codes", []))
    hypothesis_recall_hit = (
        actual_cause_code is not None and actual_cause_code in predicted_codes
    )
    recalled = [actual_cause_code] if hypothesis_recall_hit else []
    expected_level = ground_truth.get(expected_level_key)

    metrics = {
        "case_id": case_id,
        "final_diagnosis_correct": final_cause_code == actual_cause_code,
        "predicted_final_cause_code": final_cause_code,
        "actual_cause_code": actual_cause_code,
        "hypothesis_recall_hit": hypothesis_recall_hit,
        "recalled_hypothesis_codes": recalled,
        "predicted_hypothesis_codes": sorted(predicted_codes),
        "expected_hypothesis_codes": sorted(expected_codes),
        "diagnosis_level_correct": diagnosis_level == expected_level,
        "predicted_diagnosis_level": diagnosis_level,
        expected_level_key: expected_level,
        "owner_correct": owner == ground_truth.get("expected_owner"),
        "predicted_owner": owner,
        "expected_owner": ground_truth.get("expected_owner"),
        "tool_necessity": ground_truth.get("tool_necessity"),
    }
    if selected_tools is not None:
        required = list(ground_truth.get("required_tools") or [])
        payload = {"selected_tools": [{"selected_tool": name} for name in selected_tools]}
        if tool_results is not None:
            payload["tool_results"] = tool_results
        metrics["required_tools"] = required
        metrics["expected_unnecessary_tools"] = list(
            ground_truth.get("unnecessary_tools") or []
        )
        metrics["selected_tools"] = selected_tools
        metrics["required_tool_recall"] = required_tool_recall(required, selected_tools)
        metrics["unnecessary_tool_count"] = unnecessary_tool_count(required, selected_tools)
        metrics["unnecessary_tool_rate"] = unnecessary_tool_rate(required, selected_tools)
        metrics["tool_call_count"] = len(selected_tools)
        metrics["tool_failure_count"] = tool_failure_count(payload)
    return metrics


def _attach_v3_fields(metrics: dict, payload: dict) -> dict:
    if payload.get("version") != "v3":
        return metrics
    critic = payload.get("critic_result") or {}
    if not isinstance(critic, dict):
        critic = critic.model_dump()
    metrics["revised"] = bool(payload.get("revised"))
    metrics["original_v2_cause_code"] = payload.get("original_v2_cause_code")
    metrics["original_v2_diagnosis_level"] = payload.get("original_v2_diagnosis_level")
    metrics["original_v2_owner"] = payload.get("original_v2_owner")
    metrics["critic_verdict"] = critic.get("verdict")
    return metrics


def evaluate_case(result: DiagnosisResult, ground_truth: dict) -> dict:
    return evaluate_metrics(
        case_id=result.case_id,
        predicted_codes={h.cause_code for h in result.hypotheses},
        final_cause_code=result.final_cause_code,
        diagnosis_level=result.diagnosis_level,
        owner=result.owner,
        ground_truth=ground_truth,
        expected_level_key="expected_diagnosis_level_v0",
    )


def evaluate_payload(payload: dict, ground_truth: dict) -> dict:
    is_v1 = "initial_hypotheses" in payload or "selected_tools" in payload
    if is_v1:
        predicted_codes = _hypothesis_codes(payload.get("initial_hypotheses") or [])
        expected_level_key = "expected_diagnosis_level_v1"
    else:
        predicted_codes = _hypothesis_codes(payload.get("hypotheses") or [])
        expected_level_key = "expected_diagnosis_level_v0"
    metrics = evaluate_metrics(
        case_id=payload.get("case_id"),
        predicted_codes=predicted_codes,
        final_cause_code=payload.get("final_cause_code"),
        diagnosis_level=payload.get("diagnosis_level"),
        owner=payload.get("owner"),
        ground_truth=ground_truth,
        expected_level_key=expected_level_key,
        selected_tools=selected_tool_names(payload) if is_v1 else None,
        tool_results=payload.get("tool_results") if is_v1 else None,
    )
    return _attach_v3_fields(metrics, payload)


def evaluate_result_file(result_path: Path, case_id: str | None = None) -> dict:
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    case_id = case_id or payload.get("case_id")
    if not case_id:
        raise ValueError("case_id를 알 수 없습니다. --case-id를 지정하십시오.")
    ground_truth_all = load_ground_truth()
    if case_id not in ground_truth_all:
        raise KeyError(f"ground_truth.json에 case_id가 없습니다: {case_id}")
    metrics = evaluate_payload(payload, ground_truth_all[case_id])
    metrics["case_id"] = case_id
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch Incident Copilot 평가")
    parser.add_argument(
        "--result",
        default=str(settings.RESULTS_DIR / "F-01.json"),
        help="진단 결과 JSON 경로",
    )
    parser.add_argument("--case-id", default=None, help="평가할 case_id")
    args = parser.parse_args()

    metrics = evaluate_result_file(Path(args.result), args.case_id)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
