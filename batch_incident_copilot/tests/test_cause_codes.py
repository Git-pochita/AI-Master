import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.cause_codes import validate_cause_code


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
    assert validate_cause_code("MISSING_REQUIRED_PARAMETER") == "MISSING_REQUIRED_PARAMETER"
