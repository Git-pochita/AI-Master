import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.cause_codes import CANONICAL_CAUSE_CODES, validate_cause_code
from evaluation.evaluator import load_ground_truth


def test_ground_truth_scope_cases_have_required_fields():
    all_gt = load_ground_truth()
    assert set(all_gt) == {"file_case_001", "db_case_001", "sql_case_001"}
    required = {
        "case_id",
        "incident_domain",
        "actual_cause_code",
        "expected_hypothesis_codes",
        "required_tools",
        "expected_diagnosis_level_v0",
        "expected_diagnosis_level_v1",
        "expected_owner",
    }
    for case_id, gt in all_gt.items():
        assert required.issubset(gt), case_id
        assert gt["case_id"] == case_id
    assert all_gt["db_case_001"]["required_tools"] == ["check_db_status"]
    assert all_gt["sql_case_001"]["required_tools"] == ["check_sql_metadata"]
    all_gt = load_ground_truth()
    for case_id, gt in all_gt.items():
        assert gt["actual_cause_code"] in CANONICAL_CAUSE_CODES, case_id
        for code in gt["expected_hypothesis_codes"]:
            assert code in CANONICAL_CAUSE_CODES, f"{case_id}:{code}"


def test_validate_cause_code_rejects_aliases():
    try:
        validate_cause_code("INPUT_FILE_NOT_FOUND")
        raise AssertionError("alias should be rejected")
    except ValueError:
        pass
    assert validate_cause_code("FILE_NOT_RECEIVED") == "FILE_NOT_RECEIVED"
    assert validate_cause_code("INVALID_BUSINESS_DATE") == "INVALID_BUSINESS_DATE"
    assert validate_cause_code("DB_CREDENTIAL_MISMATCH") == "DB_CREDENTIAL_MISMATCH"
    assert validate_cause_code("TABLE_NOT_FOUND") == "TABLE_NOT_FOUND"
