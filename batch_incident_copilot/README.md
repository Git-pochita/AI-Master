# Batch Incident Copilot

배치 실행 로그를 분석하는 Agentic AI PoC입니다.

V0/V1/V2/V3는 별도 프로젝트가 아니라 같은 코드베이스의 개발 단계입니다.

- V0 Baseline: 로그만 보고 단일 LLM이 진단
- V1 Tool Use: LLM이 필요한 점검 Tool을 선택하고 Tool Evidence를 반영해 최종 진단
- V2 Dynamic Planning / Re-planning: 조사 계획을 세우고 evidence가 부족하면 Re-plan하여 추가 Tool을 실행 (구현 및 30건 평가 완료)
- V3 Critic / Reflection: 동결된 V2 진단을 Critic이 검증하고, 불일치가 있을 때만 Reflection으로 최종 진단을 1회 교정. 추가 Tool은 실행하지 않음 (구현 및 30건 평가 완료)

설계와 평가 기록:

- V2 설계: [`docs/v2_dynamic_planning_design.md`](docs/v2_dynamic_planning_design.md)
- V2 handoff: [`docs/next_steps_v2.md`](docs/next_steps_v2.md)
- V3 설계: [`docs/v3_critic_reflection_design.md`](docs/v3_critic_reflection_design.md)

## 요구 사항

- Python 3.10+
- Azure OpenAI 호환 엔드포인트 접근 권한

## 설치

```bash
cd batch_incident_copilot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 환경 변수

위치: `batch_incident_copilot/.env`

```bash
cp .env.example .env
```

API Key는 코드에 넣지 않습니다.

## 실행

CLI는 평가/저장용 `--case-id`를 받습니다. 생략하면 로그 파일명 stem을 사용합니다. Streamlit UI는 `case_id`를 입력받지 않으며, 로그 파일 업로드 또는 로그 직접 입력만으로 분석을 시작합니다.

V0 Baseline:

```bash
python main.py --version v0 --log data/sample_logs/F-01.log --case-id F-01
```

기본값은 v0입니다. `--version`을 생략해도 V0로 동작합니다.

V1 Tool Use:

```bash
python main.py --version v1 --log data/sample_logs/F-01.log --case-id F-01
python main.py --version v1 --log data/sample_logs/D-01.log --case-id D-01
python main.py --version v1 --log data/sample_logs/S-01.log --case-id S-01
```

현재 Tool (`app/tools/registry.py`):

- `check_file_status`
- `validate_parameter`
- `check_db_status`
- `check_sql_metadata`

모든 Tool은 로컬 mock JSON만 조회합니다. 실제 DB 접속과 credential 검증은 하지 않습니다.

V2 Dynamic Planning:

```bash
python main.py --version v2 --log data/sample_logs/F-05.log --case-id F-05
```

V3 Critic / Reflection:

```bash
python main.py --version v3 --log data/sample_logs/F-02.log --case-id F-02
```

CLI `--version` 선택지: `v0`, `v1`, `v2`, `v3`, `v3_1`. `v3_1`은 V3와 같은 `diagnose_v3()`이며 공식 평가 결과를 별도 디렉터리에 저장하는 alias입니다.

결과 저장 위치 (`config/settings.py`):

- V0: `results/v0_baseline/<case_id>.json`
- V1: `results/v1_tool_use/<case_id>.json`
- V2: `results/v2_planning/<case_id>.json`
- V3: `results/v3_critic/<case_id>.json`
- V3.1: `results/v3_1_critic/<case_id>.json`

## 평가

단일 결과:

```bash
python evaluation/evaluator.py --result results/v0_baseline/F-01.json --case-id F-01
python evaluation/evaluator.py --result results/v1_tool_use/F-01.json --case-id F-01
```

일괄 평가. 기본값은 V0 + V1입니다.

```bash
python evaluation/run_evaluation.py --versions v0 v1
python evaluation/run_evaluation.py --versions v2
python evaluation/run_evaluation.py --versions v3
```

지정 케이스만 실행:

```bash
python evaluation/run_evaluation.py --versions v0 v1 --case-id F-01 D-01 S-01
```

집계 리포트 (`evaluation/reports/`):

- `evaluation/reports/v0_summary.json`
- `evaluation/reports/v1_summary.json`
- `evaluation/reports/v0_vs_v1.md`
- `evaluation/reports/v2_summary.json` (V2 1차, 보존)
- `evaluation/reports/v1_vs_v2.md`
- `evaluation/reports/v2_refined_summary.json` (V2 refined)
- `evaluation/reports/v1_vs_v2_refined.md`
- `evaluation/reports/v3_summary.json`
- `evaluation/reports/v2_refined_vs_v3.md`
- `evaluation/reports/v3_1_summary.json`
- `evaluation/reports/v3_vs_v3_1.md`

공식 평가셋은 `evaluation/ground_truth.json` 30건입니다. 기존 공식 리포트 경로는 바꾸지 말고, V0/V1/V2 1차를 포함해 보존된 리포트는 덮어쓰지 마십시오.

## Streamlit UI

```bash
cd batch_incident_copilot
streamlit run streamlit_app.py
```

브라우저에서 분석 모드(V0 / V1 / V2 / V3)를 고른 뒤, 로그 파일을 업로드하거나 텍스트를 붙여넣고 [분석 시작]을 누르면 됩니다. `case_id` 입력란은 없습니다. CLI `--case-id`와 평가 파이프라인의 `case_id`는 그대로 사용할 수 있습니다.

## 테스트

```bash
cd batch_incident_copilot
pytest -q
```
