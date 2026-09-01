import json

from typing import Any, Callable

from app.schemas import ToolResult
from app.tools.check_db_status import check_db_status
from app.tools.check_file_status import check_file_status
from app.tools.check_sql_metadata import check_sql_metadata
from app.tools.validate_parameter import validate_parameter
from config import settings

PARAMETERS_PATH = settings.PROJECT_ROOT / "data" / "mock" / "parameters.json"


def _supported_parameters() -> list[str]:
    rules = json.loads(PARAMETERS_PATH.read_text(encoding="utf-8"))
    return [
        f"{job}.{name}"
        for job, params in rules.items()
        for name in params
    ]


def get_tool_specs() -> list[dict[str, Any]]:
    supported = ", ".join(_supported_parameters()) or "(없음)"
    return [
        {
            "name": "check_file_status",
            "description": (
                "로컬 mock 파일 카탈로그에서 지정 경로의 수신/존재 상태를 조회합니다. "
                "같은 디렉터리에 있는 다른 mock 파일 상태(same_directory_files)도 함께 반환합니다. "
                "실제 파일 시스템은 읽지 않습니다. "
                "path는 필수이며 로그에 경로가 없으면 이 Tool을 고르지 마십시오."
            ),
            "required": ["path"],
            "arguments": {"path": "조회할 파일 경로"},
        },
        {
            "name": "validate_parameter",
            "description": (
                "로컬 mock 규칙과 배치 파라미터 값을 비교합니다. "
                "실제 DB나 운영 설정은 조회하지 않습니다. "
                "원인 코드는 반환하지 않으며 provided, format_valid, range_valid, "
                "is_valid, expected_value 상태만 반환합니다. "
                "값이 없으면 parameter_value를 빈 문자열로 넘기면 됩니다. "
                f"현재 검증 가능한 항목: {supported}. "
                "job_name, parameter_name은 필수입니다. parameter_value는 값이 없으면 빈 문자열."
            ),
            "required": ["job_name", "parameter_name"],
            "arguments": {
                "job_name": "배치 잡 이름",
                "parameter_name": "mock 규칙에 있는 파라미터 이름",
                "parameter_value": "로그에서 확인한 파라미터 값",
            },
        },
        {
            "name": "check_db_status",
            "description": (
                "로컬 mock JSON에서 DB 계정 잠금, credential 상태, 접속 설정 유효 여부만 조회합니다. "
                "실제 DB에 접속하지 않고 password/API key 같은 secret도 검증하지 않습니다. "
                "원인 코드는 반환하지 않으며 account_locked, credential_status, "
                "connection_config_valid 상태만 반환합니다. "
                "connection_name과 account는 모두 필수입니다. "
                "로그 또는 extracted_info에 둘 다 있을 때만 이 Tool을 고르십시오. "
                "로그에 없는 커넥션/계정 이름을 만들지 말고, mock 기본 계정을 넣지 마십시오."
            ),
            "required": ["connection_name", "account"],
            "arguments": {
                "connection_name": "로그에서 확인한 DB 커넥션 이름",
                "account": "로그에서 확인한 DB 계정",
            },
        },
        {
            "name": "check_sql_metadata",
            "description": (
                "로컬 mock JSON에서 schema/table/column 존재 여부를 조회합니다. "
                "실제 DB 접속이나 SQL 실행은 하지 않습니다. "
                "원인 코드는 반환하지 않으며 schema_exists, table_exists, column_exists만 반환합니다. "
                "column은 선택이며 없으면 column_exists는 null입니다. "
                "schema는 필수입니다. 로그에 없는 schema/table을 만들지 마십시오. "
                "인자: schema, table, column(선택)."
            ),
            "required": ["schema"],
            "arguments": {
                "schema": "로그에서 확인한 스키마 이름",
                "table": "로그에서 확인한 테이블 이름",
                "column": "확인할 컬럼 이름. 없으면 null",
            },
        },
    ]


TOOL_SPECS = get_tool_specs()

TOOL_REQUIRED_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "check_file_status": ("path",),
    "validate_parameter": ("job_name", "parameter_name"),
    "check_db_status": ("connection_name", "account"),
    "check_sql_metadata": ("schema",),
}


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def required_arguments(tool_name: str) -> tuple[str, ...]:
    return TOOL_REQUIRED_ARGUMENTS.get(tool_name, ())


def missing_required_arguments(tool_name: str, arguments: dict[str, Any] | None) -> list[str]:
    args = arguments or {}
    return [name for name in required_arguments(tool_name) if _blank(args.get(name))]


def complete_arguments_from_extracted(
    tool_name: str,
    arguments: dict[str, Any] | None,
    extracted_info: dict[str, Any] | None,
) -> dict[str, Any]:
    """로그에서 이미 추출된 값만 빈 인자에 채운다. mock 카탈로그 값은 쓰지 않는다."""
    args = dict(arguments or {})
    extracted = extracted_info or {}
    for name in required_arguments(tool_name):
        if _blank(args.get(name)) and not _blank(extracted.get(name)):
            args[name] = extracted[name]
    return args

HANDLERS: dict[str, Callable[..., ToolResult]] = {
    "check_file_status": check_file_status,
    "validate_parameter": validate_parameter,
    "check_db_status": check_db_status,
    "check_sql_metadata": check_sql_metadata,
}


def execute_tool(name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
    handler = HANDLERS.get(name)
    if handler is None:
        return ToolResult(
            tool=name or "unknown",
            status="FAILED",
            data=None,
            error=f"지원하지 않는 Tool입니다: {name}",
        )
    missing = missing_required_arguments(name, arguments)
    if missing:
        return ToolResult(
            tool=name,
            status="FAILED",
            data=None,
            error=f"필수 인자가 없습니다: {', '.join(missing)}",
        )
    try:
        return handler(**(arguments or {}))
    except Exception as exc:
        return ToolResult(
            tool=name,
            status="FAILED",
            data=None,
            error=f"Tool 실행 오류: {exc}",
        )
