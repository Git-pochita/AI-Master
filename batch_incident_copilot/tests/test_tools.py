import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas import ToolResult
from app.tools.check_file_status import check_file_status
from app.tools.evidence import filter_evidence, supporting_tool_results
from app.tools.validate_parameter import validate_parameter


def test_check_file_status_success():
    result = check_file_status(path="/data/in/sales_20260818.csv")
    assert result.status == "SUCCESS"
    assert result.error is None
    assert result.data is not None
    assert result.data["exists"] is False
    assert result.data["received"] is False


def test_check_file_status_failed():
    result = check_file_status(path="")
    assert result.status == "FAILED"
    assert result.data is None
    assert result.error


def test_validate_parameter_valid():
    result = validate_parameter(
        job_name="DAILY_SALES_LOAD",
        parameter_name="business_date",
        parameter_value="20260819",
    )
    assert result.status == "SUCCESS"
    assert result.data["is_valid"] is True
    assert result.data["expected_value"] == "20260819"


def test_validate_parameter_invalid():
    result = validate_parameter(
        job_name="DAILY_SALES_LOAD",
        parameter_name="business_date",
        parameter_value="20260818",
    )
    assert result.status == "SUCCESS"
    assert result.data["is_valid"] is False
    assert result.data["parameter_value"] == "20260818"


def test_failed_tool_results_are_not_used_as_evidence():
    failed = ToolResult(
        tool="check_file_status",
        status="FAILED",
        data=None,
        error="카탈로그에 경로가 없습니다: /tmp/missing.csv",
    )
    success = ToolResult(
        tool="validate_parameter",
        status="SUCCESS",
        data={"is_valid": False, "parameter_value": "20260818"},
        error=None,
    )
    usable = supporting_tool_results([failed, success])
    assert usable == [success]
    evidence = filter_evidence(
        [
            "카탈로그에 경로가 없습니다: /tmp/missing.csv",
            "business_date=20260818 is invalid",
        ],
        [failed, success],
    )
    assert "카탈로그에 경로가 없습니다: /tmp/missing.csv" not in evidence
    assert "business_date=20260818 is invalid" in evidence
