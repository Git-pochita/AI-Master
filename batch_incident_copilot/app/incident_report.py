"""최종 진단 payload를 팀장 보고용 장애 초동 보고서로 변환한다.

진단이나 LLM 호출은 수행하지 않는다. 기존 결과에서 확인 가능한 값만 사용한다.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


UNKNOWN = "확인되지 않음"
_TIMESTAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\b")

_OWNER_LABELS = {
    "BATCH_OPERATION": "배치 운영",
    "DBA": "DB 운영",
    "DATABASE": "DB 운영",
    "APPLICATION": "애플리케이션",
    "INFRA": "인프라",
}

_CAUSE_ACTION_TERMS = {
    "DB_CREDENTIAL_MISMATCH": ("인증", "credential", "패스워드", "비밀번호"),
    "DB_ACCOUNT_LOCKED": ("잠금", "계정"),
    "DB_CONNECTION_CONFIG_ERROR": ("접속", "연결", "connection", "설정"),
    "FILE_NOT_RECEIVED": ("파일", "수신", "전송"),
    "INVALID_FILE_PATH": ("파일", "경로", "path"),
    "INVALID_BUSINESS_DATE": ("영업일", "business", "파라미터", "날짜"),
    "MISSING_REQUIRED_PARAMETER": ("필수", "파라미터", "parameter"),
    "INVALID_PARAMETER_FORMAT": ("형식", "파라미터", "parameter"),
    "INVALID_PARAMETER_RANGE": ("범위", "파라미터", "parameter"),
    "INVALID_SCHEMA": ("스키마", "schema"),
    "TABLE_NOT_FOUND": ("테이블", "table"),
    "COLUMN_NOT_FOUND": ("컬럼", "column"),
}


class IncidentOverview(BaseModel):
    job_name: str
    occurred_at: str
    incident_type: str
    owner: str
    status: str


class IncidentCause(BaseModel):
    summary: str
    core_error: str
    final_cause: str
    cause_code: str
    diagnosis_level: str
    evidence: list[str] = Field(default_factory=list)


class IncidentReport(BaseModel):
    overview: IncidentOverview
    cause: IncidentCause
    action: str


def _text(value: Any) -> str:
    return str(value or "").strip()


def _extracted(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("extracted_info") or {}
    return value if isinstance(value, dict) else {}


def _job_name(payload: dict[str, Any]) -> str:
    info = _extracted(payload)
    return _text(info.get("job_name") or info.get("job")) or UNKNOWN


def _error_messages(payload: dict[str, Any]) -> list[str]:
    raw = _extracted(payload).get("error_messages") or []
    if isinstance(raw, str):
        raw = [raw]
    return [_text(item) for item in raw if _text(item)]


def _occurred_at(payload: dict[str, Any], log_text: str = "") -> str:
    info = _extracted(payload)
    for key in ("occurred_at", "error_time", "timestamp", "job_run_date"):
        value = _text(info.get(key))
        if value:
            match = _TIMESTAMP.search(value)
            return match.group(0).replace("T", " ") if match else value
    log_lines = _text(log_text).splitlines()
    error_lines = [line for line in log_lines if "ERROR" in line.upper()]
    for message in [*_error_messages(payload), *error_lines, *log_lines]:
        match = _TIMESTAMP.search(message)
        if match:
            return match.group(0).replace("T", " ")
    return UNKNOWN


def _core_error(payload: dict[str, Any]) -> str:
    messages = _error_messages(payload)
    if not messages:
        return UNKNOWN
    value = _TIMESTAMP.sub("", messages[0]).strip(" :-")
    return value or UNKNOWN


def _owner(payload: dict[str, Any]) -> str:
    value = _text(payload.get("owner"))
    if not value:
        return UNKNOWN
    return _OWNER_LABELS.get(value.upper(), value)


def _status(level: str) -> str:
    if level == "확인됨":
        return "원인 확인 / 조치 필요"
    if level == "가능성 높음":
        return "원인 유력 / 추가 확인 필요"
    return "원인 추정 / 확인 필요"


def _cause_summary(payload: dict[str, Any], final_cause: str, level: str) -> str:
    core_error = _core_error(payload)
    ending = "확인되었습니다" if level == "확인됨" else "판단됩니다"
    if core_error == UNKNOWN:
        return f"최종 원인은 {final_cause}로 {ending}."
    return f"로그에서 {core_error}가 발생했으며, 최종 원인은 {final_cause}로 {ending}."


def _tool_evidence(payload: dict[str, Any], cause_code: str) -> list[str]:
    lines: list[str] = []
    for result in payload.get("tool_results") or []:
        if not isinstance(result, dict) or result.get("status") != "SUCCESS":
            continue
        data = result.get("data") or {}
        if not isinstance(data, dict):
            continue
        if cause_code == "DB_CREDENTIAL_MISMATCH" and data.get("credential_status") == "MISMATCH":
            lines.append("DB 계정 인증 정보 불일치 확인")
        elif cause_code == "DB_ACCOUNT_LOCKED" and data.get("account_locked") is True:
            lines.append("DB 계정 잠금 상태 확인")
        elif cause_code == "DB_CONNECTION_CONFIG_ERROR" and data.get("connection_config_valid") is False:
            lines.append("DB 접속 설정 오류 확인")
        elif cause_code == "FILE_NOT_RECEIVED" and data.get("received") is False:
            lines.append("대상 파일 미수신 확인")
        elif cause_code == "INVALID_FILE_PATH" and data.get("exists") is False:
            lines.append("대상 파일 경로에 파일 없음 확인")
        elif cause_code in {
            "INVALID_BUSINESS_DATE",
            "MISSING_REQUIRED_PARAMETER",
            "INVALID_PARAMETER_FORMAT",
            "INVALID_PARAMETER_RANGE",
        } and data.get("is_valid") is False:
            lines.append("입력 파라미터 유효성 오류 확인")
        elif cause_code == "INVALID_SCHEMA" and data.get("schema_exists") is False:
            lines.append("DB 스키마 미존재 확인")
        elif cause_code == "TABLE_NOT_FOUND" and data.get("table_exists") is False:
            lines.append("DB 테이블 미존재 확인")
        elif cause_code == "COLUMN_NOT_FOUND" and data.get("column_exists") is False:
            lines.append("DB 컬럼 미존재 확인")
    return lines


def _human_log_evidence(payload: dict[str, Any]) -> str | None:
    core = _core_error(payload)
    if core == UNKNOWN:
        return None
    match = re.search(r"(?:ORA|SQLSTATE|ERROR)[-_: ]?[A-Z0-9-]+", core, re.IGNORECASE)
    if match:
        return f"로그 오류 {match.group(0)} 발생"
    return f"로그에서 {core} 확인"


def _evidence(payload: dict[str, Any], cause_code: str) -> list[str]:
    candidates: list[str] = []
    log_line = _human_log_evidence(payload)
    if log_line:
        candidates.append(log_line)
    candidates.extend(_tool_evidence(payload, cause_code))
    unique: list[str] = []
    for item in candidates:
        if item not in unique:
            unique.append(item)
    return unique[:2]


def _report_action(payload: dict[str, Any], cause_code: str) -> str:
    terms = _CAUSE_ACTION_TERMS.get(cause_code, ())
    actions = [_text(item) for item in payload.get("recommended_actions") or []]
    selected = next(
        (item for item in actions if terms and any(term.lower() in item.lower() for term in terms)),
        None,
    )
    if not selected:
        return "최종 원인에 대응하는 조치 확인이 필요합니다."

    if cause_code == "DB_CREDENTIAL_MISMATCH":
        account = _text(_extracted(payload).get("account"))
        subject = f"{account} 계정의 " if account else "배치 계정의 "
        return f"{subject}DB 인증 정보를 확인·수정한 후 작업 재실행 여부를 검토합니다."

    selected = re.sub(r"(?:하십시오|하세요|바랍니다)[.]?$", "할 필요가 있습니다.", selected)
    return selected


def build_incident_report(
    payload: dict[str, Any], log_text: str = ""
) -> IncidentReport:
    """기존 최종 결과를 추가 추론 없이 보고용 구조로 변환한다."""
    cause_code = _text(payload.get("final_cause_code")) or UNKNOWN
    final_cause = _text(payload.get("final_cause_name")) or UNKNOWN
    level = _text(payload.get("diagnosis_level")) or UNKNOWN
    return IncidentReport(
        overview=IncidentOverview(
            job_name=_job_name(payload),
            occurred_at=_occurred_at(payload, log_text),
            incident_type=final_cause,
            owner=_owner(payload),
            status=_status(level),
        ),
        cause=IncidentCause(
            summary=_cause_summary(payload, final_cause, level),
            core_error=_core_error(payload),
            final_cause=final_cause,
            cause_code=cause_code,
            diagnosis_level=level,
            evidence=_evidence(payload, cause_code),
        ),
        action=_report_action(payload, cause_code),
    )
