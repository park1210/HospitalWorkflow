# 기존 구조 분석 — 2026-10-21

## 현재 파일별 역할

| 영역 | 기존 파일 / 진입점 | 역할 |
|---|---|---|
| Memory | `app/core/longitudinal_memory.py: PatientMemoryStore` | 환자·방문·이용 가능 시각 필터, none/full_history/selective/semantic, supersedes |
| 벡터 | `app/core/memory_retrieval.py: MemoryEmbeddings`, `embedding_builder.py` | 사전 저장 벡터 검증/코사인 검색, Ollama 임베딩 생성 |
| 연구 실행 | `app/core/longitudinal_runner.py: run_longitudinal` | 방문 순서, 메모리 연결, registry, checkpoint/recovery |
| 실행 CLI | `app/scripts/run_longitudinal_research.py`, `run_paper_experiments.py` | 단일 연구 / B0–B4 비교 |
| ER/전문과 정책 | `app/core/hospital_llm_policy.py: HospitalLLMPolicy._decision` | 관찰 projection, 역할별 모델 호출, schema 검증, 행동 반환 |
| 기존 독립 Agent | `app/agents/er_department_agent.py`, `specialty_agent.py`, `patient_agent.py` | 별도 기존 simulator의 역할 구현 및 추출식 환자 응답 |
| 라우팅 | `app/core/agent_registry.py: AgentRegistry.route`, `routing_utility.py` | 모델/전문과 binding, keyword baseline, fitted utility |
| Specialty/LoRA 실행 | registry의 model → `role_call` → `OllamaClient` | 등록된 전문과 모델 호출. 어댑터를 매번 로딩하는 구조가 아니라 배포된 Ollama 모델 이름으로 선택 |
| VoI | `app/core/information_value.py: InformationPolicy`, `information_outcomes.py`, `diagnostic_belief.py` | 명시적 outcome model, belief 갱신, finite-horizon 가치/IG, stopping |
| 상태 | `hospital_case_runtime.py`, `hospital_scheduler_state.py` | 질문/검사/협진/메모리/VoI/audit/자원/가상시간 |
| 주 루프 | `hospital_parallel_scheduler.py: step/run_until` | 사건 큐, 진료, 검사 자원 배정, 결과 도착, 종료 |
| Environment | `HospitalLLMPolicy.build_objective_finding`, `PatientAgent`, scheduler 결과 handlers | 입력 검사 결과 공개, 환자 fact 선택, 상태 갱신 |
| 다른 진입점 | `app/main.py`, `app/core/simulator.py`, UI/시각화 scripts | 유지. 이번 변경의 주 대상은 longitudinal + parallel LLM 경로 |

## 수정 전 실제 흐름

방문 시작 → chief_complaint로 메모리 1회 검색 → ER 관찰 → 라우터가 협진 메뉴 제한
→ ER에서 VoI가 직접 결정하거나 ER 모델 호출 → 질문/검사/협진/진단
→ 협진 선택 때만 전문과 모델 호출 → scheduler가 결과·상태 갱신.

현재 adaptive utility는 accuracy 가중 추정 성공률에서 비용/지연 penalty를 차감한다.
VoI는 `ask_patient/request_test/consult_specialty`를 이미 지원하며 T_LOW/T_HIGH는
코어 규칙이 아니라 기존 challenge fixture의 검사 이름이다.
과거 실험 입력/결과를 삭제하거나 덮어써서 이 이름을 없애면 재현 자료가 훼손된다.

## 최소 수정 계획

1. 기존 observation 모듈에 encounter 입력 정규화 및 source-event 조회 함수 추가.
   `index_encounter_id/start`, `past_visits`, `current_initial_state`,
   `current_encounter_events`, `primary_specialty`를 지원한다.
   primary_specialty는 평가용이며 라우팅 입력으로 사용하지 않는다.
2. 기존 retrieval 함수를 유지하고 encounter에서는 현재 공개 상태로 query를 구성하여
   각 의사 결정 전에 다시 검색한다. 기존 chief-complaint 입력과 비교 모드는 유지.
3. RoutingUtility 이름/학습 자료 호환은 유지하되 선택 점수에서 cost/latency penalty 제거.
   기존 성공률 estimator 또는 기존 keyword score의 argmax로 전문과를 선택한다.
4. encounter 경로에서는 선택된 전문과 모델을 기존 role_call로 실제 호출한다.
   이후 공통 Ask/Test/Consult/Diagnose 후보를 기존 selector에 연결한다.
5. 기존 scheduler와 결과 handlers를 재사용한다. encounter에서는 저장된 event에서만
   질문/검사/협진 evidence를 공개하며 시각·target을 검증한다.
6. 기존 CLI에서 작은 encounter pilot을 실행한다. 실제 호출과 mock 검증을 구분한다.

## 그대로 유지할 부분

폴더 구조, 기존 파일, 기존 사례/결과, 스케줄러 자원/시간/완료 처리,
memory 필터/유사도 알고리즘, registry 모델 binding, Ollama 호출,
LLM audit, evidence grounding, checkpoint/recovery, B0/B1/B2 비교 인터페이스.

## 확인된 주의점

- 작업 시작 시 여러 파일에 기존 미커밋 수정이 있다. 이 수정들을 되돌리지 않는다.
- `longitudianl_memory` 오타로 추가 memory instruction이 실행되지 않는 부분은 수정 대상.
- 새 encounter 모드는 과거 논문 결과와 다른 실행 계약이다. 과거 결과를 새 구현 성능으로 해석하지 않는다.
- 기존 semantic artifact는 chief complaint hash에 묶여 있다. 확장 query에는 일치하는 새 벡터가 필요하며
  불일치 시 임의 lexical fallback을 하지 않는다.
- 실제 Bayesian 모델의 likelihood가 없는 event에 임의 확률을 만들지 않는다.
