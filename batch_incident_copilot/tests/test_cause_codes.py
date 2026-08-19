import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.cause_codes import CANONICAL_CAUSE_CODES, validate_cause_code
from evaluation.evaluator import load_ground_truth


def test_ground_truth_uses_canonical_codes():
    gt = load_ground_truth()["file_case_001"]
    assert gt["actual_cause_code"] in CANONICAL_CAUSE_CODES
    for code in gt["expected_hypothesis_codes"]:
        assert code in CANONICAL_CAUSE_CODES


def test_validate_cause_code_rejects_aliases():
    try:
        validate_cause_code("INPUT_FILE_NOT_FOUND")
        raise AssertionError("alias should be rejected")
    except ValueError:
        pass
    assert validate_cause_code("FILE_NOT_RECEIVED") == "FILE_NOT_RECEIVED"
    assert validate_cause_code("INVALID_BUSINESS_DATE") == "INVALID_BUSINESS_DATE"
