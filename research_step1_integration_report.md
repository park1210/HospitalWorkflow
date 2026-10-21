# Research STEP 1 — 실제 실행 통합 결과

작성일: 2026-10-22. 범위: STEP 1만 구현. STEP 2~4의 새 구현은 진행하지 않았다.

## 1. 기존 상태와 변경 범위

작업 전 Git 변경 사항을 확인했다. 이미 수정되어 있던 수학 모델, 평가 모듈, 테스트는 보존했다. 아래 표는 Git 전체 diff가 아니라 **이번 작업에서 추가로 수정한 파일**만 표시한다.

| 파일 | 이번 변경 |
|---|---|
| `app/core/agent_registry.py` / `select_specialty` | `adaptive`를 실제 primary selection 옵션에 추가. 기존 `route(mode='adaptive')`와 추정 정확도 계산을 재사용. Rule과 Adaptive의 이름 및 점수 의미를 구분. 비용·지연을 사용한다는 오래된 설명 수정 |
| `app/core/hospital_llm_policy.py` / `_decision` | primary router가 `adaptive`일 때 registry 결과를 실제 실행 specialty/model binding에 연결 |
| `app/core/longitudinal_runner.py` / `run_longitudinal` | `primary_router='adaptive'` 허용. 이전 실행 checkpoint와 혼합하지 않도록 clinical policy revision 갱신 |
| `app/core/information_value.py` / `InformationPolicy.propose` | encounter의 모델 후보를 공통 실행 가능 후보와 교집합 처리. 아직 공개되지 않은 질문·실제 사건에 없는 질문을 planning에서 제외. 근거 없는 Diagnose가 호출자의 unresolved 허용 조건을 무시하지 않도록 방어 |
| `app/scripts/run_longitudinal_research.py` / `main` | 기존 CLI에 `--primary-router` 추가하여 실제 primary Adaptive 실행 가능 |
| `tests/test_research_step1_runner.py` | 신규 통합 테스트 5개 |
| `research_step1_integration_report.md` | 본 보고서 |

기존 `routing-mode`는 consultation 메뉴 제어에도 사용된다. `routing-mode=adaptive`만 지정했다고 primary doctor까지 Adaptive인 것으로 해석하면 안 된다. 실제 primary doctor 선택은 **`primary_router=adaptive` / `--primary-router adaptive`**로 명시한다. 기존 기본값 `rule_similarity`는 유지했다.

## 2. 재사용한 수학 및 실행 구조

### Memory

`longitudinal_memory.PatientMemoryStore.retrieve` → `longitudinal_runner.refresh_memory` → `HospitalLLMPolicy._decision` → 의사 payload의 `observation.longitudinal_memory`.

- 같은 patient의 과거 visit만 후보로 사용하고, visit 시작 시점 이후에 이용 가능한 기록은 제외한다.
- Selective/Semantic retrieval은 superseded 기록을 제외한다.
- 기존 lexical/semantic 점수, 양의 점수 조건, top-k, 정렬 규칙은 변경하지 않았다.
- 의사 호출 audit의 `memory_context`에 기록 ID/점수를, `retrieval_query`에 실제 검색 입력을 남긴다.
- **Full History는 기존 비교 조건을 보존하므로 superseded 기록도 상태를 표시해 포함한다.** 모든 memory mode에서 superseded 기록을 제거한다고 기술하면 부정확하다.

### Routing

`AgentRegistry.select_specialty(router='adaptive')` → 기존 `route(mode='adaptive')` → `RoutingUtility.score` → 실제 선택된 specialty의 registry model 호출.

\[
\hat p(s\mid x)=\frac{1+\sum_i J(x,x_i)y_{i,s}}{2+\sum_i J(x,x_i)},\qquad s^*=\arg\max_s\hat p(s\mid x).
\]

기존 최소 학습 표본 조건을 유지한다. 모든 후보에 필요한 fitted support가 없으면 abstained와 selected_specialty=None을 기록하고 기존 ER decision loop를 사용한다. Rule 선택으로 몰래 대체하지 않는다. v1의 비용·지연 필드는 추정 정확도나 선택 점수에 사용하지 않는다.

### Multi-Step VoI

`InformationPolicy.propose` → `InformationOutcomes.observe` → `select_action` → 기존 `plan_voi`를 재사용한다.

\[
V_0(b)=\max_{\hat d}\sum_d b(d)U(\hat d,d)
\]
\[
V_h(b,A)=\max\left(V_0(b),\max_{a\in A}\sum_o P(o\mid a,b)V_{h-1}(b'_o,A\setminus\{a\})\right).
\]

- Horizon은 artifact의 1~3 값을 사용한다. 계산에는 비용·지연 penalty가 없다.
- 실제 공개된 관측으로 prior에서 posterior를 갱신하고, 다음 decision 시 재계획한다.
- planning은 모델의 outcome likelihood만 사용한다. source event의 숨겨진 실제 결과를 읽어 branch를 선택하지 않는다.
- 이미 관측된 모델 action은 consumed로 제거하고, runtime이 제공하는 미수행·시간/자원상 가능한 후보와 교차한다.
- Diagnose가 최선이어도 objective evidence gate를 통과하지 못하면 supported diagnosis로 기록하지 않는다. 허용된 경우 Unresolved 종료, 그렇지 않으면 selector unavailable을 반환한다.
- v2 cost-free artifact와 v1 호환 로딩은 기존 구현을 유지했다.

## 3. 실제 실행 흐름 및 로그

현재 공개 상태 → memory refresh → primary routing → 해당 specialty/ER Agent의 검증된 제안 → 현재 실행 가능 후보의 VoI 비교 → 선택 행동 → scheduler 실행 → evidence 공개 및 시간 진행 → 상태 갱신 → 다시 routing/VoI 계산.

Encounter 경로의 기존 specialty 호출을 보존했다. 따라서 현재는 specialty 제안을 받은 뒤 명시적 VoI 모델로 행동을 선택한다. 수학 정책이 있어도 specialty 호출을 완전히 없애는 구조는 아니다. 새로운 LLM 호출은 추가하지 않았다.

주요 저장 위치:

- `voi_state.initial_primary_routing`, `primary_routing_history`: 선택/abstention 및 근거.
- `llm_audit[].routing.executing_agent`: 실제 agent/model/version binding.
- `llm_audit[].decision`, `candidate_actions`, `selector_status`: 실행 행동·근거·정책 상태.
- `voi_state.history[]`: 현재 belief, matched outcomes, horizon, 후보 Q/IG/VoI, 선택 결과.
- `llm_audit[].memory_context`, `retrieval_query`: 실제 전달한 memory와 query.

## 4. 검증 결과

Python **3.9.7**에서 실행했다. 실제 Ollama나 외부 API를 호출하지 않았다. 기존 runner/scheduler를 사용하되 LLM만 `ScriptedSpecialist` 테스트 대역으로 교체했다.

| 검증 | 결과 |
|---|---|
| 변경 전 `python -m unittest discover -s tests -q` | 230 통과 / 0 실패 |
| 변경 후 같은 unittest 실행 | 235 통과 / 0 실패 |
| 전체 `python -m pytest tests -q` | **239 통과 / 0 실패** (22.92초) |
| 기존 CLI `--help` 확인 | 새 `--primary-router` 선택지 노출 |

pytest에는 unittest discover에서 실행하지 않는 함수형 Memory benchmark 테스트 4개도 포함된다. 두 통과 수를 합산하면 안 된다.

신규 테스트:

1. **실제 Runner Horizon 차이 및 재계획**: D0~D3 균등 prior. A_screen은 각 정답 출력 확률 .7, 나머지 각 .1. B_axis/C_axis는 각각 서로 다른 이진 분할을 알려준다. H1은 A_screen, H2는 B_axis를 실제 첫 행동으로 실행한다. H3도 실행·완료를 검증한다. H3에서는 여러 첫 행동이 최적값 1에 도달하므로 유일한 첫 행동을 요구하지 않는다. 관측 후 belief 변경, 수행 action 재선택 방지, 최종 D0, 시뮬레이션 시간 증가를 검증한다.
2. **Adaptive binding/abstention**: rule과 다른 pulmonology를 fitted model이 선택하도록 구성하고 실제 호출 model이 registry와 일치함을 검증한다. fitted artifact가 없으면 abstained 후 ER 호출을 검증한다.
3. **실행 불가능 질문과 gate**: 아직 이용 불가능한 질문과 source에 없는 질문이 planning 후보에 들어가지 않음을 검증한다. 근거 없는 확정 진단도 방지한다.
4. **Memory 실제 전달**: top-1 replacement 기록만 doctor payload와 audit에 전달되고 old/superseded 및 미래 이용 가능 기록은 제외됨을 검증한다.
5. **미래 관측 분리**: 실제 숨겨진 결과만 바꿔도 초기 planning Q/선택은 동일하고, 결과 공개 후 belief는 달라짐을 검증한다.

신규 테스트 작성 중 질문 표적에 `?`가 필요하다는 스키마 조건, memory supersession의 선행 기록 조건을 반영해 fixture를 수정했다. 기존 테스트는 삭제하거나 약화하지 않았다.

재실행:

```powershell
python -m unittest discover -s tests -p test_research_step1_runner.py -v
python -m pytest tests -q
```

실제 연구 실행 시 기존 `run_longitudinal_research` 명령에 `--primary-router adaptive --routing-utility <fitted artifact> --action-selector bayesian_voi --voi-model <outcome artifact>`를 지정한다. Horizon은 outcome artifact에 설정한다. 데이터와 registry에 맞는 검증된 artifact 경로를 사용해야 하며, 이번 categorical fixture는 임상 평가용 데이터가 아니다.

## 5. 남은 한계 및 다음 단계

- 테스트는 구현 통합과 수학 동작을 검증한다. 실제 모델 응답 품질, 임상 정확도, 임상적으로 검수된 likelihood/utility를 입증하지 않는다.
- strict encounter 경로는 기존 `prepare_encounter`에서 legacy temporal_profile을 arrival-only로 바꾼다. 검사 대기·결과 공개·scheduler 시간은 유지되지만, **이 경로에서 임의 증상 악화 모델까지 작동한다고 주장할 수 없다**. legacy 환자 진행 엔진은 변경하지 않았다. 시간별 증상 사건을 encounter로 확장하려면 별도 명세가 필요하다.
- Full History의 superseded 포함은 기존 baseline 의미를 보존하기 위한 예외다. Selective/Semantic과 구분해야 한다.
- 현재 후보 집합 내 계획이다. 미래에 새로 해제될 action이나 자원 상태 변화 자체를 Bellman transition으로 예측하지 않는다. 실행 후 현재 상태로 다시 후보를 구성한다.
- 모델에 없는 공개 관측/후보가 있으면 VoI unavailable을 기록하고 기존 specialist heuristic으로 돌아간다. 임의 likelihood를 생성하지 않는다.
- planner의 기존 최대 action 12개/state 20,000 제한 및 conditional likelihood 가정은 유지한다.
- 다음은 STEP 2: **이미 존재하는** evaluation 모듈부터 검토하고, undefined 처리·유효 분모·환자 단위 bootstrap 등의 실제 부족분만 구현한다. STEP 3~4는 이후 진행한다.
