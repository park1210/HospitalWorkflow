# 7·9번 추가 구현과 재현 방법

2026-10-17. 기능별 코드 위치는 루트 [tracker.md](../tracker.md)를 참조한다.

후속 10번 VoI도 구현했다. 이 문서는 7·9번의 검증 기록이며 새 실행·수동 테스트 방법은 [VoI 안내](voi_research.md)에 있다.

## 제공 데이터의 의미

`app/data/research_synthetic_v1/`에 6명·12방문과 12개 과거 기록을 제공한다. 환자별 train/validation/test 각 2명으로 분리했다. 관련성·오래된 기억 라벨과 진단 문자열 목록은 생성 규칙의 정답이며 **임상 미검수 합성 자료**다. 실제 환자 자료나 전문가 검수 결과를 대신하지 않는다.

- `bundle.json`: 데이터, 라벨, 분할, 검수 상태의 통합 계약.
- `cases*.json`, `memory.json`, `annotations.json`, `expected_diagnoses.json`: 기존 실행기 입력.
- `embeddings_lexical.json`: 외부 모델 없는 해시 단어 벡터 기준선.
- `embeddings_semantic.json`: 로컬 embeddinggemma가 생성한 실제 768차원 벡터. revision은 설치 모델 digest.
- `embedding_smoke.json`: 12방문에서 환자/시점 필터와 검색·충돌 후보 표시 점검 결과.
- `registry_local.json`: 설치된 ER·신경과·호흡기과 모델과 조회 시점 digest.
- `routing_probes_*.json`: 관측이 부족한 합성 사례에서 unresolved 답을 평가하는 단일 판단 과제. 질환 진단 성능 비교용이 아니다.
- `prices_local_api_only.json`: 로컬 API 요금만 0으로 선언. 전기·장비·인건비를 포함하는 총비용 0이라는 뜻이 아니다.
- `routing_*observed.json`, `routing_*cpu.json`, `routing_*bounded.json`: 실제 시도 기록. 성공/실패와 토큰 사용량을 확인해야 한다.

검증과 새 자료 생성:

```powershell
python -m app.scripts.prepare_research_data --bundle app/data/research_synthetic_v1/bundle.json
python -m app.scripts.prepare_research_data --output-dir outputs/research/new_synthetic_bundle
```

검증기는 환자 분할 중복, 미래/다른 환자의 기억 라벨, 진단 라벨 누락을 거부한다. `expert_reviewed` 선언에는 reviewer와 review_reference가 필요하지만, 검수의 진실성까지 자동 인증하지 않는다. 실행별 오용 라벨은 소스 데이터에 넣지 않고 사후 검수한다.

## 7번: 실제 임베딩과 충돌 후보

```powershell
python -m app.scripts.build_memory_embeddings --memory app/data/research_synthetic_v1/memory.json --cases app/data/research_synthetic_v1/cases.json --model embeddinggemma --revision YOUR_MODEL_DIGEST --endpoint http://localhost:11434 --cpu --output outputs/research/new_embeddings.json
```

공식 [Ollama embed API](https://docs.ollama.com/api/embed)를 사용한다. 동일 텍스트를 한 번만 처리하고 배치 요청하며, 원문 해시와 벡터 차원·유한성·노름을 검사한다. 자동 모델 다운로드는 하지 않는다. `--cpu`는 GPU 메모리가 부족할 때 사용한다. 생성된 벡터를 사용하는 검색 자체에는 모델 호출이 없다. 새로 생성된 누적 기억을 검색하려면 그 기록의 벡터도 생성해야 한다. 제공 산출물은 고정 기억 실험에 바로 사용할 수 있다.

충돌 탐지는 동일 대상의 `Patient reports X` / `Patient denies X`, `X: present` / `X: absent`, `X 있음` / `X 없음`을 인식한다. 같은 환자의 검색된 비대체 기록끼리만 비교한다. 반대 서술은 실제 시간 변화일 수 있어 `requires_review`로 표시하고 두 원문을 보존한다. 복합 부정·동의어·가족력·임상적 양립 불가능성 전체를 이해하는 NLI 모델은 아니다. 확정 갱신은 기존 supersedes 입력으로 처리한다.

## 7번: 실패 재개

```powershell
python -m app.scripts.run_longitudinal_research --cases app/data/research_synthetic_v1/cases_test.json --initial-memory app/data/research_synthetic_v1/memory.json --memory-source fixed --memory-mode semantic --memory-embeddings app/data/research_synthetic_v1/embeddings_semantic.json --max-retries 1 --output outputs/research/test_memory.json
```

CLI는 완료 방문마다 `test_memory.checkpoint.json`을 원자적으로 교체한다. 모델 호출 실패는 기본 1회 재시도하며 0~3회로 제한한다. 재시도는 실패한 방문 처음부터 실행한다. 이미 완료한 방문은 재실행하거나 기억에 중복 저장하지 않는다. 실패 방문에서 발생한 호출은 discarded_attempts와 비용 집계에 남는다.

```powershell
python -m app.scripts.run_longitudinal_research --cases app/data/research_synthetic_v1/cases_test.json --initial-memory app/data/research_synthetic_v1/memory.json --memory-source fixed --memory-mode semantic --memory-embeddings app/data/research_synthetic_v1/embeddings_semantic.json --resume outputs/research/test_memory.checkpoint.json --output outputs/research/test_memory_resumed.json
```

재개는 데이터·모델·라우팅·검색·라벨 설정 서명 및 체크포인트 무결성이 같아야 한다. 진료 중간 이벤트에서 정확히 이어가는 재개는 아니다. 강제 종료 직전 미저장 호출 비용은 복구할 수 없다. 무결성 해시는 우발적 파일 손상 감지용이며 전자서명 인증이 아니다. 시간 제한으로 미완료된 방문도 동일 설정으로 재개할 수 있지만, 한도 자체를 바꾸는 것은 새 실험이다.

## 9번: 수집 → 학습 → 평가 → 실행

### 동일 관측 결과 수집

```powershell
python -m app.scripts.collect_routing_outcomes --probes app/data/research_synthetic_v1/routing_probes_train.json --registry app/data/research_synthetic_v1/registry_local.json --prices app/data/research_synthetic_v1/prices_local_api_only.json --native-endpoint http://localhost:11434 --cpu --output outputs/research/train_outcomes.json
```

모든 등록 전문과에 같은 관측을 제공한다. probe는 patient_id, decision_id, split, observation, expected_diagnoses를 포함하지만 정답과 split은 모델에 보내지 않는다. 미공개 사실을 observation에 넣지 않는 책임은 데이터 작성자에게도 있다. 같은 모델의 probe를 연속 실행하여 로딩 반복을 줄인다. 응답 진단 최대 80자, 근거 최대 160자의 구조를 강제한다. 대소문자/공백을 정규화해 허용 진단 목록과 비교하고 실패는 correct=false로 남긴다.

### 효용 학습

```powershell
python -m app.scripts.routing_research fit --registry app/data/research_synthetic_v1/registry_local.json --data outputs/research/train_outcomes.json --min-samples 2 --accuracy-weight 1 --cost-weight 0 --latency-weight 0.001 --output outputs/research/utility.json
```

train 행만 허용하며 같은 판단의 모든 전문과 결과를 요구한다. 비용이 알려지지 않은 행을 0으로 채우지 않고 거부한다. 비용 단위는 같은 통화, 지연 단위는 초다. 가중치는 연구자가 정하는 실험 설정이며 임상적으로 검증된 값이 아니다.

관측 토큰 Jaccard 유사도 w를 가중치로 사용한다. 성공률 추정은 `(1 + Σw·correct)/(2 + Σw)`이며 비용·지연은 가중 평균이다. `U = α·P(correct) − β·cost − γ·latency`가 최대인 가용 전문과를 선택한다. 최소 표본 미달 후보가 있으면 전체 메뉴를 유지하며, 기록에 이유를 남긴다. 온라인 학습이나 보정된 임상 확률은 아니다. 현재 한 진료과당 한 모델만 허용한다.

### 별도 환자 평가

validation/test probe를 별도 파일로 수집한 후:

```powershell
python -m app.scripts.routing_research evaluate --registry app/data/research_synthetic_v1/registry_local.json --data outputs/research/test_outcomes.json --utility outputs/research/utility.json --output outputs/research/regret.json
```

같은 관측의 후보별 실제 결과로 oracle 효용과 선택 효용의 차이를 계산한다. 학습 환자 중복, 모델/버전 불일치, 서로 다른 관측의 후보 비교를 거부한다. 결과 누락이나 기권이 있으면 전체 mean_regret는 null이고 coverage와 부분 결과를 함께 제공한다. 단일 판단 probe의 Regret이며 전체 진료 경로의 임상 이득을 의미하지 않는다.

### 실제 실행기 연결

기존 실행 명령에 다음 옵션을 추가한다:

```text
--agent-registry app/data/research_synthetic_v1/registry_local.json
--routing-mode adaptive
--routing-utility outputs/research/utility.json
--token-prices app/data/research_synthetic_v1/prices_local_api_only.json
```

라우터는 전문과 후보 메뉴를 정하고, 기존 의사는 질문·검사·협진·진단의 시점을 결정한다. 라우터의 추가 LLM 호출은 없으며 기존 객관적 근거 종료 조건·호출 한도·판단 근거 기록을 유지한다. 학습 환자가 실행 사례에 포함되면 거부한다.

## 비용과 성능 해석

[OpenAI 호환 Chat Completions usage](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) 또는 [Ollama native token counts](https://docs.ollama.com/api/chat)를 기록한다. 원문 출력 검증에 실패해도 반환된 사용량은 보존한다. 네트워크 실패 등으로 usage가 없으면 비용도 null이다. total_cost는 모든 호출이 계산 가능할 때만 제공하며 known_cost는 알려진 부분합이다. 캐시·배치·단계별 가격 정책은 계산하지 않는 단순 선형 단가 모델이다.

다음 연구 단계는 전문가 검수 데이터 확보, 실제 진단 과제의 반복 평가, 확률 보정, 임상적으로 의미 있는 비용 정의다. 실제 임상 데이터가 없으므로 이번 합성 산출물을 임상 성능 주장에 사용하지 않는다.

## 이번 검증 결과

- 자동 테스트 140개 통과, 변경 파일 공백 검사 통과.
- 실제 embeddinggemma 768차원 벡터 생성 및 12방문 검색 확인.
- 실제 신경과/호흡기과 모델의 bounded 학습 probe 4회·별도 환자 시험 probe 4회 성공.
- `routing_utility_bounded.json` 학습과 `routing_regret_smoke.json` 평가 생성. 이 toy 과제에서 coverage=1, mean_regret=0이었다. 두 모델이 모두 근거 부족을 답하는 단순 과제로, 임상 검증을 의미하지 않는다.
- GPU 실행 시간 초과와 최초 CPU 출력 잘림을 보존했다. CPU 전환과 길이 제한 스키마로 수집 경로를 점검했다. 일반 진료 실행기의 모든 시간 초과가 해결됐다는 의미는 아니다.
- 학습 지연에는 CPU 실행·로딩이 포함된다. 다른 장비/실행 조건에서는 다시 수집해야 한다.
