import json
import re
from pathlib import Path

from app.schemas import ToolResult
from config import settings

PARAMETERS_PATH = settings.PROJECT_ROOT / "data" / "mock" / "parameters.json"


def _load_rules() -> dict:
    return json.loads(Path(PARAMETERS_PATH).read_text(encoding="utf-8"))


def _optional_text(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _format_valid(value: str, rule: dict) -> bool | None:
    pattern = rule.get("format_pattern")
    allowed = rule.get("allowed_values")
    if not pattern and not allowed:
        return None
    ok = True
    if pattern:
        ok = bool(re.fullmatch(str(pattern), value))
    if ok and allowed:
        ok = value in [str(item) for item in allowed]
    return ok


def _range_valid(value: str, rule: dict) -> bool | None:
    min_value = rule.get("min")
    max_value = rule.get("max")
    if min_value is None and max_value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return False
    if min_value is not None and number < float(min_value):
        return False
    if max_value is not None and number > float(max_value):
        return False
    return True


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
    value = _optional_text(parameter_value)
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

    expected = _optional_text(rule.get("expected_value"))
    required = bool(rule.get("required", True))
    provided = value != ""
    format_valid = _format_valid(value, rule) if provided else None
    range_valid = _range_valid(value, rule) if provided else None
    matches_expected = (value == expected) if provided and expected else True
    is_valid = provided and (format_valid is not False) and (range_valid is not False) and matches_expected
    if not provided:
        is_valid = not required

    return ToolResult(
        tool="validate_parameter",
        status="SUCCESS",
        data={
            "job_name": job,
            "parameter_name": name,
            "parameter_value": value if provided else None,
            "required": required,
            "provided": provided,
            "format_valid": format_valid,
            "range_valid": range_valid,
            "expected_value": expected or None,
            "allowed_values": rule.get("allowed_values"),
            "min": rule.get("min"),
            "max": rule.get("max"),
            "is_valid": is_valid,
            "rule": rule.get("rule"),
            "job_run_date": rule.get("job_run_date"),
        },
        error=None,
    )
