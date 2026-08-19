from __future__ import annotations

CAUSE_CODE_GROUPS: dict[str, tuple[str, ...]] = {
    "FILE": (
        "FILE_NOT_RECEIVED",
        "INVALID_FILE_PATH",
        "INVALID_BUSINESS_DATE",
    ),
    "DB": (
        "DB_CREDENTIAL_MISMATCH",
        "DB_ACCOUNT_LOCKED",
        "DB_CONNECTION_CONFIG_ERROR",
    ),
    "SQL": (
        "TABLE_NOT_FOUND",
        "COLUMN_NOT_FOUND",
        "INVALID_SCHEMA",
    ),
    "PARAMETER": (
        "MISSING_REQUIRED_PARAMETER",
        "INVALID_PARAMETER_FORMAT",
        "INVALID_PARAMETER_RANGE",
        "INVALID_BUSINESS_DATE",
    ),
}

CAUSE_CODE_NAMES: dict[str, str] = {
    "FILE_NOT_RECEIVED": "파일 미수신",
    "INVALID_FILE_PATH": "파일 경로 오류",
    "INVALID_BUSINESS_DATE": "실행일자 파라미터 오류",
    "DB_CREDENTIAL_MISMATCH": "DB 인증 정보 불일치",
    "DB_ACCOUNT_LOCKED": "DB 계정 잠김",
    "DB_CONNECTION_CONFIG_ERROR": "DB 접속 설정 오류",
    "TABLE_NOT_FOUND": "테이블 없음",
    "COLUMN_NOT_FOUND": "컬럼 없음",
    "INVALID_SCHEMA": "스키마 오류",
    "MISSING_REQUIRED_PARAMETER": "필수 파라미터 누락",
    "INVALID_PARAMETER_FORMAT": "파라미터 형식 오류",
    "INVALID_PARAMETER_RANGE": "파라미터 범위 오류",
}

CANONICAL_CAUSE_CODES: frozenset[str] = frozenset(
    code for codes in CAUSE_CODE_GROUPS.values() for code in codes
)


def validate_cause_code(value: str) -> str:
    code = (value or "").strip()
    if code not in CANONICAL_CAUSE_CODES:
        allowed = ", ".join(sorted(CANONICAL_CAUSE_CODES))
        raise ValueError(
            "cause_code는 Canonical Cause Code Vocabulary 중 하나여야 합니다. "
            f"허용 값: {allowed}"
        )
    return code


def vocabulary_prompt_block() -> str:
    lines = [
        "cause_code는 반드시 아래 Canonical Cause Code 중 하나만 선택하십시오.",
        "허용되지 않은 새 코드(예: INPUT_FILE_NOT_FOUND)를 만들지 마십시오.",
        "초기 가설에 없던 원인도 Tool Evidence로 발견할 수 있지만, 코드 이름은 아래 목록 안에서만 고르십시오.",
        "",
    ]
    for group, codes in CAUSE_CODE_GROUPS.items():
        lines.append(f"{group}:")
        for code in codes:
            lines.append(f"- {code}: {CAUSE_CODE_NAMES[code]}")
        lines.append("")
    return "\n".join(lines).rstrip()
