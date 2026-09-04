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
TITLE_HYPOTHESES = "초기 원인 후보 생성"
TITLE_PLANNING = "Investigation Plan 생성"
TITLE_REPLAN = "Re-planning"
TITLE_TOOL = "Tool 실행"
TITLE_EVIDENCE = "Evidence Aggregation 완료"
TITLE_CRITIC = "Critic 검증 완료"
TITLE_REFLECTION = "Reflection 완료"

_PRIVATE_COT_MARKERS = (
    "chain_of_thought",
    "private_reasoning",
    "hidden_reasoning",
    "revision_reason",
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
    progress_fn(event)


def contains_private_cot(event: ProgressEvent) -> bool:
    blob = " ".join([event.title, *event.details, *map(str, event.metadata.values())])
    lowered = blob.lower()
    return any(marker in lowered for marker in _PRIVATE_COT_MARKERS)


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
    extracted = extracted_info or {}
    details: list[str] = []
    errors = extracted.get("error_messages")
    if isinstance(errors, list):
        for item in errors:
            text = _truncate(str(item), 100)
            if text:
                details.append(text)
    elif isinstance(errors, str) and errors.strip():
        details.append(_truncate(errors, 100))
    for key, label in (
        ("error_code", "error_code"),
        ("return_code", "return_code"),
        ("job_name", "job"),
        ("job", "job"),
    ):
        value = extracted.get(key)
        if value in (None, "", [], {}):
            continue
        line = f"{label}={value}"
        if line not in details:
            details.append(line)
        if label == "job":
            break
    emit(
        progress_fn,
        ProgressEvent(
            step=STEP_LOG_ANALYSIS,
            title=TITLE_LOG_ANALYSIS,
            details=details,
            status="done",
        ),
    )


def _hypothesis_rows(hypotheses: Iterable[Any]) -> list[str]:
    rows: list[str] = []
    for item in hypotheses or []:
        if isinstance(item, dict):
            code = item.get("cause_code")
            name = item.get("cause_name") or ""
        else:
            code = getattr(item, "cause_code", None)
            name = getattr(item, "cause_name", "") or ""
        if not code:
            continue
        rows.append(f"`{code}` {name}".strip())
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
            goal = step.get("goal") or ""
        else:
            tool = getattr(step, "candidate_tool", None)
            goal = getattr(step, "goal", "") or ""
        if tool:
            tools.append(str(tool))
        label = f"`{tool}`" if tool else "추가 확인 항목"
        goal_text = _truncate(str(goal), 80)
        if goal_text:
            details.append(f"{label} — {goal_text}")
        else:
            details.append(label)
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
    details = ["이전 점검만으로는 원인을 확정하기 부족합니다."]
    if selected_tool:
        details.append(f"추가 점검: `{selected_tool}`")
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
    details = [f"`{tool_name}`"]
    if status == "FAILED":
        details.append("실행 실패 (최종 근거에서 제외)")
    else:
        details.extend(highlight_tool_data(payload.get("data") or {}))
    emit(
        progress_fn,
        ProgressEvent(
            step=STEP_TOOL,
            title=TITLE_TOOL,
            details=details,
            status="done",
            metadata={
                "tool": tool_name,
                "status": status,
                "round": round_index,
            },
        ),
    )


def emit_evidence(progress_fn: ProgressCallback | None) -> None:
    emit(
        progress_fn,
        ProgressEvent(
            step=STEP_EVIDENCE,
            title=TITLE_EVIDENCE,
            details=["수집된 Tool 결과와 로그 신호를 종합했습니다."],
            status="done",
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
    details = [
        f"verdict: `{payload.get('verdict') or 'PASS'}`",
        f"evidence_consistent: `{payload.get('evidence_consistent')}`",
    ]
    if issue_types:
        details.append("issue types: " + ", ".join(f"`{name}`" for name in issue_types))
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
    details = ["V2 진단과 Critic 이슈를 비교해 최종 진단을 재검토했습니다."]
    if revised and original_cause and final_cause and original_cause != final_cause:
        details.append(f"원인 코드: `{original_cause}` → `{final_cause}`")
    elif revised:
        details.append("진단 수준 또는 원인을 교정했습니다.")
    else:
        details.append("원인 코드는 유지했습니다.")
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
