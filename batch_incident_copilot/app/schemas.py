import re
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.cause_codes import validate_cause_code

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
        return validate_cause_code(code)


class ToolResult(BaseModel):
    tool: str
    status: Literal["SUCCESS", "FAILED"]
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class ToolSelection(BaseModel):
    selected_tool: Optional[str] = None
    reason: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("selected_tool", mode="before")
    @classmethod
    def empty_tool_to_none(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"null", "none"}:
            return None
        return text


class StopReason(str, Enum):
    EVIDENCE_SUFFICIENT = "EVIDENCE_SUFFICIENT"
    NO_ACTIONABLE_TOOL = "NO_ACTIONABLE_TOOL"
    MISSING_REQUIRED_ARGUMENTS = "MISSING_REQUIRED_ARGUMENTS"
    MAX_PLANNING_ROUNDS = "MAX_PLANNING_ROUNDS"
    MAX_TOOL_CALLS = "MAX_TOOL_CALLS"
    DUPLICATE_TOOL_CALL_BLOCKED = "DUPLICATE_TOOL_CALL_BLOCKED"


class InvestigationStep(BaseModel):
    goal: str = ""
    candidate_tool: Optional[str] = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    argument_status: Literal["READY", "MISSING_ARGUMENTS"] = "READY"
    related_cause_codes: list[str] = Field(default_factory=list)
    status: Literal[
        "pending",
        "executed",
        "skipped_missing_args",
        "blocked_duplicate",
    ] = "pending"

    @field_validator("candidate_tool", mode="before")
    @classmethod
    def empty_candidate_to_none(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"null", "none"}:
            return None
        return text

    @field_validator("related_cause_codes")
    @classmethod
    def canonical_related_codes(cls, value: list[str]) -> list[str]:
        codes: list[str] = []
        for item in value or []:
            try:
                codes.append(validate_cause_code(str(item).strip()))
            except ValueError:
                continue
        return codes


class HypothesisState(BaseModel):
    cause_code: str
    cause_name: str = ""
    origin: Literal["initial", "planner"] = "initial"
    status: Literal[
        "active",
        "strengthened",
        "weakened",
        "eliminated",
        "adopted",
    ] = "active"
    signals: list[str] = Field(default_factory=list)

    @field_validator("cause_code")
    @classmethod
    def canonical_working_code(cls, value: str) -> str:
        return validate_cause_code(value.strip())


class PlanningRound(BaseModel):
    round_index: int
    goal: str = ""
    investigation_plan: list[InvestigationStep] = Field(default_factory=list)
    hypothesis_states: list[HypothesisState] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    evidence_sufficient: bool = False
    selected_tool: Optional[str] = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    replanned: bool = False
    stop_reason: Optional[StopReason] = None
    tool_result: Optional[ToolResult] = None


class PlannerDecision(BaseModel):
    investigation_plan: list[InvestigationStep] = Field(default_factory=list)
    hypothesis_states: list[HypothesisState] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    evidence_sufficient: bool = False
    selected_tool: Optional[str] = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    stop_reason: Optional[StopReason] = None

    @field_validator("selected_tool", mode="before")
    @classmethod
    def empty_tool_to_none(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"null", "none"}:
            return None
        return text


class V2DiagnosisResult(BaseModel):
    version: Literal["v2"] = "v2"
    case_id: Optional[str] = None
    summary: str = ""
    extracted_info: dict[str, Any] = Field(default_factory=dict)
    initial_hypotheses: list[Hypothesis]
    working_hypotheses: list[HypothesisState] = Field(default_factory=list)
    investigation_plan: list[InvestigationStep] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    current_round: int = 0
    stop_reason: StopReason
    planning_trace: list[PlanningRound] = Field(default_factory=list)
    selected_tools: list[ToolSelection] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    final_cause_code: str
    final_cause_name: str
    diagnosis_level: Literal["추정", "가능성 높음", "확인됨"]
    owner: str
    evidence: list[str]
    limitations: list[str]
    recommended_actions: list[str] = Field(default_factory=list)

    @field_validator("final_cause_code")
    @classmethod
    def final_cause_code_canonical(cls, value: str) -> str:
        code = value.strip()
        if not CAUSE_CODE_PATTERN.fullmatch(code):
            raise ValueError(
                "final_cause_code는 UPPER_SNAKE_CASE여야 합니다. 예: INVALID_BUSINESS_DATE"
            )
        return validate_cause_code(code)


class V1DiagnosisResult(BaseModel):
    case_id: Optional[str] = None
    summary: str = ""
    extracted_info: dict[str, Any] = Field(default_factory=dict)
    initial_hypotheses: list[Hypothesis]
    selected_tools: list[ToolSelection] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    final_cause_code: str
    final_cause_name: str
    diagnosis_level: Literal["추정", "가능성 높음", "확인됨"]
    owner: str
    evidence: list[str]
    limitations: list[str]
    recommended_actions: list[str] = Field(default_factory=list)

    @field_validator("final_cause_code")
    @classmethod
    def final_cause_code_canonical(cls, value: str) -> str:
        code = value.strip()
        if not CAUSE_CODE_PATTERN.fullmatch(code):
            raise ValueError(
                "final_cause_code는 UPPER_SNAKE_CASE여야 합니다. 예: INVALID_BUSINESS_DATE"
            )
        return validate_cause_code(code)


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

    @field_validator("final_cause_code")
    @classmethod
    def final_cause_code_canonical(cls, value: str) -> str:
        code = value.strip()
        if not CAUSE_CODE_PATTERN.fullmatch(code):
            raise ValueError(
                "final_cause_code는 UPPER_SNAKE_CASE여야 합니다. 예: INVALID_BUSINESS_DATE"
            )
        return validate_cause_code(code)

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


AgentComponent = Literal[
    "Perception",
    "Reasoning",
    "Memory",
    "Action",
    "Feedback",
    "Evaluation",
    "Governance",
]


def utc_timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class AgentEvent(BaseModel):
    """관찰 가능한 실행 이벤트. LLM 내부 Chain-of-Thought를 담지 않는다."""

    component: AgentComponent
    step: str
    summary: str
    detail: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=utc_timestamp)
    round: Optional[int] = None
    status: Optional[str] = None
    source: Optional[str] = None


class CriticIssueType(str, Enum):
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    BETTER_SUPPORTED_CAUSE = "BETTER_SUPPORTED_CAUSE"
    FAILED_EVIDENCE_USED = "FAILED_EVIDENCE_USED"
    DIAGNOSIS_LEVEL_TOO_HIGH = "DIAGNOSIS_LEVEL_TOO_HIGH"
    DIAGNOSIS_LEVEL_TOO_LOW = "DIAGNOSIS_LEVEL_TOO_LOW"
    OWNER_MISMATCH = "OWNER_MISMATCH"


class CriticIssue(BaseModel):
    issue_type: CriticIssueType
    description: str
    related_evidence: list[str] = Field(default_factory=list)
    blocking: bool = True


class CriticResult(BaseModel):
    verdict: Literal["PASS", "REVISE"]
    evidence_consistent: bool
    diagnosis_level_appropriate: bool
    owner_consistent: bool
    issues: list[CriticIssue] = Field(default_factory=list)
    recommended_cause_code: Optional[str] = None
    recommended_diagnosis_level: Optional[Literal["추정", "가능성 높음", "확인됨"]] = None
    recommended_owner: Optional[str] = None
    revision_reason: str = ""

    @field_validator("recommended_cause_code")
    @classmethod
    def recommended_cause_canonical(cls, value: Optional[str]) -> Optional[str]:
        if value is None or str(value).strip() == "":
            return None
        return validate_cause_code(value.strip())


class V3DiagnosisResult(BaseModel):
    version: Literal["v3"] = "v3"
    case_id: Optional[str] = None
    summary: str = ""
    extracted_info: dict[str, Any] = Field(default_factory=dict)
    initial_hypotheses: list[Hypothesis]
    working_hypotheses: list[HypothesisState] = Field(default_factory=list)
    investigation_plan: list[InvestigationStep] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    current_round: int = 0
    stop_reason: StopReason
    planning_trace: list[PlanningRound] = Field(default_factory=list)
    selected_tools: list[ToolSelection] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    critic_result: CriticResult
    revised: bool
    original_v2_cause_code: str
    original_v2_diagnosis_level: str
    original_v2_owner: str
    final_cause_code: str
    final_cause_name: str
    diagnosis_level: Literal["추정", "가능성 높음", "확인됨"]
    owner: str
    evidence: list[str]
    limitations: list[str]
    recommended_actions: list[str] = Field(default_factory=list)

    @field_validator("final_cause_code", "original_v2_cause_code")
    @classmethod
    def v3_cause_canonical(cls, value: str) -> str:
        code = value.strip()
        if not CAUSE_CODE_PATTERN.fullmatch(code):
            raise ValueError(
                "cause_code는 UPPER_SNAKE_CASE여야 합니다. 예: INVALID_FILE_PATH"
            )
        return validate_cause_code(code)
