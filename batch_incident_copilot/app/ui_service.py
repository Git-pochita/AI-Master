from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.baseline import diagnose
from app.input_validator import SUPPORTED_EXTENSIONS, validate_log_content, validate_log_path
from app.schemas import ValidationDecision, ValidationResult

logger = logging.getLogger(__name__)

SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)\S+"),
    re.compile(r"atl-[A-Za-z0-9]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
)

EXTRACT_FIELDS = (
    ("job_name", "Job name"),
    ("job", "Job name"),
    ("error_code", "Error code"),
    ("return_code", "Return code"),
    ("error_messages", "주요 오류"),
    ("input_path", "File path"),
    ("file_path", "File path"),
    ("path", "File path"),
    ("business_date", "Parameter / business_date"),
    ("parameters", "Parameters"),
    ("connection_name", "DB connection"),
    ("account", "DB account"),
    ("sql_object", "SQL object"),
    ("table", "SQL object"),
    ("schema", "SQL object"),
)


class AnalysisOutcome(BaseModel):
    ok: bool
    version: str
    validation: ValidationResult
    result: dict[str, Any] | None = None
    error: str | None = None
    case_id: str | None = None
    trace: dict[str, Any] | None = None


def public_error_message(exc: BaseException) -> str:
    text = str(exc)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    if not text.strip():
        return "분석 중 오류가 발생했습니다."
    return text


def validate_input(log_text: str, filename: str | None = None) -> ValidationResult:
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            return ValidationResult(
                decision=ValidationDecision.ABORT,
                reasons=[f"지원하지 않는 확장자입니다: {suffix or '확장자 없음'}"],
            )
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=suffix,
                delete=False,
            ) as tmp:
                tmp.write(log_text)
                tmp_path = tmp.name
            return validate_log_path(tmp_path)
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
    return validate_log_content(log_text)


def run_backend(version: str, log_text: str, case_id: str):
    if version == "v1":
        from app.tool_use import diagnose_v1

        return diagnose_v1(log_text, case_id=case_id)
    if version == "v2":
        from app.planning import diagnose_v2

        return diagnose_v2(log_text, case_id=case_id)
    return diagnose(log_text, case_id=case_id)


def extract_visible_fields(extracted_info: dict[str, Any] | None) -> list[tuple[str, Any]]:
    if not extracted_info:
        return []
    shown_labels: set[str] = set()
    rows: list[tuple[str, Any]] = []
    for key, label in EXTRACT_FIELDS:
        if key not in extracted_info:
            continue
        if label in shown_labels:
            continue
        value = extracted_info[key]
        if value in (None, "", [], {}):
            continue
        shown_labels.add(label)
        rows.append((label, value))
    return rows


def summarize_tool_data(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}
    summary: dict[str, Any] = {}
    for key in (
        "path",
        "filename",
        "exists",
        "received",
        "job_name",
        "parameter_name",
        "parameter_value",
        "expected_value",
        "is_valid",
        "format_valid",
        "range_valid",
        "rule",
        "job_run_date",
        "connection_name",
        "account",
        "account_locked",
        "credential_status",
        "connection_config_valid",
        "schema",
        "table",
        "column",
        "schema_exists",
        "table_exists",
        "column_exists",
    ):
        if key in data:
            summary[key] = data[key]
    return summary


def analyze(
    version: str,
    log_text: str,
    case_id: str | None = None,
    filename: str | None = None,
) -> AnalysisOutcome:
    resolved_case_id = case_id or (Path(filename).stem if filename else "ui_case")
    validation = validate_input(log_text, filename=filename)
    if validation.decision == ValidationDecision.ABORT:
        return AnalysisOutcome(
            ok=False,
            version=version,
            validation=validation,
            result=None,
            error=None,
            case_id=resolved_case_id,
            trace=None,
        )
    try:
        result = run_backend(version, log_text, resolved_case_id)
        payload = result.model_dump()
        from app.trace import build_execution_trace

        trace_version = "v1" if version == "v2" else version
        trace = build_execution_trace(trace_version, payload).model_dump()
        if version == "v2":
            trace["version"] = "v2"
            trace["planning_trace"] = payload.get("planning_trace") or []
            trace["stop_reason"] = payload.get("stop_reason")
        return AnalysisOutcome(
            ok=True,
            version=version,
            validation=validation,
            result=payload,
            error=None,
            case_id=resolved_case_id,
            trace=trace,
        )
    except Exception as exc:
        logger.exception("analysis failed")
        return AnalysisOutcome(
            ok=False,
            version=version,
            validation=validation,
            result=None,
            error=public_error_message(exc),
            case_id=resolved_case_id,
            trace=None,
        )


def hypotheses_from_result(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("initial_hypotheses"):
        return payload["initial_hypotheses"]
    return payload.get("hypotheses") or []
