# V3 Critic / Reflection 설계

상태: **설계만**. 이 문서 작성 시점에 V3 코드, V2 코드, Prompt, Ground Truth, evaluator는 수정하지 않는다.

기준: 최신 `main` (`b769456` Merge PR #14 Agent Event Log 이후)  
V2 동결. V3 구현은 이 문서 합의 후 별도 PR에서 시작한다.

관련 문서:

- V2 설계: [`v2_dynamic_planning_design.md`](v2_dynamic_planning_design.md)
- V2 handoff: [`next_steps_v2.md`](next_steps_v2.md)
- AgentEvent: [`agent_event_log.md`](agent_event_log.md)
- V2 refined 공식 리포트: `evaluation/reports/v1_vs_v2_refined.md`, `v2_refined_summary.json`

---

## 1. V3 목적

V3의 역할은 **새로운 조사 Planning이 아니다.**

V2가 이미 수집한 SUCCESS Tool evidence와 최종 진단이 서로 맞는지 검증하고, 불일치가 있을 때만 최종 진단을 한 번 교정한다.

한 줄:

> Producer(`diagnose_v2`)가 조사한 결과를 Critic이 evidence 기준으로 검증하고, REVISE일 때만 Reflection/Revision이 최종 diagnosis를 교정한다.

하지 않는 것:

- Planner / Re-plan 루프를 다시 돌리지 않음
- 추가 Tool 실행을 원칙적으로 하지 않음
- F-02/F-04 `case_id` 분기, GT를 runtime prompt에 넣기, `same_directory_files` → `INVALID_FILE_PATH` 하드코딩
- V2 Prompt / `has_parameter_anomaly_signal()` / evaluator / GT 변경

V2가 푼 문제(F-05: 조사 부족 → Re-plan으로 `validate_parameter` 추가)와 V3가 푸는 문제(F-02/F-04: 조사는 충분, 최종 원인 선택이 표면 증상에 고정)는 다르다.

---

## 2. V2 한계 (실측)

### 2.1 동결된 V2 공식 지표

출처: `evaluation/reports/v1_vs_v2_refined.md`, `v2_refined_summary.json`. 모델 Azure OpenAI `gpt-4.1`.

| Metric | V2 refined |
| --- | --- |
| Final Diagnosis Accuracy | 93.3% (28/30) |
| Hypothesis Recall | 86.7% (`initial_hypotheses` 기준, V2 Planning KPI 아님) |
| Diagnosis Level Accuracy | 100% |
| Owner Accuracy | 100% |
| Required Tool Recall | 98.3% |
| Unnecessary Tool Rate | 6.7% |
| failed_runs | 0 |

V2 오답은 **F-02, F-04** 두 건뿐이다. 둘 다 GT `INVALID_FILE_PATH`, V2 예측 `FILE_NOT_RECEIVED`. Tool Recall은 둘 다 1.0 (`check_file_status`만, refined).

### 2.2 V2 실행 구조 (재사용 대상)

코드 근거: `app/planning.py` `diagnose_v2()`, `app/tool_use.py` `finalize_diagnosis()`, `app/tools/evidence.py`.

```text
diagnose_v2(log)
  → V0 diagnose()            # extracted_info + initial_hypotheses 동결
  → Planner 루프             # plan → tool → sufficiency → 필요 시 re-plan
  → execute_tool()           # 기존 4개 mock Tool
  → finalize_diagnosis()     # V1 최종 진단기 재사용
  → filter_evidence()        # FAILED error 문자열 제거
  → apply_diagnosis_level_policy()  # SUCCESS 없으면 확인됨 금지
  → V2DiagnosisResult
```

V3는 이 파이프라인 **앞단을 바꾸지 않고** `V2DiagnosisResult`를 입력으로 받는다.

### 2.3 실패 원인 분류

| case | GT | V1 | V2 1차 | V2 refined | Tool (refined) | 실패 층 |
| --- | --- | --- | --- | --- | --- | --- |
| F-02 | INVALID_FILE_PATH | 정답 | 오답 | 오답 | check_file_status | finalizer evidence 해석 |
| F-04 | INVALID_FILE_PATH | 오답 | 오답 | 오답 | check_file_status | finalizer evidence 해석 |
| F-05 | INVALID_BUSINESS_DATE | 오답 | 정답 | 정답 | file + validate_parameter | V2가 해결. V3에서 재조사하지 않음 |

근거: `v1_vs_v2_refined.md` 케이스표, `results/v2_planning/F-02.json`, `F-04.json`.

공통점:

- `check_file_status` **SUCCESS**
- 대상 경로 `exists=false`, `received=false`
- `same_directory_files`에 **이름이 매우 유사한 파일이 exists=true / received=true**
- `initial_hypotheses`에 이미 `INVALID_FILE_PATH`가 있음 (Hypothesis Recall hit)
- Planner working hypothesis / round-2 reason에도 경로 오타 가능성이 적혀 있음
- 그런데 `finalize_diagnosis()`는 `FILE_NOT_RECEIVED` / `확인됨`을 선택

즉 Planning 실패가 아니라 **이미 있는 SUCCESS 필드를 최종 원인 선택에 쓰지 못한 것**이다. V2 설계 문서 5절도 이 해석을 V3로 명시적으로 미뤄 두었다.

### 2.4 F-02 실측 (저장 결과)

출처: `data/sample_logs/F-02.log`, `evaluation/ground_truth.json` F-02, `results/v2_planning/F-02.json`.

- 로그 경로: `/data/in/sale_20260901.csv` (오타형), `business_date=20260901`, `FileNotFoundError`
- extracted_info: `job_name=DAILY_SALES_LOAD`, `input_path=/data/in/sale_20260901.csv`, `return_code=12`
- Tool: `check_file_status` 1회 SUCCESS
- 대상: `exists=false`, `received=false`, `filename=sale_20260901.csv`
- 같은 디렉터리: `sales_20260901.csv`는 `exists=true`, `received=true` (size 204800)
- V2 final: `FILE_NOT_RECEIVED` / `확인됨` / `BATCH_OPERATION`
- evidence에 sibling 존재 사실도 적혀 있으나 최종 코드는 미수신
- GT notes: “로그 경로는 없고, 같은 디렉터리의 `sales_20260901.csv`는 존재한다.”

V1은 같은 Tool만으로 `INVALID_FILE_PATH` 정답. V2 refined는 extra `validate_parameter`를 제거했지만 최종 코드는 그대로 오답. **회귀는 조사량이 아니라 finalizer 선택.**

### 2.5 F-04 실측 (저장 결과)

출처: `data/sample_logs/F-04.log`, GT F-04, `results/v2_planning/F-04.json`.

- 로그 경로: `/data/in/partner/partnr_20260901.csv`, `JOB=DAILY_PARTNER_LOAD`
- Tool: `check_file_status` SUCCESS, 대상 `exists=false`
- sibling: `partner_20260901.csv` `exists=true`, `received=true`
- V2 `planning_trace` round 2의 planner `reason`은 경로 오타 가능성을 **강하게 시사**한다고 적음. 이 문장은 **설계/발표 분석용**이다. Critic runtime 입력에는 planner `reason`을 넣지 않는다 (5.3절).
- V2 final은 그래도 `FILE_NOT_RECEIVED`
- V1도 동일 오답. V3의 대표 target

### 2.6 대조: V2가 맞춘 FILE 케이스 (Critic이 건드리면 안 되는 형태)

`results/v2_planning/F-01.json`, `F-03.json`:

- F-01: 대상 `orders_20260901.csv` 미존재. sibling `orders_20260831.csv`도 미수신. **전일 파일이지 오타 후보가 아님.** V2 `FILE_NOT_RECEIVED` 정답.
- F-03: 대상 `payments_20260901.csv` 미존재. `same_directory_files`에 수신된 유사 파일 없음. V2 `FILE_NOT_RECEIVED` 정답.

따라서 Critic 규칙은 “디렉터리에 다른 파일이 있으면 무조건 `INVALID_FILE_PATH`”가 되어서는 안 된다. 그 규칙은 F-01/F-03 regression을 만든다.

---

## 3. Producer-Critic 구조

```text
diagnose_v3(log)
    │
    ▼
diagnose_v2(log)          # Producer. V2 동결. 재구현하지 않음
    │
    ▼
V2DiagnosisResult
    │
    ▼
Critic (1회)              # SUCCESS evidence ↔ final diagnosis
    │
    ├─ PASS ──────────────► V3DiagnosisResult (V2 최종 필드 그대로)
    │
    └─ REVISE
         │
         ▼
    Reflection / Revision (1회)
         │                  # 추가 Tool 없음. FAILED error 제외
         ▼
    V3DiagnosisResult
```

| 역할 | 구현 위치 (제안) | 책임 |
| --- | --- | --- |
| Producer | 기존 `diagnose_v2()` | 조사 계획, Tool 실행, V2 최종 진단 |
| Critic | 신규 `app/critic.py` (제안) | 구조화 검증. 조사 재실행 없음 |
| Reflection / Revision | 신규 `diagnose_v3()` 내부 1회 | Critic 이슈를 보고 최종 diagnosis만 재작성 |
| Observability | 기존 `build_agent_events()` 확장 | Feedback / Evaluation 이벤트 |

CLI는 `--version v3`를 추가하는 방향. `diagnose_v1()` / `diagnose_v2()` 계약은 유지.

추가 Tool이 필요하다고 Critic이 판단하더라도 **이번 PoC는 limitation으로 남긴다.** 조사를 다시 시작하지 않는다.

---

## 4. Critic 검증 항목

기본값: **PASS**. REVISE는 아래 blocking issue가 있을 때만.

### A. Evidence ↔ Diagnosis Consistency (`EVIDENCE_CONFLICT`)

질문: 현재 `final_cause_code`가 **모든 SUCCESS Tool 필드**를 설명하는가?

설명하지 못하는 SUCCESS 필드가 있으면 conflict다.

FILE 예 (일반 원칙, case_id 없음):

- 대상 경로 `exists=false` / `received=false` 만으로는 `FILE_NOT_RECEIVED`와 `INVALID_FILE_PATH`가 둘 다 가능하다. **이것만으로 REVISE하지 않는다.**
- 같은 디렉터리에 **대상과 이름이 매우 유사하고 received=true인 파일**이 있으면, “파일이 안 왔다”는 설명은 sibling 수신 사실을 남긴다. `INVALID_FILE_PATH`(경로/파일명 오설정)가 두 사실을 함께 설명하는지 검토한다.

DB/SQL/PARAMETER도 동일 질문이다. 예: `account_locked=false`인데 `DB_ACCOUNT_LOCKED`로 확정하면 conflict.

금지:

- `if same_directory_files: INVALID_FILE_PATH`
- F-02/F-04 문자열 매칭
- GT `actual_cause_code`를 Critic 입력에 넣기

### B. Alternative Cause Check (`BETTER_SUPPORTED_CAUSE`)

질문: canonical vocabulary 안의 **다른 코드**가 현재 코드보다 SUCCESS evidence를 더 잘 설명하는가?

제약:

- 후보 집합 = `app/cause_codes.py` `CANONICAL_CAUSE_CODES` only
- 새 코드 생성 금지. `validate_cause_code()`로 검증
- 동점이면 **Producer(V2) 유지 = PASS**. 애매하면 고치지 않는 것이 regression 방지의 핵심
- 대안이 초기 가설에 없어도 된다 (V1/V2 finalizer와 동일). 다만 SUCCESS 필드로 뒷받침해야 한다

A만 있거나 B만 있으면 **cause_code를 바꾸지 않는다.** cause 변경은 아래 Cause Revision Gate를 모두 통과할 때만 허용한다.

### Cause Revision Gate

목적: **Unnecessary Revision Rate와 V2 정답 28건 regression을 최소화**하는 것. 이 gate에 case_id를 넣지 않는다.

최종 `cause_code` 변경은 아래를 **모두** 만족할 때만 허용한다.

1. `EVIDENCE_CONFLICT` 존재 — 현재 V2 final cause가 하나 이상의 중요한 SUCCESS evidence를 설명하지 못함
2. `BETTER_SUPPORTED_CAUSE` 존재 — canonical cause vocabulary 안의 다른 cause가 그 conflict를 더 잘 설명함
3. 대안 cause는 `validate_cause_code()`를 통과한 canonical code
4. 대안 cause를 지지하는 근거는 SUCCESS Tool evidence, 또는 original log / `extracted_info`의 관찰 가능한 사실이어야 함
5. 현재 cause와 대안 cause의 근거가 동점 또는 애매하면 V2 유지 = PASS

```text
EVIDENCE_CONFLICT only
→ cause 변경 금지
→ 필요하면 diagnosis level 하향 또는 limitation 추가

BETTER_SUPPORTED_CAUSE only
→ 현재 cause와 명확한 conflict가 없으면 PASS

EVIDENCE_CONFLICT
+ BETTER_SUPPORTED_CAUSE
+ canonical alternative
+ SUCCESS evidence support
→ cause revision 허용
```

`verdict=REVISE`가 나와도 gate를 못 통과하면 Revision은 cause를 바꾸지 않는다. level/`limitations`만 손볼 수 있다.

### C. FAILED Tool Evidence Guard (`FAILED_EVIDENCE_USED`)

`status=FAILED`의 `error`가 `evidence[]`에 들어 있으면 blocking.

재사용:

- `supporting_tool_results()` — SUCCESS만
- `filter_evidence()` — error 토큰 제거

FAILED는 `limitations`와 AgentEvent Governance로만 남긴다. root cause supporting evidence로 쓰지 않는다.

V2는 이미 이 가드를 finalizer 뒤에 적용한다. Critic은 **Revision 출력에도 재적용**하고, 우회가 있으면 REVISE한다.

### D. Diagnosis Level Calibration

허용값: `추정` | `가능성 높음` | `확인됨` (기존 schema와 동일).

재사용: `apply_diagnosis_level_policy()` (`app/tool_use.py`).

| 상황 | 기대 |
| --- | --- |
| SUCCESS Tool이 원인을 직접 입증 | `확인됨` 가능 |
| 간접 evidence만 | `가능성 높음` 또는 `추정` |
| SUCCESS 없음 / FAILED만 / NOT_CALLABLE | `확인됨` 금지 → 정책이 `추정`으로 cap |

issue:

- `DIAGNOSIS_LEVEL_TOO_HIGH` — 예: SUCCESS 없이 확인됨 (정책이 이미 막지만 Revision 후 재검사)
- `DIAGNOSIS_LEVEL_TOO_LOW` — 강한 SUCCESS가 있는데 추정. **보수적으로 다룬다.** V2 level accuracy 100%를 깨지 않기 위해, TOO_LOW만으로 cause를 바꾸지 말고 level만 권고. 구현 시 TOO_LOW는 기본적으로 non-blocking 후보로 두고, PoC 1차에서는 TOO_HIGH와 FAILED만 확정 blocking으로 해도 된다.

F-02/F-04의 `확인됨` 자체는 GT `expected_diagnosis_level_v1=확인됨`과 같다. 문제는 level이 아니라 cause다.

### E. Owner Consistency (`OWNER_MISMATCH`)

현재 V2 Owner Accuracy 100%. 공식 prompt는 배치 잡 실행 이슈에 `BATCH_OPERATION`을 쓴다 (`prompts/v1_final_diagnosis_prompt.txt` 원칙 9, V0 system prompt).

Critic 원칙:

- owner가 비었거나 확연히 이상한 값일 때만 issue
- F-02/F-04처럼 cause만 틀린 케이스에서 owner를 바꾸지 않음
- `recommended_owner` 기본값 `null`
- **불필요한 owner 수정 금지**

---

## 5. Structured Output

자유 텍스트 Critic 금지. Pydantic structured output.

기존 schema와의 관계:

- `StopReason`을 Critic verdict에 재사용하지 않음 (V2 조사 종료 이유와 다름)
- `V2DiagnosisResult`에 critic 필드를 넣지 않음 (V2 API 유지)
- `final_cause_code`와 같이 `validate_cause_code()` 적용
- `diagnosis_level` Literal은 V1/V2와 동일
- AgentEvent `source`는 구현 시 `"v3"` 추가. 지금은 enum이 문자열이므로 스키마 충돌 없음

### 5.1 제안 모델

설계 예시일 뿐, 이 문서에서 Python을 구현하지 않는다. list 필드는 mutable default(`= []`)를 쓰지 않고 `Field(default_factory=list)`를 쓴다.

```python
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CriticIssueType(str, Enum):
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    BETTER_SUPPORTED_CAUSE = "BETTER_SUPPORTED_CAUSE"
    FAILED_EVIDENCE_USED = "FAILED_EVIDENCE_USED"
    DIAGNOSIS_LEVEL_TOO_HIGH = "DIAGNOSIS_LEVEL_TOO_HIGH"
    DIAGNOSIS_LEVEL_TOO_LOW = "DIAGNOSIS_LEVEL_TOO_LOW"
    OWNER_MISMATCH = "OWNER_MISMATCH"


class CriticIssue(BaseModel):
    issue_type: CriticIssueType
    description: str  # 관찰 가능한 불일치. private CoT 금지
    related_evidence: list[str] = Field(default_factory=list)
    blocking: bool = True


class CriticResult(BaseModel):
    verdict: Literal["PASS", "REVISE"]
    evidence_consistent: bool
    diagnosis_level_appropriate: bool
    owner_consistent: bool
    issues: list[CriticIssue] = Field(default_factory=list)
    recommended_cause_code: Optional[str] = None  # canonical only
    recommended_diagnosis_level: Optional[
        Literal["추정", "가능성 높음", "확인됨"]
    ] = None
    recommended_owner: Optional[str] = None  # 기본 None
    revision_reason: str = ""  # 짧은 상태 전환 문장. LLM 사고 전문 아님
```

조정안:

1. `recommended_cause_code`는 있으면 `validate_cause_code()`. Cause Revision Gate를 통과하지 못하면 권고가 있어도 Revision은 cause를 유지한다.
2. `blocking=False` issue는 PASS를 깨지 않음 (TOO_LOW, owner 메모용). FAILED / TOO_HIGH 등 blocking issue가 있으면 verdict=REVISE일 수 있다. **cause 변경은 verdict와 별개로 Cause Revision Gate를 통과해야 한다.**
3. PASS이면 `recommended_*`는 null. 권고를 조용히 실어 보내면 Revision이 유혹된다.
4. `revision_reason` / `description`에 `selected_tools[].reason`, planner `reason`/`goal`, 진단 `summary`를 복사하지 않음 (AgentEvent CoT 정책과 동일).

### 5.2 Hybrid 검증 (권장)

전부 LLM에만 맡기지 않는다. Unnecessary Revision을 줄이기 위함.

| 검사 | 방식 |
| --- | --- |
| C FAILED evidence | 결정적. `filter_evidence` / error 토큰 |
| D level cap | 결정적. `apply_diagnosis_level_policy` |
| E owner 공란 | 결정적. 비어 있으면 issue, 그 외 기본 PASS |
| A/B evidence vs alternative | LLM structured Critic. 입력은 5.3 allowlist만. **GT 없음. case_id 없음. planner rationale 없음.** |

### 5.3 Critic runtime 입력 (allowlist / denylist)

Critic은 Producer의 판단을 따라가는 두 번째 LLM이 아니라, **동일한 관찰 가능한 evidence를 독립적으로 재검증**하는 역할이어야 한다. Planner rationale를 입력하면 confirmation bias가 생길 수 있으므로 제외한다.

분석/발표 문서에서 “Planner도 오타 가능성을 인지했다”고 **설명하는 것**은 허용한다. 그 텍스트를 Critic runtime 입력에 넣는 것과는 구분한다.

**허용 (allowlist):**

- original log
- `extracted_info`
- SUCCESS tool results / normalized evidence (`supporting_tool_results()`)
- V2 `final_cause_code`
- V2 `diagnosis_level`
- V2 `owner`
- V2 filtered `evidence` (`filter_evidence()` 이후)
- canonical cause vocabulary (`app/cause_codes.py`)

**금지 (denylist):**

- ground truth
- `case_id`
- `planning_trace[].reason`
- planner `goal`
- planner 자유서술 rationale
- `selected_tools[].reason`
- LLM 내부 Chain-of-Thought
- 기존 Agent의 자유서술 판단을 그대로 복사한 텍스트 (진단 `summary` 전문, unresolved_questions의 자유 서술 등)

---

## 6. Revision / Reflection 정책

이 프로젝트에서 Reflection의 정의:

> V2 결과와 Critic 피드백을 비교해, 어떤 최종 진단 필드를 수정해야 하는지 재검토하고 structured diagnosis를 한 번 교정하는 단계.

추상적 self-talk 루프가 아니다.

### 6.1 횟수

- Critic 1회
- Revision 1회
- 그 다음 재Critic 없음 (무한 루프 금지)

### 6.2 PASS

V3 최종 필드 = V2 최종 필드.

- `revised=false`
- `original_v2_cause_code = v2.final_cause_code`
- `critic_result.verdict=PASS`
- planning_trace / tool_results는 V2 그대로

### 6.3 REVISE

Revision 입력:

- original log
- extracted_info
- SUCCESS Tool results만 (`supporting_tool_results`)
- V2 final cause / level / owner / evidence / limitations
- Critic issues (type + related_evidence)

Revision 출력: V1 `FinalDraft`와 같은 최종 진단 필드.

원칙:

- Critic `recommended_cause_code`를 **무조건 채택하지 않음**
- **cause_code 변경은 Cause Revision Gate를 모두 통과한 경우에만** (`EVIDENCE_CONFLICT` + `BETTER_SUPPORTED_CAUSE` + canonical alternative + SUCCESS/관찰 가능 근거). 한쪽 issue만으로는 cause를 바꾸지 않음
- 동점/애매하면 V2 cause 유지
- FAILED error는 supporting evidence 제외 (`filter_evidence` 재적용)
- `apply_diagnosis_level_policy` 재적용
- canonical cause만
- 추가 Tool 없음
- 확신이 안 되면 **V2 cause를 유지**하고 limitation에 Critic 이슈를 남김. `revised=false`가 될 수 있음
- Revision 입력에도 planner `reason` / `goal` / `selected_tools[].reason`을 넣지 않음 (5.3과 동일)

`revised=true` 조건: `final_cause_code` 또는 `diagnosis_level`이 V2와 달라졌을 때. owner만 바꾼 것은 권장하지 않으며, 바꾸더라도 KPI에서 별도 표시.

### 6.4 Prompt 재사용

- 조사/Plan: `v2_planning_prompt.txt` **수정하지 않음**
- V2 finalizer: `v1_final_diagnosis_prompt.txt` **수정하지 않음** (V2 동결)
- 신규: `prompts/v3_critic_prompt.txt`, `prompts/v3_revision_prompt.txt` (구현 단계)

Revision prompt는 “Critic 권고를 복사하라”가 아니라 “SUCCESS 필드가 현재 cause와 충돌하는지 다시 고르라”여야 한다.

---

## 7. V3 state / result schema

`V2DiagnosisResult`는 그대로 둔다. V3는 별도 모델.

```python
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
    stop_reason: StopReason          # Producer(V2) 값 그대로
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
```

선택: 디버깅용 `v2_result: V2DiagnosisResult` 임베드는 CLI JSON이 커진다. PoC는 `original_v2_*` 스칼라 + 동일 planning/tool 필드로 충분. 전체 V2 dump가 필요하면 `results/`에 v2와 v3를 따로 저장.

구현 시 `run_diagnosis("v3")`만 `V3DiagnosisResult`를 반환. evaluator의 `evaluate_payload()`는 기존처럼 `final_cause_code` / `selected_tools` / `initial_hypotheses`를 읽으면 된다. **기존 metric 공식은 변경하지 않음.** Critic KPI는 v3 전용 리포트에만 추가.

---

## 8. AgentEvent mapping

기존 adapter `build_agent_events()`를 확장한다. V0/V1/V2 이벤트는 유지. V3는 V2 이벤트 뒤에 Feedback/Evaluation을 붙인다.

private CoT 비노출 정책은 [`agent_event_log.md`](agent_event_log.md)와 동일. issue type / verdict / 변경된 cause만.

| 조건 | component | step | summary 예 | metadata |
| --- | --- | --- | --- | --- |
| 항상 | Feedback | critic_check | 최종 진단과 수집된 evidence의 일치 여부를 검증했습니다. | verdict, issue_types, issue_count |
| 항상 | Evaluation | evidence_consistency | evidence 일관성 검사 결과를 기록했습니다. | verdict, evidence_consistent, issue_count |
| verdict=REVISE | Feedback | revision_requested | Critic이 최종 진단 재검토를 요청했습니다. | recommended_cause_code (있으면) |
| Revision 수행 | Feedback | reflection | V2 진단과 Critic 이슈를 비교해 최종 진단을 재검토했습니다. | revised |
| cause 또는 level 변경 | Reasoning | final_revision | 최종 원인을 교정했습니다. | original, next, diagnosis_level |
| PASS | (revision_requested / reflection / final_revision 없음) | | | |

빈 Feedback 이벤트를 V0/V1/V2에 만들지 않는 정책은 유지. `source="v3"`.

`Governance / human_review_requested`는 이번 PoC out of scope (HITL 없음).

---

## 9. F-02 / F-04에 설계가 일반 원칙으로 적용되는 방식

런타임에 case_id/GT를 쓰지 않는다. 아래는 **설계 검증용 설명**이다.

### 9.1 공통 evidence 패턴

두 케이스 모두:

1. 대상 파일 SUCCESS: missing
2. sibling SUCCESS: 유사 이름 + received=true
3. V2 cause `FILE_NOT_RECEIVED`는 1을 설명하고 2를 설명하지 못함
4. canonical 대안 `INVALID_FILE_PATH`는 1+2를 함께 설명
5. 다른 canonical(예: `INVALID_BUSINESS_DATE`)은 이 FILE evidence를 더 잘 설명하지 않음 (F-02/F-04는 날짜 불일치 signal 없음. refined도 extra param tool 없음)

→ Cause Revision Gate: `EVIDENCE_CONFLICT` **그리고** `BETTER_SUPPORTED_CAUSE` + canonical 대안 + SUCCESS 근거 → cause revision 허용  
→ Revision이 SUCCESS sibling 필드를 반영하면 `INVALID_FILE_PATH` 후보  
→ 이 설명은 설계 검증용이다. runtime gate에 case_id를 넣지 않는다.

### 9.2 왜 F-01/F-03은 PASS여야 하는가

- F-01 sibling은 **전일 파일**이고 그것조차 미수신. 오타 후보가 아님. 현재 cause가 남은 SUCCESS 필드를 모순 없이 설명.
- F-03은 수신된 유사 파일이 없음. missing target만 있음.

애매하면 V2 유지. 이것이 Unnecessary Revision Rate 방어다.

### 9.3 하드코딩하면 안 되는 것

```text
# 금지
if case_id in {"F-02", "F-04"}: return INVALID_FILE_PATH
if same_directory_files: return INVALID_FILE_PATH
if "sale_" in path: ...
```

허용되는 일반 질문:

- 현재 cause가 설명하지 못하는 SUCCESS 필드가 있는가?
- 그 필드를 더 잘 설명하는 canonical cause가 있는가?
- 동점이면 V2를 유지하는가?

---

## 10. 테스트 전략

구현 전 정의. LLM live 없이 fixture 우선. 저장 결과 `results/v2_planning/F-02.json` 등을 deterministic 입력으로 쓸 수 있다.

1. V2 정답 + 강한 일치 evidence (예: F-01/F-03 형태, 또는 P-01 `is_valid=false`) → Critic PASS, 필드 불변
2. conflicting SUCCESS + 더 잘 설명하는 canonical 대안이 **동시에** 있는 형태 → Cause Revision Gate 통과, cause 변경 허용. `EVIDENCE_CONFLICT`만 있거나 `BETTER_SUPPORTED_CAUSE`만 있으면 cause 변경 금지
2b. Critic 입력 fixture에 `planning_trace[].reason` / `selected_tools[].reason` / `case_id` / GT가 없음을 검증
3. FAILED Tool만 → 확인됨 금지 (`apply_diagnosis_level_policy`)
4. FAILED error 문자열이 evidence에 있으면 `FAILED_EVIDENCE_USED`, Revision 후 evidence에서 제거
5. SUCCESS 없이 확인됨 → TOO_HIGH / cap
6. 적절한 level → PASS (level만 트집 금지)
7. owner `BATCH_OPERATION` + 배치 실패 → owner 수정 없음
8. `recommended_cause_code="NOT_A_CODE"` 거부 (`validate_cause_code`)
9. PASS → V3 final == V2 final, `revised=false`
10. REVISE → Revision 함수 1회만 (mock counter)
11. Critic 후 재Critic 호출 없음. 루프 상한 상수
12. AgentEvent: critic_check, evidence_consistency; REVISE 시 revision_requested / reflection; 변경 시 final_revision
13. 이벤트/CriticResult에 planner reason, chain_of_thought 필드 없음
14. `diagnose_v2()` 기존 `tests/test_v2.py` 전부 유지. V3 모듈이 planning.py를 수정하지 않음

평가기: 기존 108+ AgentEvent 테스트는 깨지지 않아야 한다. V3 테스트는 신규 파일.

---

## 11. 평가 KPI

공식 30건 GT는 고정. V0/V1/V2 리포트는 덮어쓰지 않음. V3는 `v3_summary.json`, `v2_vs_v3.md` 같은 **새 파일**만.

### 11.1 최소 목표

| KPI | V2 refined | V3 목표 |
| --- | --- | --- |
| F-02 final cause | 오답 | 개선 (INVALID_FILE_PATH) |
| F-04 final cause | 오답 | 개선 (INVALID_FILE_PATH) |
| V2 정답 28건 | 정답 | **신규 cause regression 0** |
| Final Diagnosis Accuracy | 93.3% (28/30) | 최소 **96.7% (29/30)** 후보. 이상적 100% (30/30) |
| Diagnosis Level Accuracy | 100% | >= 100% 유지 |
| Owner Accuracy | 100% | >= 100% 유지 |
| FAILED evidence misuse | (V2 가드) | **0** |
| failed_runs | 0 | 0 |
| Required Tool Recall | 98.3% | V2와 동일 (추가 Tool 없음) |
| Unnecessary Tool Rate | 6.7% | V2와 동일 (추가 Tool 없음) |

96.7%는 F-02/F-04 중 1건만 고쳐도 도달한다. 둘 다 고치면 100%. 최소 목표를 96.7%로 두는 이유는 Critic이 28건을 건드리다 실패하는 것을 막기 위함이다. **28건 보호가 F-04 1건보다 우선이다.**

### 11.2 Critic 전용 지표 (중요)

기존 `evaluate_payload()` 공식을 바꾸지 않고 v3 리포트에만 추가.

V2 정답 여부: 해당 케이스 GT vs `original_v2_cause_code` (같은 30건, V2 refined 리포트와 교차 확인).

**Unnecessary Revision Rate** (핵심):

```text
U = (V2 final cause가 GT와 일치인데 V3가 cause를 바꾼 건수)
  / (V2 final cause가 GT와 일치한 건수)
```

목표: **U = 0**. 허용 상한 후보는 <= 1/28. 0이 아니면 V3 accuracy가 제자리이거나 하락할 수 있다.

**Critic Revision Precision**:

```text
P = (Critic verdict=REVISE 이고, V3 cause가 GT와 일치하며, V2 cause는 GT와 불일치한 건수)
  / (verdict=REVISE 건수)
```

REVISE를 남발하면 P가 떨어진다. PASS가 기본이어야 P와 U가 동시에 좋아진다.

보조:

- Revision Adoption Rate: REVISE 중 `revised=true` 비율. Critic이 REVISE했는데 Revision이 항상 무시하면 Critic이 무의미. 반대로 항상 채택하면 U가 오른다.
- Owner change count: 목표 0
- Extra tool calls vs V2: 목표 0

---

## 12. Out of Scope

이번 설계와 이후 첫 V3 구현 PR 모두에서 제외:

- 이 문서 단계의 V3 코드 구현
- V2 `planning.py` / `v2_planning_prompt.txt` / `has_parameter_anomaly_signal()` 수정
- F-02/F-04 하드코딩, GT 수정, evaluator 공식 변경
- 공식 V0/V1/V2 리포트 재실행·덮어쓰기
- RAG / CRAG / ToT
- LangGraph로 실행 그래프 교체
- HITL / `human_review_requested`
- Multi-agent, 장기 Memory
- Critic 무한 루프, Re-plan + Critic 혼합 조사

---

## 13. 구현 단계 제안

코드는 다음 PR에서. 순서를 지키면 V2 regression을 빨리 발견한다.

1. **Schema만**: `CriticIssue`, `CriticResult`, `V3DiagnosisResult`. 단위 테스트(canonical validation, PASS 기본값).
2. **결정적 Critic 가드**: FAILED evidence, diagnosis_level cap, owner 공란. LLM 없음.
3. **LLM Critic A/B**: structured output. 5.3 allowlist만 입력. Cause Revision Gate(A+B 동시) 없이 cause를 바꾸지 않음. F-01/F-03 형태 PASS.
4. **Revision 1회**: V2 prompt 미수정. 신규 revision prompt. 무조건 채택 금지 + filter_evidence 재적용.
5. **`diagnose_v3()` + CLI `--version v3`**: 내부에서 `diagnose_v2()` 호출만.
6. **AgentEvent v3 steps** + Streamlit 고수준 Trace (기존 V2 Trace 유지).
7. **테스트 14항** + 기존 pytest 전부.
8. **공식 30건 V3 평가** (Azure). 새 리포트만 작성. V2 리포트 보존. U와 P를 표에 넣음.

단계 3에서 F-01 PASS가 안 되면 단계 8로 가지 않는다.

---

## 부록. 재사용 맵

| 구성요소 | V3 |
| --- | --- |
| `diagnose_v2()` | Producer로 그대로 호출 |
| `execute_tool()` / Tool mock | 재실행하지 않음. V2 결과 재사용 |
| `finalize_diagnosis()` | V2 경로 유지. V3 Revision은 별도 함수 |
| `filter_evidence()`, `supporting_tool_results()`, `apply_diagnosis_level_policy()` | Critic 가드 + Revision 후처리에 재사용 |
| `validate_cause_code()` | Critic 권고 / V3 final |
| `V2DiagnosisResult` | 입력. 필드 추가하지 않음 |
| `build_agent_events()` | v3 이벤트 추가 |
| `evaluation/ground_truth.json` | 고정 |
| `evaluate_payload()` | 기존 KPI 유지. Critic KPI는 리포트 층 |
