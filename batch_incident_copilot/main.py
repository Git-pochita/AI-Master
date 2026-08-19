import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.baseline import diagnose
from app.input_validator import validate_log_path
from app.schemas import ValidationDecision
from config import settings


def resolve_log_path(log_arg: str) -> Path:
    path = Path(log_arg)
    if path.exists():
        return path
    candidate = PROJECT_ROOT / log_arg
    if candidate.exists():
        return candidate
    return path


def save_result(case_id: str, payload: dict) -> Path:
    settings.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = settings.RESULTS_DIR / f"{case_id}.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch Incident Copilot V0 Baseline")
    parser.add_argument("--log", required=True, help="배치 실행 로그 파일 경로")
    parser.add_argument("--case-id", default=None, help="평가/저장용 case_id")
    args = parser.parse_args()

    log_path = resolve_log_path(args.log)
    case_id = args.case_id or log_path.stem

    validation = validate_log_path(log_path)
    if validation.decision == ValidationDecision.ABORT:
        print(
            json.dumps(
                {
                    "case_id": case_id,
                    "validation": validation.model_dump(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    if validation.decision == ValidationDecision.WARN:
        print(
            json.dumps({"validation": validation.model_dump()}, ensure_ascii=False),
            file=sys.stderr,
        )

    log_text = log_path.read_text(encoding="utf-8")
    result = diagnose(log_text, case_id=case_id)
    payload = result.model_dump()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    out_path = save_result(case_id, payload)
    print(f"saved: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
