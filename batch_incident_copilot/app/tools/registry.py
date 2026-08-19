import json

from typing import Any, Callable

from app.schemas import ToolResult
from app.tools.check_file_status import check_file_status
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
                "실제 파일 시스템은 읽지 않습니다. 인자: path."
            ),
            "arguments": {"path": "조회할 파일 경로"},
        },
        {
            "name": "validate_parameter",
            "description": (
                "로컬 mock 규칙과 배치 파라미터 값을 비교합니다. "
                "실제 DB나 운영 설정은 조회하지 않습니다. "
                f"현재 검증 가능한 항목: {supported}. "
                "인자: job_name, parameter_name, parameter_value."
            ),
            "arguments": {
                "job_name": "배치 잡 이름",
                "parameter_name": "mock 규칙에 있는 파라미터 이름",
                "parameter_value": "로그에서 확인한 파라미터 값",
            },
        },
    ]


TOOL_SPECS = get_tool_specs()

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
