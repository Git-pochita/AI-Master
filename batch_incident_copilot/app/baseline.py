import json
import re

from app.llm_client import chat_complete
from app.schemas import DiagnosisResult
from config import settings


def load_system_prompt() -> str:
    return settings.PROMPT_PATH.read_text(encoding="utf-8")


def extract_json_object(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM 응답에서 JSON 객체를 찾지 못했습니다.")
    parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LLM 응답 JSON이 객체가 아닙니다.")
    return parsed


def build_user_prompt(log_text: str, case_id: str | None) -> str:
    case_line = f"case_id: {case_id}" if case_id else "case_id: null"
    return (
        "다음 배치 실행 로그만을 근거로 진단하십시오.\n"
        f"{case_line}\n\n"
        "--- LOG START ---\n"
        f"{log_text}\n"
        "--- LOG END ---\n"
    )


def diagnose(log_text: str, case_id: str | None = None) -> DiagnosisResult:
    system_prompt = load_system_prompt()
    user_prompt = build_user_prompt(log_text, case_id)
    raw = chat_complete(system_prompt, user_prompt)
    try:
        payload = extract_json_object(raw)
        result = DiagnosisResult.model_validate(payload)
    except Exception as first_error:
        retry_user = (
            user_prompt
            + "\n이전 응답이 스키마에 맞지 않았습니다. JSON 객체만 다시 출력하십시오.\n"
            + f"오류: {first_error}"
        )
        raw = chat_complete(system_prompt, retry_user)
        payload = extract_json_object(raw)
        result = DiagnosisResult.model_validate(payload)

    if case_id:
        result.case_id = case_id
    return result
