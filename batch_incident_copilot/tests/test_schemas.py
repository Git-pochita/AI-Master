import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas import Hypothesis


@pytest.mark.parametrize(
    "code",
    [
        "FILE_NOT_RECEIVED",
        "INVALID_BUSINESS_DATE",
        "INVALID_FILE_PATH",
        "TABLE_NOT_FOUND",
        "DB_CREDENTIAL_MISMATCH",
        "DB_ACCOUNT_LOCKED",
        "COLUMN_NOT_FOUND",
        "INVALID_SCHEMA",
        "MISSING_REQUIRED_PARAMETER",
    ],
)
def test_cause_code_accepts_canonical(code: str):
    hypothesis = Hypothesis(
        cause_code=code,
        cause_name="테스트",
        evidence=["로그 근거"],
    )
    assert hypothesis.cause_code == code


@pytest.mark.parametrize(
    "code",
    [
        "",
        "file_not_received",
        "FILE-NOT-RECEIVED",
        "FILE_",
        "_FILE",
        "FILE__NOT",
        "파일없음",
        "FILE NOT",
        "A",
        "FILE2",
        "ERR_404",
        "INPUT_FILE_NOT_FOUND",
        "INPUT_PATH_CONFIGURATION_ERROR",
        "INPUT_PATH_MISCONFIGURATION",
    ],
)
def test_cause_code_rejects_invalid_or_non_canonical(code: str):
    with pytest.raises(ValidationError):
        Hypothesis(
            cause_code=code,
            cause_name="테스트",
            evidence=["로그 근거"],
        )
