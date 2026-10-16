# KSC 샘플 논문에 맞춘 실험 방법

기준: 사용자 제공 `KSC2026_심사용_샘플스타일_3페이지.pdf`의 4장, 표 1·2. PDF는 단순 양식이 아니라 본 프로젝트의 연구 설계 초안이다. 이 문서는 그 설계를 실행 가능한 명령으로 옮긴다. 샘플의 인용 문헌·학회 제출 규정은 별도로 검증하지 않았다.

## 1. 조건과 비교

### 2026-10-17 출력 계약 수정

`paper_pilot_01`의 B1/B2/B3는 JSON 파싱 오류였으며 모두 출력 768토큰 한도에 도달했다. 수정 후 `paper_pilot_fixed_01`에서 B0~B4 × 두 방문이 모두 완료됐고 호출 실패는 0이었다. 실제 LLM 응답 16개는 모두 `finish_reason=stop`, 출력 62~95토큰이었다. 두 합성 사례의 정답률은 모든 조건에서 1.0이었다. 임상 성능 검증은 아니다.

- 의사 출력의 rationale 240자, assessment 160자, target 240자와 증거/기억 배열 최대 4개를 생성 스키마에 명시한다. 출력 한도 768은 늘리지 않았다.
- 모든 조건에 같은 VoI 모형의 **전체 진단 후보 목록**을 제공하고 supported diagnosis는 해당 명칭을 쓰게 한다. 환자별 정답 라벨은 모델에 제공하지 않는다. 이제 자유 진단명이 아닌 유한 후보 진단 실험이므로 논문에 명시한다.
- 토큰 한도 종료는 `output_truncated`, 잘못된 JSON은 `invalid_json`, 검증 실패는 `schema_validation`으로 기록한다. `llm_audit.response_metadata`에는 finish_reason과 출력 문자 수를 보존한다.
- 이전 결과를 재채점하거나 덮어쓰지 않았다. 진단 후보 제공과 프롬프트가 변경되어 이전/이후 결과를 동일 설정 반복으로 합치지 않는다. 기존 checkpoint와도 계약이 달라진다.
- 새 검증: 출력 잘림·메타데이터 격리 및 공통 진단 후보 정보 경계 검사 2개, 기존 VoI 검사 4개 통과. 자동 재시도/오류를 숨기는 JSON 복구는 추가하지 않았다.

| 조건 | 기억 | 라우팅 | VoI |
|---|---|---|---|
| B0 | 없음 | ER only | 없음 |
| B1 | Full history | ER only | 없음 |
| B2 | selective 또는 semantic top-k | ER only | 없음 |
| B3 | B2와 동일 | adaptive | 없음 |
| B4 | B2와 동일 | adaptive | 적용 |
| R0 (보충 실험) | B2와 동일 | LLM 후보 선택 | 없음 |

`기본 ER`은 본 실행기에서 `er_only`로 명확히 정의했다. 그러므로 B2→B3에는 협진 활성화 효과가 포함된다. 라우팅 자체의 비교에는 R0→B3를 추가한다. 모든 조건은 같은 사례, fixed memory, 라벨, 모델 설정, 시간 한도를 사용한다. B4는 VoI가 기억 조회를 선택할 때까지 기억을 숨기므로 B3→B4는 정보 접근 시점 변화도 포함한다.

## 2. 가장 짧은 실행

프로젝트 루트, 기존 Python 환경에서 실행한다. 모든 출력 디렉터리는 새 이름이어야 한다.

```powershell
# 입력·설정 검증만. LLM 호출 없음
python -m app.scripts.run_paper_experiments

# B4 두 합성 방문으로 파이프라인 확인. LLM 호출 차단
python -m app.scripts.run_paper_experiments --execute --offline --conditions B4 --repeats 1 --output-dir outputs/paper_check_01
```

두 번째 실행의 기대값: B4 완료율 1, 합성 정답률 1, 평균 행동 수 2, LLM 호출 0. 이는 논문 성능 실험이 아닌 입출력·실행 경로 확인이다. B0~B3에 `--offline`을 쓰면 모델 호출이 차단되어 실패 기록이 생성된다.

## 3. 실제 LLM B0~B4 실험

Ollama 서버를 실행하고 `ollama list`로 `paper_experiment.example.json`에 연결된 registry의 ER·전문과 모델이 설치되어 있는지 확인한다. 환자 역할은 `app/config.py`의 기본 모델 설정을 사용한다. 모델 태그가 같아도 가중치가 바뀔 수 있으므로 registry의 version과 실제 digest를 대조한다. 실행기는 선언된 버전을 보존하지만 서버의 실제 digest를 자동 인증하지 않는다.

```powershell
# 첫 실행: 2 방문 × 5 조건 × 1회
python -m app.scripts.run_paper_experiments --execute --repeats 1 --output-dir outputs/paper_pilot_01

# 기본 3회 반복: 2 방문 × 5 조건 × 3회
python -m app.scripts.run_paper_experiments --execute --output-dir outputs/paper_repeat_01

# 협진을 허용한 정책끼리 비교
python -m app.scripts.run_paper_experiments --execute --conditions R0 B3 --output-dir outputs/paper_routing_01
```

모델 호출 수·소요 시간은 경로에 따라 달라진다. 실패 호출은 자동 재시도하지 않는다. 한 조건이 실패해도 다음 조건을 실행한다. 해당 조건에서 미실행된 후속 방문도 계획 분모에 포함한다. 일부 실패 시 종료 코드는 1이며 부분 결과는 보존된다. 새 실행은 새 폴더를 사용한다. 이 배치 명령 자체에는 재개/기존 결과 합치기 기능이 없다. 방문 checkpoint는 진단 및 기존 단일 실행기 재개용으로 보존한다.

반복 번호는 LLM seed가 아니다. decoding 설정은 manifest에 보존하고 동일하게 유지하지만 백엔드의 완전한 재현성은 보장하지 않는다. 반복마다 조건 순서를 회전하여 항상 같은 조건이 최초 모델 로딩을 부담하는 문제를 일부 줄인다. 전용 장비 상태·GPU/CPU·동시 작업 유무도 논문에 기록한다.

## 4. 본 실험용 데이터 교체

`paper_experiment.example.json`을 복사해 `--plan 경로`로 지정한다. 파일 경로는 **plan 파일의 폴더 기준**이다.

- `cases`: 동일 환자의 여러 방문. 방문 ID·timezone 포함 시각 필수. 모델에는 공개 관측만 전달한다.
- `labels`: `[patient_id, visit_id]`를 JSON 문자열로 만든 키 → 진단 정답 문자열 또는 허용 별칭 목록. VoI 모형의 정식 진단명도 포함해야 한다.
- `memory`: 이전 방문 기억, 출처, 공개 시각, supersedes 관계.
- `annotations`: 같은 방문 키 → `relevant_memory_ids`, `stale_memory_ids`. 합성 예제 라벨은 생성 규칙 기반이며 임상 검수 라벨이 아니다.
- `gold_departments` (선택): 방문 키 → 허용 전문과 목록. 반드시 공통 department catalog의 값 사용. 없으면 관련 지표는 NA.
- `registry`, `routing_utility`: 비교할 모델과 학습된 라우터. 학습 환자와 평가 환자 중복을 거부한다.
- `voi_model`: 진단 후보, prior, 행동 결과 likelihood, 효용, 비용. 평가 환자로 맞춘 모형을 사용하면 안 된다.
- `embeddings` (semantic일 때 필수): 같은 기억·질의에 대한 실제 임베딩. `retrieved_mode: semantic`으로 설정한다. lexical selective 결과를 의미 임베딩 결과라고 쓰지 않는다.
- `prices`: 사용자가 선언한 모델별 토큰 단가. 로컬 API 단가 0은 전기·장비·시간 비용 0을 뜻하지 않는다.

모든 조건에 공통으로 넣는 annotations에는 `misused_memory_ids`를 허용하지 않는다. 오용은 각 실행 결과를 검수한 뒤 그 실행 전용 annotation을 만들어 `evaluate_longitudinal_memory`로 별도 평가한다. stale 검색률과 stale 오용률은 다르다.

현재 예제는 두 환자, 이전 기억 1개씩이며 협진 필요성·stale 충돌·검색 경쟁을 충분히 만들지 않는다. 실제 연구에는 관련/무관/갱신된 기억, 전문과 선택이 갈리는 관측, 추가 검사 가치가 높은/낮은 관측을 포함해야 한다. train/validation/test는 **환자 단위로** 분리하고 test 결과를 보고 가중치·top-k·임계값을 조정하지 않는다. 3회 반복은 사용 편의를 위한 기본값이며 충분한 표본 수의 근거가 아니다.

## 5. 지표와 산출물

| 파일 | 용도 |
|---|---|
| `manifest.json`, `inputs/` | 입력 사본·SHA256, 코드 SHA256, decoding 설정, 조건 보존 |
| `B*_r*.report.json` | 실제 방문별 trajectory, routing, VoI, 호출 로그 |
| `B*_r*.checkpoint.json`, `*.error.json` | 실패·부분 실행 확인 |
| `episodes.csv` | 방문×반복×조건별 지표 |
| `table.csv` | 조건별 평균과 모든 지표의 coverage |
| `results.json` | 환자 단위 paired 차이·bootstrap CI, 비용, 실행 시간 |
| `paper_results.md` | 논문 표로 옮길 요약 |

- 전체 계획 기준 정답률: 실패·미완료·미실행은 0. 완료 방문만의 정답률도 별도 제공한다. 두 값을 함께 보고한다.
- Action Count: 로그에 선택된 의료 행동과 VoI 기억 조회 수. 실패하여 선택되지 않은 응답은 행동 수에 포함하지 않고 failed calls에 포함한다. 검사 수는 완료 검사 수이다.
- LLM 호출 수는 실패·차단된 시도도 포함한다. `offline_blocked` 보고서의 호출 수가 1이어도 외부 모델 요청은 하지 않은 것이다. 토큰, 호출 latency, timeout, 완료시간을 기록한다. timeout은 호출 오류 유형에 timeout이 명시된 경우만 센다. 모든 연결 실패가 timeout인 것은 아니다.
- Expected IG는 VoI 후보 모형의 기대 entropy 감소 합계이다. 실측 IG나 B0~B3의 IG를 대신하지 않는다. 없는 값은 NA.
- 기억 Precision/Recall은 방문별 macro 평균이며 coverage와 함께 제공한다. 오용 라벨 없이는 오용률을 0으로 표시하지 않는다.
- `consult_department_precision`은 완료된 협진 중 허용 진료과 비율의 방문 평균이다. 미협진 방문은 NA. 최종 배정 전문과 정확도도 별도 제공한다. 두 값 모두 Router Regret와 다르다.
- 인접 비교는 환자별 방문·반복 차이를 먼저 평균하고, 환자를 단위로 2,000회 bootstrap한다. `candidate - baseline`, 95% percentile 구간. 누락 쌍이 있으면 전체 차이·CI는 NA이고 부분 차이만 제공한다. 표의 방문 평균과 paired의 환자 균등 가중 평균은 다를 수 있다.
- “정확도 유지”를 주장하려면 사전에 허용 감소 폭을 정하고 충분한 표본에서 비열등성을 평가해야 한다. 차이가 유의하지 않거나 작은 예제에서 같다는 사실만으로 유지가 입증되지 않는다.

## 6. Router Regret의 별도 실험

같은 관측을 모든 후보 전문과에 제공한 사후 결과가 있어야 oracle을 계산할 수 있다. 단일 trajectory의 선택 로그만으로 생성하지 않는다. 저장된 toy 응답으로 경로를 점검하려면:

```powershell
python -m app.scripts.routing_research evaluate --registry app/data/research_synthetic_v1/registry_local.json --data app/data/research_synthetic_v1/routing_test_bounded.json --utility app/data/research_synthetic_v1/routing_utility_bounded.json --output outputs/paper_router_check_01.json
```

본 실험은 [7·9번 수집 안내](research_7_9_completion.md)에 따라 새로운 train/test probe 응답을 수집하고 fit/evaluate를 실행한다. 현재 저장 toy 결과는 과거 실행 재평가임을 표에 명시한다.

## 7. 논문 문장 수정 권고

1. 식 (7)의 VoI 임계값만으로 종료하는 설명은 현재 코드와 다르다. 현재는 객관적 증거 + stop_probability 충족 시 확진하며, 근거가 부족하면 기존 예산·미해결 종료 조건을 따른다. VoI가 음수라도 종료할 근거가 없으면 진행할 수 있다.
2. Adaptive Routing은 호출할 전문과 후보 메뉴를 제한하고, ER이 실제 협진 여부·시점을 결정한다. 항상 Specialty Agent를 호출하는 그림과 구분한다.
3. “120개 테스트 통과”는 이번 실행 결과로 갱신할 수 없다. 이번에는 최소 검사만 실행한다. 본인이 전체 회귀를 실행한 시점의 실제 개수를 기록한다.
4. 진단 평가는 문자열 정규화/허용 별칭 비교다. 자유로운 진단 문장의 임상적 동일성을 자동 판정했다고 쓰지 않는다.
5. 3페이지에서는 설정표 + B0~B4 핵심 결과표 + paired 효과 그림에 집중하고, 세부 coverage·실패 분석은 별첨/저장소에 둔다. 논문에 실제로 실행하지 않은 실험 결과를 채우지 않는다.
