import json

from app.baseline import diagnose, extract_json_object
from app.cause_codes import validate_cause_code, vocabulary_prompt_block
from app.llm_client import chat_complete
from app.schemas import ToolSelection, ToolResult, V1DiagnosisResult
from app.tools.registry import (
    complete_arguments_from_extracted,
    execute_tool,
    get_tool_specs,
)
from app.tools.evidence import filter_evidence, supporting_tool_results
from config import settings

MAX_TOOL_CALLS = 2


def _load_prompt(path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_json_with_retry(system_prompt: str, user_prompt: str, model_cls):
    raw = chat_complete(system_prompt, user_prompt)
    try:
        payload = extract_json_object(raw)
        return model_cls.model_validate(payload)
    except Exception as first_error:
        retry_user = (
            user_prompt
            + "\n이전 응답이 스키마에 맞지 않았습니다. JSON 객체만 다시 출력하십시오.\n"
            + f"오류: {first_error}"
        )
        raw = chat_complete(system_prompt, retry_user)
        payload = extract_json_object(raw)
        return model_cls.model_validate(payload)


def _tool_select_user_prompt(
    log_text: str,
    initial,
    already_called: list[str],
    tool_results: list[ToolResult],
) -> str:
    return (
        "다음 정보를 보고 지금 필요한 Tool을 하나만 선택하십시오.\n\n"
        f"case_id: {initial.case_id}\n"
        f"extracted_info: {json.dumps(initial.extracted_info, ensure_ascii=False)}\n"
        f"initial_hypotheses: {json.dumps([h.model_dump() for h in initial.hypotheses], ensure_ascii=False)}\n"
        f"already_called_tools: {json.dumps(already_called, ensure_ascii=False)}\n"
        f"previous_tool_results: {json.dumps([r.model_dump() for r in tool_results], ensure_ascii=False)}\n"
        f"available_tools: {json.dumps(get_tool_specs(), ensure_ascii=False)}\n\n"
        "--- LOG START ---\n"
        f"{log_text}\n"
        "--- LOG END ---\n"
    )


def select_tool(
    log_text: str,
    initial,
    already_called: list[str],
    tool_results: list[ToolResult],
) -> ToolSelection:
    system_prompt = _load_prompt(settings.V1_TOOL_SELECT_PROMPT_PATH)
    user_prompt = _tool_select_user_prompt(
        log_text, initial, already_called, tool_results
    )
    selection = _parse_json_with_retry(system_prompt, user_prompt, ToolSelection)
    if selection.selected_tool in already_called:
        selection.selected_tool = None
        selection.reason = (
            selection.reason + " (이미 호출한 Tool이라 추가 호출을 생략합니다.)"
        ).strip()
    return selection


def collect_tool_results(
    log_text: str,
    initial,
    progress_fn=None,
) -> tuple[list[ToolSelection], list[ToolResult]]:
    from app.progress import STEP_TOOL, TITLE_TOOL, emit_running, emit_tool

    selections: list[ToolSelection] = []
    results: list[ToolResult] = []
    already_called: list[str] = []

    for _ in range(MAX_TOOL_CALLS):
        emit_running(progress_fn, STEP_TOOL, TITLE_TOOL)
        selection = select_tool(log_text, initial, already_called, results)
        if not selection.selected_tool:
            break
        selection.arguments = complete_arguments_from_extracted(
            selection.selected_tool,
            selection.arguments,
            getattr(initial, "extracted_info", None),
        )
        emit_running(
            progress_fn,
            STEP_TOOL,
            TITLE_TOOL,
            metadata={"tool": selection.selected_tool},
        )
        tool_result = execute_tool(selection.selected_tool, selection.arguments)
        emit_tool(progress_fn, selection.selected_tool, tool_result)
        selections.append(selection)
        results.append(tool_result)
        already_called.append(selection.selected_tool)
    return selections, results


def _final_user_prompt(log_text: str, initial, tool_results: list[ToolResult]) -> str:
    usable = [item.model_dump() for item in supporting_tool_results(tool_results)]
    return (
        "V0 초기 가설과 SUCCESS Tool 결과만 사용해 최종 진단하십시오.\n"
        "FAILED Tool 결과는 아래에 포함하지 않았습니다.\n\n"
        f"case_id: {initial.case_id}\n"
        f"extracted_info: {json.dumps(initial.extracted_info, ensure_ascii=False)}\n"
        f"initial_hypotheses: {json.dumps([h.model_dump() for h in initial.hypotheses], ensure_ascii=False)}\n"
        f"success_tool_results: {json.dumps(usable, ensure_ascii=False)}\n\n"
        "--- LOG START ---\n"
        f"{log_text}\n"
        "--- LOG END ---\n"
    )


def finalize_diagnosis(log_text: str, initial, tool_results: list[ToolResult]) -> dict:
    from pydantic import BaseModel, field_validator

    class FinalDraft(BaseModel):
        summary: str
        final_cause_code: str
        final_cause_name: str
        diagnosis_level: str
        owner: str
        evidence: list[str]
        limitations: list[str]
        recommended_actions: list[str] = []

        @field_validator("final_cause_code")
        @classmethod
        def canonical_code(cls, value: str) -> str:
            return validate_cause_code(value.strip())

    system_prompt = (
        _load_prompt(settings.V1_FINAL_PROMPT_PATH).rstrip()
        + "\n\n"
        + vocabulary_prompt_block()
        + "\n"
    )
    user_prompt = _final_user_prompt(log_text, initial, tool_results)
    draft = _parse_json_with_retry(system_prompt, user_prompt, FinalDraft)
    payload = draft.model_dump()
    payload["evidence"] = filter_evidence(payload.get("evidence") or [], tool_results)
    if not payload["evidence"]:
        payload["evidence"] = [
            f"{item.tool}: {json.dumps(item.data, ensure_ascii=False)}"
            for item in supporting_tool_results(tool_results)
        ]
    original_level = payload.get("diagnosis_level") or "추정"
    capped = apply_diagnosis_level_policy(original_level, tool_results)
    payload["diagnosis_level"] = capped
    if original_level == "확인됨" and capped != "확인됨":
        notes = list(payload.get("limitations") or [])
        notes.append(
            "SUCCESS Tool 결과가 없어 diagnosis_level을 확인됨에서 추정으로 조정했습니다."
        )
        payload["limitations"] = notes
    return payload


def apply_diagnosis_level_policy(level: str, tool_results: list[ToolResult]) -> str:
    """확인됨은 SUCCESS Tool evidence가 있을 때만 허용한다. cause_code는 바꾸지 않는다."""
    if level not in {"추정", "가능성 높음", "확인됨"}:
        level = "추정"
    if supporting_tool_results(tool_results):
        return level
    if level == "확인됨":
        return "추정"
    return level


def diagnose_v1(
    log_text: str,
    case_id: str | None = None,
    progress_fn=None,
) -> V1DiagnosisResult:
    from app.progress import (
        STEP_EVIDENCE,
        STEP_LOG_ANALYSIS,
        TITLE_EVIDENCE_RUNNING,
        TITLE_LOG_ANALYSIS_RUNNING,
        emit_evidence,
        emit_initial_perception,
        emit_running,
    )

    emit_running(progress_fn, STEP_LOG_ANALYSIS, TITLE_LOG_ANALYSIS_RUNNING)
    initial = diagnose(log_text, case_id=case_id)
    emit_initial_perception(progress_fn, initial.extracted_info, initial.hypotheses)
    selections, tool_results = collect_tool_results(
        log_text, initial, progress_fn=progress_fn
    )
    emit_running(progress_fn, STEP_EVIDENCE, TITLE_EVIDENCE_RUNNING)
    final_payload = finalize_diagnosis(log_text, initial, tool_results)
    emit_evidence(progress_fn)
    result = V1DiagnosisResult(
        case_id=case_id or initial.case_id,
        summary=final_payload["summary"],
        extracted_info=initial.extracted_info,
        initial_hypotheses=initial.hypotheses,
        selected_tools=selections,
        tool_results=tool_results,
        final_cause_code=final_payload["final_cause_code"],
        final_cause_name=final_payload["final_cause_name"],
        diagnosis_level=final_payload["diagnosis_level"],
        owner=final_payload["owner"],
        evidence=final_payload["evidence"],
        limitations=final_payload["limitations"],
        recommended_actions=final_payload.get("recommended_actions") or [],
    )
    return result
