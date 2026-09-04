"""분석 진행 상태를 시연 UI에 전달하는 고수준 progress 이벤트.

진단 결과/평가 의미를 바꾸지 않는다. LLM 내부 Chain-of-Thought나
planner/critic의 장문 reason은 담지 않는다.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Literal

from pydantic import BaseModel, Field

from app.schemas import ToolResult, ValidationDecision, ValidationResult

ProgressStatus = Literal["running", "done"]

STEP_VALIDATION = "validation"
STEP_LOG_ANALYSIS = "log_analysis"
STEP_HYPOTHESES = "hypotheses"
STEP_PLANNING = "planning"
STEP_REPLAN = "replan"
STEP_TOOL = "tool"
STEP_EVIDENCE = "evidence"
STEP_CRITIC = "critic"
STEP_REFLECTION = "reflection"

TITLE_VALIDATION = "입력 로그 검증 완료"
TITLE_VALIDATION_FAILED = "입력 로그 검증 실패"
TITLE_LOG_ANALYSIS = "핵심 오류 분석 완료"
TITLE_LOG_ANALYSIS_RUNNING = "핵심 오류 분석"
TITLE_HYPOTHESES = "초기 원인 후보 생성"
TITLE_PLANNING = "Investigation Plan 생성"
TITLE_REPLAN = "Re-planning"
TITLE_TOOL = "Tool 실행"
TITLE_EVIDENCE = "Evidence Aggregation 완료"
TITLE_EVIDENCE_RUNNING = "Evidence Aggregation"
TITLE_CRITIC = "Critic 검증 완료"
TITLE_CRITIC_RUNNING = "Critic 검증"
TITLE_REFLECTION = "Reflection 완료"
TITLE_REFLECTION_RUNNING = "Reflection"

_PRIVATE_COT_MARKERS = (
    "chain_of_thought",
    "chain-of-thought",
    "private_reasoning",
    "hidden_reasoning",
    "revision_reason",
    "planner_reason",
    "scratchpad",
)

TOOL_HIGHLIGHT_KEYS = (
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
)


class ProgressEvent(BaseModel):
    step: str
    title: str
    details: list[str] = Field(default_factory=list)
    status: ProgressStatus = "done"
    metadata: dict[str, Any] = Field(default_factory=dict)


ProgressCallback = Callable[[ProgressEvent], None]


def emit(progress_fn: ProgressCallback | None, event: ProgressEvent) -> None:
    if progress_fn is None:
        return
    event.details = [
        line for line in event.details if not _looks_like_private(str(line))
    ]
    progress_fn(event)


def _looks_like_private(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _PRIVATE_COT_MARKERS)


def contains_private_cot(event: ProgressEvent) -> bool:
    blob = " ".join([event.title, *event.details, *map(str, event.metadata.values())])
    return _looks_like_private(blob)


def _truncate(text: str, limit: int = 80) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def highlight_tool_data(data: dict[str, Any] | None) -> list[str]:
    if not data:
        return []
    lines: list[str] = []
    for key in TOOL_HIGHLIGHT_KEYS:
        if key not in data:
            continue
        value = data[key]
        if value in (None, "", [], {}):
            continue
        lines.append(f"{key}={value}")
    return lines


def emit_validation(
    progress_fn: ProgressCallback | None,
    validation: ValidationResult,
) -> None:
    failed = validation.decision == ValidationDecision.ABORT
    emit(
        progress_fn,
        ProgressEvent(
            step=STEP_VALIDATION,
            title=TITLE_VALIDATION_FAILED if failed else TITLE_VALIDATION,
            details=list(validation.reasons or []),
            status="done",
            metadata={"decision": validation.decision.value},
        ),
    )


def emit_log_analysis(
    progress_fn: ProgressCallback | None,
    extracted_info: dict[str, Any] | None,
) -> None:
    emit(
        progress_fn,
        ProgressEvent(
            step=STEP_LOG_ANALYSIS,
            title=TITLE_LOG_ANALYSIS,
            details=_log_analysis_details(extracted_info),
            status="done",
        ),
    )


def _log_analysis_details(extracted_info: dict[str, Any] | None) -> list[str]:
    extracted = extracted_info or {}
    details: list[str] = []
    errors = extracted.get("error_messages")
    if isinstance(errors, list):
        for item in errors:
            text = _truncate(str(item), 100)
            if text and text not in details:
                details.append(text)
    elif isinstance(errors, str) and errors.strip():
        details.append(_truncate(errors, 100))
    seen_labels: set[str] = set()
    for key, label in (
        ("error_code", "error_code"),
        ("return_code", "return_code"),
        ("job_name", "job"),
        ("job", "job"),
        ("input_path", "path"),
        ("file_path", "path"),
        ("path", "path"),
    ):
        if label in seen_labels:
            continue
        value = extracted.get(key)
        if value in (None, "", [], {}):
            continue
        details.append(f"{label}={value}")
        seen_labels.add(label)
    return details


def _hypothesis_rows(hypotheses: Iterable[Any]) -> list[str]:
    rows: list[str] = []
    for item in hypotheses or []:
        if isinstance(item, dict):
            code = item.get("cause_code")
        else:
            code = getattr(item, "cause_code", None)
        if not code:
            continue
        rows.append(str(code))
    return rows


def emit_hypotheses(
    progress_fn: ProgressCallback | None,
    hypotheses: Iterable[Any],
) -> None:
    details = _hypothesis_rows(hypotheses)
    emit(
        progress_fn,
        ProgressEvent(
            step=STEP_HYPOTHESES,
            title=TITLE_HYPOTHESES,
            details=details,
            status="done",
            metadata={"count": len(details)},
        ),
    )


def emit_initial_perception(
    progress_fn: ProgressCallback | None,
    extracted_info: dict[str, Any] | None,
    hypotheses: Iterable[Any],
) -> None:
    emit_log_analysis(progress_fn, extracted_info)
    emit_hypotheses(progress_fn, hypotheses)


def running_label(event: ProgressEvent) -> str:
    tool = event.metadata.get("tool")
    if event.step == STEP_TOOL and tool:
        if str(tool) in event.title:
            return event.title
        return f"{event.title} · {tool}"
    return event.title


def format_progress_markdown(
    events: list[ProgressEvent],
    running_title: str | None = None,
) -> str:
    """st.empty().markdown()으로 한 번에 다시 그려 라이브 갱신한다.

    markdown 리스트 문법('- ', '* ')은 쓰지 않는다. st.status 중첩 시
    본문이 비는 Streamlit 버그를 피하기 위함이다.
    """
    blocks: list[str] = []
    for event in events:
        if event.status != "done":
            continue
        lines = [f"✓ **{event.title}**"]
        for item in event.details:
            text = str(item).strip()
            if not text:
                continue
            if not text.startswith("· "):
                text = f"· {text}"
            lines.append(text)
        blocks.append("\n\n".join(lines))
    if running_title:
        blocks.append(f"진행 중: **{running_title}**")
    if not blocks:
        return "분석 단계를 기다리는 중입니다."
    return "\n\n".join(blocks)


def emit_running(
    progress_fn: ProgressCallback | None,
    step: str,
    title: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    emit(
        progress_fn,
        ProgressEvent(
            step=step,
            title=title,
            details=[],
            status="running",
            metadata=metadata or {},
        ),
    )


def emit_planning(
    progress_fn: ProgressCallback | None,
    investigation_plan: Iterable[Any],
    *,
    round_index: int | None = None,
) -> None:
    details: list[str] = []
    tools: list[str] = []
    for step in investigation_plan or []:
        if isinstance(step, dict):
            tool = step.get("candidate_tool")
        else:
            tool = getattr(step, "candidate_tool", None)
        if not tool:
            continue
        name = str(tool)
        tools.append(name)
        if details:
            details.append(f"{name} 후보")
        else:
            details.append(name)
    emit(
        progress_fn,
        ProgressEvent(
            step=STEP_PLANNING,
            title=TITLE_PLANNING,
            details=details,
            status="done",
            metadata={"round": round_index, "tools": tools},
        ),
    )


def emit_replan(
    progress_fn: ProgressCallback | None,
    selected_tool: str | None,
    *,
    round_index: int | None = None,
) -> None:
    details = ["이전 점검만으로 원인 확정 부족"]
    if selected_tool:
        details.append(f"다음 점검: {selected_tool}")
    emit(
        progress_fn,
        ProgressEvent(
            step=STEP_REPLAN,
            title=TITLE_REPLAN,
            details=details,
            status="done",
            metadata={"round": round_index, "selected_tool": selected_tool},
        ),
    )


def emit_tool(
    progress_fn: ProgressCallback | None,
    tool_name: str,
    result: ToolResult | dict[str, Any] | None,
    *,
    round_index: int | None = None,
) -> None:
    payload = result.model_dump() if isinstance(result, ToolResult) else (result or {})
    status = str(payload.get("status") or "")
    if status == "FAILED":
        details = ["실행 실패 (최종 근거에서 제외)"]
    else:
        details = highlight_tool_data(payload.get("data") or {})
    emit(
        progress_fn,
        ProgressEvent(
            step=STEP_TOOL,
            title=f"{TITLE_TOOL} · {tool_name}",
            details=details,
            status="done",
            metadata={
                "tool": tool_name,
                "status": status,
                "round": round_index,
            },
        ),
    )


def _looks_like_raw_json(text: str) -> bool:
    stripped = (text or "").lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def evidence_details(
    evidence: Iterable[str] | None = None,
    tool_results: Iterable[Any] | None = None,
    *,
    limit: int = 4,
) -> list[str]:
    """최종 판단에 쓰인 핵심 evidence만 2~4줄로 요약한다. raw JSON/CoT는 넣지 않는다."""
    lines: list[str] = []
    for text in evidence or []:
        cleaned = _truncate(str(text).strip(), 120)
        if not cleaned or _looks_like_private(cleaned) or _looks_like_raw_json(cleaned):
            continue
        if cleaned not in lines:
            lines.append(cleaned)
        if len(lines) >= limit:
            return lines
    if len(lines) >= 2:
        return lines[:limit]
    for item in tool_results or []:
        payload = item.model_dump() if hasattr(item, "model_dump") else dict(item or {})
        if str(payload.get("status") or "") != "SUCCESS":
            continue
        tool = str(payload.get("tool") or "")
        for field in highlight_tool_data(payload.get("data") or {}):
            line = f"{tool}: {field}" if tool else field
            if line not in lines:
                lines.append(line)
            if len(lines) >= limit:
                return lines
    return lines[:limit]


def emit_evidence(
    progress_fn: ProgressCallback | None,
    evidence: Iterable[str] | None = None,
    tool_results: Iterable[Any] | None = None,
) -> None:
    details = evidence_details(evidence, tool_results)
    emit(
        progress_fn,
        ProgressEvent(
            step=STEP_EVIDENCE,
            title=TITLE_EVIDENCE,
            details=details,
            status="done",
            metadata={"count": len(details)},
        ),
    )


def _issue_types(issues: Iterable[Any]) -> list[str]:
    names: list[str] = []
    for item in issues or []:
        if isinstance(item, dict):
            value = item.get("issue_type")
        else:
            value = getattr(item, "issue_type", None)
        if value is None:
            continue
        names.append(value.value if hasattr(value, "value") else str(value))
    return names


def emit_critic(progress_fn: ProgressCallback | None, critic: Any) -> None:
    payload = critic.model_dump() if hasattr(critic, "model_dump") else dict(critic or {})
    issue_types = _issue_types(payload.get("issues") or [])
    details = [str(payload.get("verdict") or "PASS")]
    if issue_types:
        details.append("issue type: " + ", ".join(issue_types))
    emit(
        progress_fn,
        ProgressEvent(
            step=STEP_CRITIC,
            title=TITLE_CRITIC,
            details=details,
            status="done",
            metadata={
                "verdict": payload.get("verdict"),
                "issue_types": issue_types,
            },
        ),
    )


def emit_reflection(
    progress_fn: ProgressCallback | None,
    *,
    revised: bool,
    original_cause: str | None = None,
    final_cause: str | None = None,
) -> None:
    details: list[str] = []
    if original_cause and final_cause:
        details.append(f"{original_cause} → {final_cause}")
    elif revised:
        details.append("진단 수준 교정")
    emit(
        progress_fn,
        ProgressEvent(
            step=STEP_REFLECTION,
            title=TITLE_REFLECTION,
            details=details,
            status="done",
            metadata={
                "revised": revised,
                "original_cause": original_cause,
                "final_cause": final_cause,
            },
        ),
    )
