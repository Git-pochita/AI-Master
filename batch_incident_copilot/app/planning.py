from __future__ import annotations

import json
import re
from typing import Any, Callable

from app.baseline import diagnose
from app.cause_codes import CAUSE_CODE_NAMES, vocabulary_prompt_block
from app.schemas import (
    Hypothesis,
    HypothesisState,
    InvestigationStep,
    PlannerDecision,
    PlanningRound,
    StopReason,
    ToolResult,
    ToolSelection,
    V2DiagnosisResult,
)
from app.tool_use import _load_prompt, _parse_json_with_retry, finalize_diagnosis
from app.tools.evidence import supporting_tool_results
from app.tools.registry import (
    complete_arguments_from_extracted,
    execute_tool,
    get_tool_specs,
    missing_required_arguments,
)
from config import settings

MAX_PLANNING_ROUNDS = 3
MAX_TOOL_CALLS = 3

ALLOWED_TOOLS = {
    "check_file_status",
    "validate_parameter",
    "check_db_status",
    "check_sql_metadata",
}

EXTRACTED_ALIASES: dict[str, tuple[str, ...]] = {
    "path": ("path", "input_path", "file_path"),
    "job_name": ("job_name", "job"),
    "parameter_value": ("parameter_value", "business_date"),
    "connection_name": ("connection_name",),
    "account": ("account",),
    "schema": ("schema",),
    "table": ("table",),
    "column": ("column",),
}

_LOG_TIMESTAMP_DATE = re.compile(r"(?m)^(\d{4})-(\d{2})-(\d{2})(?:[ T])")
_COMPACT_DATE = re.compile(r"^\d{8}$")
_NAMED_DATE = re.compile(
    r"\b(?:business_date|actual_business_date|parameter_value)=(\d{8})\b"
)
_PARAMETER_ERROR_SIGNAL = re.compile(
    r"parameter rejected|parameter format invalid|mismatch|"
    r"expected_business_date|actual_business_date|expected\s*=|actual\s*=",
    re.IGNORECASE,
)


def tool_fingerprint(tool_name: str, arguments: dict[str, Any] | None) -> str:
    args = arguments or {}
    normalized = {
        str(key): args[key]
        for key in sorted(args)
        if args[key] not in (None, "")
    }
    return tool_name + "|" + json.dumps(
        normalized,
        ensure_ascii=False,
        default=str,
        sort_keys=True,
    )


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _lookup_alias(source: dict[str, Any], key: str) -> Any:
    for alias in EXTRACTED_ALIASES.get(key, (key,)):
        if alias in source and not _blank(source.get(alias)):
            return source[alias]
    if key in source and not _blank(source.get(key)):
        return source[key]
    return None


def complete_v2_arguments(
    tool_name: str,
    arguments: dict[str, Any] | None,
    extracted_info: dict[str, Any] | None,
    tool_results: list[ToolResult],
) -> dict[str, Any]:
    args = complete_arguments_from_extracted(tool_name, arguments, extracted_info)
    extracted = extracted_info or {}
    success_data: dict[str, Any] = {}
    for item in supporting_tool_results(tool_results):
        if item.data:
            success_data.update(item.data)
    for key in list(args.keys()) + list(EXTRACTED_ALIASES.keys()):
        if _blank(args.get(key)):
            value = _lookup_alias(extracted, key)
            if _blank(value):
                value = _lookup_alias(success_data, key)
            if not _blank(value):
                args[key] = value
    if tool_name == "validate_parameter" and _blank(args.get("parameter_name")):
        if not _blank(extracted.get("business_date")) or not _blank(args.get("parameter_value")):
            args["parameter_name"] = "business_date"
    return args


def _compact_dates_from_log_timestamps(log_text: str) -> set[str]:
    return {
        f"{year}{month}{day}"
        for year, month, day in _LOG_TIMESTAMP_DATE.findall(log_text or "")
    }


def _candidate_parameter_dates(
    extracted_info: dict[str, Any] | None,
    log_text: str,
) -> set[str]:
    dates: set[str] = set()
    extracted = extracted_info or {}
    for key in ("business_date", "parameter_value", "actual_business_date"):
        value = extracted.get(key)
        if isinstance(value, str) and _COMPACT_DATE.fullmatch(value.strip()):
            dates.add(value.strip())
    for match in _NAMED_DATE.finditer(log_text or ""):
        dates.add(match.group(1))
    return dates


def has_parameter_anomaly_signal(
    log_text: str,
    extracted_info: dict[str, Any] | None,
) -> bool:
    """파라미터 이상을 지지하는 관찰 가능한 신호가 있는지 본다.

    job_name/business_date 필드가 있다는 것만으로는 True가 되지 않는다.
    """
    extracted = extracted_info or {}
    if _PARAMETER_ERROR_SIGNAL.search(log_text or ""):
        return True
    expected = extracted.get("expected_business_date")
    actual = extracted.get("actual_business_date") or extracted.get("business_date")
    if (
        isinstance(expected, str)
        and isinstance(actual, str)
        and _COMPACT_DATE.fullmatch(expected.strip())
        and _COMPACT_DATE.fullmatch(actual.strip())
        and expected.strip() != actual.strip()
    ):
        return True
    run_dates = _compact_dates_from_log_timestamps(log_text or "")
    param_dates = _candidate_parameter_dates(extracted, log_text or "")
    return bool(run_dates and param_dates and param_dates.isdisjoint(run_dates))


def additional_investigation_justified(
    tool_name: str,
    log_text: str,
    extracted_info: dict[str, Any] | None,
    tool_results: list[ToolResult],
) -> bool:
    """이미 Tool을 실행한 뒤 추가 Tool을 호출해도 되는지 가드한다.

    첫 Tool은 막지 않는다. validate_parameter 추가 호출만 concrete signal을 요구한다.
    """
    if not tool_results:
        return True
    if tool_name != "validate_parameter":
        return True
    return has_parameter_anomaly_signal(log_text, extracted_info)


def _initial_working_hypotheses(hypotheses: list[Hypothesis]) -> list[HypothesisState]:
    states: list[HypothesisState] = []
    for item in hypotheses:
        states.append(
            HypothesisState(
                cause_code=item.cause_code,
                cause_name=item.cause_name or CAUSE_CODE_NAMES.get(item.cause_code, item.cause_code),
                origin="initial",
                status="active",
                signals=list(item.evidence or []),
            )
        )
    return states


def _merge_hypothesis_states(
    current: list[HypothesisState],
    incoming: list[HypothesisState],
) -> list[HypothesisState]:
    merged = {item.cause_code: item.model_copy(deep=True) for item in current}
    for item in incoming:
        previous = merged.get(item.cause_code)
        origin = item.origin
        if previous and previous.origin == "initial":
            origin = "initial"
        elif previous is None and origin == "initial":
            origin = "planner"
        status = item.status
        if previous is None and status == "active":
            status = "adopted"
        merged[item.cause_code] = HypothesisState(
            cause_code=item.cause_code,
            cause_name=item.cause_name or CAUSE_CODE_NAMES.get(item.cause_code, item.cause_code),
            origin=origin,
            status=status,
            signals=list(item.signals or (previous.signals if previous else [])),
        )
    return list(merged.values())


def _planner_user_prompt(
    *,
    log_text: str,
    extracted_info: dict[str, Any],
    initial_hypotheses: list[Hypothesis],
    working_hypotheses: list[HypothesisState],
    executed: list[dict[str, Any]],
    tool_results: list[ToolResult],
    round_index: int,
) -> str:
    success = [item.model_dump() for item in supporting_tool_results(tool_results)]
    return (
        "다음 조사 상태를 보고 계획과 다음 Tool을 결정하십시오.\n"
        "case_id와 정답 원인 코드는 제공되지 않습니다.\n\n"
        f"current_round: {round_index}\n"
        f"max_planning_rounds: {MAX_PLANNING_ROUNDS}\n"
        f"max_tool_calls: {MAX_TOOL_CALLS}\n"
        f"extracted_info: {json.dumps(extracted_info, ensure_ascii=False)}\n"
        f"initial_hypotheses: {json.dumps([h.model_dump() for h in initial_hypotheses], ensure_ascii=False)}\n"
        f"working_hypotheses: {json.dumps([h.model_dump() for h in working_hypotheses], ensure_ascii=False)}\n"
        f"already_executed: {json.dumps(executed, ensure_ascii=False)}\n"
        f"tool_results: {json.dumps([r.model_dump() for r in tool_results], ensure_ascii=False)}\n"
        f"success_evidence: {json.dumps(success, ensure_ascii=False)}\n"
        f"available_tools: {json.dumps(get_tool_specs(), ensure_ascii=False)}\n\n"
        "--- LOG START ---\n"
        f"{log_text}\n"
        "--- LOG END ---\n"
    )


def call_planner(
    *,
    log_text: str,
    extracted_info: dict[str, Any],
    initial_hypotheses: list[Hypothesis],
    working_hypotheses: list[HypothesisState],
    executed: list[dict[str, Any]],
    tool_results: list[ToolResult],
    round_index: int,
) -> PlannerDecision:
    system_prompt = (
        _load_prompt(settings.V2_PLANNING_PROMPT_PATH).rstrip()
        + "\n\n"
        + vocabulary_prompt_block()
        + "\n"
    )
    user_prompt = _planner_user_prompt(
        log_text=log_text,
        extracted_info=extracted_info,
        initial_hypotheses=initial_hypotheses,
        working_hypotheses=working_hypotheses,
        executed=executed,
        tool_results=tool_results,
        round_index=round_index,
    )
    decision = _parse_json_with_retry(system_prompt, user_prompt, PlannerDecision)
    if decision.selected_tool and decision.selected_tool not in ALLOWED_TOOLS:
        decision.selected_tool = None
        decision.reason = (
            decision.reason + " (지원하지 않는 Tool이라 선택을 취소했습니다.)"
        ).strip()
    return decision


def _round_goal(decision: PlannerDecision) -> str:
    for step in decision.investigation_plan:
        if step.goal:
            return step.goal
    return decision.reason or "조사 계획"


def _evidence_summary(result: ToolResult | None) -> dict[str, Any]:
    if result is None:
        return {}
    if result.status != "SUCCESS":
        return {"status": "FAILED", "error": result.error}
    from app.ui_service import summarize_tool_data

    summary = summarize_tool_data(result.data)
    summary["status"] = "SUCCESS"
    return summary


def diagnose_v2(
    log_text: str,
    case_id: str | None = None,
    plan_fn: Callable[..., PlannerDecision] | None = None,
    finalize_fn: Callable[..., dict] | None = None,
) -> V2DiagnosisResult:
    initial = diagnose(log_text, case_id=case_id)
    initial_hypotheses = [item.model_copy(deep=True) for item in initial.hypotheses]
    working = _initial_working_hypotheses(initial_hypotheses)
    investigation_plan: list[InvestigationStep] = []
    unresolved: list[str] = []
    selections: list[ToolSelection] = []
    results: list[ToolResult] = []
    executed: list[dict[str, Any]] = []
    seen: set[str] = set()
    trace: list[PlanningRound] = []
    stop_reason: StopReason | None = None
    planner = plan_fn or call_planner
    finalizer = finalize_fn or finalize_diagnosis

    for round_index in range(1, MAX_PLANNING_ROUNDS + 1):
        if len(results) >= MAX_TOOL_CALLS:
            stop_reason = StopReason.MAX_TOOL_CALLS
            break

        decision = planner(
            log_text=log_text,
            extracted_info=initial.extracted_info,
            initial_hypotheses=initial_hypotheses,
            working_hypotheses=working,
            executed=executed,
            tool_results=results,
            round_index=round_index,
        )
        if decision.investigation_plan:
            investigation_plan = [step.model_copy(deep=True) for step in decision.investigation_plan]
        if decision.hypothesis_states:
            working = _merge_hypothesis_states(working, decision.hypothesis_states)
        if decision.unresolved_questions:
            unresolved = list(decision.unresolved_questions)

        planner_tool = decision.selected_tool
        arguments = complete_v2_arguments(
            planner_tool or "",
            decision.arguments,
            initial.extracted_info,
            results,
        ) if planner_tool else dict(decision.arguments or {})
        if (
            planner_tool
            and results
            and not additional_investigation_justified(
                planner_tool,
                log_text,
                initial.extracted_info,
                results,
            )
        ):
            decision.reason = (
                decision.reason
                + " (추가 조사 조건 미충족: 해당 가설을 지지하는 concrete signal이 없어 Tool 선택을 취소했습니다.)"
            ).strip()
            planner_tool = None
        if (
            (decision.evidence_sufficient or not planner_tool)
            and results
            and not any(item.tool == "validate_parameter" for item in results)
            and has_parameter_anomaly_signal(log_text, initial.extracted_info)
        ):
            param_args = complete_v2_arguments(
                "validate_parameter",
                {},
                initial.extracted_info,
                results,
            )
            if not missing_required_arguments("validate_parameter", param_args):
                planner_tool = "validate_parameter"
                arguments = param_args
                decision.evidence_sufficient = False
                decision.reason = (
                    (decision.reason or "")
                    + " (로그/extracted_info에 파라미터 이상 concrete signal이 남아 있어 validate_parameter를 추가합니다.)"
                ).strip()
        replanned = round_index > 1
        round_stop: StopReason | None = None
        tool_result: ToolResult | None = None
        recorded_tool: str | None = None
        recorded_args: dict[str, Any] = {}

        if decision.evidence_sufficient or not planner_tool:
            if decision.evidence_sufficient:
                round_stop = StopReason.EVIDENCE_SUFFICIENT
            elif decision.stop_reason in {
                StopReason.MISSING_REQUIRED_ARGUMENTS,
                StopReason.NO_ACTIONABLE_TOOL,
                StopReason.EVIDENCE_SUFFICIENT,
            }:
                round_stop = decision.stop_reason
            else:
                round_stop = StopReason.NO_ACTIONABLE_TOOL
            stop_reason = round_stop
        elif missing_required_arguments(planner_tool, arguments):
            round_stop = StopReason.MISSING_REQUIRED_ARGUMENTS
            stop_reason = round_stop
            recorded_tool = planner_tool
            recorded_args = arguments
        else:
            fingerprint = tool_fingerprint(planner_tool, arguments)
            if fingerprint in seen:
                round_stop = StopReason.DUPLICATE_TOOL_CALL_BLOCKED
                stop_reason = round_stop
                recorded_tool = planner_tool
                recorded_args = arguments
            else:
                tool_result = execute_tool(planner_tool, arguments)
                seen.add(fingerprint)
                recorded_tool = planner_tool
                recorded_args = arguments
                selections.append(
                    ToolSelection(
                        selected_tool=planner_tool,
                        reason=decision.reason,
                        arguments=arguments,
                    )
                )
                results.append(tool_result)
                executed.append({"tool": planner_tool, "arguments": arguments})
                for step in investigation_plan:
                    if step.candidate_tool == planner_tool and step.status == "pending":
                        step.status = "executed"
                        break

        trace.append(
            PlanningRound(
                round_index=round_index,
                goal=_round_goal(decision),
                investigation_plan=[step.model_copy(deep=True) for step in investigation_plan],
                hypothesis_states=[item.model_copy(deep=True) for item in working],
                unresolved_questions=list(unresolved),
                evidence_sufficient=decision.evidence_sufficient,
                selected_tool=recorded_tool,
                arguments=recorded_args,
                reason=decision.reason,
                evidence_summary=_evidence_summary(tool_result),
                replanned=replanned,
                stop_reason=round_stop,
                tool_result=tool_result,
            )
        )
        if stop_reason is not None:
            break
    else:
        if stop_reason is None:
            stop_reason = StopReason.MAX_PLANNING_ROUNDS

    if stop_reason is None:
        stop_reason = StopReason.MAX_PLANNING_ROUNDS

    final_payload = finalizer(log_text, initial, results)
    return V2DiagnosisResult(
        version="v2",
        case_id=case_id or initial.case_id,
        summary=final_payload["summary"],
        extracted_info=initial.extracted_info,
        initial_hypotheses=initial_hypotheses,
        working_hypotheses=working,
        investigation_plan=investigation_plan,
        unresolved_questions=unresolved,
        current_round=len(trace),
        stop_reason=stop_reason,
        planning_trace=trace,
        selected_tools=selections,
        tool_results=results,
        final_cause_code=final_payload["final_cause_code"],
        final_cause_name=final_payload["final_cause_name"],
        diagnosis_level=final_payload["diagnosis_level"],
        owner=final_payload["owner"],
        evidence=final_payload["evidence"],
        limitations=final_payload["limitations"],
        recommended_actions=final_payload.get("recommended_actions") or [],
    )
