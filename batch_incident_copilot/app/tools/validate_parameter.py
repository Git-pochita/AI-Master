import json
from pathlib import Path

from app.schemas import ToolResult
from config import settings

PARAMETERS_PATH = settings.PROJECT_ROOT / "data" / "mock" / "parameters.json"


def _load_rules() -> dict:
    return json.loads(Path(PARAMETERS_PATH).read_text(encoding="utf-8"))


def validate_parameter(
    job_name: str | None = None,
    parameter_name: str | None = None,
    parameter_value: str | None = None,
    **_kwargs,
) -> ToolResult:
    missing = [
        name
        for name, value in [
            ("job_name", job_name),
            ("parameter_name", parameter_name),
            ("parameter_value", parameter_value),
        ]
        if value is None or not str(value).strip()
    ]
    if missing:
        return ToolResult(
            tool="validate_parameter",
            status="FAILED",
            data=None,
            error=f"필수 인자가 없습니다: {', '.join(missing)}",
        )
    try:
        rules = _load_rules()
    except (OSError, json.JSONDecodeError) as exc:
        return ToolResult(
            tool="validate_parameter",
            status="FAILED",
            data=None,
            error=f"파라미터 규칙을 읽을 수 없습니다: {exc}",
        )

    job = str(job_name).strip()
    name = str(parameter_name).strip()
    value = str(parameter_value).strip()
    job_rules = rules.get(job)
    if not job_rules:
        return ToolResult(
            tool="validate_parameter",
            status="FAILED",
            data=None,
            error=f"알 수 없는 job_name입니다: {job}",
        )
    rule = job_rules.get(name)
    if not rule:
        return ToolResult(
            tool="validate_parameter",
            status="FAILED",
            data=None,
            error=f"알 수 없는 parameter_name입니다: {name}",
        )

    expected = str(rule.get("expected_value", "")).strip()
    is_valid = value == expected
    return ToolResult(
        tool="validate_parameter",
        status="SUCCESS",
        data={
            "job_name": job,
            "parameter_name": name,
            "parameter_value": value,
            "expected_value": expected,
            "is_valid": is_valid,
            "rule": rule.get("rule"),
            "job_run_date": rule.get("job_run_date"),
        },
        error=None,
    )
