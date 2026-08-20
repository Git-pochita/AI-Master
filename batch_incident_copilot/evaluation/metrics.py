from __future__ import annotations

from typing import Any, Iterable


def selected_tool_names(payload: dict[str, Any] | None) -> list[str]:
    names: list[str] = []
    for item in (payload or {}).get("selected_tools") or []:
        if isinstance(item, dict):
            name = item.get("selected_tool")
        else:
            name = getattr(item, "selected_tool", None)
        if name:
            names.append(str(name))
    return names


def tool_failure_count(payload: dict[str, Any] | None) -> int:
    count = 0
    for item in (payload or {}).get("tool_results") or []:
        status = item.get("status") if isinstance(item, dict) else getattr(item, "status", None)
        if status == "FAILED":
            count += 1
    return count


def required_tool_recall(required: Iterable[str], actual: Iterable[str]) -> float:
    required_list = [name for name in required if name]
    if not required_list:
        return 1.0
    actual_set = set(actual)
    hits = sum(1 for name in required_list if name in actual_set)
    return hits / len(required_list)


def unnecessary_tool_count(required: Iterable[str], actual: Iterable[str]) -> int:
    required_set = set(name for name in required if name)
    return sum(1 for name in actual if name not in required_set)


def unnecessary_tool_rate(required: Iterable[str], actual: Iterable[str]) -> float:
    actual_list = list(actual)
    if not actual_list:
        return 0.0
    return unnecessary_tool_count(required, actual_list) / len(actual_list)


def mean(values: Iterable[float | int | bool]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(float(item) for item in items) / len(items)


def aggregate_case_metrics(version: str, case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(case_rows)
    failed_runs = [row for row in case_rows if row.get("run_status") != "success"]
    evaluated = [row for row in case_rows if row.get("run_status") == "success"]

    def _field(row: dict[str, Any], key: str, default=False):
        if row.get("run_status") != "success":
            return default
        return row.get(key, default)

    summary: dict[str, Any] = {
        "version": version,
        "total_cases": total,
        "evaluated_cases": len(evaluated),
        "failed_runs": len(failed_runs),
        "final_diagnosis_accuracy": mean(
            1.0 if _field(row, "final_diagnosis_correct") else 0.0 for row in case_rows
        ),
        "hypothesis_recall": mean(
            1.0 if _field(row, "hypothesis_recall_hit") else 0.0 for row in case_rows
        ),
        "diagnosis_level_accuracy": mean(
            1.0 if _field(row, "diagnosis_level_correct") else 0.0 for row in case_rows
        ),
        "owner_accuracy": mean(
            1.0 if _field(row, "owner_correct") else 0.0 for row in case_rows
        ),
        "cases": case_rows,
    }
    if version == "v1":
        summary["required_tool_recall"] = mean(
            float(_field(row, "required_tool_recall", 0.0) or 0.0) for row in case_rows
        )
        summary["unnecessary_tool_rate"] = mean(
            float(_field(row, "unnecessary_tool_rate", 0.0) or 0.0) for row in case_rows
        )
        summary["average_tool_calls"] = mean(
            float(_field(row, "tool_call_count", 0) or 0) for row in case_rows
        )
        summary["tool_failure_count"] = sum(
            int(_field(row, "tool_failure_count", 0) or 0) for row in case_rows
        )
    return summary
