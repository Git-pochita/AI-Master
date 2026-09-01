import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas import Hypothesis, ToolResult, ToolSelection, V1DiagnosisResult
from app.tools.check_db_status import check_db_status
from app.tools.check_file_status import check_file_status
from app.tools.check_sql_metadata import check_sql_metadata
from app.tools.validate_parameter import validate_parameter
from app.trace import (
    build_execution_trace,
    format_tool_input,
    purpose_for_tool,
)


def _hyp(code: str, name: str, evidence: str) -> dict:
    return Hypothesis(cause_code=code, cause_name=name, evidence=[evidence]).model_dump()


def test_purpose_and_input_use_observable_arguments_only():
    args = {
        "job_name": "DAILY_SALES_LOAD",
        "parameter_name": "business_date",
        "parameter_value": "20260818",
    }
    assert purpose_for_tool("validate_parameter", args) == "business_date 값이 정상인지 확인"
    assert (
        format_tool_input("validate_parameter", args)
        == "job=DAILY_SALES_LOAD, parameter=business_date, value=20260818"
    )


def test_v1_trace_from_real_parameter_and_file_tools():
    param_result = validate_parameter(
        job_name="DAILY_SALES_LOAD",
        parameter_name="business_date",
        parameter_value="20260818",
    )
    file_result = check_file_status(path="/data/in/sales_20260818.csv")
    assert param_result.status == "SUCCESS"
    assert param_result.data["is_valid"] is False
    assert param_result.data["expected_value"] == "20260819"
    assert file_result.status == "SUCCESS"

    payload = V1DiagnosisResult(
        case_id="file_case_001",
        summary="unused-llm-prose",
        extracted_info={
            "job_name": "DAILY_SALES_LOAD",
            "business_date": "20260818",
            "input_path": "/data/in/sales_20260818.csv",
            "error_messages": ["FileNotFoundError: /data/in/sales_20260818.csv"],
            "return_code": "12",
        },
        initial_hypotheses=[
            Hypothesis(
                cause_code="FILE_NOT_RECEIVED",
                cause_name="파일 미수신",
                evidence=["FileNotFoundError"],
            ),
            Hypothesis(
                cause_code="INVALID_BUSINESS_DATE",
                cause_name="실행일자 파라미터 오류",
                evidence=["business_date=20260818"],
            ),
        ],
        selected_tools=[
            ToolSelection(
                selected_tool="validate_parameter",
                reason="이 필드는 Trace 목적에 사용하지 않는다",
                arguments={
                    "job_name": "DAILY_SALES_LOAD",
                    "parameter_name": "business_date",
                    "parameter_value": "20260818",
                },
            ),
            ToolSelection(
                selected_tool="check_file_status",
                reason="숨기면 안 되는 CoT처럼 보이는 긴 문장",
                arguments={"path": "/data/in/sales_20260818.csv"},
            ),
        ],
        tool_results=[param_result, file_result],
        final_cause_code="INVALID_BUSINESS_DATE",
        final_cause_name="실행일자 파라미터 오류",
        diagnosis_level="확인됨",
        owner="BATCH_OPERATION",
        evidence=["expected_value=20260819", "parameter_value=20260818", "is_valid=false"],
        limitations=["mock"],
        recommended_actions=["business_date를 잡 실행일로 수정"],
    ).model_dump()

    assert "log_analysis" not in payload
    assert "tool_rounds" not in payload
    assert "diagnosis_updates" not in payload

    trace = build_execution_trace("v1", payload)
    dumped = trace.model_dump()

    assert dumped["log_analysis"]["message"] == "로그 분석 시작"
    assert "FileNotFoundError: /data/in/sales_20260818.csv" in dumped["log_analysis"]["core_errors"]
    assert "return_code=12" in dumped["log_analysis"]["core_errors"]
    codes = [item["cause_code"] for item in dumped["log_analysis"]["initial_hypotheses"]]
    assert codes == ["FILE_NOT_RECEIVED", "INVALID_BUSINESS_DATE"]

    assert dumped["tool_rounds"][0]["tool"] == "validate_parameter"
    assert dumped["tool_rounds"][0]["purpose"] == "business_date 값이 정상인지 확인"
    assert dumped["tool_rounds"][0]["input_display"].startswith("job=DAILY_SALES_LOAD")
    assert dumped["tool_rounds"][0]["status"] == "SUCCESS"
    evidence = dumped["tool_rounds"][0]["evidence"]
    assert evidence["actual"] == "20260818"
    assert evidence["expected"] == "20260819"
    assert evidence["is_valid"] is False
    assert "이 필드는 Trace 목적에 사용하지 않는다" not in str(dumped)
    assert "unused-llm-prose" not in str(dumped["log_analysis"])
    assert "숨기면 안 되는 CoT" not in str(dumped)

    updates = {item["cause_code"]: item["change"] for item in dumped["diagnosis_updates"]}
    assert updates["INVALID_BUSINESS_DATE"] == "가능성 상승"
    assert updates["FILE_NOT_RECEIVED"] == "파생 현상으로 재분류"

    final = dumped["final_diagnosis"]
    assert final["final_cause_code"] == "INVALID_BUSINESS_DATE"
    assert final["diagnosis_level"] == "확인됨"
    assert final["owner"] == "BATCH_OPERATION"
    assert "is_valid=false" in final["evidence"][-1] or any(
        "is_valid=false" in item for item in final["evidence"]
    )
    assert final["recommended_actions"] == ["business_date를 잡 실행일로 수정"]


def test_failed_tool_is_not_used_as_update_signal():
    failed = ToolResult(
        tool="check_db_status",
        status="FAILED",
        data=None,
        error="DB_STATUS_DATA_NOT_FOUND",
    )
    payload = {
        "extracted_info": {"error_messages": ["login failed"]},
        "initial_hypotheses": [
            _hyp("DB_CREDENTIAL_MISMATCH", "DB 인증 정보 불일치", "login failed"),
            _hyp("DB_ACCOUNT_LOCKED", "DB 계정 잠김", "login failed"),
        ],
        "selected_tools": [
            {
                "selected_tool": "check_db_status",
                "reason": "x",
                "arguments": {"connection_name": "UNKNOWN", "account": "nobody"},
            }
        ],
        "tool_results": [failed.model_dump()],
        "final_cause_code": "DB_CREDENTIAL_MISMATCH",
        "final_cause_name": "DB 인증 정보 불일치",
        "diagnosis_level": "추정",
        "owner": "BATCH_OPERATION",
        "evidence": ["login failed"],
        "recommended_actions": [],
    }
    trace = build_execution_trace("v1", payload)
    assert trace.tool_rounds[0].status == "FAILED"
    assert trace.tool_rounds[0].error == "DB_STATUS_DATA_NOT_FOUND"
    updates = {item.cause_code: item.change for item in trace.diagnosis_updates}
    assert updates["DB_CREDENTIAL_MISMATCH"] == "가능성 상승"
    assert updates["DB_ACCOUNT_LOCKED"] == "유지"


def test_real_db_tool_strengthens_credential_mismatch():
    result = check_db_status(connection_name="SALES_DB", account="batch_user")
    assert result.status == "SUCCESS"
    assert result.data["credential_status"] == "MISMATCH"
    payload = {
        "extracted_info": {
            "connection_name": "SALES_DB",
            "account": "batch_user",
            "error_messages": ["ORA-01017: invalid username/password"],
        },
        "initial_hypotheses": [
            _hyp("DB_CREDENTIAL_MISMATCH", "DB 인증 정보 불일치", "login failed"),
            _hyp("DB_ACCOUNT_LOCKED", "DB 계정 잠김", "login failed"),
        ],
        "selected_tools": [
            {
                "selected_tool": "check_db_status",
                "reason": "unused",
                "arguments": {"connection_name": "SALES_DB", "account": "batch_user"},
            }
        ],
        "tool_results": [result.model_dump()],
        "final_cause_code": "DB_CREDENTIAL_MISMATCH",
        "final_cause_name": "DB 인증 정보 불일치",
        "diagnosis_level": "확인됨",
        "owner": "BATCH_OPERATION",
        "evidence": ["credential_status=MISMATCH"],
        "recommended_actions": ["credential 확인"],
    }
    trace = build_execution_trace("v1", payload)
    assert trace.tool_rounds[0].evidence["credential_status"] == "MISMATCH"
    updates = {item.cause_code: item.change for item in trace.diagnosis_updates}
    assert updates["DB_CREDENTIAL_MISMATCH"] == "가능성 상승"
    assert updates["DB_ACCOUNT_LOCKED"] == "가능성 하락"


def test_real_sql_tool_strengthens_table_not_found():
    result = check_sql_metadata(schema="SALES", table="SALES_SUMMARY")
    assert result.status == "SUCCESS"
    assert result.data["table_exists"] is False
    payload = {
        "extracted_info": {
            "schema": "SALES",
            "table": "SALES_SUMMARY",
            "error_messages": ["table not found: SALES.SALES_SUMMARY"],
        },
        "initial_hypotheses": [
            _hyp("TABLE_NOT_FOUND", "테이블 없음", "table not found"),
            _hyp("INVALID_SCHEMA", "스키마 오류", "schema"),
        ],
        "selected_tools": [
            {
                "selected_tool": "check_sql_metadata",
                "reason": "unused",
                "arguments": {"schema": "SALES", "table": "SALES_SUMMARY", "column": None},
            }
        ],
        "tool_results": [result.model_dump()],
        "final_cause_code": "TABLE_NOT_FOUND",
        "final_cause_name": "테이블 없음",
        "diagnosis_level": "확인됨",
        "owner": "BATCH_OPERATION",
        "evidence": ["table_exists=false"],
        "recommended_actions": [],
    }
    trace = build_execution_trace("v1", payload)
    assert trace.tool_rounds[0].evidence["table_exists"] is False
    updates = {item.cause_code: item.change for item in trace.diagnosis_updates}
    assert updates["TABLE_NOT_FOUND"] == "가능성 상승"
    assert updates["INVALID_SCHEMA"] == "가능성 하락"


def test_v0_trace_has_no_tool_rounds_and_keeps_non_final_hypotheses():
    payload = {
        "summary": "V0 prose",
        "extracted_info": {
            "job_name": "DAILY_SALES_LOAD",
            "error_messages": ["FileNotFoundError: /data/in/sales_20260818.csv"],
        },
        "hypotheses": [
            _hyp("FILE_NOT_RECEIVED", "파일 미수신", "FileNotFoundError"),
            _hyp("INVALID_BUSINESS_DATE", "실행일자 파라미터 오류", "business_date=20260818"),
        ],
        "final_cause_code": "FILE_NOT_RECEIVED",
        "final_cause_name": "파일 미수신",
        "diagnosis_level": "추정",
        "owner": "BATCH_OPERATION",
        "evidence": [],
        "recommended_actions": ["파일 수신 여부 확인"],
        "limitations": ["로그만 사용"],
    }
    trace = build_execution_trace("v0", payload)
    assert trace.tool_rounds == []
    updates = {item.cause_code: item.change for item in trace.diagnosis_updates}
    assert updates["FILE_NOT_RECEIVED"] == "가능성 상승"
    assert updates["INVALID_BUSINESS_DATE"] == "유지"
    assert trace.final_diagnosis.evidence == ["FileNotFoundError"]
    assert "V0 prose" not in str(trace.log_analysis.model_dump())


def test_contradicted_hypothesis_is_downgraded():
    result = check_file_status(path="/data/in/sales_20260819.csv")
    assert result.status == "SUCCESS"
    assert result.data["exists"] is True
    payload = {
        "extracted_info": {"error_messages": ["unexpected"]},
        "initial_hypotheses": [
            _hyp("FILE_NOT_RECEIVED", "파일 미수신", "guess"),
            _hyp("INVALID_BUSINESS_DATE", "실행일자 파라미터 오류", "date"),
        ],
        "selected_tools": [
            {
                "selected_tool": "check_file_status",
                "reason": "unused",
                "arguments": {"path": "/data/in/sales_20260819.csv"},
            }
        ],
        "tool_results": [result.model_dump()],
        "final_cause_code": "INVALID_BUSINESS_DATE",
        "final_cause_name": "실행일자 파라미터 오류",
        "diagnosis_level": "추정",
        "owner": "BATCH_OPERATION",
        "evidence": ["log"],
        "recommended_actions": [],
    }
    trace = build_execution_trace("v1", payload)
    updates = {item.cause_code: item.change for item in trace.diagnosis_updates}
    assert updates["INVALID_BUSINESS_DATE"] == "가능성 상승"
    assert updates["FILE_NOT_RECEIVED"] == "가능성 하락"


def test_streamlit_renders_execution_trace_section():
    source = (PROJECT_ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert "Agent Execution Trace" in source
    assert "Investigation Process" in source
    assert "[Step 1] Log Analysis" in source
    assert "[Step 4] Diagnosis Update" in source
    assert "Chain-of-Thought" in source
    assert "_render_execution_trace(outcome.trace, version)" in source


def test_tool_use_module_does_not_import_trace():
    source = (PROJECT_ROOT / "app" / "tool_use.py").read_text(encoding="utf-8")
    assert "trace" not in source
    baseline = (PROJECT_ROOT / "app" / "baseline.py").read_text(encoding="utf-8")
    assert "trace" not in baseline
    schemas = (PROJECT_ROOT / "app" / "schemas.py").read_text(encoding="utf-8")
    assert "AgentExecutionTrace" not in schemas
    assert "execution_trace" not in schemas

