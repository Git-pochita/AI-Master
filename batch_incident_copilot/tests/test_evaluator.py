import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas import DiagnosisResult, Hypothesis
from evaluation.evaluator import evaluate_case, evaluate_payload, load_ground_truth


def _diagnosis(hypotheses: list[Hypothesis], final_cause_code: str, final_cause_name: str) -> DiagnosisResult:
    return DiagnosisResult(
        case_id="F-05",
        summary="로그에 FileNotFoundError가 기록됨",
        extracted_info={"job": "DAILY_SALES_LOAD"},
        hypotheses=hypotheses,
        final_cause_code=final_cause_code,
        final_cause_name=final_cause_name,
        diagnosis_level="추정",
        owner="BATCH_OPERATION",
        recommended_actions=["파일 존재 여부 확인"],
        limitations=["V0는 외부 상태를 확인하지 못함"],
    )


def test_hypothesis_recall_hit_when_actual_cause_is_in_hypotheses():
    result = _diagnosis(
        hypotheses=[
            Hypothesis(
                cause_code="FILE_NOT_RECEIVED",
                cause_name="파일 미수신",
                evidence=["FileNotFoundError: /data/in/sales_20260831.csv"],
            ),
            Hypothesis(
                cause_code="INVALID_BUSINESS_DATE",
                cause_name="실행일자 파라미터 오류",
                evidence=["business_date=20260831"],
            ),
            Hypothesis(
                cause_code="INVALID_FILE_PATH",
                cause_name="파일 경로 오류",
                evidence=["input=/data/in/sales_20260831.csv"],
            ),
        ],
        final_cause_code="FILE_NOT_RECEIVED",
        final_cause_name="파일 미수신",
    )
    gt = load_ground_truth()["F-05"]
    metrics = evaluate_case(result, gt)

    assert metrics["final_diagnosis_correct"] is False
    assert metrics["hypothesis_recall_hit"] is True
    assert metrics["diagnosis_level_correct"] is True
    assert metrics["owner_correct"] is True
    assert metrics["recalled_hypothesis_codes"] == ["INVALID_BUSINESS_DATE"]


def test_hypothesis_recall_miss_when_actual_cause_is_absent():
    result = _diagnosis(
        hypotheses=[
            Hypothesis(
                cause_code="FILE_NOT_RECEIVED",
                cause_name="파일 미수신",
                evidence=["FileNotFoundError: /data/in/sales_20260831.csv"],
            ),
            Hypothesis(
                cause_code="INVALID_FILE_PATH",
                cause_name="파일 경로 오류",
                evidence=["input=/data/in/sales_20260831.csv"],
            ),
        ],
        final_cause_code="FILE_NOT_RECEIVED",
        final_cause_name="파일 미수신",
    )
    gt = load_ground_truth()["F-05"]
    metrics = evaluate_case(result, gt)

    assert metrics["hypothesis_recall_hit"] is False
    assert metrics["recalled_hypothesis_codes"] == []


def test_v1_empty_required_tools_marks_any_call_unnecessary():
    gt = load_ground_truth()["P-05"]
    metrics = evaluate_payload(
        {
            "case_id": "P-05",
            "initial_hypotheses": [
                {
                    "cause_code": "INVALID_BUSINESS_DATE",
                    "cause_name": "실행일자 파라미터 오류",
                    "evidence": ["expected=20260901 actual=20260831"],
                }
            ],
            "selected_tools": [{"selected_tool": "validate_parameter"}],
            "tool_results": [],
            "final_cause_code": "INVALID_BUSINESS_DATE",
            "diagnosis_level": "추정",
            "owner": "BATCH_OPERATION",
        },
        gt,
    )
    assert metrics["required_tool_recall"] == 1.0
    assert metrics["unnecessary_tool_rate"] == 1.0
    assert "validate_parameter" in metrics["expected_unnecessary_tools"]
    assert metrics["tool_necessity"] == "NOT_NEEDED"


def test_v1_required_tools_recall_and_unnecessary():
    gt = load_ground_truth()["F-05"]
    metrics = evaluate_payload(
        {
            "case_id": "F-05",
            "initial_hypotheses": [
                {
                    "cause_code": "INVALID_BUSINESS_DATE",
                    "cause_name": "실행일자 파라미터 오류",
                    "evidence": ["business_date=20260831"],
                }
            ],
            "selected_tools": [
                {"selected_tool": "check_file_status"},
                {"selected_tool": "check_db_status"},
            ],
            "tool_results": [],
            "final_cause_code": "INVALID_BUSINESS_DATE",
            "diagnosis_level": "추정",
            "owner": "BATCH_OPERATION",
        },
        gt,
    )
    assert metrics["required_tool_recall"] == 0.5
    assert metrics["unnecessary_tool_count"] == 1
    assert metrics["unnecessary_tool_rate"] == 0.5
    assert metrics["required_tools"] == ["check_file_status", "validate_parameter"]
