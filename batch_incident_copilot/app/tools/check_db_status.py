import json
from pathlib import Path

from app.schemas import ToolResult
from config import settings

DB_STATUS_PATH = settings.PROJECT_ROOT / "data" / "mock" / "db_status.json"


def _load_catalog() -> dict:
    return json.loads(Path(DB_STATUS_PATH).read_text(encoding="utf-8"))


def check_db_status(
    connection_name: str | None = None,
    account: str | None = None,
    **_kwargs,
) -> ToolResult:
    """로컬 mock JSON에서 DB 계정/인증/접속 설정 상태만 조회한다. 실제 DB에는 접속하지 않는다."""
    missing = [
        name
        for name, value in [
            ("connection_name", connection_name),
            ("account", account),
        ]
        if value is None or not str(value).strip()
    ]
    if missing:
        return ToolResult(
            tool="check_db_status",
            status="FAILED",
            data=None,
            error=f"필수 인자가 없습니다: {', '.join(missing)}",
        )
    try:
        catalog = _load_catalog()
    except (OSError, json.JSONDecodeError) as exc:
        return ToolResult(
            tool="check_db_status",
            status="FAILED",
            data=None,
            error=f"DB 상태 카탈로그를 읽을 수 없습니다: {exc}",
        )

    conn = str(connection_name).strip()
    acct = str(account).strip()
    accounts = catalog.get(conn)
    if not isinstance(accounts, dict) or acct not in accounts:
        return ToolResult(
            tool="check_db_status",
            status="FAILED",
            data=None,
            error="DB_STATUS_DATA_NOT_FOUND",
        )

    entry = accounts[acct]
    return ToolResult(
        tool="check_db_status",
        status="SUCCESS",
        data={
            "connection_name": conn,
            "account": acct,
            "account_locked": bool(entry.get("account_locked")),
            "credential_status": entry.get("credential_status"),
            "connection_config_valid": bool(entry.get("connection_config_valid")),
        },
        error=None,
    )
