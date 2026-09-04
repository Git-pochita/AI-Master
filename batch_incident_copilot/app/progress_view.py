"""시연 화면용 progress 라벨/그룹핑. 진단 로직과 event payload는 바꾸지 않는다."""

from __future__ import annotations

import re

from app.cause_codes import CAUSE_CODE_NAMES
from app.progress import (
    STEP_CRITIC,
    STEP_EVIDENCE,
    STEP_HYPOTHESES,
    STEP_LOG_ANALYSIS,
    STEP_PLANNING,
    STEP_REFLECTION,
    STEP_REPLAN,
    STEP_TOOL,
    STEP_VALIDATION,
    ProgressEvent,
)

TOOL_LABELS = {
    "check_file_status": "파일 상태 확인",
    "validate_parameter": "실행일자 검증",
    "check_db_status": "DB 상태 확인",
    "check_sql_metadata": "SQL 메타데이터 확인",
}

OWNER_LABELS = {
    "BATCH_OPERATION": "배치 운영",
    "DATA_ENGINEER": "데이터 엔지니어",
    "DBA": "DBA",
}

ISSUE_TYPE_LABELS = {
    "EVIDENCE_CONFLICT": "근거 충돌",
    "BETTER_SUPPORTED_CAUSE": "더 잘 맞는 원인",
    "FAILED_EVIDENCE_USED": "실패 근거 사용",
    "DIAGNOSIS_LEVEL_TOO_HIGH": "진단 수준 과대",
    "DIAGNOSIS_LEVEL_TOO_LOW": "진단 수준 과소",
    "OWNER_MISMATCH": "담당 영역 불일치",
}

_STEP_GROUP = {
    STEP_VALIDATION: "로그 분석",
    STEP_LOG_ANALYSIS: "로그 분석",
    STEP_HYPOTHESES: "원인 후보",
    STEP_PLANNING: "추가 점검",
    STEP_REPLAN: "추가 점검",
    STEP_TOOL: "추가 점검",
    STEP_EVIDENCE: "근거 종합",
    STEP_CRITIC: "최종 검증",
    STEP_REFLECTION: "최종 검증",
}

_KV = re.compile(r"^([A-Za-z0-9_]+)=(.*)$")
_EQ_IN_TEXT = re.compile(r"\b(parameter_value|expected_value|business_date|exists|received|is_valid)=([^\s,]+)")


def owner_label(owner: str | None) -> str:
    value = (owner or "").strip()
    return OWNER_LABELS.get(value, value or "미지정")


def cause_label(code_or_name: str | None) -> str:
    value = (code_or_name or "").strip()
    if not value:
        return ""
    return CAUSE_CODE_NAMES.get(value, value)


def issue_type_label(value: object | None) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip()
    return ISSUE_TYPE_LABELS.get(text, text)


def verdict_label(verdict: str | None) -> str:
    text = str(verdict or "").strip()
    if text == "PASS":
        return "통과"
    if text == "REVISE":
        return "교정 필요"
    return text or "확인 완료"


def yes_no_label(value: object | None) -> str:
    if value is True:
        return "예"
    if value is False:
        return "아니오"
    return "해당 없음"


def operator_running_label(event: ProgressEvent) -> str:
    return _STEP_GROUP.get(event.step, event.title)


def format_operator_progress(
    events: list[ProgressEvent],
    running_title: str | None = None,
) -> str:
    """운영자용 누적 진행 패널. markdown 리스트('- ', '* ')는 쓰지 않는다."""
    groups: list[tuple[str, list[str]]] = []
    for title, lines in (
        ("로그 분석", _log_group(events)),
        ("원인 후보", _hypothesis_group(events)),
        ("추가 점검", _check_group(events)),
        ("근거 종합", _evidence_group(events)),
        ("최종 검증", _critic_group(events)),
    ):
        if lines:
            groups.append((title, lines[:3]))
    blocks: list[str] = []
    for title, lines in groups:
        rows = [f"✓ **{title}**"]
        for line in lines:
            text = str(line).strip()
            if not text:
                continue
            rows.append(f"· {text}")
        blocks.append("\n\n".join(rows))
    if running_title:
        blocks.append(f"진행 중: **{running_title}**")
    if not blocks:
        return "분석 단계를 기다리는 중입니다."
    return "\n\n".join(blocks)


def _done(events: list[ProgressEvent], step: str) -> list[ProgressEvent]:
    return [item for item in events if item.step == step and item.status == "done"]


def _log_group(events: list[ProgressEvent]) -> list[str]:
    failed = [
        item
        for item in _done(events, STEP_VALIDATION)
        if (item.metadata or {}).get("decision") == "ABORT"
    ]
    if failed:
        return [str(line) for line in failed[0].details[:3] if str(line).strip()]
    log_events = _done(events, STEP_LOG_ANALYSIS)
    if not log_events:
        return []
    lines: list[str] = []
    seen: set[str] = set()
    for raw in log_events[0].details:
        text = str(raw).strip()
        match = _KV.match(text)
        if match:
            key, value = match.group(1), match.group(2)
            if key == "job" and "작업" not in seen:
                lines.append(f"작업: {value}")
                seen.add("작업")
            continue
        if "주요 오류" not in seen:
            short = text.split(":", 1)[0].strip()
            lines.append(f"주요 오류: {short or text}")
            seen.add("주요 오류")
        if len(lines) >= 3:
            break
    return lines


def _hypothesis_group(events: list[ProgressEvent]) -> list[str]:
    rows: list[str] = []
    for item in _done(events, STEP_HYPOTHESES):
        for raw in item.details:
            label = cause_label(str(raw))
            if label and label not in rows:
                rows.append(label)
            if len(rows) >= 3:
                return rows
    return rows


def _check_group(events: list[ProgressEvent]) -> list[str]:
    lines: list[str] = []
    for item in events:
        if item.status != "done" or item.step != STEP_TOOL:
            continue
        line = _tool_outcome_line(item)
        if line and line not in lines:
            lines.append(line)
        if len(lines) >= 3:
            break
    if lines:
        return lines
    planning = _done(events, STEP_PLANNING)
    if not planning:
        return []
    for raw in planning[0].details:
        name = str(raw).replace(" 후보", "").strip()
        label = TOOL_LABELS.get(name, name)
        if label and label not in lines:
            lines.append(label)
        if len(lines) >= 3:
            break
    return lines


def _tool_outcome_line(event: ProgressEvent) -> str:
    tool = str((event.metadata or {}).get("tool") or "")
    label = TOOL_LABELS.get(tool, tool or "추가 점검")
    status = str((event.metadata or {}).get("status") or "")
    blob = " ".join(str(item) for item in event.details)
    if status == "FAILED" or "실행 실패" in blob:
        return f"{label} → 실패"
    if "is_valid=False" in blob:
        return f"{label} → 불일치 확인"
    if "exists=False" in blob or "received=False" in blob:
        return f"{label} → 실패"
    if "is_valid=True" in blob or "exists=True" in blob:
        return f"{label} → 확인"
    return f"{label} 완료"


def _evidence_group(events: list[ProgressEvent]) -> list[str]:
    parsed: dict[str, str] = {}
    leftovers: list[str] = []
    sources = list(_done(events, STEP_EVIDENCE)) + list(_done(events, STEP_TOOL))
    if not _done(events, STEP_EVIDENCE):
        return []
    for event in sources:
        for raw in event.details:
            text = str(raw).strip()
            if not text:
                continue
            for key, value in _EQ_IN_TEXT.findall(text):
                parsed[key] = value
            match = _KV.match(text)
            if match:
                parsed[match.group(1)] = match.group(2)
                continue
            if (
                event.step == STEP_EVIDENCE
                and not text.lstrip().startswith("{")
                and "SUCCESS data" not in text
            ):
                leftovers.append(text)
    lines: list[str] = []
    business = parsed.get("parameter_value") or parsed.get("business_date")
    expected = parsed.get("expected_value")
    if business:
        lines.append(f"business_date: {business}")
    if expected:
        lines.append(f"expected: {expected}")
    if len(lines) >= 2:
        return lines[:3]
    for item in leftovers:
        if item not in lines:
            lines.append(item)
        if len(lines) >= 3:
            break
    return lines[:3]


def _critic_group(events: list[ProgressEvent]) -> list[str]:
    if not _done(events, STEP_CRITIC) and not _done(events, STEP_REFLECTION):
        return []
    return ["진단 근거 일관성 확인 완료"]
