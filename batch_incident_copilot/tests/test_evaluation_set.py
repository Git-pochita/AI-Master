from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.cause_codes import CANONICAL_CAUSE_CODES
from app.tools.registry import HANDLERS
from config import settings
from evaluation.evaluator import load_ground_truth

REQUIRED_FIELDS = {
    "case_id",
    "incident_domain",
    "actual_cause_code",
    "expected_hypothesis_codes",
    "required_tools",
    "expected_diagnosis_level_v0",
    "expected_diagnosis_level_v1",
    "expected_owner",
}

EXPECTED_CASES = {
    "file_case_001",
    "file_case_002",
    "file_case_003",
    "db_case_001",
    "db_case_002",
    "sql_case_001",
    "sql_case_002",
    "param_case_001",
    "param_case_002",
    "param_case_003",
}


def test_ground_truth_has_ten_unique_cases():
    all_gt = load_ground_truth()
    assert len(all_gt) == 10
    assert set(all_gt) == EXPECTED_CASES
    assert len(set(all_gt)) == len(all_gt)


def test_ground_truth_fields_codes_tools_and_logs():
    all_gt = load_ground_truth()
    domains = {}
    for case_id, gt in all_gt.items():
        assert REQUIRED_FIELDS.issubset(gt), case_id
        assert gt["case_id"] == case_id
        assert gt["actual_cause_code"] in CANONICAL_CAUSE_CODES
        for code in gt["expected_hypothesis_codes"]:
            assert code in CANONICAL_CAUSE_CODES
        for tool in gt["required_tools"]:
            assert tool in HANDLERS
        log_path = settings.SAMPLE_LOGS_DIR / f"{case_id}.log"
        assert log_path.is_file(), log_path
        domains[gt["incident_domain"]] = domains.get(gt["incident_domain"], 0) + 1
    assert domains == {"FILE": 3, "DB": 2, "SQL": 2, "PARAMETER": 3}


def test_file_cases_share_surface_but_differ_in_root_cause():
    all_gt = load_ground_truth()
    assert all_gt["file_case_001"]["actual_cause_code"] == "INVALID_BUSINESS_DATE"
    assert all_gt["file_case_002"]["actual_cause_code"] == "FILE_NOT_RECEIVED"
    assert all_gt["file_case_003"]["actual_cause_code"] == "INVALID_FILE_PATH"
    assert all_gt["file_case_002"]["required_tools"] == ["check_file_status"]
    assert all_gt["file_case_003"]["required_tools"] == ["check_file_status"]
