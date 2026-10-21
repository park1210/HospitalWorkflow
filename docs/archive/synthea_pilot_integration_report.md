# Synthea pilot 연결 보고서

## 1. 작업 범위와 실제 입력

기존 architecture, simulation loop, Memory/Routing/VoI 수식은 이번 작업에서 수정하지 않았다.
새 adapter와 실행/검증 도구만 추가했다. 실제 LLM 호출은 하지 않았다.

요청 이름은 `pilot_base_cases(1).jsonl`이지만 실제로 발견된 입력은 프로젝트 최상위
`pilot_base_cases.jsonl`이다. `(1)` 파일과 동일한 파일인지는 확인되지 않았으며
이 보고서와 provenance는 **실제로 읽은 파일**을 가리킨다.

원본 SHA-256 (변환/검증 전후 동일):

```
2fb223716a62f9206ca09272960e0971312c31e8138c05adaba95f83ec4d77cc
```

원본 크기 11,147,571 bytes. 원본을 수정/재직렬화/덮어쓰지 않았다.

## 2. 생성 파일

| 파일 | 내용 |
|---|---|
| `app/data/synthea_adapter.py` | 원문 보존, temporal boundary, source-event mapping |
| `app/scripts/prepare_synthea_pilot.py` | 스키마 분석, 15개 변환 검증, offline boundary smoke |
| `app/data/synthea_pilot_encounters.json` | runner 입력 15개, 원본 보존 포함 32,701,813 bytes |
| `synthea_pilot_schema_analysis.md` | 실제 필드/건수/분포 분석 |
| `outputs/synthea_pilot_adapter/validation.json` | 자동 변환 검증 결과 |
| `outputs/synthea_pilot_adapter/offline_smoke.json` | 3개 사례 × 3개 memory 조건 trace |
| `tests/test_synthea_adapter.py` | annotation 불변성, 시간·환자 경계, source 보존 등 검사 |

## 3. 스키마와 mapping

모든 15개 사례에 case_id, patient_id, index_encounter_id/start/class,
gold_condition_code/description, primary_specialty, acceptable_specialties,
past_visits, current_encounter_events, task_eligibility, annotation_metadata가 있다.
원본에 demographics, chief_complaint, current_initial_state 필드는 없다.

| 원본 | 변환 |
|---|---|
| case_id | 동일 |
| patient_id | longitudinal.patient_id |
| index_encounter_id/start | 동일 |
| index_encounter_class | current_initial_state.doctor_visible_info.arrival_info |
| primary_specialty / acceptable_specialties | 동일한 top-level 평가 metadata |
| gold_condition_code/description | evaluation 아래 |
| annotation_metadata / task_eligibility | top-level 평가 metadata |
| past_visits | 기존 visit_id/started_at/records 구조 |
| current_encounter_events | 실행 가능한 strict source-event interface |
| 원본 과거 방문 전체 | source_past_visits (완전 보존) |
| 원본 현재 event 전체 | source_current_encounter_events (완전 보존) |
| event timestamp/type/code/description/file/row | source_event_metadata[event_id] |

현재 prepare_encounter는 event 필드 집합을 엄격하게 검사한다.
이를 수정하지 않기 위해 실행 event에는 기존 5개 필드
`event_id/action/target/available_minute/evidence`만 넣고 추가 provenance는
event_id로 연결되는 metadata에 보존했다.
source_provenance에는 실제 파일명/hash/synthea=true/adapter_version=v1을 기록했다.

## 4. current_initial_state 규칙

- encounter class만 arrival_info에 복사.
- 존재하지 않는 나이, 성별, 주호소, 증상, 진단을 추론하지 않음.
- initial vitals는 index 시작과 정확히 같은 timestamp의 observations 중
  BP/HR/RR/temperature/SpO2 코드의 유한 숫자 값만 허용.
- 같은 시각 또는 그 이전에 procedure/medication이 있으면 전후 순서를 확정할 수 없어
  initial vital로 투영하지 않음. 날짜 단위 event도 초기 정보로 쓰지 않음.
- laboratory, survey 결과와 procedure/medication 이후 결과는 초기 정보에서 제외.
- reason 필드 및 평가 annotation은 초기 관찰에 포함하지 않음.
- 초기 값 출처는 initial_state_source_event_ids로 추적.

**보수적 규칙 적용 결과 15개 모두 초기 vital 없음, 주호소 없음.**
current_initial_state는 encounter class와 빈 patient_visible_info 수준이다.
이것은 adapter가 증상을 보충해야 한다는 의미가 아니라 원본 초기 정보가 부족하다는 뜻이다.
data_limitation에 이를 기록했다.

## 5. past_visits 규칙

과거 방문 1,855개, event 25,681개를 모두 보존했고,
실행용 memory record도 25,681개 생성했다. 긴 history를 자르지 않았다.

- index 이전의 다른 방문만 허용.
- patient ID가 명시되어 있으면 현재 환자와 일치해야 함.
- memory_id는 patient_id + 원본 event_id, source_id는 원본 event_id.
- observations → objective_finding, conditions → prior_assessment, 나머지 → history.
- record text는 원본 data의 JSON 직렬화. 값을 요약하거나 새로운 의학적 문장을 만들지 않음.
- source data의 reason/gold annotation 필드와 index 이후의 stop/end/start/date 값을
  runtime text에서 제외. 원본은 source_past_visits에 그대로 보존.
- 3,724개 record에서 이런 필드 제거가 있었으며 removed_fields에 기록.

### 날짜 단위 과거 event

기존 memory schema는 timezone timestamp를 요구한다.
날짜-only 기록의 원래 날짜는 source_past_visits와 past_record_metadata.timestamp에 보존했다.
runtime available_at/observed_at에는 **다음 날 00:00 UTC라는 보수적 이용 가능 상한**을 사용한다.
이는 실제 발생시각 추정이 아니며 availability_policy에 명시한다.
상한이 index 이후이면 실행 memory에서 제외하되 원본 보존은 유지한다.
이 파일에서는 원본 과거 event 전체가 투영 가능했다.
따라서 원래 날짜의 시각 순서를 복원했다고 해석하면 안 된다.

## 6. 현재 event → action

원본 현재 event는 860개:
observations 608, procedures 78, medications 71, careplans 7,
immunizations 5, supplies 70, devices 18, imaging_studies 3.
datetime 783개, date 77개.

| 원본 | 동작 |
|---|---|
| value가 있는 observation | Test evidence |
| imaging_studies | Test evidence: 영상 획득 metadata만, 판독 결과 생성 안 함 |
| diagnostic assessment/exam/imaging/testing 등 명칭의 procedure | Test evidence: 수행 사실만 |
| 치료 procedure/medication 등 | 실행 후보로 만들지 않고 원본 보존 |
| date-only 현재 event | available_minute=null, timing_precision=date, 실행에서 보류 |
| Ask/Consult 근거 | 원본에 없어 생성하지 않음 |
| gold condition | Diagnose evidence로 만들지 않음 |

결과: **641개 Test event**, **219개 보존 전용 event**.
Ask/Consult/진단 결과를 억지로 만들지 않았다.
원본 전체는 보존되므로 보류된 이벤트가 삭제된 것은 아니다.

Test target은 원본 description 또는 modality description에 event_id를 붙여
반복 측정을 구분한다. target에 결과 value나 gold annotation을 넣지 않는다.
evidence는 reason/evaluation 필드를 제외한 원본 data의 JSON이며 정상/비정상 판정을 덧붙이지 않는다.
procedure 수행 기록은 유효한 진단 결과와 같지 않다. 기존 objective evidence gate가
텍스트의 존재를 받아들이더라도 임상 확진 근거라고 주장할 수 없다.

### 시간

datetime event: `ceil((release_timestamp - index_start)/60)`를 사용.
기존 정수 분 시계에서 원본보다 이르게 공개하지 않기 위한 올림이다.
procedure에는 완료 timestamp가 있으면 시작보다 늦은 완료시각을 적용한다.
원본 초 단위 timestamp는 그대로 별도 보존한다.
날짜-only 현재 event에는 임의 minute를 부여하지 않으며 실행에서 보류한다.

원본 시간은 기록 시각이지 검체 접수/판독 완료/의사 열람 시각이라는 증거는 없다.
별도 검사 resource_profile을 만들어내지 않았으므로 실제 runner의 자원 점유/기본
검사 시간은 기존 시뮬레이션 설정이다. Synthea에서 실측된 latency로 해석하면 안 된다.

## 7. 누수 방지

- gold/specialty/annotation metadata는 agent projection에 포함하지 않는다.
- source_* 전체, source_event_metadata도 doctor_observation에 투영하지 않는다.
- 과거 임상 기록에 실제로 포함된 질환명은 gold annotation이 아니므로 임의 삭제하지 않는다.
- 원본 annotation을 바꾸어도 초기 상태, runtime memory, 실행 event가 바뀌지 않는 검사를 추가했다.
- 초기 projection에 미래 결과가 없고, 실행 evidence가 원본 event에서 유래함을 검증한다.
- action catalog는 현재 encounter의 기록된 검사 목록을 재생 후보로 사용한다.
  **주문 가능 시각/주문 시각이 없으므로, prospective workflow의 후보 가용성을 검증한 것은 아니다.**
  미래 결과 본문은 감추지만 미래에 기록될 검사 이름이 후보 목록에 들어갈 수 있다는 한계가 있다.

## 8. Offline smoke 결과

심장내과 1개, 호흡기내과 1개, 외과 1개를 골라
none/full_history/selective 각 1회, 총 9회 기존 run_longitudinal을 실행했다.
baseline은 shared department catalog 기반의 offline registry로
RuleSimilarityRouter를 호출했다. 입력 라벨에서 router keyword/model binding을 만들지 않았다.

**실제 모델 binding은 OFFLINE_UNBOUND이며 추론/네트워크 호출 0회.**
ModelBoundary test client가 실제 role_call 진입 시 payload를 검증하고 의도적으로 중단한다.
따라서 원래 runner_status는 failed이고, trace_status는 stopped_before_model_call이다.
이를 simulation 완료/모델 성공으로 집계하면 안 된다.

| 라벨 기준 선택 사례 | none memory | full_history memory | selective memory | 최초 action 후보 수 |
|---|---:|---:|---:|---:|
| cardiology | 0 | 1,946 | 0 | 40 |
| pulmonology | 0 | 1,289 | 0 | 1 |
| surgery | 0 | 635 | 0 | 2 |

초기 query가 비어 있어 selective 검색 0건.
none/selective 라우팅은 모두 score 동점 규칙으로 cardiology를 선택했다.
full_history에서는 cardiology/internal_medicine/cardiology가 선택되었다.
이는 실제 라우팅 정확도 결과가 아니며, 평가 라벨로 강제 라우팅하지 않았음을 보여준다.
offline keyword registry는 임상 전문과 분류기로 검증되지 않았다.

full_history prompt 문자 수:
1,305,690 / 857,661 / 424,950. 토큰 수와는 다르며 실제 모델 context budget을 초과할 수 있다.
원본을 삭제하지 않고 향후 기존 max_memory_chars 등 실험 설정으로 제어해야 한다.

## 9. 검증 및 재실행

실행한 변환/전체 검증:

```
python -m app.scripts.prepare_synthea_pilot --smoke
```

같은 output은 덮어쓰지 않는다. 재실행하려면:

```
python -m app.scripts.prepare_synthea_pilot --source pilot_base_cases.jsonl --output outputs/synthea_encounters_next.json --smoke
python -m unittest discover -s tests -p test_synthea_adapter.py -v
```

자동 검증: 15개 case, ID 중복 없음, 환자/index 일치, 과거 경계,
source 전체 보존, evidence 원본 일치, nonnegative minute, initial source 시각,
annotation 불변성, 원본 hash 불변성.
추가 adapter 단위 검사 7개 모두 통과했다.
정확한 검증값은 validation.json, smoke payload/routing/candidate trace는 offline_smoke.json 참조.

## 10. 다음 실제 LLM 단계와 사용 불가 범위

현재 변환 파일은 기존 runner로 읽을 수 있다.
다만 실제 LLM 실행 전에 다음을 준비해야 한다.

1. source에 존재하는 초기 complaint/triage observation을 추가 추출할 수 있는지 확인.
   gold description에서 증상을 만들면 안 된다.
2. 필요한 전문과별 실제 model registry를 설정.
   기존 challenge registry는 신경과/호흡기내과만 있으므로 8개 label specialty 전체를 지원한다고 볼 수 없다.
3. 원본 history를 보존한 채 입력 budget을 사전에 결정하고 기록.
4. 먼저 3개 subset만 별도 파일로 추출하여 기존 CLI에서 실행.
   `--action-selector specialist_heuristic`을 사용하고 새 output 경로 지정.
5. action catalog와 관찰 공개시각을 prospective 정보로 해석하려면 주문/가용 시각 자료가 필요.

예시 (경로는 사용자가 준비할 subset/실제 registry):

```
python -m app.scripts.run_longitudinal_research --cases outputs/synthea_three_cases.json --output outputs/synthea_live_next.json --memory-mode selective --top-k 1 --memory-source fixed --agent-registry PATH_TO_REAL_REGISTRY.json --routing-mode adaptive --action-selector specialist_heuristic --minute-limit 120 --max-retries 0 --trace
```

이번 작업에서는 위 실제 실행을 하지 않았다.
Bayesian outcome model을 생성하지 않았다. 기록된 event는 counterfactual likelihood가 아니다.
Bayesian selector를 요청하면 기존 구현의 unavailable/missing_outcome_model 상태와
실제 heuristic 사용 표시가 유지된다. VoI/IG 성능 실험은 아직 할 수 없다.
