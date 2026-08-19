import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas import DiagnosisResult, Hypothesis, ValidationDecision
from app.ui_service import (
    analyze,
    extract_visible_fields,
    hypotheses_from_result,
    public_error_message,
    summarize_tool_data,
    validate_input,
)


SAMPLE = """2026-08-19 02:00:00 INFO  JOB=DAILY_SALES_LOAD START
2026-08-19 02:00:01 INFO  business_date=20260818
2026-08-19 02:00:02 INFO  input=/data/in/sales_20260818.csv
2026-08-19 02:00:03 ERROR FileNotFoundError: /data/in/sales_20260818.csv
2026-08-19 02:00:03 ERROR job failed with return_code=12
2026-08-19 02:00:04 INFO  JOB=DAILY_SALES_LOAD END
"""


def test_validate_input_empty_abort():
    result = validate_input("")
    assert result.decision == ValidationDecision.ABORT


def test_validate_input_short_warn():
    result = validate_input("ERROR boom")
    assert result.decision == ValidationDecision.WARN


def test_validate_input_sample_proceed():
    result = validate_input(SAMPLE)
    assert result.decision in {ValidationDecision.PROCEED, ValidationDecision.WARN}


def test_validate_upload_rejects_unsupported_extension():
    result = validate_input(SAMPLE, filename="case.csv")
    assert result.decision == ValidationDecision.ABORT
    assert any("확장자" in reason for reason in result.reasons)


def test_analyze_abort_does_not_call_backend(monkeypatch):
    called = {"n": 0}

    def fake_backend(*_args, **_kwargs):
        called["n"] += 1
        raise AssertionError("ABORT이면 LLM을 호출하면 안 됩니다.")

    monkeypatch.setattr("app.ui_service.run_backend", fake_backend)
    outcome = analyze("v0", "", case_id="empty")
    assert outcome.ok is False
    assert outcome.validation.decision == ValidationDecision.ABORT
    assert outcome.result is None
    assert called["n"] == 0


def test_v0_wrapper_uses_baseline(monkeypatch):
    fake = DiagnosisResult(
        case_id="file_case_001",
        summary="V0",
        extracted_info={"job_name": "DAILY_SALES_LOAD"},
        hypotheses=[
            Hypothesis(
                cause_code="FILE_NOT_RECEIVED",
                cause_name="파일 미수신",
                evidence=["FileNotFoundError"],
            )
        ],
        final_cause_code="FILE_NOT_RECEIVED",
        final_cause_name="파일 미수신",
        diagnosis_level="추정",
        owner="BATCH_OPERATION",
        recommended_actions=["확인"],
        limitations=["로그만 사용"],
    )
    monkeypatch.setattr("app.ui_service.run_backend", lambda *a, **k: fake)
    outcome = analyze("v0", SAMPLE, case_id="file_case_001")
    assert outcome.ok is True
    assert outcome.result["final_cause_code"] == "FILE_NOT_RECEIVED"
    assert "selected_tools" not in outcome.result


def test_v1_wrapper_keeps_tool_fields(monkeypatch):
    class FakeV1:
        def model_dump(self):
            return {
                "case_id": "file_case_001",
                "initial_hypotheses": [
                    {
                        "cause_code": "FILE_NOT_RECEIVED",
                        "cause_name": "파일 미수신",
                        "evidence": ["FileNotFoundError"],
                    }
                ],
                "selected_tools": [{"selected_tool": "check_file_status", "reason": "파일 확인", "arguments": {"path": "/data/in/sales_20260818.csv"}}],
                "tool_results": [{"tool": "check_file_status", "status": "SUCCESS", "data": {"exists": False}, "error": None}],
                "final_cause_code": "INVALID_BUSINESS_DATE",
                "final_cause_name": "실행일자 파라미터 오류",
                "diagnosis_level": "확인됨",
                "owner": "BATCH_OPERATION",
                "evidence": ["validate_parameter is_valid=false"],
                "limitations": ["mock"],
            }

    monkeypatch.setattr("app.ui_service.run_backend", lambda *a, **k: FakeV1())
    outcome = analyze("v1", SAMPLE, case_id="file_case_001")
    assert outcome.ok is True
    assert outcome.result["final_cause_code"] == "INVALID_BUSINESS_DATE"
    assert outcome.result["selected_tools"][0]["selected_tool"] == "check_file_status"


def test_public_error_message_redacts_secrets():
    message = public_error_message(RuntimeError("api_key=atl-SECRETVALUE123"))
    assert "atl-SECRETVALUE123" not in message
    assert "[REDACTED]" in message


def test_extract_and_summarize_helpers():
    rows = extract_visible_fields(
        {
            "job_name": "DAILY_SALES_LOAD",
            "return_code": "12",
            "input_path": "/data/in/sales_20260818.csv",
            "business_date": "20260818",
        }
    )
    labels = [label for label, _ in rows]
    assert "Job name" in labels
    assert "Return code" in labels
    summary = summarize_tool_data(
        {"exists": False, "received": False, "path": "/data/in/sales_20260818.csv", "noise": 1}
    )
    assert "exists" in summary
    assert "noise" not in summary


def test_hypotheses_from_v1_payload():
    items = hypotheses_from_result(
        {"initial_hypotheses": [{"cause_code": "FILE_NOT_RECEIVED"}], "hypotheses": []}
    )
    assert items[0]["cause_code"] == "FILE_NOT_RECEIVED"
