#!/usr/bin/env python3
"""Generate evaluation/ground_truth.json for the official 30-case set."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.cause_codes import CAUSE_CODE_NAMES

OUT = ROOT / "evaluation" / "ground_truth.json"

FILE_H = ["FILE_NOT_RECEIVED", "INVALID_BUSINESS_DATE", "INVALID_FILE_PATH"]
DB_H = ["DB_CREDENTIAL_MISMATCH", "DB_ACCOUNT_LOCKED", "DB_CONNECTION_CONFIG_ERROR"]
SQL_H = ["TABLE_NOT_FOUND", "COLUMN_NOT_FOUND", "INVALID_SCHEMA"]
PARAM_H = ["MISSING_REQUIRED_PARAMETER", "INVALID_PARAMETER_FORMAT", "INVALID_PARAMETER_RANGE"]
PARAM_DATE_H = ["INVALID_BUSINESS_DATE", "MISSING_REQUIRED_PARAMETER", "INVALID_PARAMETER_FORMAT"]
FILE_DATE_H = ["FILE_NOT_RECEIVED", "INVALID_BUSINESS_DATE", "INVALID_FILE_PATH"]
DB_SQL_H = ["TABLE_NOT_FOUND", "DB_CREDENTIAL_MISMATCH", "INVALID_SCHEMA"]


def case(
    case_id: str,
    domain: str,
    cause: str,
    scenario: str,
    notes: str,
    *,
    hypotheses: list[str],
    required_tools: list[str],
    unnecessary_tools: list[str],
    v0_level: str,
    v1_level: str,
    expected_tool_outcome: str,
    tool_fixtures: list[dict],
) -> dict:
    return {
        "case_id": case_id,
        "incident_domain": domain,
        "scenario": scenario,
        "log_file": f"{case_id}.log",
        "actual_cause_code": cause,
        "actual_cause_name": CAUSE_CODE_NAMES[cause],
        "expected_hypothesis_codes": hypotheses,
        "required_tools": required_tools,
        "unnecessary_tools": unnecessary_tools,
        "expected_tool_outcome": expected_tool_outcome,
        "expected_diagnosis_level_v0": v0_level,
        "expected_diagnosis_level_v1": v1_level,
        "expected_owner": "BATCH_OPERATION",
        "tool_fixtures": tool_fixtures,
        "notes": notes,
    }


ALL_TOOLS = [
    "check_file_status",
    "validate_parameter",
    "check_db_status",
    "check_sql_metadata",
]


def others(required: list[str]) -> list[str]:
    return [name for name in ALL_TOOLS if name not in required]


cases = [
    case(
        "F-01",
        "FILE",
        "FILE_NOT_RECEIVED",
        "실제 파일 미수신",
        "business_date와 경로 형식은 정상이다. mock에서 orders_20260901.csv가 수신되지 않았다.",
        hypotheses=FILE_H,
        required_tools=["check_file_status"],
        unnecessary_tools=others(["check_file_status"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_file_status",
                "arguments": {"path": "/data/in/orders/orders_20260901.csv"},
                "expected_status": "SUCCESS",
                "expected_data": {"exists": False, "received": False},
            }
        ],
    ),
    case(
        "F-02",
        "FILE",
        "INVALID_FILE_PATH",
        "파일 경로 오설정",
        "로그 경로 /data/in/sale_20260901.csv는 없고, 같은 디렉터리의 sales_20260901.csv는 존재한다.",
        hypotheses=FILE_H,
        required_tools=["check_file_status"],
        unnecessary_tools=others(["check_file_status"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_file_status",
                "arguments": {"path": "/data/in/sale_20260901.csv"},
                "expected_status": "SUCCESS",
                "expected_data": {"exists": False, "received": False},
            }
        ],
    ),
    case(
        "F-03",
        "FILE",
        "FILE_NOT_RECEIVED",
        "애매한 File 오류를 Tool로 미수신 확인",
        "로그는 FileNotFound가 아니라 일반 read 실패이다. mock에서 payments_20260901.csv는 미수신이다.",
        hypotheses=FILE_H,
        required_tools=["check_file_status"],
        unnecessary_tools=others(["check_file_status"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_file_status",
                "arguments": {"path": "/data/in/payments/payments_20260901.csv"},
                "expected_status": "SUCCESS",
                "expected_data": {"exists": False, "received": False},
            }
        ],
    ),
    case(
        "F-04",
        "FILE",
        "INVALID_FILE_PATH",
        "잘못된 경로이며 정상 파일은 다른 경로에 존재",
        "로그 경로 partnr_20260901.csv는 없고, 같은 디렉터리 partner_20260901.csv는 존재한다.",
        hypotheses=FILE_H,
        required_tools=["check_file_status"],
        unnecessary_tools=others(["check_file_status"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_file_status",
                "arguments": {"path": "/data/in/partner/partnr_20260901.csv"},
                "expected_status": "SUCCESS",
                "expected_data": {"exists": False, "received": False},
            }
        ],
    ),
    case(
        "F-05",
        "FILE",
        "INVALID_BUSINESS_DATE",
        "FileNotFound처럼 보이나 실제 business_date 오류",
        "표면은 FileNotFound이다. 실제 원인은 실행일자 파라미터 오류이며 check_file_status와 validate_parameter가 모두 필요하다.",
        hypotheses=FILE_DATE_H,
        required_tools=["check_file_status", "validate_parameter"],
        unnecessary_tools=others(["check_file_status", "validate_parameter"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_file_status",
                "arguments": {"path": "/data/in/sales_20260831.csv"},
                "expected_status": "SUCCESS",
                "expected_data": {"exists": False, "received": False},
            },
            {
                "tool": "validate_parameter",
                "arguments": {
                    "job_name": "DAILY_SALES_LOAD",
                    "parameter_name": "business_date",
                    "parameter_value": "20260831",
                },
                "expected_status": "SUCCESS",
                "expected_data": {"is_valid": False, "expected_value": "20260901"},
            },
        ],
    ),
    case(
        "F-06",
        "FILE",
        "FILE_NOT_RECEIVED",
        "File Tool lookup 실패",
        "경로가 파일 카탈로그에 없어 check_file_status는 FAILED이다. FAILED는 최종 근거가 아니며 diagnosis_level은 추정이다.",
        hypotheses=FILE_H,
        required_tools=["check_file_status"],
        unnecessary_tools=others(["check_file_status"]),
        v0_level="추정",
        v1_level="추정",
        expected_tool_outcome="FAILED",
        tool_fixtures=[
            {
                "tool": "check_file_status",
                "arguments": {"path": "/data/in/untracked/ghost_20260901.csv"},
                "expected_status": "FAILED",
            }
        ],
    ),
    case(
        "P-01",
        "PARAMETER",
        "INVALID_BUSINESS_DATE",
        "business_date 불일치",
        "파일 오류 없이 business_date=20260831이 거절된다. validate_parameter는 is_valid=false, expected_value=20260901을 반환한다.",
        hypotheses=PARAM_DATE_H,
        required_tools=["validate_parameter"],
        unnecessary_tools=others(["validate_parameter"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "validate_parameter",
                "arguments": {
                    "job_name": "DAILY_SALES_LOAD",
                    "parameter_name": "business_date",
                    "parameter_value": "20260831",
                },
                "expected_status": "SUCCESS",
                "expected_data": {"is_valid": False, "expected_value": "20260901"},
            }
        ],
    ),
    case(
        "P-02",
        "PARAMETER",
        "MISSING_REQUIRED_PARAMETER",
        "필수 파라미터 누락",
        "store_id 값이 없다. validate_parameter는 provided=false, required=true를 반환해야 한다.",
        hypotheses=PARAM_H,
        required_tools=["validate_parameter"],
        unnecessary_tools=others(["validate_parameter"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "validate_parameter",
                "arguments": {
                    "job_name": "DAILY_STORE_CLOSE",
                    "parameter_name": "store_id",
                    "parameter_value": "",
                },
                "expected_status": "SUCCESS",
                "expected_data": {"provided": False, "required": True, "is_valid": False},
            }
        ],
    ),
    case(
        "P-03",
        "PARAMETER",
        "INVALID_PARAMETER_FORMAT",
        "파라미터 형식 오류",
        "region_code=korea는 허용 형식/코드가 아니다. validate_parameter는 format_valid=false를 반환해야 한다.",
        hypotheses=PARAM_H,
        required_tools=["validate_parameter"],
        unnecessary_tools=others(["validate_parameter"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "validate_parameter",
                "arguments": {
                    "job_name": "DAILY_REGION_AGG",
                    "parameter_name": "region_code",
                    "parameter_value": "korea",
                },
                "expected_status": "SUCCESS",
                "expected_data": {"format_valid": False, "is_valid": False},
            }
        ],
    ),
    case(
        "P-04",
        "PARAMETER",
        "INVALID_PARAMETER_RANGE",
        "파라미터 범위 오류",
        "retry_count=99는 정수 형식이지만 허용 범위 1-5를 벗어난다. validate_parameter는 range_valid=false를 반환해야 한다.",
        hypotheses=PARAM_H,
        required_tools=["validate_parameter"],
        unnecessary_tools=others(["validate_parameter"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "validate_parameter",
                "arguments": {
                    "job_name": "DAILY_RETRY_BATCH",
                    "parameter_name": "retry_count",
                    "parameter_value": "99",
                },
                "expected_status": "SUCCESS",
                "expected_data": {"format_valid": True, "range_valid": False, "is_valid": False},
            }
        ],
    ),
    case(
        "P-05",
        "PARAMETER",
        "INVALID_BUSINESS_DATE",
        "로그에 expected/actual이 명확하여 Tool 불필요",
        "로그에 expected=20260901 actual=20260831이 명시되어 있다. Tool 호출은 불필요하며 SUCCESS Tool이 없으면 diagnosis_level은 추정이다.",
        hypotheses=PARAM_DATE_H,
        required_tools=[],
        unnecessary_tools=ALL_TOOLS,
        v0_level="추정",
        v1_level="추정",
        expected_tool_outcome="NONE",
        tool_fixtures=[],
    ),
    case(
        "P-06",
        "PARAMETER",
        "INVALID_PARAMETER_FORMAT",
        "Parameter Tool lookup 실패",
        "DAILY_PROMO_LOAD/promo_code는 파라미터 카탈로그에 없어 validate_parameter는 FAILED이다. FAILED는 최종 근거가 아니며 diagnosis_level은 추정이다.",
        hypotheses=PARAM_H,
        required_tools=["validate_parameter"],
        unnecessary_tools=others(["validate_parameter"]),
        v0_level="추정",
        v1_level="추정",
        expected_tool_outcome="FAILED",
        tool_fixtures=[
            {
                "tool": "validate_parameter",
                "arguments": {
                    "job_name": "DAILY_PROMO_LOAD",
                    "parameter_name": "promo_code",
                    "parameter_value": "summer",
                },
                "expected_status": "FAILED",
            }
        ],
    ),
    case(
        "D-01",
        "DB",
        "DB_CREDENTIAL_MISMATCH",
        "인증 정보 불일치",
        "로그는 login failure이다. mock은 credential_status=MISMATCH, account_locked=false, config 정상이다.",
        hypotheses=DB_H,
        required_tools=["check_db_status"],
        unnecessary_tools=others(["check_db_status"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_db_status",
                "arguments": {"connection_name": "SALES_DB", "account": "batch_user"},
                "expected_status": "SUCCESS",
                "expected_data": {
                    "account_locked": False,
                    "credential_status": "MISMATCH",
                    "connection_config_valid": True,
                },
            }
        ],
    ),
    case(
        "D-02",
        "DB",
        "DB_ACCOUNT_LOCKED",
        "DB 계정 잠김",
        "로그는 login failure이다. mock은 account_locked=true, credential_status=VALID, config 정상이다.",
        hypotheses=DB_H,
        required_tools=["check_db_status"],
        unnecessary_tools=others(["check_db_status"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_db_status",
                "arguments": {"connection_name": "SALES_DB", "account": "batch_rpt"},
                "expected_status": "SUCCESS",
                "expected_data": {
                    "account_locked": True,
                    "credential_status": "VALID",
                    "connection_config_valid": True,
                },
            }
        ],
    ),
    case(
        "D-03",
        "DB",
        "DB_CONNECTION_CONFIG_ERROR",
        "DB 접속 설정 오류",
        "로그는 TNS/접속 실패이다. mock REPORT_DB/batch_user는 connection_config_valid=false이다.",
        hypotheses=DB_H,
        required_tools=["check_db_status"],
        unnecessary_tools=others(["check_db_status"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_db_status",
                "arguments": {"connection_name": "REPORT_DB", "account": "batch_user"},
                "expected_status": "SUCCESS",
                "expected_data": {
                    "account_locked": False,
                    "credential_status": "VALID",
                    "connection_config_valid": False,
                },
            }
        ],
    ),
    case(
        "D-04",
        "DB",
        "DB_ACCOUNT_LOCKED",
        "일반 login failure처럼 보이지만 Tool로 account_locked=true 확인",
        "로그는 ORA-01017 login failure이다. mock SALES_DB/locked_user는 account_locked=true이다.",
        hypotheses=DB_H,
        required_tools=["check_db_status"],
        unnecessary_tools=others(["check_db_status"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_db_status",
                "arguments": {"connection_name": "SALES_DB", "account": "locked_user"},
                "expected_status": "SUCCESS",
                "expected_data": {
                    "account_locked": True,
                    "credential_status": "VALID",
                    "connection_config_valid": True,
                },
            }
        ],
    ),
    case(
        "D-05",
        "DB",
        "DB_CREDENTIAL_MISMATCH",
        "account 정보 부족으로 Tool 미호출",
        "로그에 connection_name만 있고 account가 없다. check_db_status는 호출하지 않아야 하며 diagnosis_level은 추정이다.",
        hypotheses=DB_H,
        required_tools=[],
        unnecessary_tools=ALL_TOOLS,
        v0_level="추정",
        v1_level="추정",
        expected_tool_outcome="NONE",
        tool_fixtures=[],
    ),
    case(
        "D-06",
        "DB",
        "DB_CONNECTION_CONFIG_ERROR",
        "DB Tool lookup 실패",
        "LEGACY_DB/batch_legacy는 DB 카탈로그에 없어 check_db_status는 FAILED이다. FAILED는 최종 근거가 아니며 diagnosis_level은 추정이다.",
        hypotheses=DB_H,
        required_tools=["check_db_status"],
        unnecessary_tools=others(["check_db_status"]),
        v0_level="추정",
        v1_level="추정",
        expected_tool_outcome="FAILED",
        tool_fixtures=[
            {
                "tool": "check_db_status",
                "arguments": {"connection_name": "LEGACY_DB", "account": "batch_legacy"},
                "expected_status": "FAILED",
            }
        ],
    ),
    case(
        "S-01",
        "SQL",
        "TABLE_NOT_FOUND",
        "테이블 없음",
        "schema는 있고 SALES_SUMMARY 테이블은 없다.",
        hypotheses=SQL_H,
        required_tools=["check_sql_metadata"],
        unnecessary_tools=others(["check_sql_metadata"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_sql_metadata",
                "arguments": {"schema": "SALES", "table": "SALES_SUMMARY"},
                "expected_status": "SUCCESS",
                "expected_data": {
                    "schema_exists": True,
                    "table_exists": False,
                    "column_exists": None,
                },
            }
        ],
    ),
    case(
        "S-02",
        "SQL",
        "COLUMN_NOT_FOUND",
        "컬럼 없음",
        "SALES.SALES_DAILY 테이블은 있고 TOTAL_AMT 컬럼은 없다.",
        hypotheses=SQL_H,
        required_tools=["check_sql_metadata"],
        unnecessary_tools=others(["check_sql_metadata"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_sql_metadata",
                "arguments": {
                    "schema": "SALES",
                    "table": "SALES_DAILY",
                    "column": "TOTAL_AMT",
                },
                "expected_status": "SUCCESS",
                "expected_data": {
                    "schema_exists": True,
                    "table_exists": True,
                    "column_exists": False,
                },
            }
        ],
    ),
    case(
        "S-03",
        "SQL",
        "INVALID_SCHEMA",
        "잘못되거나 존재하지 않는 schema",
        "FINANCE_X는 schema_exists=false이다. Tool SUCCESS로 스키마 오류를 확인한다.",
        hypotheses=SQL_H,
        required_tools=["check_sql_metadata"],
        unnecessary_tools=others(["check_sql_metadata"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_sql_metadata",
                "arguments": {"schema": "FINANCE_X", "table": "LEDGER"},
                "expected_status": "SUCCESS",
                "expected_data": {
                    "schema_exists": False,
                    "table_exists": None,
                    "column_exists": None,
                },
            }
        ],
    ),
    case(
        "S-04",
        "SQL",
        "TABLE_NOT_FOUND",
        "ORA-00942 상황에서 schema/table 여부를 Tool로 구분",
        "로그는 ORA-00942만 있다. mock은 SALES schema 존재, SALES_MONTHLY 테이블 없음이다.",
        hypotheses=SQL_H,
        required_tools=["check_sql_metadata"],
        unnecessary_tools=others(["check_sql_metadata"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_sql_metadata",
                "arguments": {"schema": "SALES", "table": "SALES_MONTHLY"},
                "expected_status": "SUCCESS",
                "expected_data": {
                    "schema_exists": True,
                    "table_exists": False,
                    "column_exists": None,
                },
            }
        ],
    ),
    case(
        "S-05",
        "SQL",
        "COLUMN_NOT_FOUND",
        "테이블은 존재하지만 특정 컬럼 없음",
        "SALES.SALES_DAILY는 있고 STORE_NM 컬럼은 없다.",
        hypotheses=SQL_H,
        required_tools=["check_sql_metadata"],
        unnecessary_tools=others(["check_sql_metadata"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_sql_metadata",
                "arguments": {
                    "schema": "SALES",
                    "table": "SALES_DAILY",
                    "column": "STORE_NM",
                },
                "expected_status": "SUCCESS",
                "expected_data": {
                    "schema_exists": True,
                    "table_exists": True,
                    "column_exists": False,
                },
            }
        ],
    ),
    case(
        "S-06",
        "SQL",
        "INVALID_SCHEMA",
        "SQL metadata Tool lookup 실패",
        "HR_X는 SQL 카탈로그에 없어 check_sql_metadata는 FAILED이다. FAILED는 최종 근거가 아니며 diagnosis_level은 추정이다.",
        hypotheses=SQL_H,
        required_tools=["check_sql_metadata"],
        unnecessary_tools=others(["check_sql_metadata"]),
        v0_level="추정",
        v1_level="추정",
        expected_tool_outcome="FAILED",
        tool_fixtures=[
            {
                "tool": "check_sql_metadata",
                "arguments": {"schema": "HR_X", "table": "EMPLOYEES"},
                "expected_status": "FAILED",
            }
        ],
    ),
    case(
        "C-01",
        "COMPOSITE",
        "INVALID_BUSINESS_DATE",
        "로그에 expected/actual까지 명시되어 Tool 불필요",
        "FileNotFound와 expected/actual 날짜가 로그에 모두 있다. Tool 호출은 불필요하며 SUCCESS Tool이 없으면 diagnosis_level은 추정이다.",
        hypotheses=FILE_DATE_H,
        required_tools=[],
        unnecessary_tools=ALL_TOOLS,
        v0_level="추정",
        v1_level="추정",
        expected_tool_outcome="NONE",
        tool_fixtures=[],
    ),
    case(
        "C-02",
        "COMPOSITE",
        "INVALID_BUSINESS_DATE",
        "File + Parameter 복합, 두 Tool을 사용해 근본 원인 판단",
        "orders_20260831 FileNotFound 표면과 business_date=20260831이 함께 있다. check_file_status와 validate_parameter가 모두 필요하다.",
        hypotheses=FILE_DATE_H,
        required_tools=["check_file_status", "validate_parameter"],
        unnecessary_tools=others(["check_file_status", "validate_parameter"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_file_status",
                "arguments": {"path": "/data/in/orders/orders_20260831.csv"},
                "expected_status": "SUCCESS",
                "expected_data": {"exists": False, "received": False},
            },
            {
                "tool": "validate_parameter",
                "arguments": {
                    "job_name": "DAILY_ORDERS_LOAD",
                    "parameter_name": "business_date",
                    "parameter_value": "20260831",
                },
                "expected_status": "SUCCESS",
                "expected_data": {"is_valid": False, "expected_value": "20260901"},
            },
        ],
    ),
    case(
        "C-03",
        "COMPOSITE",
        "TABLE_NOT_FOUND",
        "DB + SQL 복합, DB 정상이고 table 미존재",
        "SALES_DB/etl_user는 계정/인증/접속이 정상이다. SALES.SALES_FACT 테이블은 없다.",
        hypotheses=DB_SQL_H,
        required_tools=["check_db_status", "check_sql_metadata"],
        unnecessary_tools=others(["check_db_status", "check_sql_metadata"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_db_status",
                "arguments": {"connection_name": "SALES_DB", "account": "etl_user"},
                "expected_status": "SUCCESS",
                "expected_data": {
                    "account_locked": False,
                    "credential_status": "VALID",
                    "connection_config_valid": True,
                },
            },
            {
                "tool": "check_sql_metadata",
                "arguments": {"schema": "SALES", "table": "SALES_FACT"},
                "expected_status": "SUCCESS",
                "expected_data": {
                    "schema_exists": True,
                    "table_exists": False,
                    "column_exists": None,
                },
            },
        ],
    ),
    case(
        "C-04",
        "COMPOSITE",
        "TABLE_NOT_FOUND",
        "DB Tool 결과 정상 후 SQL 추가 조사",
        "로그에 DB connection OK가 있다. ANALYTICS_DB/batch_ok는 정상이고 ANALYTICS.METRIC_DAILY 테이블은 없다.",
        hypotheses=DB_SQL_H,
        required_tools=["check_db_status", "check_sql_metadata"],
        unnecessary_tools=others(["check_db_status", "check_sql_metadata"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="SUCCESS",
        tool_fixtures=[
            {
                "tool": "check_db_status",
                "arguments": {"connection_name": "ANALYTICS_DB", "account": "batch_ok"},
                "expected_status": "SUCCESS",
                "expected_data": {
                    "account_locked": False,
                    "credential_status": "VALID",
                    "connection_config_valid": True,
                },
            },
            {
                "tool": "check_sql_metadata",
                "arguments": {"schema": "ANALYTICS", "table": "METRIC_DAILY"},
                "expected_status": "SUCCESS",
                "expected_data": {
                    "schema_exists": True,
                    "table_exists": False,
                    "column_exists": None,
                },
            },
        ],
    ),
    case(
        "C-05",
        "COMPOSITE",
        "FILE_NOT_RECEIVED",
        "입력 로그 근거가 부족한 케이스",
        "경로/파라미터/DB 정보가 거의 없다. Tool을 호출할 인자가 부족하며 diagnosis_level은 추정이다.",
        hypotheses=FILE_H,
        required_tools=[],
        unnecessary_tools=ALL_TOOLS,
        v0_level="추정",
        v1_level="추정",
        expected_tool_outcome="NONE",
        tool_fixtures=[],
    ),
    case(
        "C-06",
        "COMPOSITE",
        "INVALID_BUSINESS_DATE",
        "File Tool FAILED + Parameter Tool SUCCESS",
        "파일 경로는 카탈로그에 없어 check_file_status는 FAILED이다. validate_parameter는 business_date 불일치를 SUCCESS로 반환한다. FAILED는 최종 근거로 쓰지 않는다.",
        hypotheses=FILE_DATE_H,
        required_tools=["check_file_status", "validate_parameter"],
        unnecessary_tools=others(["check_file_status", "validate_parameter"]),
        v0_level="추정",
        v1_level="확인됨",
        expected_tool_outcome="MIXED",
        tool_fixtures=[
            {
                "tool": "check_file_status",
                "arguments": {"path": "/data/in/missing_catalog/sales_20260831.csv"},
                "expected_status": "FAILED",
            },
            {
                "tool": "validate_parameter",
                "arguments": {
                    "job_name": "DAILY_SALES_LOAD",
                    "parameter_name": "business_date",
                    "parameter_value": "20260831",
                },
                "expected_status": "SUCCESS",
                "expected_data": {"is_valid": False, "expected_value": "20260901"},
            },
        ],
    ),
]

assert len(cases) == 30, len(cases)
payload = {item["case_id"]: item for item in cases}
assert list(payload) == [item["case_id"] for item in cases]


def main() -> None:
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(payload)} cases to {OUT}")


if __name__ == "__main__":
    main()
