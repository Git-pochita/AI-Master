from pathlib import Path

from dotenv import load_dotenv
import os

PROJECT_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(PROJECT_ROOT / ".env")

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "https://skax.ai-talentlab.com")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
AZURE_OPENAI_MODEL = os.getenv("AZURE_OPENAI_MODEL", "gpt-4.1")

PROMPT_PATH = PROJECT_ROOT / "prompts" / "v0_system_prompt.txt"
V1_TOOL_SELECT_PROMPT_PATH = PROJECT_ROOT / "prompts" / "v1_tool_select_prompt.txt"
V1_FINAL_PROMPT_PATH = PROJECT_ROOT / "prompts" / "v1_final_diagnosis_prompt.txt"
RESULTS_DIR = PROJECT_ROOT / "results" / "v0_baseline"
V0_RESULTS_DIR = RESULTS_DIR
V1_RESULTS_DIR = PROJECT_ROOT / "results" / "v1_tool_use"
GROUND_TRUTH_PATH = PROJECT_ROOT / "evaluation" / "ground_truth.json"


def require_api_key() -> str:
    if not AZURE_OPENAI_API_KEY or AZURE_OPENAI_API_KEY == "사용자가_직접_입력":
        raise RuntimeError(
            "AZURE_OPENAI_API_KEY가 설정되지 않았습니다. "
            f"{PROJECT_ROOT / '.env'} 파일을 만들고 .env.example을 참고하십시오."
        )
    return AZURE_OPENAI_API_KEY
