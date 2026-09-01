"""관찰 가능한 실행 이벤트를 Agent Execution Trace로 재구성한다.

LLM 내부 Chain-of-Thought를 생성하거나 노출하지 않는다.
diagnose / diagnose_v1 판단 로직을 변경하지 않고, 이미 저장된
extracted_info, hypotheses, selected_tools, tool_results, 최종 진단 필드만 사용한다.
"""

from __future__ import annotations

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
