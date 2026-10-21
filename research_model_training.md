# Routing / VoI 모델 학습 경로

## 이번 구현 범위

- 신규 `app/scripts/build_research_models.py`: Routing/VoI를 함께 또는 따로 학습·검증하고 artifact와 입력 SHA256 manifest를 저장한다. LLM을 호출하지 않는다.
- 기존 `routing_utility.fit_utility`의 Jaccard/Beta 수식과 `voi_evaluation.fit_outcomes`의 Dirichlet counts 수식을 재사용한다.
- `voi_evaluation.fit_outcome_spec`: 확률이 없는 명시적 action/outcome 정의와 실제 학습 관측으로 cost-free v2 모델을 만든다.
- 기존 `fit_outcomes`에서 v2 학습 출력이 내부 v1 비용 필드를 노출하던 문제를 수정했다. v1 출력 호환성은 유지한다.
- `tests/test_research_model_building.py`: 학습값, 누락 관측, 환자 누출, 실패 호출, 입력 불변성, v1/v2 호환 검증.

**학습 도구 구현 완료와 실제 데이터로 학습된 모델 확보는 다르다.** ready_100_v1에는 전문과별 응답 결과나 VoI 학습 관측이 없으므로, 이 데이터로 학습을 완료했다고 주장하거나 임의의 모델 파일을 만들지 않았다. 이벤트/환경 어댑터와 B0~B4 실행기 변경은 이번 범위에 포함하지 않았다.

## 1. Routing

기존 수집 명령을 재사용한다:

```powershell
python -m app.scripts.collect_routing_outcomes --probes TRAIN_PROBES.json --registry REGISTRY.json --prices PRICES.json --output ROUTING_TRAIN.json
```

이 명령만 실제 LLM 호출을 발생시킨다. `TRAIN_PROBES.json`은 JSON 배열이며 각 행은 다음 형태다:

```json
{
  "patient_id": "separate-training-patient",
  "decision_id": "visit1-decision1",
  "split": "train",
  "observation": {
    "chief_complaint": "실제로 공개된 주호소",
    "current_symptoms": [],
    "objective_findings": [],
    "history": [],
    "longitudinal_memory": {"records": []}
  },
  "expected_diagnoses": ["평가 전용 진단명"]
}
```

`expected_diagnoses`는 수집기가 prompt에서 제외한다. 모든 전문과에 동일한 public observation을 준다. 진단의 정규화된 문자열 일치로 correct를 계산하는 단일 assessment probe이며, 전체 trajectory 성공률이나 임상 검수와 동일하지 않다. 실패 호출을 오진으로 학습하지 않도록 신규 빌더가 실패 audit/누락 answer를 거부한다. 수집 시 비용 로그가 필요 없으면 PRICES.json은 `{}`로 사용할 수 있다. 비용은 Routing 점수에 사용하지 않는다.

학습:

```powershell
python -m app.scripts.build_research_models --evaluation-cases ready_100_v1/cases.json --registry REGISTRY.json --routing-data ROUTING_TRAIN.json --min-samples 2 --output-dir outputs/routing_model_v1
```

출력: `routing_utility.json`, `training_manifest.json`.

필수 조건:

- 학습 환자와 ready_100_v1의 평가 환자는 겹치지 않아야 한다. 100명을 전부 평가하려면 별도 학습 환자가 필요하다.
- 모든 학습 decision에 registry의 모든 specialty outcome이 있어야 한다.
- 동일 decision의 observation은 완전히 같아야 하며, 각 model/version은 registry와 일치해야 한다.
- 최소 표본 개수는 동작 조건이다. 충분한 임상 표본 수라는 뜻은 아니다. 추론 시 positive Jaccard support가 부족하면 abstain한다.
- 관측 행을 직접 제공할 수도 있지만 `correct`는 실제 응답 평가 결과여야 한다. 정답 전문과와 일치하는 agent에 임의로 true를 붙이면 안 된다.

## 2. VoI

### 확률 없는 명세 `VOI_SPEC.json`

필수 최상위 키는 `model_id`, `revision`, `provenance`, `diagnoses`, `terminal_utility`, `horizon`, `actions`다. 아래는 구조 설명용 A/B 예시이며 **ready_100 임상 모델이 아니다**.

```json
{
  "model_id": "explicit-study-model",
  "revision": "1",
  "provenance": {
    "synthetic": true,
    "review_status": "unreviewed",
    "assumptions": ["학습 자료와 행동 결과 정의의 출처를 여기에 명시"],
    "utility_scope": "algorithm_validation_only"
  },
  "diagnoses": {"A": "general_medicine", "B": "general_medicine"},
  "terminal_utility": {"A": {"A": 1, "B": 0}, "B": {"A": 0, "B": 1}},
  "horizon": 2,
  "actions": [{
    "id": "test-x", "type": "request_test", "target": "Test X",
    "outcomes": [
      {"id": "positive", "observation": {"source": "objective_findings", "text": "Test X: positive"}, "supports_diagnoses": []},
      {"id": "negative", "observation": {"source": "objective_findings", "text": "Test X: negative"}, "supports_diagnoses": []}
    ]
  }]
}
```

`prior`/`likelihood`/cost 필드는 명세에 넣지 않는다. `supports_diagnoses`는 임상 근거 없이 자동 생성하지 않는다. 빈 목록이면 해당 결과만으로 supported final diagnosis가 허용되지 않는다. utility 행렬, 진단→전문과 mapping, 검사 수치의 범주화, 결과 문자열은 연구 설계/데이터 계약에서 명시해야 한다. 빌더는 이를 임의로 추론하지 않는다.

### 학습 관측 `VOI_TRAIN.json`

JSON 배열. 한 patient/visit/action당 실제 관측된 outcome을 한 번만 입력한다:

```json
{
  "patient_id": "separate-training-patient",
  "visit_id": "visit1",
  "split": "train",
  "diagnosis": "A",
  "action_id": "test-x",
  "outcome_id": "positive"
}
```

실제 빈도와 smoothing alpha로 기존 수식을 사용한다:

\[
P(d)=\frac{N_d+\alpha}{N+|D|\alpha},\qquad
P(o\mid a,d)=\frac{N_{a,d,o}+\alpha}{N_{a,d}+|O_a|\alpha}.
\]

prior는 action 행 개수가 아니라 **중복 제거한 방문 수**로 추정한다. 모든 action×diagnosis cell에 최소 `--min-observations`개의 실제 관측을 요구한다. 관측 부족을 uniform probability만으로 채워 모델을 내보내지 않는다. 코드 내부의 uniform 초기값은 기존 validator 재사용용이며 학습 빈도로 전부 대체된 후에만 출력한다.

```powershell
python -m app.scripts.build_research_models --evaluation-cases ready_100_v1/cases.json --voi-spec VOI_SPEC.json --voi-data VOI_TRAIN.json --alpha 1 --min-observations 1 --output-dir outputs/voi_model_v1
```

출력: `voi_model.json` (schema v2, 비용 필드 없음), `training_manifest.json`.

`--min-observations 1`은 연동을 위한 최소 가용성 기준이며 통계적 충분성 기준이 아니다. 실제 실험에는 별도 validation과 표본 수 판단이 필요하다. 관측 데이터에서 어떤 검사를 시행했는지에 따른 선택 편향, 행동 간 조건부 독립 가정도 counts만으로 해소되지 않는다.

## 3. 한 번에 두 모델 생성

```powershell
python -m app.scripts.build_research_models --evaluation-cases ready_100_v1/cases.json --registry REGISTRY.json --routing-data ROUTING_TRAIN.json --voi-spec VOI_SPEC.json --voi-data VOI_TRAIN.json --output-dir outputs/research_models_v1
```

대문자 경로는 실제 준비한 파일 경로로 바꾼다. 두 모델 중 하나라도 검증 실패하면 출력 디렉터리를 생성하지 않는다. 기존 출력은 덮어쓰지 않는다. 모델 파일에는 학습 환자 ID가 기록되며 runtime의 기존 leakage 검사에도 연결된다. manifest에는 학습 입력 및 평가 cases의 SHA256을 기록한다.

## 4. 남은 입력과 테스트

현재 필요한 것은 (1) 별도 학습 환자에 대한 실제 specialty probe 결과, (2) 명시적 VoI 행동·결과·utility 정의, (3) 진단과 행동 결과가 연결된 실제 학습 관측이다. ready_100의 정답 라벨을 복사해 학습 후 같은 100명에서 평가하지 않는다. source-observed 라벨을 쓰는 탐색 연구는 검수 완료 정확도와 구분해야 한다.

```powershell
python -m pytest tests/test_research_model_building.py -q
python -m pytest tests -q
```

실제 Ollama 수집/학습용 실험은 이번 구현 과정에서 실행하지 않았다.

검증 결과: 신규 학습 계약 테스트 7개 통과. 전체 `pytest tests -q`는 **246개 통과, 실패 0개** (22.87초). CLI `--help`도 정상 동작했다.
