import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.input_validator import validate_log_content, validate_log_path
from app.schemas import ValidationDecision

SAMPLE_ERROR_LOG = """2026-09-01 02:00:00 INFO  JOB=DAILY_SALES_LOAD START
2026-09-01 02:00:01 INFO  business_date=20260831
2026-09-01 02:00:02 INFO  input=/data/in/sales_20260831.csv
2026-09-01 02:00:03 ERROR FileNotFoundError: /data/in/sales_20260831.csv
2026-09-01 02:00:03 ERROR job failed with return_code=12
2026-09-01 02:00:04 INFO  JOB=DAILY_SALES_LOAD END
"""


def test_empty_log_abort():
    result = validate_log_content("")
    assert result.decision == ValidationDecision.ABORT
    assert any("빈 로그" in reason for reason in result.reasons)


def test_empty_log_file_abort(tmp_path: Path):
    log_file = tmp_path / "empty.log"
    log_file.write_text("", encoding="utf-8")
    result = validate_log_path(log_file)
    assert result.decision == ValidationDecision.ABORT


def test_short_log_warn():
    result = validate_log_content("ERROR boom")
    assert result.decision == ValidationDecision.WARN
    assert any("짧" in reason for reason in result.reasons)


def test_normal_error_log_proceed_or_warn():
    result = validate_log_content(SAMPLE_ERROR_LOG)
    assert result.decision in {ValidationDecision.PROCEED, ValidationDecision.WARN}


def test_sample_file_proceed_or_warn():
    sample = PROJECT_ROOT / "data" / "sample_logs" / "file_case_001.log"
    result = validate_log_path(sample)
    assert result.decision in {ValidationDecision.PROCEED, ValidationDecision.WARN}
