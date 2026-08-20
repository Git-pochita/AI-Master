import json
from pathlib import Path

from app.schemas import ToolResult
from config import settings

SQL_METADATA_PATH = settings.PROJECT_ROOT / "data" / "mock" / "sql_metadata.json"


def _load_catalog() -> dict:
    return json.loads(Path(SQL_METADATA_PATH).read_text(encoding="utf-8"))


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def check_sql_metadata(
    schema: str | None = None,
    table: str | None = None,
    column: str | None = None,
    **_kwargs,
) -> ToolResult:
    """로컬 mock JSON에서 schema/table/column 존재 여부만 조회한다. 실제 DB/SQL은 실행하지 않는다."""
    schema_name = _optional(schema)
    if not schema_name:
        return ToolResult(
            tool="check_sql_metadata",
            status="FAILED",
            data=None,
            error="필수 인자가 없습니다: schema",
        )
    try:
        catalog = _load_catalog()
    except (OSError, json.JSONDecodeError) as exc:
        return ToolResult(
            tool="check_sql_metadata",
            status="FAILED",
            data=None,
            error=f"SQL metadata 카탈로그를 읽을 수 없습니다: {exc}",
        )

    entry = catalog.get(schema_name)
    if not isinstance(entry, dict):
        return ToolResult(
            tool="check_sql_metadata",
            status="FAILED",
            data=None,
            error="SQL_METADATA_DATA_NOT_FOUND",
        )

    table_name = _optional(table)
    column_name = _optional(column)
    schema_exists = bool(entry.get("schema_exists"))
    table_exists: bool | None = None
    column_exists: bool | None = None

    if schema_exists and table_name:
        tables = entry.get("tables") or {}
        table_entry = tables.get(table_name)
        if not isinstance(table_entry, dict):
            table_exists = False
        else:
            table_exists = bool(table_entry.get("table_exists"))
            if table_exists and column_name:
                columns = table_entry.get("columns") or {}
                if column_name in columns:
                    column_exists = bool(columns[column_name])
                else:
                    column_exists = False

    return ToolResult(
        tool="check_sql_metadata",
        status="SUCCESS",
        data={
            "schema": schema_name,
            "table": table_name,
            "column": column_name,
            "schema_exists": schema_exists,
            "table_exists": table_exists,
            "column_exists": column_exists,
        },
        error=None,
    )
