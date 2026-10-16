# 10번 Value of Information 구현·직접 테스트 안내

2026-10-17. 7·9번의 상태는 [루트 tracker](../tracker.md), 실행법은 [7·9 안내](research_7_9_completion.md)에 있다. 10번은 명시적 확률 모형을 사용하는 선택 기능이며 `--voi-model`을 주지 않으면 기존 정책으로 동작한다.

## 구현 범위

| 기능 | 파일·함수 | 상태 |
|---|---|---|
| 진단 확률·Bayes 갱신·엔트로피 | `app/core/diagnostic_belief.py`: `distribution`, `posterior`, `entropy` | 구현 |
| 결과 확률과 관측 연결 | `app/core/information_outcomes.py`: `InformationOutcomes`, `observe` | 구현 |
| 비용·효용·정보 이득·유한 단계 탐색 | `app/core/information_value.py`: `action_values` | 구현 |
| 행동 선택·기존 종료 조건·fallback | 같은 파일 `InformationPolicy.propose`; `hospital_llm_policy.py`: `_decision` | 구현 |
| 기억 조회 비용과 지연 노출 | `longitudinal_runner.py`: 기억 pool; `_decision`의 retrieve_memory | 구현 |
| 상태·복원·추적 | `HospitalCaseRuntime.voi_state`, `voi_memory_pool` | 구현 |
| 학습 자료로 prior/likelihood 추정 | `app/core/voi_evaluation.py`: `fit_outcomes` | 구현 |
| Brier·Log loss·ECE 및 정책 비교 | 같은 파일 `evaluate_voi`, `compare_voi` | 구현 |
| 실행·학습·평가 명령 | `run_longitudinal_research --voi-model`; `voi_research` | 구현 |

이 완료 표시는 소프트웨어 모듈의 구현을 의미한다. 실제 임상 확률이나 최적 진료 정책이 증명됐다는 의미는 아니다.

## 수학적 계약

진단 집합 D와 사전확률 b를 명시한다. 결과 o를 관측하면:

`P(o|a,b) = Σ_d b(d)·P(o|d,a)`

`b'(d) = b(d)·P(o|d,a) / P(o|a,b)`

모든 후보의 결과 확률이 0인 관측은 모형 불일치로 처리한다. 새로운 관측 때마다 공개된 결과를 prior부터 재계산하므로 같은 과거 결과를 반복 곱하지 않는다. 서로 다른 행동의 결과는 진단이 주어졌을 때 조건부 독립이라는 가정을 사용한다.

`H(b) = −Σ_d b(d) ln b(d)` (단위: nat)

`IG(a) = H(b) − Σ_o P(o|a,b)·H(b'_o)`

`V₀(b) = max_decision Σ_d b(d)·U(decision,d)`

`C(a) = w_money·money(a) + w_minutes·minutes(a) + w_tokens·tokens(a)`

`Q_h(a,b) = −C(a) + Σ_o P(o|a,b)·V_(h−1)(b'_o, remaining_actions)`

`V_h = max(V₀, max_a Q_h)` / `VoI_h(a) = Q_h(a,b) − V₀(b)`

같은 행동을 재탐색하지 않는다. horizon=1은 한 단계 정보가치, 2~3은 유한 단계 탐색이다. 최대 12행동·각 8결과·5,000개 탐색 상태로 제한한다. 범위를 넘기면 이유를 기록하고 기존 정책으로 넘긴다. 무한 단계 전역 최적성이나 실제 병원에 대한 최적성 보장은 없다.

비용은 terminal utility와 별도로 한 번 차감한다. terminal utility에 이미 같은 비용을 포함시키면 이중 차감이므로 입력 작성 시 분리해야 한다. 입력의 money는 통화/효용 단위를 연구자가 정하고, minutes는 예상 지연, tokens는 예상 토큰이다. 이 비용은 의사결정 점수이며 스케줄러의 실제 시간·청구 비용을 대체하지 않는다. 기억 조회는 내부 조회이므로 별도 시간 이벤트를 만들지 않는다. 실제 호출 비용은 기존 call_costs에 별도 기록한다.

## 안전한 실행 경계

- 확률 모형은 전체 후보와 가능한 결과 분포만 담는다. 환자의 정답이나 아직 공개되지 않은 결과는 선택기에 주지 않는다.
- 검사 결과는 현재 공개 소견, 질문 결과는 해당 질문의 답변, 협진 결과는 해당 과의 의견, 기억 결과는 실제 노출된 비대체 기록만 사용한다.
- 텍스트는 대소문자·공백만 정규화해 정확히 일치시킨다. 자유로운 LLM 서술을 자동 진단 라벨로 해석하지 않는다. 모델 밖 결과나 상충 결과는 fallback 사유로 남긴다.
- 모델의 높은 확률만으로 확진하지 않는다. stop_probability 이상이며 해당 진단에 명시적으로 연결된 현재 객관적 소견을 인용할 수 있어야 한다.
- 결정적 근거가 있으면 추가 탐색 없이 종료한다. 모든 VoI가 음수여도 기존 종료 조건을 통과하지 못하면 가능한 다음 단계로 진행한다. 따라서 수학적 비용 최적화에는 기존 확진/불확실성 제약이 추가된다.
- 탐색 내부의 terminal utility는 추상적인 최종 진단 효용이다. 향후 모든 실제 안전 조건·병원 자원 상태까지 분기별로 복제하는 세계 모형은 아니다. 현재 실행 가능한 행동 목록을 기준으로 재계획한다.
- 환자 답변과 전문과 판단은 기존 LLM 경로를 유지한다. ER의 질문/검사/협진 선택과 결정적 종료는 모형이 충분하면 수학적으로 결정해 ER 호출을 줄인다.
- 처치는 현재 VoI 정보 행동 집합에 넣지 않는다. 처치의 질병 상태 변화·치료 효용은 별도 동적 모형이 필요하며 기존 정책의 처치 경로를 유지한다.
- 등록된 9번 라우터가 허용한 전문과만 협진 후보가 된다. 9번의 메뉴 선택과 10번의 협진 가치 비교는 서로 다른 단계다.

### 기억 조회

모형에 `retrieve_memory` 행동이 있으면 7번 검색 결과를 비공개 `voi_memory_pool`에 보관하고 의사 관측에는 먼저 주지 않는다. 조회가 선택된 후에만 `memory_context`로 옮겨 posterior를 다시 계산한다. 조회 여부를 정할 때 기억 원문이나 실제 결과를 미리 읽지 않는다. No Memory 조건에서는 조회 후보를 제거한다. 같은 방문에서 한 번만 조회한다. 이 pool은 연구 보고서에는 남지만 LLM 입력에는 전달되지 않는다.

## 입력 모형과 제공 예제

`app/data/voi_synthetic/model.json`은 임상 미검수 2진단 toy 모형이다. prior=0.5/0.5, 검사 정확 결과 likelihood=0.99/0.01, 검사 비용=0.05, stop_probability=0.95, horizon=1이다. 질문·기억·협진도 각각 별도 결과 모형을 갖는다. 이 숫자는 실제 검사 민감도·특이도가 아니다.

상위 필드:

- `schema_version`, `model_id`, `revision`, `provenance`: 출처·검수 상태·가정.
- `diagnoses`: 진단명→공유 진료과 카탈로그 이름.
- `prior`: 진단별 합계 1의 확률.
- `terminal_utility`: 선택 진단×실제 진단 효용 행렬.
- `cost_weights`: money/minutes/tokens의 효용 환산 가중치.
- `stop_probability`, `horizon`, `actions`.

각 action은 id/type/target/cost/outcomes를 갖는다. type은 request_test/ask_patient/consult_specialty/retrieve_memory 중 하나다. 각 outcome에는 id, 진단별 likelihood, observation의 source/text, supports_diagnoses가 있다. 마지막 필드는 현재 객관적 검사 결과에서만 사용할 수 있다. 각 행동마다 진단별 결과 likelihood 합은 1이어야 한다. 중복 관측으로 독립 정보를 두 번 계산하지 않도록 동일 source/text를 중복 등록할 수 없다.

`cases.json`은 학습과 분리된 합성 환자 2명, `labels.json`은 방문 키→정답 진단 문자열, `memory.json`은 이전 기록, `training_outcomes.json`은 합성 학습용 결과 40행이다. 관련 임상 데이터는 포함하지 않는다.

## 직접 테스트: 권장 순서

아래 명령은 프로젝트 루트의 PowerShell에서 실행한다. 출력 파일이 이미 있으면 새 이름을 사용한다.

### 1. 모형 검사 — LLM 호출 없음

```powershell
python -m app.scripts.voi_research validate --model app/data/voi_synthetic/model.json
```

예상: status=valid와 모델 해시. 복사본에서 likelihood 합을 1이 아니게 바꾸면 실패해야 한다.

### 2. 최소 회귀 검사 — LLM 호출 없음

```powershell
python -m unittest discover -s tests -p test_voi_minimal.py -q
```

4개 검사: Bayes/VoI·유한 단계 계산, 미공개 결과 차단·스키마 검증, 실제 스케줄러의 결정적 종료/기억 비노출, 학습 환자 유출 차단. 이 작업 중 직접 실행한 범위도 이 4개뿐이다. 전체 회귀 검사는 이번에 다시 실행하지 않았다.

### 3. 실행기 경로 확인

```powershell
python -m app.scripts.run_longitudinal_research --cases app/data/voi_synthetic/cases.json --voi-model app/data/voi_synthetic/model.json --initial-memory app/data/voi_synthetic/memory.json --memory-source fixed --memory-mode full_history --max-retries 0 --output outputs/research/voi_demo.json
```

예상: completed, 환자별 T 검사→Synthetic A/B 진단, posterior=0.99, LLM 호출 0. 이 특정 예제는 결정적 경로라 호출하지 않는다. 데이터를 수정해 모형 밖 결과를 넣거나 질문/협진을 선택시키면 기존 LLM 경로를 호출할 수 있다.

보고서 `visits[].final_state.cases[case_id].voi_state.history`에서 후보별 예상 결과 확률, posterior, IG, 비용, VoI와 선택 근거를 확인한다. `llm_audit`에는 실제 모델 호출만 들어가며 수학적 결정은 `voi_state`에 기록한다.

### 4. 사후 확률·결과 평가

```powershell
python -m app.scripts.voi_research evaluate --report outputs/research/voi_demo.json --labels app/data/voi_synthetic/labels.json --output outputs/research/voi_demo_metrics.json
```

정확도, 방문별 Brier score, log loss, 10구간 ECE, 검사·질문·협진·호출 횟수, 완료 시간, 모형 비용을 확인한다. 정답 누락/미완료는 정확도 분모에서 조용히 제외하지 않고 coverage와 전체 null을 표시한다. 보정 지표는 확률의 품질 측정이며 확률이 자동으로 임상 보정됐다는 의미는 아니다. 실제 정답 확률이 0이면 log_loss를 null로 기록하고 zero_probability_truth를 표시한다.

### 5. 학습 자료로 확률 추정

```powershell
python -m app.scripts.voi_research fit --model app/data/voi_synthetic/model.json --data app/data/voi_synthetic/training_outcomes.json --alpha 1 --output outputs/research/voi_fitted.json
```

행 필드: patient_id, visit_id, split=train, diagnosis, action_id, outcome_id. 동일 방문의 같은 행동 결과 중복과 상충 진단을 거부한다. prior는 방문별 진단 빈도, likelihood는 진단·행동별 결과 빈도에 Dirichlet 평활을 적용한다. 표본이 없는 조건은 평활된 균등 분포가 되며 검증된 확률로 취급하지 않는다. 관측 누락/검사 선택 편향을 자동 교정하지 않는다. 학습 환자 ID를 기록하고 동일 환자의 실행·평가를 거부한다.

### 6. 기존 정책과 비교 — baseline은 실제 LLM 호출 가능

3번 명령에서 `--voi-model`만 제거하고 다른 설정을 유지하여 `voi_baseline.json`을 생성한다. 이후:

```powershell
python -m app.scripts.voi_research compare --baseline outputs/research/voi_baseline.json --report outputs/research/voi_demo.json --labels app/data/voi_synthetic/labels.json --output outputs/research/voi_comparison.json
```

입력·기억·라우팅·모델 설정·시간 예산이 같아야 한다. 쌍별 동일 방문을 비교한다. 정확도 차이, 호출 수 차이, 각 조건의 시간·행동 수·전체 재시도 포함 비용을 확인한다. 실제 의료 효용은 이 toy 정확도와 동일하지 않다. 미완료·fallback·모형 비용 누락 범위를 함께 검토한다.

### 7. 수동 경계 점검

복사한 모형·case로 다음을 확인한다:

1. 검사 비용을 높이면 VoI 순위가 바뀌는지.
2. likelihood를 두 진단에 같게 주면 IG≈0이 되는지.
3. prior가 높아도 현재 객관적 근거가 없으면 확진하지 않는지.
4. memory 행동의 정보가치를 높이면 조회 전에는 기억이 비공개이고 조회 후에만 belief가 바뀌는지.
5. 관측 문자열을 모형 밖 값으로 바꾸면 fallback 사유가 남는지.
6. `--routing-mode adaptive`와 9번 artifact를 함께 줄 때 허용된 과만 후보인지.
7. 실패 체크포인트에 `--resume`을 사용할 때 같은 VoI 모델만 허용하는지.

## 남은 연구 조건

실제 질병 후보·다회 방문 데이터·전문가 검수, 검사/문진/협진의 조건부 확률, 비용 단위, 손실 행렬, 조건부 독립성 검증이 필요하다. 자유 서술→결과 범주의 검수된 분류기와 동적 질병/치료 모형은 제공하지 않는다. 이 구현은 명시적 유한 모형에서 재현 가능한 VoI 실험을 가능하게 하는 기반이다.
