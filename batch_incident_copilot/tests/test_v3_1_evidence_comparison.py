from __future__ import annotations

import json
import sys
from pathlib import Path

from app.critic import (
    CRITIC_ALLOWED_KEYS,
    CRITIC_DENIED_KEYS,
    CriticLLMDraft,
    alternative_supported_by_observable,
    build_critic_input,
    cause_revision_allowed,
)
from app.evidence_comparison import (
    EvidenceComparison,
    _filename_body_prefix_shared,
    _shares_review_context,
    build_evidence_comparison,
    comparison_payload,
)
from app.schemas import CriticIssueType, CriticResult, ToolResult
from app.v3 import MAX_CRITIC_CALLS, MAX_REVISION_CALLS
from tests.test_v3 import (
    _conflict_better_draft,
    _issue,
    _load_log,
    _load_v2,
    _pass_draft,
    _revision_draft,
    _run,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


CAUSE_CODES = (
    "FILE_NOT_RECEIVED",
    "INVALID_FILE_PATH",
    "INVALID_BUSINESS_DATE",
    "DB_CREDENTIAL_MISMATCH",
    "TABLE_NOT_FOUND",
)


def _texts(rows) -> str:
    return "\n".join(item.description for item in rows)


def _compare_v2(case_id: str) -> EvidenceComparison:
    v2 = _load_v2(case_id)
    return build_evidence_comparison(
        current_cause_code=v2.final_cause_code,
        tool_results=v2.tool_results,
        log_text=_load_log(case_id),
        extracted_info=v2.extracted_info,
    )


def _file_success(
    path: str,
    *,
    exists: bool,
    received: bool,
    siblings: list[dict] | None = None,
) -> ToolResult:
    name = Path(path).name
    data = {
        "path": path,
        "exists": exists,
        "received": received,
        "filename": name,
        "same_directory_files": list(siblings or []),
    }
    return ToolResult(tool="check_file_status", status="SUCCESS", data=data, error=None)


def _parameter_success(*, is_valid: bool, value: str = "20260831", expected: str = "20260901") -> ToolResult:
    return ToolResult(
        tool="validate_parameter",
        status="SUCCESS",
        data={
            "parameter_name": "business_date",
            "parameter_value": value,
            "expected_value": expected,
            "is_valid": is_valid,
            "provided": True,
            "required": True,
        },
        error=None,
    )


def _assert_no_cause_verdict(comparison: EvidenceComparison) -> None:
    dumped = comparison_payload(comparison)
    assert "recommended_cause_code" not in dumped
    blob = json.dumps(
        {key: value for key, value in dumped.items() if key != "current_cause_code"},
        ensure_ascii=False,
    )
    for code in CAUSE_CODES:
        assert code not in blob
    joined = "\n".join(
        [
            *(_texts(comparison.supporting_observations).splitlines()),
            *(_texts(comparison.potentially_conflicting_observations).splitlines()),
            *(_texts(comparison.strong_causal_observations).splitlines()),
            *(_texts(comparison.surface_symptoms).splitlines()),
        ]
    )
    assert "therefore" not in joined.lower()
    assert "정답" not in joined


def test_f01_type_has_no_received_sibling_conflict():
    comparison = _compare_v2("F-01")
    assert comparison.current_cause_code == "FILE_NOT_RECEIVED"
    assert comparison.potentially_conflicting_observations == []
    assert "received=true" not in _texts(comparison.potentially_conflicting_observations)
    assert any("received=false" in item.description for item in comparison.supporting_observations)
    _assert_no_cause_verdict(comparison)
    result = _run("F-01", _pass_draft)
    assert result.critic_result.verdict == "PASS"
    assert result.final_cause_code == "FILE_NOT_RECEIVED"
    assert result.revised is False


def test_f02_type_marks_received_sibling_for_review():
    comparison = _compare_v2("F-02")
    conflicting = _texts(comparison.potentially_conflicting_observations)
    supporting = _texts(comparison.supporting_observations)
    assert "sales_20260901.csv" in conflicting
    assert "received=true" in conflicting
    assert "exact_name_match=false" in conflicting
    assert "date_token_overlap=true" in conflicting
    assert "filename_body_prefix_shared=true" in conflicting
    assert "ledger_20260901.csv" not in conflicting
    assert "ledger_20260901.csv" in supporting
    _assert_no_cause_verdict(comparison)
    assert comparison.current_cause_code == "FILE_NOT_RECEIVED"


def test_f03_type_has_no_false_conflict():
    comparison = _compare_v2("F-03")
    assert comparison.potentially_conflicting_observations == []
    _assert_no_cause_verdict(comparison)


def test_f04_type_marks_other_received_filename():
    comparison = _compare_v2("F-04")
    conflicting = _texts(comparison.potentially_conflicting_observations)
    assert "partner_20260901.csv" in conflicting
    assert "received=true" in conflicting
    _assert_no_cause_verdict(comparison)


def test_filename_body_prefix_sale_sales_is_shared():
    assert _filename_body_prefix_shared("sale_20260901.csv", "sales_20260901.csv") is True
    assert _shares_review_context("sale_20260901.csv", "sales_20260901.csv", {}) is True


def test_filename_body_prefix_partnr_partner_is_shared():
    assert _filename_body_prefix_shared("partnr_20260901.csv", "partner_20260901.csv") is True
    assert _shares_review_context("partnr_20260901.csv", "partner_20260901.csv", {}) is True


def test_filename_body_prefix_sales_summary_is_not_shared():
    assert _filename_body_prefix_shared("sales_20260901.csv", "summary_20260901.csv") is False
    assert _shares_review_context("sales_20260901.csv", "summary_20260901.csv", {}) is False
    tool = _file_success(
        "/data/in/sales_20260901.csv",
        exists=False,
        received=False,
        siblings=[
            {
                "path": "/data/in/summary_20260901.csv",
                "filename": "summary_20260901.csv",
                "exists": True,
                "received": True,
            }
        ],
    )
    comparison = build_evidence_comparison(
        current_cause_code="FILE_NOT_RECEIVED",
        tool_results=[tool],
    )
    assert comparison.potentially_conflicting_observations == []
    assert any(
        "summary_20260901.csv" in item.description
        for item in comparison.supporting_observations
    )


def test_filename_body_prefix_single_letter_is_not_shared():
    assert _filename_body_prefix_shared("sales_20260901.csv", "status_20260901.csv") is False
    assert _shares_review_context("sales_20260901.csv", "status_20260901.csv", {}) is False


def test_filename_body_prefix_ledger_sale_is_not_shared():
    assert _filename_body_prefix_shared("ledger_20260901.csv", "sale_20260901.csv") is False
    assert _shares_review_context("ledger_20260901.csv", "sale_20260901.csv", {}) is False


def test_f05_has_no_file_conflict_and_keeps_strong_causal():
    comparison = _compare_v2("F-05")
    assert comparison.potentially_conflicting_observations == []
    assert any(
        item.fact_type == "parameter_invalid"
        for item in comparison.strong_causal_observations
    )


def test_f05_type_parameter_is_strong_causal_file_is_surface():
    comparison = _compare_v2("F-05")
    strong = _texts(comparison.strong_causal_observations)
    surface = _texts(comparison.surface_symptoms)
    assert "is_valid=false" in strong
    assert "20260831" in strong
    assert "20260901" in strong
    assert "requested_file" in surface
    assert any(item.source == "validate_parameter" for item in comparison.strong_causal_observations)
    result = _run("F-05", _pass_draft)
    assert result.final_cause_code == "INVALID_BUSINESS_DATE"
    assert result.revised is False
    _assert_no_cause_verdict(comparison)


def test_f06_failed_tool_excluded_from_structured_evidence():
    comparison = _compare_v2("F-06")
    blob = json.dumps(comparison_payload(comparison), ensure_ascii=False)
    assert "카탈로그에 경로가 없습니다" not in blob
    assert comparison.strong_causal_observations == []
    assert all(item.source != "check_file_status" for item in comparison.supporting_observations)


def test_only_success_tool_data_normalized():
    failed = ToolResult(
        tool="check_file_status",
        status="FAILED",
        data=None,
        error="카탈로그에 경로가 없습니다",
    )
    success = _file_success("/data/in/a.csv", exists=False, received=False)
    comparison = build_evidence_comparison(
        current_cause_code="FILE_NOT_RECEIVED",
        tool_results=[failed, success],
    )
    blob = json.dumps(comparison_payload(comparison), ensure_ascii=False)
    assert "카탈로그에 경로가 없습니다" not in blob
    assert "requested_file:path=/data/in/a.csv" in blob


def test_failed_tool_excluded():
    comparison = build_evidence_comparison(
        current_cause_code="FILE_NOT_RECEIVED",
        tool_results=[
            ToolResult(
                tool="check_file_status",
                status="FAILED",
                data={"exists": False},
                error="boom",
            )
        ],
    )
    assert comparison.supporting_observations == []
    assert comparison.potentially_conflicting_observations == []
    assert comparison.strong_causal_observations == []


def test_empty_tool_results_are_safe():
    comparison = build_evidence_comparison(
        current_cause_code="FILE_NOT_RECEIVED",
        tool_results=[],
    )
    assert comparison.supporting_observations == []
    assert comparison.potentially_conflicting_observations == []
    dumped = comparison_payload(comparison)
    assert dumped["current_cause_code"] == "FILE_NOT_RECEIVED"


def test_nested_same_directory_files_flatten():
    tool = _file_success(
        "/data/in/sale_20260901.csv",
        exists=False,
        received=False,
        siblings=[
            {
                "path": "/data/in/sales_20260901.csv",
                "filename": "sales_20260901.csv",
                "exists": True,
                "received": True,
            }
        ],
    )
    comparison = build_evidence_comparison(
        current_cause_code="FILE_NOT_RECEIVED",
        tool_results=[tool],
    )
    assert any(
        "same_directory_file:name=sales_20260901.csv,received=true" in item.description
        for item in comparison.potentially_conflicting_observations
    )
    assert any(
        "sales_20260901.csv" in item.description
        for item in comparison.supporting_observations
    )


def test_received_false_sibling_is_not_conflict():
    tool = _file_success(
        "/data/in/orders_20260901.csv",
        exists=False,
        received=False,
        siblings=[
            {
                "path": "/data/in/orders_20260831.csv",
                "filename": "orders_20260831.csv",
                "exists": False,
                "received": False,
            }
        ],
    )
    comparison = build_evidence_comparison(
        current_cause_code="FILE_NOT_RECEIVED",
        tool_results=[tool],
    )
    assert comparison.potentially_conflicting_observations == []
    assert any(
        "orders_20260831.csv" in item.description
        for item in comparison.supporting_observations
    )


def test_received_true_sibling_creates_reviewable_observation():
    tool = _file_success(
        "/data/in/partnr_20260901.csv",
        exists=False,
        received=False,
        siblings=[
            {
                "name": "partner_20260901.csv",
                "path": "/data/in/partner/partner_20260901.csv",
                "exists": True,
                "received": True,
            }
        ],
    )
    comparison = build_evidence_comparison(
        current_cause_code="FILE_NOT_RECEIVED",
        tool_results=[tool],
    )
    assert any(
        "partner_20260901.csv" in item.description
        for item in comparison.potentially_conflicting_observations
    )


def test_unrelated_received_sibling_is_observable_but_not_conflict():
    tool = _file_success(
        "/data/in/sale_20260901.csv",
        exists=False,
        received=False,
        siblings=[
            {
                "path": "/data/in/ledger_20260901.csv",
                "filename": "ledger_20260901.csv",
                "exists": True,
                "received": True,
            }
        ],
    )
    comparison = build_evidence_comparison(
        current_cause_code="FILE_NOT_RECEIVED",
        tool_results=[tool],
        extracted_info={"business_date": "20260901"},
    )
    supporting = _texts(comparison.supporting_observations)
    conflicting = _texts(comparison.potentially_conflicting_observations)
    assert "ledger_20260901.csv" in supporting
    assert "received=true" in supporting
    assert "ledger_20260901.csv" not in conflicting
    assert comparison.potentially_conflicting_observations == []
    _assert_no_cause_verdict(comparison)


def test_same_directory_received_true_alone_is_not_conflict():
    tool = _file_success(
        "/data/in/target_20260901.csv",
        exists=False,
        received=False,
        siblings=[
            {
                "path": "/data/in/other_20260901.csv",
                "filename": "other_20260901.csv",
                "exists": True,
                "received": True,
            }
        ],
    )
    comparison = build_evidence_comparison(
        current_cause_code="FILE_NOT_RECEIVED",
        tool_results=[tool],
    )
    assert comparison.potentially_conflicting_observations == []
    assert any(
        "other_20260901.csv" in item.description and "received=true" in item.description
        for item in comparison.supporting_observations
    )


def test_parameter_invalid_is_strong_causal():
    comparison = build_evidence_comparison(
        current_cause_code="INVALID_BUSINESS_DATE",
        tool_results=[_parameter_success(is_valid=False)],
    )
    assert any(
        item.fact_type == "parameter_invalid"
        for item in comparison.strong_causal_observations
    )


def test_valid_parameter_is_not_invalid_causal():
    comparison = build_evidence_comparison(
        current_cause_code="FILE_NOT_RECEIVED",
        tool_results=[_parameter_success(is_valid=True, value="20260901")],
    )
    assert comparison.strong_causal_observations == []
    assert any("is_valid=true" in item.description for item in comparison.supporting_observations)


def test_deterministic_layer_does_not_choose_cause():
    comparison = _compare_v2("F-02")
    _assert_no_cause_verdict(comparison)
    payload = build_critic_input(_load_log("F-02"), _load_v2("F-02"))
    blob = json.dumps(payload["evidence_comparison"], ensure_ascii=False)
    assert "recommended_cause_code" not in payload["evidence_comparison"]
    assert "INVALID_FILE_PATH" not in blob


def test_critic_input_has_comparison_and_no_denied_keys():
    payload = build_critic_input(_load_log("F-02"), _load_v2("F-02"))
    assert set(payload) == set(CRITIC_ALLOWED_KEYS)
    assert "evidence_comparison" in payload
    for key in CRITIC_DENIED_KEYS:
        assert key not in payload
    assert "case_id" not in payload
    assert "ground_truth" not in payload
    assert "planning_trace" not in payload
    comparison = payload["evidence_comparison"]
    for key in (
        "supporting_observations",
        "potentially_conflicting_observations",
        "strong_causal_observations",
        "surface_symptoms",
    ):
        assert key in comparison


def test_critic_input_excludes_gt_case_id_and_planner_rationale():
    v2 = _load_v2("F-04")
    payload = build_critic_input(_load_log("F-04"), v2)
    blob = json.dumps(payload, ensure_ascii=False)
    assert "ground_truth" not in blob
    assert "actual_cause_code" not in blob
    for item in v2.selected_tools:
        if item.reason:
            assert item.reason not in blob
    for item in v2.planning_trace:
        if item.reason:
            assert item.reason not in blob


def test_cause_revision_gate_still_requires_both_issues():
    v2 = _load_v2("F-02")
    token = "sales_20260901.csv"
    critic = CriticResult(
        verdict="REVISE",
        evidence_consistent=False,
        diagnosis_level_appropriate=True,
        owner_consistent=True,
        issues=[_issue(CriticIssueType.EVIDENCE_CONFLICT, [token])],
        recommended_cause_code="INVALID_FILE_PATH",
    )
    assert (
        cause_revision_allowed(
            critic,
            current_cause=v2.final_cause_code,
            log_text=_load_log("F-02"),
            extracted_info=v2.extracted_info,
            tool_results=v2.tool_results,
        )
        is False
    )


def test_pass_preserves_v2_after_structured_comparison():
    v2 = _load_v2("F-01")
    result = _run("F-01", _pass_draft)
    assert result.final_cause_code == v2.final_cause_code
    assert result.diagnosis_level == v2.diagnosis_level
    assert result.revised is False


def test_critic_and_revision_remain_single_call():
    critic_calls = {"n": 0}
    revise_calls = {"n": 0}
    v2 = _load_v2("F-02")

    def critic_fn(*_a, **_k):
        critic_calls["n"] += 1
        return _conflict_better_draft("sales_20260901.csv")

    def revise_fn(*_a, **_k):
        revise_calls["n"] += 1
        return _revision_draft(v2, "INVALID_FILE_PATH")

    _run("F-02", critic_fn, revise_fn=revise_fn)
    assert critic_calls["n"] == 1
    assert revise_calls["n"] == 1
    assert MAX_CRITIC_CALLS == 1
    assert MAX_REVISION_CALLS == 1


def test_no_additional_tool_in_comparison_module():
    source = (PROJECT_ROOT / "app" / "evidence_comparison.py").read_text(encoding="utf-8")
    assert "execute_tool" not in source
    assert "diagnose_v2" not in source


def test_false_negative_recovery_uses_structured_related_evidence():
    v2 = _load_v2("F-02")
    comparison = _compare_v2("F-02")
    token = comparison.potentially_conflicting_observations[0].description

    def critic_fn(*_a, **_k):
        return CriticLLMDraft(
            evidence_consistent=False,
            issues=[
                _issue(CriticIssueType.EVIDENCE_CONFLICT, [token]),
                _issue(CriticIssueType.BETTER_SUPPORTED_CAUSE, [token]),
            ],
            recommended_cause_code="INVALID_FILE_PATH",
        )

    assert (
        cause_revision_allowed(
            CriticResult(
                verdict="REVISE",
                evidence_consistent=False,
                diagnosis_level_appropriate=True,
                owner_consistent=True,
                issues=[
                    _issue(CriticIssueType.EVIDENCE_CONFLICT, [token]),
                    _issue(CriticIssueType.BETTER_SUPPORTED_CAUSE, [token]),
                ],
                recommended_cause_code="INVALID_FILE_PATH",
            ),
            current_cause=v2.final_cause_code,
            log_text=_load_log("F-02"),
            extracted_info=v2.extracted_info,
            tool_results=v2.tool_results,
        )
        is True
    )
    result = _run(
        "F-02",
        critic_fn,
        revise_fn=lambda _log, producer, _critic: _revision_draft(
            producer, "INVALID_FILE_PATH"
        ),
    )
    assert result.final_cause_code == "INVALID_FILE_PATH"
    assert result.revised is True


def test_false_positive_protection_pass_keeps_current_cause():
    result = _run("F-05", _pass_draft)
    assert result.critic_result.verdict == "PASS"
    assert result.final_cause_code == "INVALID_BUSINESS_DATE"
    comparison = _compare_v2("F-05")
    assert comparison.strong_causal_observations
    assert comparison.surface_symptoms


def test_gate_blocks_when_related_evidence_is_not_observable():
    v2 = _load_v2("F-05")
    paraphrase = "로그: FileNotFoundError: /data/in/sales_20260831.csv"

    def critic_fn(*_a, **_k):
        return CriticLLMDraft(
            evidence_consistent=False,
            issues=[
                _issue(CriticIssueType.EVIDENCE_CONFLICT, [paraphrase]),
                _issue(CriticIssueType.BETTER_SUPPORTED_CAUSE, [paraphrase]),
            ],
            recommended_cause_code="FILE_NOT_RECEIVED",
        )

    result = _run(
        "F-05",
        critic_fn,
        revise_fn=lambda _log, producer, _critic: _revision_draft(
            producer, "FILE_NOT_RECEIVED"
        ),
        v2=v2,
    )
    assert result.critic_result.verdict == "REVISE"
    assert result.final_cause_code == "INVALID_BUSINESS_DATE"
    assert (
        alternative_supported_by_observable(
            "FILE_NOT_RECEIVED",
            log_text=_load_log("F-05"),
            extracted_info=v2.extracted_info,
            tool_results=v2.tool_results,
            related_evidence=[paraphrase],
            current_cause=v2.final_cause_code,
        )
        is False
    )


def test_db_and_sql_success_fields_are_normalized():
    db = ToolResult(
        tool="check_db_status",
        status="SUCCESS",
        data={
            "connection_name": "SALES_DB",
            "account": "batch_user",
            "account_locked": False,
            "credential_status": "MISMATCH",
            "connection_config_valid": True,
        },
    )
    sql = ToolResult(
        tool="check_sql_metadata",
        status="SUCCESS",
        data={
            "schema": "SALES",
            "table": "SALES_SUMMARY",
            "column": None,
            "schema_exists": True,
            "table_exists": False,
            "column_exists": None,
        },
    )
    comparison = build_evidence_comparison(
        current_cause_code="DB_CREDENTIAL_MISMATCH",
        tool_results=[db, sql],
    )
    assert any(item.source == "check_db_status" for item in comparison.supporting_observations)
    assert any(item.source == "check_sql_metadata" for item in comparison.supporting_observations)
    assert any("credential_status=MISMATCH" in item.description for item in comparison.strong_causal_observations)
    assert any("table_exists=false" in item.description for item in comparison.strong_causal_observations)
    _assert_no_cause_verdict(comparison)


def test_agent_event_records_comparison_counts():
    from app.agent_events import build_agent_events

    payload = _run("F-02", _pass_draft).model_dump()
    events = build_agent_events("v3", payload)
    comparison = next(item for item in events if item.step == "evidence_comparison")
    assert comparison.component == "Evaluation"
    assert comparison.metadata["potentially_conflicting_count"] >= 1
    assert "supporting_count" in comparison.metadata
    assert "strong_causal_count" in comparison.metadata
    assert "surface_symptom_count" in comparison.metadata
    assert "reason" not in comparison.metadata


def test_official_v3_baseline_artifacts_untouched():
    official = [
        PROJECT_ROOT / "evaluation" / "reports" / "v3_summary.json",
        PROJECT_ROOT / "evaluation" / "reports" / "v2_refined_vs_v3.md",
        PROJECT_ROOT / "results" / "v3_critic" / "F-02.json",
    ]
    for path in official:
        assert path.exists()
