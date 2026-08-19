import json
from pathlib import Path

from app.schemas import ToolResult
from config import settings

FILE_STATUS_PATH = settings.PROJECT_ROOT / "data" / "mock" / "file_status.json"


def _load_catalog() -> dict:
    return json.loads(Path(FILE_STATUS_PATH).read_text(encoding="utf-8"))


def check_file_status(path: str | None = None, **_kwargs) -> ToolResult:
    if not path or not str(path).strip():
        return ToolResult(
            tool="check_file_status",
            status="FAILED",
            data=None,
            error="path 인자가 필요합니다.",
        )
    try:
        catalog = _load_catalog()
    except (OSError, json.JSONDecodeError) as exc:
        return ToolResult(
            tool="check_file_status",
            status="FAILED",
            data=None,
            error=f"파일 상태 카탈로그를 읽을 수 없습니다: {exc}",
        )

    key = str(path).strip()
    if key not in catalog:
        return ToolResult(
            tool="check_file_status",
            status="FAILED",
            data=None,
            error=f"카탈로그에 경로가 없습니다: {key}",
        )
    return ToolResult(
        tool="check_file_status",
        status="SUCCESS",
        data=catalog[key],
        error=None,
    )
