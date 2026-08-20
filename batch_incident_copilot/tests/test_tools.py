import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas import ToolResult
from app.tools.check_db_status import check_db_status
from app.tools.check_file_status import check_file_status
from app.tools.check_sql_metadata import check_sql_metadata
from app.tools.evidence import filter_evidence, supporting_tool_results
from app.tools.registry import HANDLERS, execute_tool, get_tool_specs
from app.tools.validate_parameter import validate_parameter


def test_check_file_status_success():
    result = check_file_status(path="/data/in/sales_20260818.csv")
    assert result.status == "SUCCESS"
    assert result.error is None
    assert result.data is not None
    assert result.data["exists"] is False
    assert result.data["received"] is False
    siblings = {item["path"]: item for item in result.data["same_directory_files"]}
    assert siblings["/data/in/sales_20260818.csv"]["exists"] is False
    assert siblings["/data/in/sales_20260819.csv"]["exists"] is True
    assert siblings["/data/in/sales_20260819.csv"]["received"] is True


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


def test_check_db_status_success_credential_mismatch():
    result = check_db_status(connection_name="SALES_DB", account="batch_user")
    assert result.status == "SUCCESS"
    assert result.error is None
    assert result.data is not None
    assert result.data["account_locked"] is False
    assert result.data["credential_status"] == "MISMATCH"
    assert result.data["connection_config_valid"] is True
    assert "cause_code" not in result.data
    assert "password" not in result.data
    assert "api_key" not in result.data


def test_check_db_status_failed_not_found():
    result = check_db_status(connection_name="UNKNOWN_DB", account="batch_user")
    assert result.status == "FAILED"
    assert result.data is None
    assert result.error == "DB_STATUS_DATA_NOT_FOUND"


def test_check_db_status_failed_missing_args():
    result = check_db_status(connection_name="", account="")
    assert result.status == "FAILED"
    assert result.data is None
    assert result.error


def test_check_db_status_mock_states():
    locked = check_db_status(connection_name="SALES_DB", account="locked_user")
    assert locked.status == "SUCCESS"
    assert locked.data["account_locked"] is True
    assert locked.data["credential_status"] == "VALID"
    assert locked.data["connection_config_valid"] is True

    config_error = check_db_status(connection_name="REPORT_DB", account="batch_user")
    assert config_error.status == "SUCCESS"
    assert config_error.data["account_locked"] is False
    assert config_error.data["credential_status"] == "VALID"
    assert config_error.data["connection_config_valid"] is False


def test_check_sql_metadata_success_table_missing():
    result = check_sql_metadata(schema="SALES", table="SALES_SUMMARY", column=None)
    assert result.status == "SUCCESS"
    assert result.error is None
    assert result.data is not None
    assert result.data["schema_exists"] is True
    assert result.data["table_exists"] is False
    assert result.data["column_exists"] is None
    assert "cause_code" not in result.data


def test_check_sql_metadata_failed_not_found():
    result = check_sql_metadata(schema="NO_SUCH_SCHEMA", table="ANY_TABLE")
    assert result.status == "FAILED"
    assert result.data is None
    assert result.error == "SQL_METADATA_DATA_NOT_FOUND"


def test_check_sql_metadata_failed_missing_schema():
    result = check_sql_metadata(schema="", table="SALES_SUMMARY")
    assert result.status == "FAILED"
    assert result.data is None
    assert result.error


def test_check_sql_metadata_schema_table_column_states():
    missing_column = check_sql_metadata(
        schema="SALES",
        table="SALES_DAILY",
        column="TOTAL_AMT",
    )
    assert missing_column.status == "SUCCESS"
    assert missing_column.data["schema_exists"] is True
    assert missing_column.data["table_exists"] is True
    assert missing_column.data["column_exists"] is False

    existing_column = check_sql_metadata(
        schema="SALES",
        table="SALES_DAILY",
        column="SALES_DT",
    )
    assert existing_column.status == "SUCCESS"
    assert existing_column.data["column_exists"] is True

    invalid_schema = check_sql_metadata(schema="FINANCE_X", table="ANY_TABLE")
    assert invalid_schema.status == "SUCCESS"
    assert invalid_schema.data["schema_exists"] is False
    assert invalid_schema.data["table_exists"] is None
    assert invalid_schema.data["column_exists"] is None


def test_registry_includes_db_and_sql_tools():
    names = {spec["name"] for spec in get_tool_specs()}
    assert names == {
        "check_file_status",
        "validate_parameter",
        "check_db_status",
        "check_sql_metadata",
    }
    assert set(HANDLERS) == names
    db = execute_tool(
        "check_db_status",
        {"connection_name": "SALES_DB", "account": "batch_user"},
    )
    assert db.status == "SUCCESS"
    sql = execute_tool(
        "check_sql_metadata",
        {"schema": "SALES", "table": "SALES_SUMMARY"},
    )
    assert sql.status == "SUCCESS"


def test_failed_db_sql_results_are_not_used_as_evidence():
    failed = ToolResult(
        tool="check_db_status",
        status="FAILED",
        data=None,
        error="DB_STATUS_DATA_NOT_FOUND",
    )
    success = ToolResult(
        tool="check_sql_metadata",
        status="SUCCESS",
        data={"schema_exists": True, "table_exists": False, "column_exists": None},
        error=None,
    )
    usable = supporting_tool_results([failed, success])
    assert usable == [success]
    evidence = filter_evidence(
        ["DB_STATUS_DATA_NOT_FOUND", "schema_exists=true table_exists=false"],
        [failed, success],
    )
    assert "DB_STATUS_DATA_NOT_FOUND" not in evidence
    assert "schema_exists=true table_exists=false" in evidence
