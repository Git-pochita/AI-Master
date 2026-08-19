from app.schemas import ToolResult


def supporting_tool_results(tool_results: list[ToolResult]) -> list[ToolResult]:
    """SUCCESS Tool만 근거로 사용한다. FAILED는 제외한다."""
    return [item for item in tool_results if item.status == "SUCCESS"]


def filter_evidence(evidence: list[str], tool_results: list[ToolResult]) -> list[str]:
    banned = [
        item.error
        for item in tool_results
        if item.status != "SUCCESS" and item.error
    ]
    if not banned:
        return list(evidence)
    return [text for text in evidence if not any(token in text for token in banned)]
