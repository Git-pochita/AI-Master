"""V3.1 Structured Evidence Comparison.

SUCCESS Tool / log / extracted_info의 관찰 가능한 필드만 구조화한다.
원인 코드는 결정하지 않는다. FAILED Tool error는 사용하지 않는다.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field

from app.schemas import ToolResult
from app.tools.evidence import supporting_tool_results

_DATE_TOKEN = re.compile(r"(?<!\d)\d{8}(?!\d)")
# 1글자 prefix(sales/summary)를 제외하기 위한 일반 기준. cause를 고르지 않는다.
_MIN_SHARED_PREFIX_LEN = 3
_MIN_SHARED_PREFIX_RATIO = 0.5


class StructuredObservation(BaseModel):
    source: str
    fact_type: str
    description: str
    raw_reference: str | None = None


class EvidenceComparison(BaseModel):
    current_cause_code: str
    supporting_observations: list[StructuredObservation] = Field(default_factory=list)
    potentially_conflicting_observations: list[StructuredObservation] = Field(
        default_factory=list
    )
    strong_causal_observations: list[StructuredObservation] = Field(default_factory=list)
    surface_symptoms: list[StructuredObservation] = Field(default_factory=list)


def _bool_text(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return str(value)


def _file_name(entry: dict[str, Any] | None, fallback_path: str = "") -> str:
    payload = entry or {}
    name = payload.get("filename") or payload.get("name")
    if name:
        return str(name)
    path = str(payload.get("path") or fallback_path or "")
    return PurePosixPath(path).name if path else ""


def _date_tokens(text: str) -> set[str]:
    return set(_DATE_TOKEN.findall(text or ""))


def _filename_body(name: str) -> str:
    """확장자와 8자리 날짜 토큰을 뺀 파일명 body. 원인 판정용이 아니다."""
    stem = PurePosixPath(name or "").stem
    body = _DATE_TOKEN.sub("", stem)
    return re.sub(r"[^A-Za-z0-9]+", "", body).lower()


def _shared_prefix(left: str, right: str) -> str:
    chars: list[str] = []
    for one, two in zip(left, right):
        if one != two:
            break
        chars.append(one)
    return "".join(chars)


def _extracted_date_tokens(extracted_info: dict[str, Any] | None) -> set[str]:
    dates: set[str] = set()
    payload = extracted_info or {}
    for key in ("business_date", "job_run_date"):
        dates |= _date_tokens(str(payload.get(key) or ""))
    return dates


def _date_token_overlap(
    requested_name: str,
    sibling_name: str,
    extracted_info: dict[str, Any] | None,
) -> bool:
    requested_dates = _date_tokens(requested_name) | _extracted_date_tokens(extracted_info)
    sibling_dates = _date_tokens(sibling_name)
    return bool(requested_dates & sibling_dates)


def _filename_body_prefix_shared(requested_name: str, sibling_name: str) -> bool:
    left = _filename_body(requested_name)
    right = _filename_body(sibling_name)
    if not left or not right:
        return False
    shared = _shared_prefix(left, right)
    if len(shared) < _MIN_SHARED_PREFIX_LEN:
        return False
    shorter = min(len(left), len(right))
    return (len(shared) / shorter) >= _MIN_SHARED_PREFIX_RATIO


def _shares_review_context(
    requested_name: str,
    sibling_name: str,
    extracted_info: dict[str, Any] | None,
) -> bool:
    """요청 파일과 sibling이 같은 운영 맥락을 갖는지. cause를 고르지 않는다."""
    if not requested_name or not sibling_name:
        return False
    return _date_token_overlap(
        requested_name, sibling_name, extracted_info
    ) and _filename_body_prefix_shared(requested_name, sibling_name)


def _observation(
    *,
    source: str,
    fact_type: str,
    description: str,
    raw_reference: str | None = None,
) -> StructuredObservation:
    return StructuredObservation(
        source=source,
        fact_type=fact_type,
        description=description,
        raw_reference=raw_reference,
    )


def _append_unique(bucket: list[StructuredObservation], item: StructuredObservation) -> None:
    key = (item.source, item.fact_type, item.description)
    if any((row.source, row.fact_type, row.description) == key for row in bucket):
        return
    bucket.append(item)


def _normalize_file(
    data: dict[str, Any],
    comparison: EvidenceComparison,
    extracted_info: dict[str, Any] | None = None,
) -> None:
    source = "check_file_status"
    path = str(data.get("path") or "")
    filename = _file_name(data, path)
    exists = data.get("exists")
    received = data.get("received")

    if path:
        _append_unique(
            comparison.supporting_observations,
            _observation(
                source=source,
                fact_type="requested_file_state",
                description=f"requested_file:path={path},exists={_bool_text(exists)}",
                raw_reference=path,
            ),
        )
        _append_unique(
            comparison.supporting_observations,
            _observation(
                source=source,
                fact_type="requested_file_state",
                description=f"requested_file:path={path},received={_bool_text(received)}",
                raw_reference=path,
            ),
        )
    if filename:
        _append_unique(
            comparison.supporting_observations,
            _observation(
                source=source,
                fact_type="requested_file_state",
                description=f"requested_file:name={filename}",
                raw_reference=filename,
            ),
        )
    if exists is False or received is False:
        _append_unique(
            comparison.surface_symptoms,
            _observation(
                source=source,
                fact_type="target_missing",
                description=(
                    f"requested_file:path={path},exists={_bool_text(exists)},"
                    f"received={_bool_text(received)}"
                ),
                raw_reference=path or filename,
            ),
        )

    siblings = data.get("same_directory_files")
    if not isinstance(siblings, list):
        return
    for raw in siblings:
        if not isinstance(raw, dict):
            continue
        sibling_path = str(raw.get("path") or "")
        sibling_name = _file_name(raw, sibling_path)
        if not sibling_name and not sibling_path:
            continue
        if path and sibling_path and sibling_path == path:
            continue
        if filename and sibling_name and sibling_name == filename:
            continue
        sibling_received = raw.get("received")
        sibling_exists = raw.get("exists")
        ordinary = _observation(
            source=source,
            fact_type="same_directory_file",
            description=(
                f"same_directory_file:name={sibling_name},"
                f"exists={_bool_text(sibling_exists)},"
                f"received={_bool_text(sibling_received)}"
            ),
            raw_reference=sibling_name or sibling_path,
        )
        if sibling_received is True and _shares_review_context(
            filename, sibling_name, extracted_info
        ):
            date_overlap = _date_token_overlap(filename, sibling_name, extracted_info)
            prefix_shared = _filename_body_prefix_shared(filename, sibling_name)
            _append_unique(
                comparison.potentially_conflicting_observations,
                _observation(
                    source=source,
                    fact_type="received_other_file",
                    description=(
                        f"same_directory_file:name={sibling_name},received=true,"
                        f"exact_name_match=false,"
                        f"date_token_overlap={_bool_text(date_overlap)},"
                        f"filename_body_prefix_shared={_bool_text(prefix_shared)}"
                    ),
                    raw_reference=sibling_name,
                ),
            )
            _append_unique(comparison.supporting_observations, ordinary)
            continue
        _append_unique(comparison.supporting_observations, ordinary)


def _normalize_parameter(
    data: dict[str, Any],
    comparison: EvidenceComparison,
) -> None:
    source = "validate_parameter"
    name = str(data.get("parameter_name") or "")
    value = data.get("parameter_value")
    expected = data.get("expected_value")
    is_valid = data.get("is_valid")
    provided = data.get("provided")
    required = data.get("required")
    description = (
        f"parameter:name={name},value={value},expected={expected},"
        f"is_valid={_bool_text(is_valid)}"
    )
    _append_unique(
        comparison.supporting_observations,
        _observation(
            source=source,
            fact_type="parameter_state",
            description=description,
            raw_reference=name or None,
        ),
    )
    if is_valid is False:
        _append_unique(
            comparison.strong_causal_observations,
            _observation(
                source=source,
                fact_type="parameter_invalid",
                description=description,
                raw_reference=str(value) if value is not None else name or None,
            ),
        )
    if provided is False and required is True:
        _append_unique(
            comparison.strong_causal_observations,
            _observation(
                source=source,
                fact_type="parameter_missing",
                description=f"parameter:name={name},provided=false,required=true",
                raw_reference=name or None,
            ),
        )


def _normalize_db(
    data: dict[str, Any],
    comparison: EvidenceComparison,
) -> None:
    source = "check_db_status"
    connection = str(data.get("connection_name") or "")
    account = str(data.get("account") or "")
    locked = data.get("account_locked")
    credential = data.get("credential_status")
    config_valid = data.get("connection_config_valid")
    description = (
        f"db:connection={connection},account={account},"
        f"account_locked={_bool_text(locked)},"
        f"credential_status={credential},"
        f"connection_config_valid={_bool_text(config_valid)}"
    )
    _append_unique(
        comparison.supporting_observations,
        _observation(
            source=source,
            fact_type="db_state",
            description=description,
            raw_reference=account or connection or None,
        ),
    )
    invalid = locked is True or config_valid is False
    if isinstance(credential, str) and credential and credential.upper() not in {
        "VALID",
        "OK",
        "MATCH",
    }:
        invalid = True
    if invalid:
        _append_unique(
            comparison.strong_causal_observations,
            _observation(
                source=source,
                fact_type="db_invalid_state",
                description=description,
                raw_reference=account or connection or None,
            ),
        )


def _normalize_sql(
    data: dict[str, Any],
    comparison: EvidenceComparison,
) -> None:
    source = "check_sql_metadata"
    schema = data.get("schema")
    table = data.get("table")
    column = data.get("column")
    schema_exists = data.get("schema_exists")
    table_exists = data.get("table_exists")
    column_exists = data.get("column_exists")
    description = (
        f"sql:schema={schema},table={table},column={column},"
        f"schema_exists={_bool_text(schema_exists)},"
        f"table_exists={_bool_text(table_exists)},"
        f"column_exists={_bool_text(column_exists)}"
    )
    _append_unique(
        comparison.supporting_observations,
        _observation(
            source=source,
            fact_type="sql_state",
            description=description,
            raw_reference=str(table or schema or ""),
        ),
    )
    missing = (
        schema_exists is False
        or table_exists is False
        or column_exists is False
    )
    if missing:
        _append_unique(
            comparison.strong_causal_observations,
            _observation(
                source=source,
                fact_type="sql_object_missing",
                description=description,
                raw_reference=str(column or table or schema or ""),
            ),
        )


def _normalize_log(
    log_text: str,
    extracted_info: dict[str, Any],
    comparison: EvidenceComparison,
) -> None:
    for line in (log_text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "FileNotFoundError" in stripped or "File not found" in stripped:
            _append_unique(
                comparison.surface_symptoms,
                _observation(
                    source="log",
                    fact_type="read_failure",
                    description=stripped[:240],
                    raw_reference=stripped[:240],
                ),
            )
    errors = extracted_info.get("error_messages")
    if isinstance(errors, list):
        for item in errors:
            text = str(item)
            if "FileNotFoundError" in text or "File not found" in text:
                _append_unique(
                    comparison.surface_symptoms,
                    _observation(
                        source="extracted_info",
                        fact_type="read_failure",
                        description=text[:240],
                        raw_reference=text[:240],
                    ),
                )


_TOOL_NORMALIZERS = {
    "check_file_status": _normalize_file,
    "validate_parameter": _normalize_parameter,
    "check_db_status": _normalize_db,
    "check_sql_metadata": _normalize_sql,
}


def build_evidence_comparison(
    *,
    current_cause_code: str,
    tool_results: list[ToolResult] | None,
    log_text: str = "",
    extracted_info: dict[str, Any] | None = None,
) -> EvidenceComparison:
    comparison = EvidenceComparison(current_cause_code=current_cause_code)
    context = extracted_info or {}
    for item in supporting_tool_results(list(tool_results or [])):
        data = item.data if isinstance(item.data, dict) else None
        if not data:
            continue
        if item.tool == "check_file_status":
            _normalize_file(data, comparison, context)
            continue
        normalizer = _TOOL_NORMALIZERS.get(item.tool)
        if normalizer is None:
            continue
        normalizer(data, comparison)
    _normalize_log(log_text, context, comparison)
    return comparison


def comparison_payload(comparison: EvidenceComparison) -> dict[str, Any]:
    return comparison.model_dump()
