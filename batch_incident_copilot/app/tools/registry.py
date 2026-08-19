from typing import Any, Callable

from app.schemas import ToolResult
from app.tools.check_file_status import check_file_status
from app.tools.validate_parameter import validate_parameter

TOOL_SPECS = [
    {
        "name": "check_file_status",
        "description": (
            "로컬 mock 파일 카탈로그에서 지정 경로의 수신/존재 상태를 조회합니다. "
            "실제 파일 시스템은 읽지 않습니다. 인자: path."
        ),
        "arguments": {"path": "조회할 파일 경로"},
    },
    {
        "name": "validate_parameter",
        "description": (
            "로컬 mock 규칙과 배치 파라미터 값을 비교합니다. "
            "실제 DB나 운영 설정은 조회하지 않습니다. "
            "인자: job_name, parameter_name, parameter_value."
        ),
        "arguments": {
            "job_name": "배치 잡 이름",
            "parameter_name": "파라미터 이름",
            "parameter_value": "로그에서 확인한 파라미터 값",
        },
    },
]

HANDLERS: dict[str, Callable[..., ToolResult]] = {
    "check_file_status": check_file_status,
    "validate_parameter": validate_parameter,
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
    try:
        return handler(**(arguments or {}))
    except Exception as exc:
        return ToolResult(
            tool=name,
            status="FAILED",
            data=None,
            error=f"Tool 실행 오류: {exc}",
        )
