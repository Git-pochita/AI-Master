"""관찰 가능한 실행 이벤트를 Agent Execution Trace로 재구성한다.

LLM 내부 Chain-of-Thought를 생성하거나 노출하지 않는다.
diagnose / diagnose_v1 판단 로직을 변경하지 않고, 이미 저장된
extracted_info, hypotheses, selected_tools, tool_results, 최종 진단 필드만 사용한다.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.cause_codes import CAUSE_CODE_NAMES

HypothesisChange = Literal[
    "가능성 상승",
    "가능성 하락",
    "파생 현상으로 재분류",
    "유지",
    "신규 채택",
]

TOOL_PURPOSE: dict[str, str] = {
    "check_file_status": "입력 파일 수신/존재 여부 확인",
    "validate_parameter": "파라미터 값이 정상인지 확인",
    "check_db_status": "DB 계정 잠금·인증·접속 설정 상태 확인",
    "check_sql_metadata": "SQL schema/table/column 존재 여부 확인",
}

EVIDENCE_ALIASES: dict[str, str] = {
    "parameter_value": "actual",
    "expected_value": "expected",
}

EVIDENCE_KEYS: tuple[str, ...] = (
    "path",
    "filename",
    "exists",
    "received",
    "job_name",
    "parameter_name",
    "actual",
    "expected",
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


class HypothesisUpdate(BaseModel):
    cause_code: str
    cause_name: str = ""
    change: HypothesisChange
    signals: list[str] = Field(default_factory=list)


class ToolRound(BaseModel):
    tool: str
    purpose: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    input_display: str = ""
    status: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    excluded_from_final_evidence: bool = False


class LogAnalysisStep(BaseModel):
    message: str = "로그 분석 시작"
    core_errors: list[str] = Field(default_factory=list)
    extracted_fields: list[dict[str, Any]] = Field(default_factory=list)
    initial_hypotheses: list[dict[str, str]] = Field(default_factory=list)


class FinalDiagnosisStep(BaseModel):
    final_cause_code: str = ""
    final_cause_name: str = ""
    diagnosis_level: str = ""
    owner: str = ""
    evidence: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class AgentExecutionTrace(BaseModel):
    version: str
    log_analysis: LogAnalysisStep
    tool_rounds: list[ToolRound] = Field(default_factory=list)
    diagnosis_updates: list[HypothesisUpdate] = Field(default_factory=list)
    final_diagnosis: FinalDiagnosisStep


class TraceViewRow(BaseModel):
    kind: Literal["text", "kv", "error", "note"] = "text"
    label: str = ""
    value: str


class TraceViewSection(BaseModel):
    title: str
    rows: list[TraceViewRow] = Field(default_factory=list)


def _hypotheses(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("initial_hypotheses"):
        return list(payload["initial_hypotheses"])
    return list(payload.get("hypotheses") or [])


def _core_errors(extracted: dict[str, Any] | None) -> list[str]:
    if not extracted:
        return []
    errors: list[str] = []
    messages = extracted.get("error_messages")
    if isinstance(messages, list):
        errors.extend(str(item) for item in messages if item not in (None, ""))
    elif isinstance(messages, str) and messages.strip():
        errors.append(messages.strip())
    for key in ("error_code", "return_code"):
        value = extracted.get(key)
        if value not in (None, ""):
            errors.append(f"{key}={value}")
    return errors


def _extracted_fields(extracted: dict[str, Any] | None) -> list[dict[str, Any]]:
    from app.ui_service import extract_visible_fields

    rows = []
    for label, value in extract_visible_fields(extracted):
        rows.append({"label": label, "value": value})
    return rows


def _cause_name(code: str, fallback: str = "") -> str:
    return fallback or CAUSE_CODE_NAMES.get(code, code)


def purpose_for_tool(tool: str, arguments: dict[str, Any] | None) -> str:
    args = arguments or {}
    if tool == "validate_parameter":
        name = args.get("parameter_name") or args.get("parameter")
        if name:
            return f"{name} 값이 정상인지 확인"
    if tool == "check_file_status":
        path = args.get("path")
        if path:
            return f"입력 파일 수신/존재 여부 확인 ({path})"
        return TOOL_PURPOSE[tool]
    if tool == "check_sql_metadata":
        parts = [args[key] for key in ("schema", "table", "column") if args.get(key)]
        if parts:
            return f"SQL 객체 존재 여부 확인 ({'.'.join(str(p) for p in parts)})"
    return TOOL_PURPOSE.get(tool, f"{tool} 점검")


def format_tool_input(tool: str, arguments: dict[str, Any] | None) -> str:
    args = arguments or {}
    if tool == "validate_parameter":
        mapping = [
            ("job", args.get("job_name") or args.get("job")),
            ("parameter", args.get("parameter_name") or args.get("parameter")),
            ("value", args.get("parameter_value") or args.get("value")),
        ]
        parts = [f"{key}={value}" for key, value in mapping if value not in (None, "")]
        return ", ".join(parts)
    parts = [f"{key}={value}" for key, value in args.items() if value not in (None, "")]
    return ", ".join(parts)


def evidence_from_tool_data(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}
    from app.ui_service import summarize_tool_data

    summary = summarize_tool_data(data)
    display: dict[str, Any] = {}
    for key in EVIDENCE_KEYS:
        source_key = key
        if key in ("actual", "expected"):
            continue
        if source_key not in summary:
            continue
        label = EVIDENCE_ALIASES.get(source_key, source_key)
        if label in display:
            continue
        display[label] = summary[source_key]
    return display


def _tool_signals(tool_results: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    """cause_code -> {support: [...], contradict: [...]} Tool SUCCESS 필드만 사용한다."""
    grouped: dict[str, dict[str, list[str]]] = {}

    def add(code: str, polarity: str, signal: str) -> None:
        bucket = grouped.setdefault(code, {"support": [], "contradict": []})
        if signal not in bucket[polarity]:
            bucket[polarity].append(signal)

    for result in tool_results:
        if result.get("status") != "SUCCESS":
            continue
        tool = result.get("tool") or ""
        data = result.get("data") or {}

        if tool == "validate_parameter":
            name = str(data.get("parameter_name") or "")
            is_valid = data.get("is_valid")
            value = data.get("parameter_value")
            if name == "business_date":
                if is_valid is False:
                    add("INVALID_BUSINESS_DATE", "support", "is_valid=false")
                elif is_valid is True:
                    add("INVALID_BUSINESS_DATE", "contradict", "is_valid=true")
            empty_value = value is None or str(value).strip() == ""
            if empty_value:
                add("MISSING_REQUIRED_PARAMETER", "support", "parameter_value empty")
            if data.get("format_valid") is False:
                add("INVALID_PARAMETER_FORMAT", "support", "format_valid=false")
            elif data.get("format_valid") is True:
                add("INVALID_PARAMETER_FORMAT", "contradict", "format_valid=true")
            if data.get("range_valid") is False:
                add("INVALID_PARAMETER_RANGE", "support", "range_valid=false")
            elif data.get("range_valid") is True:
                add("INVALID_PARAMETER_RANGE", "contradict", "range_valid=true")

        elif tool == "check_file_status":
            exists = data.get("exists")
            received = data.get("received")
            if exists is False or received is False:
                add(
                    "FILE_NOT_RECEIVED",
                    "support",
                    f"exists={exists}, received={received}",
                )
            if exists is True and received is not False:
                add("FILE_NOT_RECEIVED", "contradict", "exists=true")
            siblings = data.get("same_directory_files") or []
            other_exists = any(
                item.get("exists") and item.get("path") != data.get("path")
                for item in siblings
                if isinstance(item, dict)
            )
            if exists is False and other_exists:
                add("INVALID_FILE_PATH", "support", "same_directory_files exists")

        elif tool == "check_db_status":
            cred = data.get("credential_status")
            if cred == "MISMATCH":
                add("DB_CREDENTIAL_MISMATCH", "support", "credential_status=MISMATCH")
            elif cred == "MATCH":
                add("DB_CREDENTIAL_MISMATCH", "contradict", "credential_status=MATCH")
            if data.get("account_locked") is True:
                add("DB_ACCOUNT_LOCKED", "support", "account_locked=true")
            elif data.get("account_locked") is False:
                add("DB_ACCOUNT_LOCKED", "contradict", "account_locked=false")
            if data.get("connection_config_valid") is False:
                add(
                    "DB_CONNECTION_CONFIG_ERROR",
                    "support",
                    "connection_config_valid=false",
                )
            elif data.get("connection_config_valid") is True:
                add(
                    "DB_CONNECTION_CONFIG_ERROR",
                    "contradict",
                    "connection_config_valid=true",
                )

        elif tool == "check_sql_metadata":
            if data.get("schema_exists") is False:
                add("INVALID_SCHEMA", "support", "schema_exists=false")
            elif data.get("schema_exists") is True:
                add("INVALID_SCHEMA", "contradict", "schema_exists=true")
            if data.get("table_exists") is False:
                add("TABLE_NOT_FOUND", "support", "table_exists=false")
            elif data.get("table_exists") is True:
                add("TABLE_NOT_FOUND", "contradict", "table_exists=true")
            if data.get("column_exists") is False:
                add("COLUMN_NOT_FOUND", "support", "column_exists=false")
            elif data.get("column_exists") is True:
                add("COLUMN_NOT_FOUND", "contradict", "column_exists=true")

    return grouped


def build_diagnosis_updates(
    payload: dict[str, Any],
    *,
    has_successful_tools: bool,
) -> list[HypothesisUpdate]:
    hypotheses = _hypotheses(payload)
    initial_codes = [
        item.get("cause_code")
        for item in hypotheses
        if item.get("cause_code")
    ]
    names = {
        item.get("cause_code"): item.get("cause_name") or ""
        for item in hypotheses
        if item.get("cause_code")
    }
    final_code = payload.get("final_cause_code") or ""
    signals = _tool_signals(payload.get("tool_results") or [])
    supported_final = bool(
        final_code and signals.get(final_code, {}).get("support")
    )

    ordered: list[str] = []
    if final_code:
        ordered.append(final_code)
    for code in initial_codes:
        if code not in ordered:
            ordered.append(code)

    updates: list[HypothesisUpdate] = []
    for code in ordered:
        support = signals.get(code, {}).get("support") or []
        contradict = signals.get(code, {}).get("contradict") or []
        in_initial = code in initial_codes

        if code == final_code and not in_initial:
            change: HypothesisChange = "신규 채택"
            used_signals = support
        elif code == final_code:
            change = "가능성 상승"
            used_signals = support
        elif contradict:
            change = "가능성 하락"
            used_signals = contradict
        elif has_successful_tools and (supported_final or bool(signals)):
            change = "파생 현상으로 재분류"
            used_signals = []
        else:
            change = "유지"
            used_signals = []

        updates.append(
            HypothesisUpdate(
                cause_code=code,
                cause_name=_cause_name(code, names.get(code, "")),
                change=change,
                signals=list(used_signals),
            )
        )
    return updates


def _final_evidence(payload: dict[str, Any]) -> list[str]:
    items = [str(item) for item in (payload.get("evidence") or []) if item]
    if items:
        return items
    final_code = payload.get("final_cause_code")
    for hyp in _hypotheses(payload):
        if hyp.get("cause_code") == final_code:
            return [str(item) for item in (hyp.get("evidence") or []) if item]
    return []


def _build_tool_rounds(payload: dict[str, Any]) -> list[ToolRound]:
    selections = list(payload.get("selected_tools") or [])
    results = list(payload.get("tool_results") or [])
    count = max(len(selections), len(results))
    rounds: list[ToolRound] = []
    for index in range(count):
        selection = selections[index] if index < len(selections) else {}
        result = results[index] if index < len(results) else {}
        tool = (
            result.get("tool")
            or selection.get("selected_tool")
            or "unknown"
        )
        arguments = selection.get("arguments") or {}
        rounds.append(
            ToolRound(
                tool=tool,
                purpose=purpose_for_tool(tool, arguments),
                arguments=arguments,
                input_display=format_tool_input(tool, arguments),
                status=str(result.get("status") or ""),
                evidence=evidence_from_tool_data(result.get("data") or {}),
                error=result.get("error"),
                excluded_from_final_evidence=str(result.get("status") or "") == "FAILED",
            )
        )
    return rounds


def build_execution_trace(version: str, payload: dict[str, Any] | None) -> AgentExecutionTrace:
    data = payload or {}
    extracted = data.get("extracted_info") or {}
    hypotheses = _hypotheses(data)
    tool_rounds = _build_tool_rounds(data) if version == "v1" else []
    has_successful_tools = any(item.status == "SUCCESS" for item in tool_rounds)

    return AgentExecutionTrace(
        version=version,
        log_analysis=LogAnalysisStep(
            message="로그 분석 시작",
            core_errors=_core_errors(extracted),
            extracted_fields=_extracted_fields(extracted),
            initial_hypotheses=[
                {
                    "cause_code": item.get("cause_code") or "",
                    "cause_name": item.get("cause_name")
                    or _cause_name(item.get("cause_code") or ""),
                }
                for item in hypotheses
                if item.get("cause_code")
            ],
        ),
        tool_rounds=tool_rounds,
        diagnosis_updates=build_diagnosis_updates(
            data,
            has_successful_tools=has_successful_tools,
        ),
        final_diagnosis=FinalDiagnosisStep(
            final_cause_code=str(data.get("final_cause_code") or ""),
            final_cause_name=str(data.get("final_cause_name") or ""),
            diagnosis_level=str(data.get("diagnosis_level") or ""),
            owner=str(data.get("owner") or ""),
            evidence=_final_evidence(data),
            recommended_actions=[
                str(item)
                for item in (data.get("recommended_actions") or [])
                if item
            ],
        ),
    )


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _row(kind: Literal["text", "kv", "error", "note"], value: Any, label: str = "") -> TraceViewRow | None:
    text = _stringify(value)
    if not text:
        return None
    return TraceViewRow(kind=kind, label=label, value=text)


def _extend(rows: list[TraceViewRow], row: TraceViewRow | None) -> None:
    if row is not None:
        rows.append(row)


def build_trace_view(trace: AgentExecutionTrace) -> list[TraceViewSection]:
    """Streamlit에 그릴 섹션. 빈 값은 넣지 않아 '-', '*' bullet이 생기지 않게 한다."""
    sections: list[TraceViewSection] = []
    analysis = trace.log_analysis
    log_rows: list[TraceViewRow] = []
    _extend(log_rows, _row("text", analysis.message or "로그 분석 시작"))
    if analysis.core_errors:
        _extend(log_rows, _row("text", "핵심 오류"))
        for item in analysis.core_errors:
            _extend(log_rows, _row("text", item))
    else:
        _extend(log_rows, _row("note", "extracted_info에서 표시할 오류 메시지가 없습니다."))
    if analysis.extracted_fields:
        _extend(log_rows, _row("text", "추출된 필드"))
        for field in analysis.extracted_fields:
            label = _stringify(field.get("label"))
            value = field.get("value")
            if isinstance(value, list):
                joined = ", ".join(_stringify(item) for item in value if _stringify(item))
                _extend(log_rows, _row("kv", joined, label=label))
            else:
                _extend(log_rows, _row("kv", value, label=label))
    sections.append(TraceViewSection(title="Log Analysis", rows=log_rows))

    hyp_rows: list[TraceViewRow] = []
    if analysis.initial_hypotheses:
        for item in analysis.initial_hypotheses:
            code = _stringify(item.get("cause_code"))
            name = _stringify(item.get("cause_name"))
            if not code:
                continue
            _extend(hyp_rows, _row("text", f"{code} — {name}" if name else code))
    else:
        _extend(hyp_rows, _row("note", "초기 가설이 없습니다."))
    sections.append(TraceViewSection(title="Initial Hypotheses", rows=hyp_rows))

    call_rows: list[TraceViewRow] = []
    arg_rows: list[TraceViewRow] = []
    result_rows: list[TraceViewRow] = []
    if trace.version != "v1":
        _extend(call_rows, _row("note", "V0는 Tool을 호출하지 않습니다."))
        _extend(arg_rows, _row("note", "V0는 Tool 인자가 없습니다."))
        _extend(result_rows, _row("note", "V0는 Tool 실행 결과가 없습니다."))
    elif not trace.tool_rounds:
        _extend(call_rows, _row("note", "호출한 Tool이 없습니다."))
        _extend(arg_rows, _row("note", "전달된 Tool arguments가 없습니다."))
        _extend(result_rows, _row("note", "Tool 실행 결과가 없습니다."))
    else:
        for index, item in enumerate(trace.tool_rounds, start=1):
            prefix = f"[{index}] {item.tool}"
            _extend(call_rows, _row("kv", item.tool, label=f"Tool {index}"))
            _extend(call_rows, _row("kv", item.purpose, label="목적"))
            _extend(arg_rows, _row("text", prefix))
            if item.input_display:
                _extend(arg_rows, _row("kv", item.input_display, label="Input"))
            if item.arguments:
                for key, value in item.arguments.items():
                    _extend(arg_rows, _row("kv", value, label=str(key)))
            else:
                _extend(arg_rows, _row("note", f"{item.tool}: 전달된 arguments가 없습니다."))
            _extend(result_rows, _row("text", prefix))
            _extend(result_rows, _row("kv", item.status or "UNKNOWN", label="status"))
            if item.status == "FAILED" or item.excluded_from_final_evidence:
                _extend(result_rows, _row("error", item.error or "Tool 실행 실패"))
                _extend(
                    result_rows,
                    _row(
                        "note",
                        "FAILED Tool 결과는 최종 evidence에서 제외했습니다.",
                    ),
                )
            elif item.evidence:
                for key, value in item.evidence.items():
                    _extend(result_rows, _row("kv", value, label=str(key)))
            else:
                _extend(result_rows, _row("note", "표시할 evidence 필드가 없습니다."))

    sections.append(TraceViewSection(title="Tool Call", rows=call_rows))
    sections.append(TraceViewSection(title="Tool Arguments", rows=arg_rows))
    sections.append(TraceViewSection(title="Tool Result", rows=result_rows))

    update_rows: list[TraceViewRow] = []
    _extend(
        update_rows,
        _row(
            "note",
            "Tool SUCCESS 필드와 최종 원인 코드로 계산한 구조화 상태입니다. 내부 reasoning 문장은 없습니다.",
        ),
    )
    if trace.diagnosis_updates:
        for item in trace.diagnosis_updates:
            _extend(update_rows, _row("kv", item.change, label=item.cause_code))
            for signal in item.signals:
                _extend(update_rows, _row("kv", signal, label="signal"))
    else:
        _extend(update_rows, _row("note", "표시할 가설 상태 변화가 없습니다."))
    sections.append(TraceViewSection(title="Evidence / Diagnosis Update", rows=update_rows))

    final = trace.final_diagnosis
    final_rows: list[TraceViewRow] = []
    _extend(final_rows, _row("kv", final.final_cause_code, label="final_cause"))
    _extend(final_rows, _row("kv", final.final_cause_name, label="final_cause_name"))
    _extend(final_rows, _row("kv", final.diagnosis_level, label="diagnosis_level"))
    _extend(final_rows, _row("kv", final.owner, label="owner"))
    if final.evidence:
        _extend(final_rows, _row("text", "evidence"))
        for item in final.evidence:
            _extend(final_rows, _row("text", item))
    else:
        _extend(final_rows, _row("note", "표시할 evidence가 없습니다."))
    if final.recommended_actions:
        _extend(final_rows, _row("text", "recommended_action"))
        for item in final.recommended_actions:
            _extend(final_rows, _row("text", item))
    else:
        _extend(final_rows, _row("note", "권고 조치가 없습니다."))
    sections.append(TraceViewSection(title="Final Diagnosis", rows=final_rows))
    return sections

