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


def save_result(case_id: str, payload: dict, results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"{case_id}.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out_path


def run_diagnosis(version: str, log_text: str, case_id: str):
    if version == "v1":
        from app.tool_use import diagnose_v1

        return diagnose_v1(log_text, case_id=case_id)
    return diagnose(log_text, case_id=case_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch Incident Copilot")
    parser.add_argument("--log", required=True, help="배치 실행 로그 파일 경로")
    parser.add_argument("--case-id", default=None, help="평가/저장용 case_id")
    parser.add_argument(
        "--version",
        choices=["v0", "v1"],
        default="v0",
        help="v0: 단일 LLM baseline, v1: Tool Use",
    )
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
    result = run_diagnosis(args.version, log_text, case_id)
    payload = result.model_dump()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    results_dir = settings.V1_RESULTS_DIR if args.version == "v1" else settings.V0_RESULTS_DIR
    out_path = save_result(case_id, payload, results_dir)
    print(f"saved: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
