# Ask/Test 이벤트가 연결된 100개 재생 데이터

기존 100명·100개 사례와 전체 과거 기록, 과별 최대 20% 분포를 유지했다. 원본에 있는 환자 보고값과 검사값을 기존 실행기의 정확한 `{event_id, action, target, available_minute, evidence}` 구조로 연결한다. 원본 v1 및 모델 프로젝트를 덮어쓰지 않는다.

## 모델 프로젝트에서 바꿀 데이터 경로

기존 `ready_100_v1/cases.json` 대신 새 폴더의 **`cases.json`**을 읽는다. 함께 제공한 `memory.json`, `labels_observed.json`, `departments_source_policy.json`을 사용한다. 새 폴더를 모델 프로젝트로 복사하거나 아래 절대 경로를 입력 경로로 지정할 수 있다.

```text
C:\Users\wondt\2026\001_Lecture\007_thesis\001_synthea-docker\experiments\24_action_replay_100\output\action_replay_100_v1
```

모델 측 자료 경로를 이 폴더로 실제 바꾸어야 한다. 기존 합성 데이터로 실행하는 기본 명령은 자동으로 이 자료를 사용하지 않는다. `run_paper_experiments.py`의 B3/B4 wiring, registry/routing utility/VoI model은 이 데이터 변경과 별도다. 새 데이터만으로 그 artifact가 생성되지는 않는다.

**모델·simulator·LLM·테스트는 실행하지 않았다.** 데이터 생성과 원본 hash/연결/파일 구조 대조만 수행했다. 실제 모델 실행은 사용자가 한다.

## 무엇이 달라졌는가

- 100개 모두 실제 환자 보고 observation을 응답으로 연결한 Ask 이벤트를 가진다.
- 초기에는 원본의 증상명만 표시한다. 통증 점수는 `What was your most recently reported pain score?`에 대한 source 응답에서 얻는다.
- 응답은 원본 code/description/value/units/기록 시각의 deterministic JSON이다. 원본 대화록이나 새 임상 면담을 생성한 것이 아니다. 자유로운 모든 질문을 답하는 환자 모델도 아니다.
- 실제 observation 값은 Test 결과로, diagnostic procedure는 수행 사실로만 연결한다. 없는 검사값·영상 판독·treatment response·Consult note는 만들지 않는다.
- 약물은 Test로 바꾸지 않는다. 실제 Test source가 없는 case에 검사를 만들어 넣지 않는다. 실제 수는 `replay_summary.json`에 있다.
- evaluation 정답은 초기 정보나 응답에 복사하지 않는다. 검사 원본의 실제 결과가 진단을 뒷받침할 수는 있지만, evaluation 파일에서 결과를 생성하지 않는다.

## 최신 시각을 사용하는 방법

기본 `cases.json`은 **latest-within-index snapshot replay**다. 같은 환자의 해당 index encounter 안에서 **검사 종류별 최신 기록값**을 고르고, 요청하면 그 값을 반환할 수 있도록 `available_minute=0`으로 둔다. 같은 시각에 상충하는 값이 있으면 모두 유지한다.

이는 사용자가 허용한 최신 상태 재생 가정이다. 실제 검사 결과가 방문 시작에 공개되었다고 주장하지 않는다. 초기 doctor 입력에 그 검사값을 넣지 않으며 요청 후에만 evidence로 반환한다. 실제 `start_time`, 과거 Memory, original decision time을 최신 시각으로 변조하지 않는다. 최신 snapshot reference 시각은 `data_replay`와 audit에 따로 기록한다. 다른 방문이나 미래 follow-up의 마지막 값을 현재 방문에 가져오지 않는다.

증상은 original decision time 이하에서 실제 기록된 patient report의 최신값만 사용한다. raw JSON의 최종 resolved 상태를 과거 상태로 간주하지 않으며, update 시각을 onset이나 duration으로 바꾸지 않는다.

대체 파일 `cases_recorded_time_proxy.json`도 제공한다. 여기는 원본 시각 구간 상한과 index 시작의 차이를 분으로 올려 `available_minute`에 연결한다. 이 또한 **기록 시각 기반 proxy**이며 실제 release time은 아니다. 긴 실제 간격이 들어갈 수 있어 기본 snapshot보다 실행 제한 시간에 걸릴 가능성이 크다. 원본 시각을 짧게 압축하지 않았다.

두 시간 정책을 한 실험에서 섞지 않는다. snapshot 정책에서 얻은 결과를 임상 시간순 정보 획득의 인과적 VoI 검증으로 해석하지 않는다. 기존 실행기의 기본 turnaround/resource duration은 그대로 적용되므로 `available_minute=0`이 모델 내 대기 시간이 무조건 0이라는 의미도 아니다.

## 파일과 공개 범위

| 파일 | 용도 |
|---|---|
| `cases.json` | 기존 prepare_encounter 형식, snapshot 정책 |
| `cases_recorded_time_proxy.json` | 같은 100개, 기록 시각 proxy 정책 |
| `memory.json` | v1의 전체 과거 기록 그대로 |
| `patient_states.jsonl` | patient 전용 원본 보고 fact. doctor prompt에 전체 전달 금지 |
| `event_audit.jsonl` | 각 생성 이벤트의 원본 연결·원본 시각·재생 가정, environment/검수 전용 |
| `environment.jsonl`, `provenance.jsonl` | v1 원본 source 및 미채택 후보 그대로 |
| `labels_observed.json`, `departments_source_policy.json`, `annotations.jsonl` | 평가/분석 전용, 미검수 상태 유지 |
| `case_event_summary.csv`, `replay_summary.json`, `replay_report.md` | case별 Ask/Test 수·누락 이유·한계 |

`cases.json` 전체를 LLM에 보내지 않는다. 현재 실행기는 `prepare_encounter`와 역할별 projection을 거쳐야 한다. 기존 모델은 Test 이벤트 이름 전체를 `available_tests`로 공개한다. 이 **source에 의존한 action catalog 편향은 native 호환 버전에 남아 있다.** 데이터 파일만 바꾸어서 모델 내부의 이 동작까지 제거하지는 않았다.

Test 이름도 초기 doctor 입력에서 숨기는 strict 계약은 동봉한 `replay_loader.py`로 제공한다. `ReplayDataset.doctor_input(case_id)`는 Test 이름과 evidence를 공개하지 않는다. 신뢰된 environment만 `source_evidence(case_id, action, target, minute)`로 실제 선택한 source를 조회한다. 이 로더는 데이터 접근 계층이며 검색/routing/VoI 모델이나 simulator가 아니다. 기존 모델이 이 로더를 사용하도록 연결하는 작업은 별도다.

## 남아 있는 제한

문진 내용은 실제 통증 점수에 한정된다. 없는 통증 부위·기간·동반 증상에 대한 질문을 무리하게 추가하지 않았다. 기존 실행기는 등록된 질문과 정확히 일치하는 target만 받으므로 제공된 질문 목록을 사용해야 한다. 실제 source가 없는 Consult 응답은 계속 없음으로 남는다. Source-observed 진단/과 후보와 사람이 확정한 clinical gold는 구분하며 relevance/stale/VoI gold는 추가하지 않았다. Routing/VoI 모델의 학습과 paper runner 조건 연결도 여전히 필요하다.

## 재생성

이미 생성된 파일 또는 압축본을 사용하면 된다. 새 재생 정책으로 다시 생성할 때는 새 output 경로를 사용한다.

```powershell
python experiments/24_action_replay_100/build_action_replay.py --output experiments/24_action_replay_100/output/action_replay_100_v2
```
