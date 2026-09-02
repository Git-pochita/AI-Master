"""고수준 Agent Event Log — Batch Incident Copilot

이 문서는 개발 가이드의 7대 구성요소를 이 프로젝트의 실제 진단 흐름에 맞게
정규화한 observability 계층을 설명한다. 성능 개선이나 V3 Critic 구현이 아니다.

## 목적

V0 / V1 / V2 실행 결과를 UI·데모에서 같은 고수준 이벤트로 보여 주기 위함이다.

기존 `AgentExecutionTrace`(V0/V1)와 V2 `planning_trace`는 유지한다.
그 위에 `build_agent_events(version, result) -> list[AgentEvent]` adapter만 둔다.
진단 payload, Planner Prompt, Ground Truth, evaluator는 이 계층의 입력이며 변경하지 않는다.

## AgentEvent schema

정의 위치: `app/schemas.py` (`AgentEvent`)
변환 위치: `app/agent_events.py` (`build_agent_events`)

| 필드 | 설명 |
| --- | --- |
| `component` | Perception / Reasoning / Memory / Action / Feedback / Evaluation / Governance |
| `step` | `log_analysis`, `planning`, `tool_call` 등 짧은 단계 id |
| `summary` | 관찰 가능한 상태 전환 한 줄 |
| `detail` | 부가 설명. 비어 있을 수 있음 |
| `metadata` | job_name, tool, arguments, stop_reason 등 구조화 값 |
| `timestamp` | UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SS.ffffffZ`) |
| `round` | V2 planning round. 없으면 null |
| `status` | SUCCESS / FAILED / stop_reason 등. 없으면 null |
| `source` | `v0` / `v1` / `v2` |

private Chain-of-Thought 필드(`reason`, `thinking`, `chain_of_thought` 등)는 모델에 없다.

## 7대 component 매핑

이 프로젝트에서 실제로 쓰는 매핑:

| Component | 사용 |
| --- | --- |
| Perception | 로그 분석, extracted_info(error_code / return_code / job_name 등) |
| Reasoning | 초기 가설, tool 선택, planning / replan, sufficiency, hypothesis update, stop(EVIDENCE_SUFFICIENT / NO_ACTIONABLE_TOOL), 최종 진단 |
| Action | Tool Call, Tool Result **SUCCESS** |
| Governance | Tool FAILED, MISSING_REQUIRED_ARGUMENTS, DUPLICATE_TOOL_CALL_BLOCKED, MAX_PLANNING_ROUNDS, MAX_TOOL_CALLS |
| Feedback | V0/V1/V2에서는 비움. V3 Critic / Reflection에서 사용 예정 |
| Evaluation | runtime 진단과 evaluator를 섞지 않음. V3에서 evidence consistency 등으로 확장 |
| Memory | enum에만 포함. 장기/세션 메모리 이벤트를 만들지 않음 |

없는 단계를 채우기 위해 빈 Action/Feedback 이벤트를 만들지 않는다.

## V0 이벤트 예시

Tool이 없으므로 3단계면 충분하다.

1. `[Perception] log_analysis` — 오류 코드·주요 필드 추출
2. `[Reasoning] initial_hypotheses` — 초기 원인 후보 n개
3. `[Reasoning] final_diagnosis` — 최종 Cause / diagnosis level

## V1 이벤트 예시

1. Perception / log_analysis
2. Reasoning / initial_hypotheses
3. Reasoning / tool_selection — 예: 파일 상태 확인 필요
4. Action / tool_call — tool=`check_file_status`
5. Action / tool_result — status=SUCCESS, exists/received 등
6. Reasoning / evidence_update — SUCCESS 필드 기반 가설 상태 변화
7. Reasoning / final_diagnosis

FAILED Tool은 Action SUCCESS로 보이지 않는다. Governance / tool_failure 이고
`excluded_from_final_evidence=true` 이다.

## V2 이벤트 예시 (F-05 형태)

1. Perception / log_analysis
2. Reasoning / initial_hypotheses
3. Reasoning / planning (round 1, 예: check_file_status)
4. Action / tool_call · tool_result (`check_file_status`)
5. Reasoning / sufficiency_check (`evidence_sufficient=false`)
6. Reasoning / replan (round 2, 예: validate_parameter)
7. Action / tool_call · tool_result (`validate_parameter`)
8. Reasoning / hypothesis_update — 초기 가설에 없던 원인 신규 채택
9. Reasoning / stop — `stop_reason=EVIDENCE_SUFFICIENT`
10. Reasoning / final_diagnosis

`stop_reason` 매핑:

| stop_reason | component / step |
| --- | --- |
| EVIDENCE_SUFFICIENT | Reasoning / stop |
| NO_ACTIONABLE_TOOL | Reasoning / stop |
| MISSING_REQUIRED_ARGUMENTS | Governance / missing_arguments |
| MAX_PLANNING_ROUNDS | Governance / planning_limit |
| MAX_TOOL_CALLS | Governance / tool_call_limit |
| DUPLICATE_TOOL_CALL_BLOCKED | Governance / duplicate_tool_blocked |

## Chain-of-Thought 비노출

고수준 로그는 관찰 가능한 실행 이벤트와 상태 전환만 담는다.

포함하지 않음:

- LLM `summary` / `reason` / `goal` 전문
- hidden reasoning token
- “나는 이렇게 생각했다” 식 자유 서술

허용 예:

- “현재 evidence만으로 근본 원인을 확정하기 부족합니다.”
- “validate_parameter 실행”
- “INVALID_BUSINESS_DATE를 신규 원인 후보로 채택했습니다.”
- “EVIDENCE_SUFFICIENT로 종료”

변환기는 `selected_tools[].reason`, `planning_trace[].reason`, 진단 `summary`를
이벤트 summary/detail로 복사하지 않는다.

## V3 확장 (미구현)

이번 계층은 아래 step을 받을 수 있게 component enum만 열어 둔다. 코드는 추가하지 않는다.

- Feedback / critic_check
- Feedback / revision_requested
- Feedback / reflection
- Evaluation / evidence_consistency
- Governance / human_review_requested

V2 Planner Prompt, `has_parameter_anomaly_signal()`, F-02/F-04, GT, evaluator,
공식 30건 평가는 이 문서의 범위가 아니다.
