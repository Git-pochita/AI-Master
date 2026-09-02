"""진단 결과 payload를 고수준 AgentEvent 목록으로 정규화한다.

기존 AgentExecutionTrace / planning_trace를 대체하지 않는다.
관찰 가능한 상태 전환만 기록하며, LLM reason/summary 등 private CoT는 복사하지 않는다.
"""

from __future__ import annotations

from typing import Any

from app.cause_codes import CAUSE_CODE_NAMES
from app.schemas import AgentComponent, AgentEvent, StopReason, utc_timestamp
from app.trace import build_diagnosis_updates

ALLOWED_COMPONENTS: tuple[AgentComponent, ...] = (
    "Perception",
    "Reasoning",
    "Memory",
    "Action",
    "Feedback",
    "Evaluation",
    "Governance",
)

COMPONENT_ICONS: dict[str, str] = {
    "Perception": "👁️",
    "Reasoning": "🧠",
    "Memory": "💾",
    "Action": "⚡",
    "Feedback": "🔄",
    "Evaluation": "📊",
    "Governance": "🛡️",
}

STEP_LABELS: dict[str, str] = {
    "log_analysis": "Log Analysis",
    "initial_hypotheses": "Initial Hypotheses",
    "tool_selection": "Tool Selection",
    "tool_call": "Tool Call",
    "tool_result": "Tool Result",
    "evidence_update": "Evidence Update",
    "hypothesis_update": "Hypothesis Update",
    "planning": "Planning",
    "replan": "Re-plan",
    "sufficiency_check": "Sufficiency Check",
    "stop": "Stop",
    "final_diagnosis": "Final Diagnosis",
    "tool_failure": "Tool Failure",
    "missing_arguments": "Missing Arguments",
    "planning_limit": "Planning Limit",
    "tool_call_limit": "Tool Call Limit",
    "duplicate_tool_blocked": "Duplicate Tool Blocked",
}

# AgentEvent 스키마에 두면 안 되는 private CoT 필드.
# summary는 고수준 한 줄이며 LLM 내부 사고 전문이 아니다.
_PRIVATE_COT_FIELDS = (
    "reason",
    "thinking",
    "chain_of_thought",
    "private_reasoning",
    "cot",
    "hidden_reasoning",
)

_EXTRACT_META_KEYS = (
    "job_name",
    "job",
    "business_date",
    "input_path",
    "file_path",
    "path",
    "error_code",
    "return_code",
)

_TOOL_NEED_SUMMARY = {
    "check_file_status": "파일 상태 확인이 필요합니다.",
    "validate_parameter": "파라미터 정합성을 확인해야 합니다.",
    "check_db_status": "DB 상태 확인이 필요합니다.",
    "check_sql_metadata": "SQL metadata 확인이 필요합니다.",
}

_PLANNING_SUMMARY = {
    "check_file_status": "파일 상태 확인이 필요하다고 판단했습니다.",
    "validate_parameter": "파라미터 정합성을 추가로 확인해야 한다고 판단했습니다.",
    "check_db_status": "DB 상태 확인이 필요하다고 판단했습니다.",
    "check_sql_metadata": "SQL metadata 확인이 필요하다고 판단했습니다.",
}

_STOP_EVENTS: dict[str, tuple[AgentComponent, str, str]] = {
    "EVIDENCE_SUFFICIENT": (
        "Reasoning",
        "stop",
        "근거가 충분하여 조사를 종료합니다.",
    ),
    "NO_ACTIONABLE_TOOL": (
        "Reasoning",
        "stop",
        "추가 실행 가능한 tool이 없어 조사를 종료합니다.",
    ),
    "MISSING_REQUIRED_ARGUMENTS": (
        "Governance",
        "missing_arguments",
        "필수 인자가 없어 조사를 종료합니다.",
    ),
    "MAX_PLANNING_ROUNDS": (
        "Governance",
        "planning_limit",
        "최대 planning round에 도달하여 조사를 종료합니다.",
    ),
    "MAX_TOOL_CALLS": (
        "Governance",
        "tool_call_limit",
        "최대 tool 호출 횟수에 도달하여 조사를 종료합니다.",
    ),
    "DUPLICATE_TOOL_CALL_BLOCKED": (
        "Governance",
        "duplicate_tool_blocked",
        "중복 tool 호출이 차단되어 조사를 종료합니다.",
    ),
}

_CHANGE_SUMMARY = {
    "가능성 상승": "가능성이 상승했습니다.",
    "가능성 하락": "가능성이 하락했습니다.",
    "파생 현상으로 재분류": "파생 현상으로 재분류했습니다.",
    "신규 채택": "신규 원인 후보로 채택했습니다.",
    "유지": "상태를 유지했습니다.",
}


def _hypotheses(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("initial_hypotheses"):
        return list(payload["initial_hypotheses"])
    return list(payload.get("hypotheses") or [])


def _cause_codes(payload: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for item in _hypotheses(payload):
        code = item.get("cause_code")
        if code and code not in codes:
            codes.append(str(code))
    return codes


def _event(
    *,
    component: AgentComponent,
    step: str,
    summary: str,
    detail: str = "",
    metadata: dict[str, Any] | None = None,
    round: int | None = None,
    status: str | None = None,
    source: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        component=component,
        step=step,
        summary=summary,
        detail=detail,
        metadata=metadata or {},
        timestamp=utc_timestamp(),
        round=round,
        status=status,
        source=source,
    )


def _extracted_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    extracted = payload.get("extracted_info") or {}
    meta: dict[str, Any] = {}
    for key in _EXTRACT_META_KEYS:
        value = extracted.get(key)
        if value not in (None, "", [], {}):
            meta[key] = value
    return meta


def _tool_result_payload(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        return {}
    data = result.get("data")
    if isinstance(data, dict):
        return data
    return {}


def _tool_result_summary(tool: str, result: dict[str, Any]) -> str:
    data = _tool_result_payload(result)
    if tool == "check_file_status":
        exists = data.get("exists")
        received = data.get("received")
        if exists is False and received is False:
            return "파일이 존재하지 않고 수신되지 않은 상태를 확인했습니다."
        if exists is True:
            return "파일이 존재하는 상태를 확인했습니다."
        return "파일 상태를 확인했습니다."
    if tool == "validate_parameter":
        name = data.get("parameter_name") or data.get("parameter") or "parameter"
        if data.get("is_valid") is False:
            return f"{name}가 기대값과 불일치함을 확인했습니다."
        if data.get("is_valid") is True:
            return f"{name}가 기대값과 일치함을 확인했습니다."
        return f"{name} 검증 결과를 확인했습니다."
    if tool == "check_db_status":
        return "DB 상태 점검 결과를 확인했습니다."
    if tool == "check_sql_metadata":
        return "SQL metadata 점검 결과를 확인했습니다."
    return f"{tool} 실행 결과를 확인했습니다."


def _tool_result_metadata(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    data = _tool_result_payload(result)
    meta: dict[str, Any] = {
        "tool": tool,
        "status": result.get("status") or "SUCCESS",
    }
    for key in (
        "exists",
        "received",
        "path",
        "is_valid",
        "parameter_name",
        "parameter_value",
        "expected_value",
        "account_locked",
        "credential_status",
        "schema_exists",
        "table_exists",
        "column_exists",
    ):
        if key in data:
            meta[key] = data[key]
    return meta


def _planning_summary(tool: str | None) -> str:
    if not tool:
        return "추가 실행 가능한 tool이 없다고 판단했습니다."
    return _PLANNING_SUMMARY.get(tool, f"{tool} 실행이 필요하다고 판단했습니다.")


def _replan_summary(tool: str | None, arguments: dict[str, Any] | None) -> str:
    args = arguments or {}
    param = args.get("parameter_name") or args.get("parameter")
    if tool == "validate_parameter" and param:
        return f"{param} 이상 신호를 확인하여 추가 조사를 계획했습니다."
    if tool == "validate_parameter":
        return "파라미터 이상 신호를 확인하여 추가 조사를 계획했습니다."
    if tool:
        return f"{tool} 추가 실행을 계획했습니다."
    return "추가 조사를 계획했습니다."


def _paired_tool_rounds(payload: dict[str, Any]) -> list[dict[str, Any]]:
    selections = list(payload.get("selected_tools") or [])
    results = list(payload.get("tool_results") or [])
    count = max(len(selections), len(results))
    rounds: list[dict[str, Any]] = []
    for index in range(count):
        selection = selections[index] if index < len(selections) else {}
        result = results[index] if index < len(results) else {}
        tool = result.get("tool") or selection.get("selected_tool")
        if not tool:
            continue
        rounds.append(
            {
                "tool": tool,
                "arguments": selection.get("arguments") or {},
                "result": result,
            }
        )
    return rounds


def _is_terminal_round(item: dict[str, Any]) -> bool:
    return not item.get("tool_result") and not item.get("selected_tool")


def _later_round_has_tool(rounds: list[dict[str, Any]], index: int) -> bool:
    return any(
        later.get("tool_result") is not None or later.get("selected_tool")
        for later in rounds[index + 1 :]
        if not _is_terminal_round(later)
    )


def _append_tool_events(
    events: list[AgentEvent],
    *,
    tool: str,
    arguments: dict[str, Any],
    result: dict[str, Any] | None,
    source: str,
    round_index: int | None = None,
) -> None:
    events.append(
        _event(
            component="Action",
            step="tool_call",
            summary=f"{tool} 실행",
            metadata={"tool": tool, "arguments": arguments},
            round=round_index,
            source=source,
        )
    )
    if not result:
        return
    status = str(result.get("status") or "")
    if status == "FAILED":
        events.append(
            _event(
                component="Governance",
                step="tool_failure",
                summary=f"{tool} 실행에 실패했습니다.",
                detail="FAILED error는 최종 원인 evidence로 사용하지 않습니다.",
                metadata={
                    "tool": tool,
                    "error": result.get("error"),
                    "excluded_from_final_evidence": True,
                },
                round=round_index,
                status="FAILED",
                source=source,
            )
        )
        return
    events.append(
        _event(
            component="Action",
            step="tool_result",
            summary=_tool_result_summary(tool, result),
            metadata=_tool_result_metadata(tool, result),
            round=round_index,
            status="SUCCESS",
            source=source,
        )
    )


def _log_analysis_event(payload: dict[str, Any], source: str) -> AgentEvent:
    meta = _extracted_metadata(payload)
    return _event(
        component="Perception",
        step="log_analysis",
        summary="로그에서 오류 코드와 주요 실행 정보를 추출했습니다.",
        metadata=meta,
        source=source,
    )


def _initial_hypotheses_event(payload: dict[str, Any], source: str) -> AgentEvent:
    codes = _cause_codes(payload)
    count = len(codes)
    return _event(
        component="Reasoning",
        step="initial_hypotheses",
        summary=f"초기 원인 후보 {count}개를 생성했습니다.",
        metadata={"cause_codes": codes, "count": count},
        source=source,
    )


def _final_diagnosis_event(payload: dict[str, Any], source: str) -> AgentEvent:
    code = str(payload.get("final_cause_code") or "")
    name = str(payload.get("final_cause_name") or CAUSE_CODE_NAMES.get(code, ""))
    level = str(payload.get("diagnosis_level") or "")
    summary = f"최종 원인: {code} / {level}" if code else "최종 진단을 확정했습니다."
    return _event(
        component="Reasoning",
        step="final_diagnosis",
        summary=summary,
        metadata={
            "final_cause_code": code,
            "final_cause_name": name,
            "diagnosis_level": level,
            "owner": payload.get("owner"),
        },
        source=source,
    )


def _normalize_stop_reason(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, StopReason):
        return value.value
    text = str(value)
    return text.removeprefix("StopReason.")


def _stop_event(stop_reason: Any, source: str) -> AgentEvent | None:
    normalized = _normalize_stop_reason(stop_reason)
    if not normalized:
        return None
    mapped = _STOP_EVENTS.get(normalized)
    if mapped is None:
        return _event(
            component="Governance",
            step="stop",
            summary="조사를 종료합니다.",
            metadata={"stop_reason": normalized},
            source=source,
        )
    component, step, summary = mapped
    return _event(
        component=component,
        step=step,
        summary=summary,
        metadata={"stop_reason": normalized},
        status=normalized,
        source=source,
    )


def _v0_events(payload: dict[str, Any]) -> list[AgentEvent]:
    source = "v0"
    return [
        _log_analysis_event(payload, source),
        _initial_hypotheses_event(payload, source),
        _final_diagnosis_event(payload, source),
    ]


def _v1_evidence_events(payload: dict[str, Any], source: str) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    has_success = any(
        (item.get("status") == "SUCCESS")
        for item in (payload.get("tool_results") or [])
    )
    for update in build_diagnosis_updates(payload, has_successful_tools=has_success):
        if update.change == "유지":
            continue
        suffix = _CHANGE_SUMMARY.get(update.change, update.change)
        events.append(
            _event(
                component="Reasoning",
                step="evidence_update",
                summary=f"{update.cause_code} {suffix}",
                metadata={
                    "cause_code": update.cause_code,
                    "change": update.change,
                    "signals": list(update.signals),
                },
                source=source,
            )
        )
    return events


def _v1_events(payload: dict[str, Any]) -> list[AgentEvent]:
    source = "v1"
    events = [
        _log_analysis_event(payload, source),
        _initial_hypotheses_event(payload, source),
    ]
    selected = [
        item.get("selected_tool")
        for item in (payload.get("selected_tools") or [])
        if item.get("selected_tool")
    ]
    if selected:
        first = selected[0]
        events.append(
            _event(
                component="Reasoning",
                step="tool_selection",
                summary=_TOOL_NEED_SUMMARY.get(first, f"{first} 실행이 필요합니다."),
                metadata={"selected_tools": selected},
                source=source,
            )
        )
    for item in _paired_tool_rounds(payload):
        _append_tool_events(
            events,
            tool=item["tool"],
            arguments=item["arguments"],
            result=item["result"],
            source=source,
        )
    events.extend(_v1_evidence_events(payload, source))
    stop = _stop_event(payload.get("stop_reason"), source)
    if stop is not None:
        events.append(stop)
    events.append(_final_diagnosis_event(payload, source))
    return events


def _v2_events(payload: dict[str, Any]) -> list[AgentEvent]:
    source = "v2"
    events = [
        _log_analysis_event(payload, source),
        _initial_hypotheses_event(payload, source),
    ]
    rounds = list(payload.get("planning_trace") or [])
    initial_codes = set(_cause_codes(payload))
    adopted: set[str] = set()

    if not rounds:
        for item in _paired_tool_rounds(payload):
            _append_tool_events(
                events,
                tool=item["tool"],
                arguments=item["arguments"],
                result=item["result"],
                source=source,
            )
    else:
        for index, item in enumerate(rounds):
            if _is_terminal_round(item):
                continue
            tool = item.get("selected_tool")
            result = item.get("tool_result")
            arguments = item.get("arguments") or {}
            round_index = item.get("round_index") or (index + 1)
            replanned = bool(item.get("replanned")) or index > 0
            unresolved = list(item.get("unresolved_questions") or [])

            if replanned:
                events.append(
                    _event(
                        component="Reasoning",
                        step="replan",
                        summary=_replan_summary(tool, arguments),
                        metadata={
                            "planning_round": round_index,
                            "selected_tool": tool,
                            "unresolved_questions": unresolved,
                        },
                        round=round_index,
                        source=source,
                    )
                )
            else:
                events.append(
                    _event(
                        component="Reasoning",
                        step="planning",
                        summary=_planning_summary(tool),
                        metadata={
                            "planning_round": round_index,
                            "selected_tool": tool,
                            "unresolved_questions": unresolved,
                        },
                        round=round_index,
                        source=source,
                    )
                )

            if result is not None and tool:
                _append_tool_events(
                    events,
                    tool=tool,
                    arguments=arguments,
                    result=result,
                    source=source,
                    round_index=round_index,
                )
                if result.get("status") == "SUCCESS":
                    for state in item.get("hypothesis_states") or []:
                        code = state.get("cause_code")
                        if not code or code in initial_codes or code in adopted:
                            continue
                        if state.get("origin") == "planner" or state.get("status") == "adopted":
                            events.append(
                                _event(
                                    component="Reasoning",
                                    step="hypothesis_update",
                                    summary=f"{code}를 신규 원인 후보로 채택했습니다.",
                                    metadata={
                                        "cause_code": code,
                                        "origin": state.get("origin"),
                                        "status": state.get("status"),
                                    },
                                    round=round_index,
                                    source=source,
                                )
                            )
                            adopted.add(code)
                if result.get("status") == "SUCCESS" and item.get("evidence_sufficient") is False:
                    if _later_round_has_tool(rounds, index):
                        events.append(
                            _event(
                                component="Reasoning",
                                step="sufficiency_check",
                                summary="현재 evidence만으로 근본 원인을 확정하기 부족합니다.",
                                metadata={"evidence_sufficient": False},
                                round=round_index,
                                status="insufficient",
                                source=source,
                            )
                        )

    stop = _stop_event(payload.get("stop_reason"), source)
    if stop is not None:
        events.append(stop)
    events.append(_final_diagnosis_event(payload, source))
    return events


def build_agent_events(version: str, payload: dict[str, Any] | None) -> list[AgentEvent]:
    data = payload or {}
    if version == "v0":
        return _v0_events(data)
    if version == "v2":
        return _v2_events(data)
    return _v1_events(data)


def build_agent_event_views(events: list[AgentEvent] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    for item in events:
        event = item if isinstance(item, AgentEvent) else AgentEvent.model_validate(item)
        label = STEP_LABELS.get(event.step, event.step.replace("_", " ").title())
        icon = COMPONENT_ICONS.get(event.component, "")
        prefix = f"{icon} " if icon else ""
        views.append(
            {
                "title": f"{prefix}[{event.component}] {label} — {event.summary}",
                "icon": icon,
                "component": event.component,
                "step": event.step,
                "step_label": label,
                "summary": event.summary,
                "detail": event.detail,
                "metadata": event.metadata,
                "timestamp": event.timestamp,
                "round": event.round,
                "status": event.status,
                "source": event.source,
            }
        )
    return views


def event_contains_private_cot(event: AgentEvent) -> bool:
    """스키마에 private CoT 전용 필드가 있으면 True. summary는 고수준 한 줄이라 해당하지 않는다."""
    del event
    fields = set(AgentEvent.model_fields)
    return any(name in fields for name in _PRIVATE_COT_FIELDS)
