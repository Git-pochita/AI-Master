import re
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

CAUSE_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*")


class ValidationDecision(str, Enum):
    ABORT = "ABORT"
    WARN = "WARN"
    PROCEED = "PROCEED"


class ValidationResult(BaseModel):
    decision: ValidationDecision
    reasons: list[str] = Field(default_factory=list)


class Hypothesis(BaseModel):
    cause_code: str
    cause_name: str
    evidence: list[str]

    @field_validator("cause_code")
    @classmethod
    def cause_code_upper_snake(cls, value: str) -> str:
        code = value.strip()
        if not CAUSE_CODE_PATTERN.fullmatch(code):
            raise ValueError(
                "cause_code는 영문 대문자/숫자와 underscore로 구분한 "
                "UPPER_SNAKE_CASE여야 합니다. 예: FILE_NOT_RECEIVED"
            )
        return code


class DiagnosisResult(BaseModel):
    case_id: Optional[str] = None
    summary: str
    extracted_info: dict[str, Any] = Field(default_factory=dict)
    hypotheses: list[Hypothesis]
    final_cause_code: str
    final_cause_name: str
    diagnosis_level: Literal["추정", "가능성 높음", "확인됨"]
    owner: str
    recommended_actions: list[str]
    limitations: list[str]

    @model_validator(mode="after")
    def final_cause_must_be_one_of_hypotheses(self) -> "DiagnosisResult":
        if not self.hypotheses:
            raise ValueError("hypotheses는 최소 1개 이상이어야 합니다.")
        matched = next(
            (h for h in self.hypotheses if h.cause_code == self.final_cause_code),
            None,
        )
        if matched is None:
            raise ValueError("final_cause_code는 hypotheses 중 하나여야 합니다.")
        if self.final_cause_name != matched.cause_name:
            self.final_cause_name = matched.cause_name
        return self
