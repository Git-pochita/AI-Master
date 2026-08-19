import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas import DiagnosisResult
from config import settings


def load_ground_truth() -> dict:
    return json.loads(settings.GROUND_TRUTH_PATH.read_text(encoding="utf-8"))


def evaluate_case(result: DiagnosisResult, ground_truth: dict) -> dict:
    actual_cause_code = ground_truth.get("actual_cause_code")
    expected_codes = set(ground_truth.get("expected_hypothesis_codes", []))
    predicted_codes = {h.cause_code for h in result.hypotheses}
    hypothesis_recall_hit = (
        actual_cause_code is not None and actual_cause_code in predicted_codes
    )
    recalled = [actual_cause_code] if hypothesis_recall_hit else []

    return {
        "case_id": result.case_id,
        "final_diagnosis_correct": result.final_cause_code == actual_cause_code,
        "predicted_final_cause_code": result.final_cause_code,
        "actual_cause_code": actual_cause_code,
        "hypothesis_recall_hit": hypothesis_recall_hit,
        "recalled_hypothesis_codes": recalled,
        "predicted_hypothesis_codes": sorted(predicted_codes),
        "expected_hypothesis_codes": sorted(expected_codes),
        "diagnosis_level_correct": result.diagnosis_level
        == ground_truth.get("expected_diagnosis_level_v0"),
        "predicted_diagnosis_level": result.diagnosis_level,
        "expected_diagnosis_level_v0": ground_truth.get("expected_diagnosis_level_v0"),
        "owner_correct": result.owner == ground_truth.get("expected_owner"),
        "predicted_owner": result.owner,
        "expected_owner": ground_truth.get("expected_owner"),
    }


def evaluate_result_file(result_path: Path, case_id: str | None = None) -> dict:
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    result = DiagnosisResult.model_validate(payload)
    case_id = case_id or result.case_id
    if not case_id:
        raise ValueError("case_id를 알 수 없습니다. --case-id를 지정하십시오.")
    ground_truth_all = load_ground_truth()
    if case_id not in ground_truth_all:
        raise KeyError(f"ground_truth.json에 case_id가 없습니다: {case_id}")
    return evaluate_case(result, ground_truth_all[case_id])


def main() -> None:
    parser = argparse.ArgumentParser(description="V0 Baseline 평가 (file_case_001)")
    parser.add_argument(
        "--result",
        default=str(settings.RESULTS_DIR / "file_case_001.json"),
        help="진단 결과 JSON 경로",
    )
    parser.add_argument("--case-id", default=None, help="평가할 case_id")
    args = parser.parse_args()

    metrics = evaluate_result_file(Path(args.result), args.case_id)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
