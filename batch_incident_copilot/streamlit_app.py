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

st.set_page_config(page_title="Batch Incident Copilot", layout="wide")

st.title("Batch Incident Copilot")
st.caption("배치 실행 로그 기반 장애 초동 분석 및 대응 지원")

MODE_OPTIONS = {
    "V0 Baseline": "v0",
    "V1 Tool Use": "v1",
}

mode_label = st.radio(
    "분석 모드",
    list(MODE_OPTIONS.keys()),
    horizontal=True,
)
version = MODE_OPTIONS[mode_label]

if version == "v0":
    st.info("V0: 로그만 이용해 원인을 추정하는 Baseline")
else:
    st.info("V1: LLM이 필요한 점검 Tool을 선택하고 Tool Evidence를 반영해 최종 진단")

uploaded = st.file_uploader("로그 파일 업로드 (.log, .txt)", type=["log", "txt"])
pasted = st.text_area("로그 직접 입력", height=220, placeholder="배치 실행 로그를 붙여넣으십시오.")

col_id, col_btn = st.columns([2, 1])
with col_id:
    case_id = st.text_input("case_id (선택)", value="file_case_001")
with col_btn:
    st.write("")
    started = st.button("분석 시작", type="primary", use_container_width=True)


def _load_log() -> tuple[str, str | None, str | None]:
    if uploaded is not None:
        raw = uploaded.getvalue()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return "", uploaded.name, "읽을 수 없는 입력입니다: UTF-8로 디코딩하지 못했습니다."
        return text, uploaded.name, None
    return pasted, None, None


def _render_validation(validation: dict) -> None:
    st.subheader("입력 검증")
    decision = validation.get("decision")
    st.write(f"status: **{decision}**")
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


def _render_extracted(payload: dict) -> None:
    st.subheader("추출 정보")
    rows = extract_visible_fields(payload.get("extracted_info") or {})
    if not rows:
        st.caption("표시할 추출 정보가 없습니다.")
        return
    for label, value in rows:
        if isinstance(value, list):
            st.markdown(f"**{label}**")
            for item in value:
                st.write(f"- {item}")
        else:
            st.write(f"**{label}:** {value}")


def _render_hypotheses(payload: dict) -> None:
    st.subheader("초기 원인 가설")
    items = hypotheses_from_result(payload)
    if not items:
        st.caption("초기 가설이 없습니다.")
        return
    for item in items:
        st.markdown(f"**{item.get('cause_code')}** — {item.get('cause_name')}")
        for evidence in item.get("evidence") or []:
            st.write(f"- {evidence}")


def _render_diagnosis_level(level: str) -> None:
    st.markdown(f"**diagnosis_level:** `{level}`")
    if level == "확인됨":
        st.success("확인됨")
    elif level == "가능성 높음":
        st.warning("가능성 높음")
    else:
        st.info(level or "추정")


def _render_final(payload: dict) -> None:
    st.subheader("최종 진단")
    st.write(f"**final_cause_code:** `{payload.get('final_cause_code')}`")
    st.write(f"**final_cause_name:** {payload.get('final_cause_name')}")
    _render_diagnosis_level(str(payload.get("diagnosis_level") or ""))
    st.write(f"**owner:** {payload.get('owner')}")
    st.markdown("**evidence**")
    evidence_items = list(payload.get("evidence") or [])
    if not evidence_items:
        for hyp in payload.get("hypotheses") or []:
            if hyp.get("cause_code") == payload.get("final_cause_code"):
                evidence_items = list(hyp.get("evidence") or [])
                break
    if evidence_items:
        for item in evidence_items:
            st.write(f"- {item}")
    else:
        st.caption("표시할 evidence가 없습니다.")
    st.markdown("**limitations**")
    for item in payload.get("limitations") or []:
        st.write(f"- {item}")


def _render_tools(payload: dict) -> None:
    st.subheader("점검 Tool 실행 결과")
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
        with st.expander(title, expanded=True):
            st.write(f"**tool name:** {tool_name}")
            arguments = selection.get("arguments") or {}
            if arguments:
                st.write("**arguments**")
                for key, value in arguments.items():
                    st.write(f"- {key}: {value}")
            if selection.get("reason"):
                st.write(f"**선택 이유:** {selection.get('reason')}")
            st.write(f"**status:** {status}")
            if status == "FAILED":
                st.error(result.get("error") or "Tool 실행 실패")
                st.caption("FAILED Tool 결과는 최종 근거의 일부로 사용하지 않습니다.")
            else:
                summary = summarize_tool_data(result.get("data") or {})
                if summary:
                    st.write("**data 요약**")
                    for key, value in summary.items():
                        st.write(f"- {key}: {value}")
                extra = result.get("data") or {}
                siblings = extra.get("same_directory_files")
                if siblings:
                    st.write("**same_directory_files**")
                    for item in siblings:
                        st.write(
                            f"- {item.get('path')}: exists={item.get('exists')}, "
                            f"received={item.get('received')}"
                        )


if started:
    log_text, filename, decode_error = _load_log()
    if decode_error:
        st.error(decode_error)
    elif not (log_text or "").strip():
        st.error("로그 파일을 업로드하거나 로그 텍스트를 입력하십시오.")
    else:
        with st.spinner("분석 중입니다."):
            outcome = analyze(
                version=version,
                log_text=log_text,
                case_id=case_id or None,
                filename=filename,
            )
        _render_validation(outcome.validation.model_dump())
        if outcome.validation.decision == ValidationDecision.ABORT:
            st.stop()
        if outcome.error:
            st.error(outcome.error)
            st.stop()
        payload = outcome.result or {}
        _render_extracted(payload)
        _render_hypotheses(payload)
        if version == "v1":
            _render_tools(payload)
        _render_final(payload)
