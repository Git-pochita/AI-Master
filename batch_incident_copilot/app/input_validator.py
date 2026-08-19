from pathlib import Path

from app.schemas import ValidationDecision, ValidationResult

SUPPORTED_EXTENSIONS = {".log", ".txt"}
MIN_LOG_CHARS = 80
MIN_LOG_LINES = 3
ERROR_KEYWORDS = ("ERROR", "FAIL")


def validate_log_path(log_path: str | Path) -> ValidationResult:
    path = Path(log_path)
    suffix = path.suffix.lower()
    if suffix and suffix not in SUPPORTED_EXTENSIONS:
        return ValidationResult(
            decision=ValidationDecision.ABORT,
            reasons=[f"지원하지 않는 확장자입니다: {suffix}"],
        )
    if not suffix:
        return ValidationResult(
            decision=ValidationDecision.ABORT,
            reasons=["지원하지 않는 확장자입니다: 확장자 없음"],
        )
    if not path.exists() or not path.is_file():
        return ValidationResult(
            decision=ValidationDecision.ABORT,
            reasons=[f"읽을 수 없는 입력입니다: 파일이 없거나 파일이 아닙니다 ({path})"],
        )
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return ValidationResult(
            decision=ValidationDecision.ABORT,
            reasons=[f"읽을 수 없는 입력입니다: {exc}"],
        )
    return validate_log_content(content)


def validate_log_content(content: str | None) -> ValidationResult:
    if content is None:
        return ValidationResult(
            decision=ValidationDecision.ABORT,
            reasons=["읽을 수 없는 입력입니다: content가 None입니다."],
        )
    stripped = content.strip()
    if not stripped:
        return ValidationResult(
            decision=ValidationDecision.ABORT,
            reasons=["빈 로그입니다."],
        )

    reasons: list[str] = []
    line_count = len([line for line in stripped.splitlines() if line.strip()])
    if len(stripped) < MIN_LOG_CHARS or line_count < MIN_LOG_LINES:
        reasons.append(
            f"로그가 너무 짧습니다. (chars={len(stripped)}, lines={line_count})"
        )

    upper = stripped.upper()
    if not any(keyword in upper for keyword in ERROR_KEYWORDS):
        reasons.append("ERROR 또는 FAIL 문자열이 없습니다.")

    if reasons:
        return ValidationResult(decision=ValidationDecision.WARN, reasons=reasons)

    return ValidationResult(
        decision=ValidationDecision.PROCEED,
        reasons=["기본적인 장애 분석이 가능한 로그입니다."],
    )
