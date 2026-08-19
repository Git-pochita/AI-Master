import json
from pathlib import Path, PurePosixPath

from app.schemas import ToolResult
from config import settings

FILE_STATUS_PATH = settings.PROJECT_ROOT / "data" / "mock" / "file_status.json"


def _load_catalog() -> dict:
    return json.loads(Path(FILE_STATUS_PATH).read_text(encoding="utf-8"))


def _directory_of(path: str) -> str:
    return str(PurePosixPath(path).parent)


def _with_filename(entry: dict, path: str) -> dict:
    payload = dict(entry)
    payload["path"] = payload.get("path") or path
    payload["filename"] = PurePosixPath(payload["path"]).name
    return payload


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

    directory = _directory_of(key)
    same_directory_files = [
        _with_filename(entry, entry_path)
        for entry_path, entry in sorted(catalog.items())
        if _directory_of(entry_path) == directory
    ]
    data = _with_filename(catalog[key], key)
    data["same_directory_files"] = same_directory_files
    return ToolResult(
        tool="check_file_status",
        status="SUCCESS",
        data=data,
        error=None,
    )
