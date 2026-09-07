import json
from pathlib import Path

from app.incident_report import build_incident_report


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _d01_payload() -> dict:
    return json.loads(
        (PROJECT_ROOT / "results" / "v3_critic" / "D-01.json").read_text(
            encoding="utf-8"
        )
    )


def test_builds_manager_report_from_existing_final_result():
    report = build_incident_report(
        _d01_payload(),
        log_text=(PROJECT_ROOT / "data" / "sample_logs" / "D-01.log").read_text(),
    )

    assert report.overview.job_name == "DAILY_SALES_DB_LOAD"
    assert report.overview.occurred_at == "2026-09-01 03:10:03"
    assert report.overview.incident_type == "DB 인증 정보 불일치"
    assert report.overview.owner == "배치 운영"
    assert report.overview.status == "원인 확인 / 조치 필요"
    assert report.cause.cause_code == "DB_CREDENTIAL_MISMATCH"
    assert report.cause.diagnosis_level == "확인됨"
    assert "ORA-01017" in report.cause.summary


def test_report_limits_evidence_to_direct_human_readable_items():
    report = build_incident_report(_d01_payload())

    assert 1 <= len(report.cause.evidence) <= 2
    rendered = " ".join(report.cause.evidence)
    assert "인증 정보 불일치" in rendered
    assert "check_db_status" not in rendered
    assert "credential_status" not in rendered
    assert "{" not in rendered


def test_selects_one_action_related_to_final_cause_not_first_action():
    payload = _d01_payload()
    payload["recommended_actions"] = [
        "애플리케이션 로그를 장기간 모니터링하십시오.",
        "batch_user 계정의 DB 인증 정보를 재확인 및 갱신하십시오.",
    ]

    report = build_incident_report(payload)

    assert report.action == "batch_user 계정의 DB 인증 정보를 확인·수정한 후 작업 재실행 여부를 검토합니다."


def test_uses_safe_fallback_when_no_action_directly_matches_cause():
    payload = _d01_payload()
    payload["recommended_actions"] = ["서버 디스크 사용량을 확인하십시오."]

    report = build_incident_report(payload)

    assert report.action == "최종 원인에 대응하는 조치 확인이 필요합니다."


def test_does_not_invent_missing_overview_values():
    payload = {
        "summary": "원인을 특정하기 어렵습니다.",
        "extracted_info": {},
        "final_cause_code": "UNKNOWN_CAUSE",
        "final_cause_name": "원인 미상",
        "diagnosis_level": "추정",
        "owner": "",
        "evidence": [],
        "tool_results": [],
        "recommended_actions": [],
    }

    report = build_incident_report(payload)

    assert report.overview.job_name == "확인되지 않음"
    assert report.overview.occurred_at == "확인되지 않음"
    assert report.overview.owner == "확인되지 않음"
    assert report.cause.core_error == "확인되지 않음"
    assert report.cause.evidence == []
    assert report.action == "최종 원인에 대응하는 조치 확인이 필요합니다."


def test_streamlit_separates_report_and_detail_with_tabs():
    source = (PROJECT_ROOT / "streamlit_app.py").read_text(encoding="utf-8")

    assert 'st.tabs(["장애 초동 보고서", "분석 상세"])' in source
    assert "with report_tab:" in source
    assert "with detail_tab:" in source
    assert 'with st.expander("분석 상세", expanded=False):' not in source
    assert "build_incident_report(payload, log_text=log_text)" in source


def test_streamlit_keeps_debug_views_collapsed_and_replan_wording_is_historical():
    source = (PROJECT_ROOT / "streamlit_app.py").read_text(encoding="utf-8")

    for title in ("Agent Execution Trace", "고수준 Agent Trace", "원본 진단 필드"):
        assert f'with st.expander("{title}", expanded=False):' in source
    assert "이 라운드는 이전 라운드의 근거 부족으로 재계획되었습니다." in source
    assert "추가 조사가 필요하여 Re-plan 했습니다." not in source


def test_limitations_render_only_in_analysis_final_section():
    source = (PROJECT_ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    report_block = source.split("def _render_incident_report", 1)[1].split(
        "def _render_final", 1
    )[0]
    final_block = source.split("def _render_final", 1)[1].split(
        "def _render_extracted", 1
    )[0]
    raw_fields_block = source.split(
        'with st.expander("원본 진단 필드", expanded=False):', 1
    )[1]

    assert "limitations" not in report_block
    assert 'st.markdown("**제약사항**")' in final_block
    assert 'st.caption("표시할 제약사항이 없습니다.")' in final_block
    assert "limitations" not in raw_fields_block
