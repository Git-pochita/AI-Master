import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.metrics import (
    aggregate_case_metrics,
    required_tool_recall,
    selected_tool_names,
    unnecessary_tool_rate,
)
from evaluation.report import render_comparison_markdown


def test_required_tool_recall():
    assert required_tool_recall(["check_file_status", "validate_parameter"], ["check_file_status"]) == 0.5
    assert required_tool_recall(["check_db_status"], ["check_db_status"]) == 1.0
    assert required_tool_recall(["check_sql_metadata"], []) == 0.0
    assert required_tool_recall([], ["check_file_status"]) == 1.0


def test_unnecessary_tool_rate():
    assert unnecessary_tool_rate(
        ["check_db_status"],
        ["check_file_status", "check_db_status"],
    ) == 0.5
    assert unnecessary_tool_rate(["check_db_status"], ["check_db_status"]) == 0.0
    assert unnecessary_tool_rate(["check_db_status"], []) == 0.0


def test_selected_tool_names_and_aggregate():
    payload = {
        "selected_tools": [
            {"selected_tool": "check_file_status"},
            {"selected_tool": None},
        ]
    }
    assert selected_tool_names(payload) == ["check_file_status"]
    rows = [
        {
            "case_id": "a",
            "run_status": "success",
            "final_diagnosis_correct": True,
            "hypothesis_recall_hit": True,
            "diagnosis_level_correct": True,
            "owner_correct": True,
            "required_tool_recall": 1.0,
            "unnecessary_tool_rate": 0.0,
            "tool_call_count": 1,
            "tool_failure_count": 0,
        },
        {
            "case_id": "b",
            "run_status": "success",
            "final_diagnosis_correct": False,
            "hypothesis_recall_hit": False,
            "diagnosis_level_correct": True,
            "owner_correct": True,
            "required_tool_recall": 0.5,
            "unnecessary_tool_rate": 0.5,
            "tool_call_count": 2,
            "tool_failure_count": 1,
        },
        {
            "case_id": "c",
            "run_status": "failed",
            "error": "LLM 실패",
        },
    ]
    v0 = aggregate_case_metrics("v0", rows)
    assert v0["total_cases"] == 3
    assert v0["failed_runs"] == 1
    assert v0["final_diagnosis_accuracy"] == 1 / 3
    assert "required_tool_recall" not in v0
    v1 = aggregate_case_metrics("v1", rows)
    assert v1["required_tool_recall"] == (1.0 + 0.5 + 0.0) / 3
    assert v1["unnecessary_tool_rate"] == (0.0 + 0.5 + 0.0) / 3
    assert v1["average_tool_calls"] == (1 + 2 + 0) / 3
    assert v1["tool_failure_count"] == 1


def test_report_generation_contains_comparison_table():
    v0 = {
        "final_diagnosis_accuracy": 0.4,
        "hypothesis_recall": 0.5,
        "diagnosis_level_accuracy": 1.0,
        "owner_accuracy": 1.0,
        "cases": [
            {
                "case_id": "file_case_001",
                "run_status": "success",
                "predicted_final_cause_code": "FILE_NOT_RECEIVED",
                "final_diagnosis_correct": False,
            }
        ],
    }
    v1 = {
        "final_diagnosis_accuracy": 0.8,
        "hypothesis_recall": 0.5,
        "diagnosis_level_accuracy": 1.0,
        "owner_accuracy": 1.0,
        "required_tool_recall": 1.0,
        "unnecessary_tool_rate": 0.1,
        "cases": [
            {
                "case_id": "file_case_001",
                "run_status": "success",
                "predicted_final_cause_code": "INVALID_BUSINESS_DATE",
                "selected_tools": ["check_file_status", "validate_parameter"],
                "final_diagnosis_correct": True,
            }
        ],
    }
    md = render_comparison_markdown(
        v0=v0,
        v1=v1,
        ground_truth={
            "file_case_001": {
                "actual_cause_code": "INVALID_BUSINESS_DATE",
                "incident_domain": "FILE",
            }
        },
        model="gpt-4.1",
        notes=[],
    )
    assert "# V0 vs V1 Evaluation" in md
    assert "Final Diagnosis Accuracy | 40.0% | 80.0%" in md
    assert "Required Tool Recall | N/A | 100.0%" in md
    assert "local/mock PoC" in md
    assert "file_case_001 | INVALID_BUSINESS_DATE | FILE_NOT_RECEIVED | INVALID_BUSINESS_DATE" in md
