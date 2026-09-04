from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas import ValidationDecision
from app.ui_service import (
    analyze,
    extract_visible_fields,
    hypotheses_from_result,
    summarize_tool_data,
)
from app.agent_events import build_agent_event_views
from app.trace import AgentExecutionTrace, build_trace_view
from app.progress import ProgressEvent
from app.progress_view import (
    cause_label,
    format_operator_progress,
    issue_type_label,
    operator_running_label,
    owner_label,
    verdict_label,
    yes_no_label,
)

st.set_page_config(page_title="Batch Incident Copilot", layout="wide")

st.title("Batch Incident Copilot")
st.caption("배치 실행 로그 기반 장애 초동 분석 및 대응 지원")

MODE_OPTIONS = {
    "V0 Baseline": "v0",
    "V1 Tool Use": "v1",
    "V2 Dynamic Planning": "v2",
    "V3 Critic / Reflection": "v3",
}

mode_label = st.radio(
    "분석 모드",
    list(MODE_OPTIONS.keys()),
    horizontal=True,
)
version = MODE_OPTIONS[mode_label]

if version == "v0":
    st.info("V0: 로그만 이용해 원인을 추정하는 Baseline")
elif version == "v1":
    st.info("V1: LLM이 필요한 점검 Tool을 선택하고 Tool Evidence를 반영해 최종 진단")
elif version == "v2":
    st.info("V2: 조사 계획을 세우고 evidence가 부족하면 Re-plan하여 추가 Tool을 실행")
else:
    st.info("V3: 동결된 V2 진단을 Critic이 검증하고, 필요할 때만 Reflection으로 1회 교정")

uploaded = st.file_uploader("로그 파일 업로드 (.log, .txt)", type=["log", "txt"])
pasted = st.text_area("로그 직접 입력", height=220, placeholder="배치 실행 로그를 붙여넣으십시오.")
started = st.button("분석 시작", type="primary")


def _load_log() -> tuple[str, str | None, str | None]:
    if uploaded is not None:
        raw = uploaded.getvalue()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return "", uploaded.name, "읽을 수 없는 입력입니다: UTF-8로 디코딩하지 못했습니다."
        return text, uploaded.name, None
    return pasted, None, None


def _redraw_progress(
    slot,
    events: list[ProgressEvent],
    running_title: str | None,
) -> None:
    # container 자식 누적 대신 empty.markdown 한 장으로 다시 그린다.
    # 같은 스크립트 스레드에서 단계가 끝날 때마다 websocket delta가 나가게 한다.
    slot.markdown(format_operator_progress(events, running_title))


def _item(text) -> None:
    """markdown 리스트('- ', '* ')를 쓰지 않는다. 중첩 expander에서 bullet만 남는 버그를 피한다."""
    value = str(text).strip()
    if not value:
        return
    if value.startswith(("- ", "* ")):
        value = value[2:].strip()
    st.markdown(f"· {value}")


def _render_validation(validation: dict) -> None:
    st.subheader("입력 검증")
    decision = validation.get("decision")
    st.write(f"상태: **{decision}**")
    reasons = validation.get("reasons") or []
    if decision == ValidationDecision.ABORT.value:
        for reason in reasons:
            st.error(reason)
    elif decision == ValidationDecision.WARN.value:
        for reason in reasons:
            st.warning(reason)
        st.caption("경고가 있지만 분석을 계속합니다.")
    else:
        for reason in reasons:
            st.success(reason)


def _render_trace_row(row) -> None:
    if row.kind == "error":
        st.error(row.value)
        return
    if row.kind == "note":
        st.info(row.value)
        return
    if row.kind == "kv":
        st.markdown(f"**{row.label}:** {row.value}" if row.label else row.value)
        return
    value = str(row.value or "").strip()
    if value.startswith(("- ", "* ")):
        _item(value)
        return
    st.markdown(value)


def _render_execution_trace(trace: dict | None, version_name: str) -> None:
    st.subheader("Agent Execution Trace")
    st.caption(
        "시스템에서 발생한 관찰 가능한 이벤트만 단계별로 표시합니다. "
        "LLM 내부 Chain-of-Thought는 출력하지 않습니다."
    )
    if not trace:
        st.warning("실행 Trace를 만들지 못했습니다.")
        return

    # st.status + nested st.expander 조합은 Streamlit에서 본문이 사라지고
    # 빈 '-', '*' bullet만 남는 현상을 만든다. 중첩 없이 bordered container만 사용한다.
    payload = dict(trace)
    if version_name:
        payload["version"] = version_name
    model = AgentExecutionTrace.model_validate(payload)
    sections = build_trace_view(model)
    st.markdown("**Investigation Process**")
    for section in sections:
        with st.container(border=True):
            st.markdown(f"**{section.title}**")
            if not section.rows:
                st.info("표시할 항목이 없습니다.")
                continue
            for row in section.rows:
                _render_trace_row(row)


def _evidence_items(payload: dict) -> list:
    evidence_items = list(payload.get("evidence") or [])
    if evidence_items:
        return evidence_items
    for hyp in hypotheses_from_result(payload):
        if hyp.get("cause_code") == payload.get("final_cause_code"):
            return list(hyp.get("evidence") or [])
    return []


def _render_final(payload: dict) -> None:
    st.subheader("최종 진단")
    cause_name = str(payload.get("final_cause_name") or "").strip()
    cause_code = str(payload.get("final_cause_code") or "").strip()
    if not cause_name:
        cause_name = cause_label(cause_code) or "원인 미정"
    st.markdown(f"## {cause_name}")
    if cause_code:
        st.caption(cause_code)
    st.write(f"진단 수준: **{payload.get('diagnosis_level') or '추정'}**")
    st.write(f"담당 영역: **{owner_label(payload.get('owner'))}**")

    st.markdown("**근거**")
    evidence_items = _evidence_items(payload)
    if evidence_items:
        for item in evidence_items:
            _item(item)
    else:
        st.caption("표시할 근거가 없습니다.")

    st.markdown("**권장 조치**")
    actions = payload.get("recommended_actions") or []
    if actions:
        for item in actions:
            _item(item)
    else:
        st.caption("권고 조치가 없습니다.")

    st.markdown("**제약사항**")
    limitations = payload.get("limitations") or []
    if limitations:
        for item in limitations:
            _item(item)
    else:
        st.caption("표시할 제약사항이 없습니다.")


def _render_extracted(payload: dict) -> None:
    rows = extract_visible_fields(payload.get("extracted_info") or {})
    if not rows:
        st.caption("표시할 추출 정보가 없습니다.")
        return
    for label, value in rows:
        if isinstance(value, list):
            st.markdown(f"**{label}**")
            for item in value:
                _item(item)
        else:
            st.write(f"**{label}:** {value}")


def _render_hypotheses(payload: dict) -> None:
    items = hypotheses_from_result(payload)
    if not items:
        st.caption("초기 가설이 없습니다.")
        return
    for item in items:
        name = item.get("cause_name") or cause_label(item.get("cause_code"))
        code = item.get("cause_code")
        st.markdown(f"**{name}**")
        if code:
            st.caption(str(code))
        for evidence in item.get("evidence") or []:
            _item(evidence)


def _render_tools(payload: dict) -> None:
    selections = payload.get("selected_tools") or []
    results = payload.get("tool_results") or []
    if not selections and not results:
        st.caption("실행된 Tool이 없습니다.")
        return
    count = max(len(selections), len(results))
    for index in range(count):
        selection = selections[index] if index < len(selections) else {}
        result = results[index] if index < len(results) else {}
        tool_name = result.get("tool") or selection.get("selected_tool") or "unknown"
        status = result.get("status")
        title = f"점검 {index + 1} - {tool_name}"
        if status:
            title = f"{title} ({status})"
        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.write(f"**tool name:** {tool_name}")
            arguments = selection.get("arguments") or {}
            if arguments:
                st.write("**arguments**")
                for key, value in arguments.items():
                    _item(f"{key}: {value}")
            st.write(f"**status:** {status}")
            if status == "FAILED":
                st.error(result.get("error") or "Tool 실행 실패")
                st.caption("FAILED Tool 결과는 최종 근거의 일부로 사용하지 않습니다.")
            else:
                summary = summarize_tool_data(result.get("data") or {})
                if summary:
                    st.write("**data 요약**")
                    for key, value in summary.items():
                        _item(f"{key}: {value}")
                extra = result.get("data") or {}
                siblings = extra.get("same_directory_files")
                if siblings:
                    st.write("**same_directory_files**")
                    for item in siblings:
                        _item(
                            f"{item.get('path')}: exists={item.get('exists')}, "
                            f"received={item.get('received')}"
                        )


def _render_agent_events(trace: dict | None) -> None:
    st.subheader("고수준 Agent Trace")
    st.caption(
        "공통 AgentEvent로 정규화한 관찰 가능 실행 단계입니다. "
        "LLM 내부 Chain-of-Thought는 출력하지 않습니다."
    )
    events = (trace or {}).get("agent_events") or []
    if not events:
        st.info("표시할 AgentEvent가 없습니다.")
        return
    for view in build_agent_event_views(events):
        with st.container(border=True):
            st.markdown(f"**{view['title']}**")
            if view.get("detail"):
                st.caption(view["detail"])
            extra = {
                key: view[key]
                for key in ("timestamp", "round", "status", "source")
                if view.get(key) not in (None, "")
            }
            if extra:
                st.json(extra)
            metadata = view.get("metadata") or {}
            if metadata:
                st.json(metadata)


def _render_v2_trace(payload: dict) -> None:
    st.subheader("Agent Execution Trace")
    st.caption(
        "시스템에서 발생한 관찰 가능한 이벤트만 단계별로 표시합니다. "
        "LLM 내부 Chain-of-Thought는 출력하지 않습니다."
    )
    with st.container(border=True):
        st.markdown("**Log Analysis**")
        _render_extracted(payload)
    with st.container(border=True):
        st.markdown("**Initial Hypotheses**")
        _render_hypotheses(payload)

    rounds = payload.get("planning_trace") or []
    if not rounds:
        st.info("planning_trace가 없습니다.")
    for item in rounds:
        round_index = item.get("round_index")
        title = f"Plan Round {round_index}"
        if item.get("replanned"):
            title = f"Re-plan / {title}"
        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.write(f"**goal:** {item.get('goal') or '-'}")
            st.write(f"**reason:** {item.get('reason') or '-'}")
            questions = item.get("unresolved_questions") or []
            if questions:
                st.markdown("**unresolved_questions**")
                for question in questions:
                    _item(question)
            plan_steps = item.get("investigation_plan") or []
            if plan_steps:
                st.markdown("**investigation_plan**")
                for step in plan_steps:
                    tool = step.get("candidate_tool") or "none"
                    _item(
                        f"{step.get('goal') or ''} / {tool} / {step.get('status')}"
                    )

        if item.get("selected_tool"):
            with st.container(border=True):
                st.markdown(f"**Tool Call (round {round_index})**")
                st.write(f"**tool:** `{item.get('selected_tool')}`")
                arguments = item.get("arguments") or {}
                for key, value in arguments.items():
                    _item(f"{key}: {value}")
            result = item.get("tool_result") or {}
            with st.container(border=True):
                st.markdown(f"**Tool Result (round {round_index})**")
                status = result.get("status")
                st.write(f"**status:** {status or '-'}")
                if status == "FAILED":
                    st.error(result.get("error") or "Tool 실행 실패")
                    st.caption("FAILED Tool 결과는 최종 근거의 일부로 사용하지 않습니다.")
                else:
                    summary = item.get("evidence_summary") or summarize_tool_data(
                        result.get("data") or {}
                    )
                    for key, value in summary.items():
                        _item(f"{key}: {value}")

        with st.container(border=True):
            st.markdown(f"**Evidence / Hypothesis Update (round {round_index})**")
            states = item.get("hypothesis_states") or []
            if not states:
                st.caption("가설 상태 갱신이 없습니다.")
            for state in states:
                _item(
                    f"`{state.get('cause_code')}` ({state.get('origin')}): "
                    f"{state.get('status')}"
                )
                for signal in state.get("signals") or []:
                    st.caption(str(signal))

        with st.container(border=True):
            st.markdown(f"**Sufficiency Decision (round {round_index})**")
            sufficient = item.get("evidence_sufficient")
            st.write(f"**evidence_sufficient:** `{sufficient}`")
            if item.get("replanned"):
                st.write("추가 조사가 필요하여 Re-plan 했습니다.")
            if item.get("stop_reason"):
                st.write(f"**round stop_reason:** `{item.get('stop_reason')}`")

    with st.container(border=True):
        st.markdown("**Stop Reason**")
        st.write(f"**stop_reason:** `{payload.get('stop_reason')}`")
        st.write(f"**current_round:** {payload.get('current_round')}")


def _issue_type_value(item) -> object:
    if isinstance(item, dict):
        return item.get("issue_type")
    value = getattr(item, "issue_type", None)
    return value.value if hasattr(value, "value") else value


def _render_v3_detail(payload: dict) -> None:
    st.caption("Critic 자유서술 reasoning은 표시하지 않습니다.")
    critic = payload.get("critic_result") or {}
    if not isinstance(critic, dict):
        critic = critic.model_dump()
    issues = critic.get("issues") or []
    with st.container(border=True):
        st.markdown("**원래 진단**")
        st.write(
            f"원인: {cause_label(payload.get('original_v2_cause_code'))} "
            f"({payload.get('original_v2_cause_code')})"
        )
        st.write(f"진단 수준: {payload.get('original_v2_diagnosis_level')}")
        st.write(f"담당 영역: {owner_label(payload.get('original_v2_owner'))}")
    with st.container(border=True):
        st.markdown("**검증 결과**")
        st.write(f"결과: {verdict_label(critic.get('verdict'))}")
        st.write(f"원인 교정: {yes_no_label(payload.get('revised'))}")
        st.write(f"근거 일관성: {yes_no_label(critic.get('evidence_consistent'))}")
        if issues:
            st.markdown("**확인된 이슈**")
            for item in issues:
                row = item if isinstance(item, dict) else item.model_dump()
                blocking = "차단" if row.get("blocking") else "참고"
                _item(f"{issue_type_label(_issue_type_value(item))} ({blocking})")
        else:
            st.caption("확인된 이슈 없음")
    with st.container(border=True):
        st.markdown("**최종 원인**")
        st.write(
            f"원인: {payload.get('final_cause_name') or cause_label(payload.get('final_cause_code'))}"
        )
        st.caption(str(payload.get("final_cause_code") or ""))
        st.write(f"진단 수준: {payload.get('diagnosis_level')}")
        st.write(f"담당 영역: {owner_label(payload.get('owner'))}")


if started:
    log_text, filename, decode_error = _load_log()
    if decode_error:
        st.error(decode_error)
    elif not (log_text or "").strip():
        st.error("로그 파일을 업로드하거나 로그 텍스트를 입력하십시오.")
    else:
        st.subheader("분석 진행 과정")
        progress_events: list[ProgressEvent] = []
        # 라이브 패널을 status 밖에 둔다. collapse 후에도 한 번만 보이게 한다.
        progress_slot = st.empty()
        # 이전 실행의 최종 진단이 분석 중에 남아 보이지 않도록 아래 영역을 먼저 비운다.
        result_slot = st.empty()
        _redraw_progress(progress_slot, progress_events, None)
        with st.status("분석 중", expanded=True) as status_widget:
            st.caption("단계별 점검을 실행하고 있습니다.")

            def on_progress(event: ProgressEvent) -> None:
                if event.status == "running":
                    label = operator_running_label(event)
                    _redraw_progress(progress_slot, progress_events, label)
                    status_widget.update(
                        label=f"분석 중 · {label}",
                        state="running",
                    )
                    return
                progress_events.append(event)
                _redraw_progress(progress_slot, progress_events, None)
                status_widget.update(label="분석 중", state="running")

            outcome = analyze(
                version=version,
                log_text=log_text,
                filename=filename,
                progress_fn=on_progress,
            )
            _redraw_progress(progress_slot, progress_events, None)
            if (
                outcome.error
                or outcome.validation.decision == ValidationDecision.ABORT
            ):
                status_widget.update(label="분석 중단", state="error")
            else:
                status_widget.update(label="분석 완료", state="complete")

        if outcome.validation.decision == ValidationDecision.ABORT:
            with result_slot.container():
                _render_validation(outcome.validation.model_dump())
            st.stop()
        if outcome.error:
            with result_slot.container():
                st.error(outcome.error)
            st.stop()
        payload = outcome.result or {}
        with result_slot.container():
            st.divider()
            _render_final(payload)
            if version == "v3":
                st.caption("최종 검증 완료")
                with st.expander("상세 보기", expanded=False):
                    _render_v3_detail(payload)
            with st.expander("상세 실행 Trace", expanded=False):
                if version in {"v2", "v3"}:
                    _render_v2_trace(payload)
                else:
                    _render_execution_trace(outcome.trace, version)
                _render_agent_events(outcome.trace)
            with st.expander("원본 진단 필드", expanded=False):
                st.markdown("추출 정보")
                _render_extracted(payload)
                st.markdown("초기 원인 가설")
                _render_hypotheses(payload)
                if version in {"v1", "v2", "v3"}:
                    st.markdown("점검 Tool 원본 결과")
                    _render_tools(payload)
