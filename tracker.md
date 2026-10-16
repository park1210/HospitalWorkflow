# 7·9·10번 연구 구현 현황과 작업 지도

기준일: 2026-10-17. 기능별 완료는 명시된 소프트웨어 범위의 완료이며 임상 정확도 입증을 뜻하지 않는다. 함수명을 유지보수 기준 위치로 사용한다. 상대 경로는 저장소 루트 기준이다.

최신 실행 명령과 산출물 해석: [7·9번 추가 구현 안내](docs/research_7_9_completion.md). 바로 사용할 합성 자료: `app/data/research_synthetic_v1/`.

10번 구현·직접 테스트: [VoI 안내](docs/voi_research.md). 합성 모형과 입력: `app/data/voi_synthetic/`. 이번 10번 작업은 사용자 요청에 따라 핵심 4개 검사만 실행했고 전체 회귀·실제 LLM 실험은 반복하지 않았다.

## 1. 전체 현황

### 모델 실행과 병행할 오프라인 비교 — 완료

- `app/scripts/compare_memory_retrieval.py::compare/main`: 7번 lexical/저장 벡터 top-k 비교, 유형별 macro 평균·coverage·경계 검사·해시, 동일 입력 확인 후 semantic paper plan 생성. 실제 임베딩 생성은 별도 명령.
- `app/scripts/compare_routing_baselines.py::compare/main`: 9번 rule/random/adaptive의 저장 응답 비교, oracle 대비 regret·coverage·근거. 동일 관측·모델 버전·환자 split 검증, 결측은 NA.
- `app/core/hospital_llm_policy.py::_decision`: B3 `Unavailable department` 발생을 계기로 행동별 target enum 생성 제약 추가. 추가 모델 호출 없음. 실제 B3 재검증은 남음.
- `tests/test_component_comparison_minimal.py` 2개 + `test_output_contract_minimal.py` 2개 통과. 기존 toy 응답 및 validation memory 오프라인 비교 완료. 새 LLM/임베딩 호출 없음.
- 남은 실행 작업 4개와 명령: [추가 검사 안내](docs/component_comparison_tests.md).

### 두 사례 이후의 도전 실험 세트 — 구현 및 오프라인 점검 완료

- `app/scripts/prepare_challenge_benchmark.py::build`: 12명·24방문, 환자 단위 train/validation/test, 무관/갱신/충돌/표현 차이 유형, fixed memory·미래 sentinel·평가 라벨·비용 조건별 plan 생성.
- 같은 파일 `audit_memory`: 검색 경계·관련성 점검 96회, top-k 1/3·Full History·No Memory 비교. 실제 임베딩은 미포함.
- `app/data/challenge_v1/`: 재현 가능한 합성·미검수 자료. 이전 toy routing utility를 복사했으며 새 학습·임상 검수 아님.
- `app/scripts/run_paper_experiments.py::prepare/main/export`: 평가 전용 scenario 매핑 검증, episodes의 scenario_group과 stratified_table.csv/JSON 유형별 평균·coverage 추가. 모델 관측에는 유형을 전달하지 않음.
- 7번 검색 차이를 드러내는 데이터, 10번 비용 민감도 plan 준비. 9번 전문과 성능 차이 데이터 수집은 남음.
- 실행: `outputs/challenge_validation_check_02/` 비용 조건 B4 8방문 완료, 새 LLM 호출 없음. 전체 LLM B0~B4 40방문 실험은 아직 미실행.
- 안내: [도전 실험 방법](docs/challenge_benchmark.md).

### 논문 파일럿 JSON 실패 수정 — 완료

- `app/core/hospital_llm_policy.py::_decision`: 응답 문자열·배열 길이 제약, 공통 진단 후보 및 supported target enum. 추가 LLM 호출 없음.
- `app/core/longitudinal_runner.py::run_longitudinal`: optional `diagnosis_catalog` 검증·정책 연결·실험/재개 계약 보존.
- `app/scripts/run_paper_experiments.py::main`: B0~B4 모두 동일한 모형의 진단 후보 목록 제공. 환자별 정답은 평가에만 사용.
- `app/llm/ollama_client.py::chat`, `app/llm/role_call.py::role_call`: finish_reason·출력 문자 수, truncation/JSON/validation 실패 분류, ContextVar 호출 간 격리.
- 최소 검사 6개 통과. 실제 `outputs/paper_pilot_fixed_01/`: 5조건 × 2방문 모두 완료, 실패 0, 합성 정답 일치 10/10. LLM 응답 16개 모두 정상 종료, 62~95 출력 토큰. 기존 결과 보존.

### KSC 논문 실험 실행 도구 — 완료 범위

- `paper_experiment.example.json`: B0~B4 공통 입력·반복·검색 설정. 현재 자료는 두 환자의 합성 파일럿.
- `app/scripts/run_paper_experiments.py`: `prepare` 사전 검사, `main` B0~B4 및 보충 R0 실행·checkpoint·입력/코드 해시 보존, `export` CSV/Markdown/JSON 출력. 기본 동작은 호출 없는 검증.
- `app/core/paper_evaluation.py`: `episode_rows` 실패/미실행 분모 보존, 기억·호출·행동·시간·전문과 지표; `aggregate` 평균과 coverage; `paired` 환자 단위 차이/95% bootstrap 구간.
- `app/core/hospital_llm_policy.py`: `_decision`에 선택 action/target/rationale 로그 추가. LLM 호출 증가 없음.
- 7번: B0/B1/B2 기억 비교. 9번: B3/R0, 별도 기존 regret 도구 연계. 10번: B3/B4 비교와 기대 IG 기록.
- `app/data/voi_synthetic/memory_annotations.json`: 합성 생성 규칙 기반 relevance/stale 라벨. 임상 검수 아님.
- 실행 방법과 논문-코드 차이: [논문 실험 안내](docs/paper_experiments.md). 새 UI는 [구성 제안](docs/new_ui_proposal.md)만 작성.
- 전체 실제 LLM B0~B4 연구 결과, 임상 검수, 조건별 stale misuse 검수, 배치 재개/취소는 완료 항목이 아니다.
- 이번 최소 검증: paper 집계 검사 2개 + 기존 VoI 검사 4개 통과. 오프라인 B4 두 방문 완료. B0 호출 차단 실패 후 B4 계속 실행, 실패/미실행 분모 유지 확인. 실제 LLM 비교 실험은 사용자 실행용으로 준비했으며 수행하지 않음.

### UI 이전 빠른 데모 — 완료

- 실행: `python -m app.scripts.run_research_demo`
- 구현 위치: `app/scripts/run_research_demo.py`의 `run_demo` (조건별 실행·평가·검증·라우팅 재학습·보고서), `OfflineOnly` (외부 호출 차단), `main` (새 결과 폴더와 종료 코드).
- 7번: 기존 기억 풀의 지연 노출을 실제 엔진에서 검증. 비용 조건에 따라 기억 조회 선택.
- 9번: 기존 저장 LLM 응답을 train/test 환자 분리하여 효용 재학습·선택·regret 평가. 새로운 협진 생성은 아님.
- 10번: 실제 엔진에서 세 조건 × 두 방문 실행, 행동 근거·확률·비용·조기 종료·평가 보존.
- 수식: 기존 `VoI(a) = E[V(posterior)] - V(prior) - C(a)`와 라우팅 `U = w_accuracy × p - w_cost × cost - w_latency × latency`를 그대로 사용.
- 문서: [빠른 데모 실행·결과·후속 실험](docs/quick_research_demo.md).
- 최소 실험 결과: 6개 방문 완료, 조건별 합성 정답 일치율 1.0, 새 LLM 호출 0. 기억 허용 비용 조건에서는 조회 후 검사·진단. 임상 성능 또는 전체 LLM 역할 통합 검증을 뜻하지 않음.

| 연구 | 현재 수준 | 이번 이후 필요한 핵심 |
|---|---|---|
| 7 Longitudinal Memory | 5개 검색 모드·평가·합성 데이터·실제 임베딩·충돌 후보 탐지·방문 단위 재개 | 임상 검수, 자유로운 문장의 의미 충돌 검증 |
| 9 Adaptive Specialty Routing | Registry·기준선·학습 효용 라우팅·Regret·토큰/비용 계측 구현 | 임상 데이터로 학습/보정, 충분한 모델별 성능 자료 |
| 10 Value of Information | 유한 확률 모형·Bayes 갱신·비용/효용·유한 단계 VoI 선택·실행 연결·평가 구현 | 임상 확률/효용 검수, 실제 데이터와 수동 실험 |

## 2. 7번 기능 지도

| 기능 | 파일 / 수정 위치 | 상태 | 완료 범위 또는 남은 작업 |
|---|---|---|---|
| 환자·방문·시간대 | `app/core/longitudinal_memory.py`: `timestamp`, `visit_identity` | 완료 | 명시적 식별자와 timezone 검사 |
| 기억 스키마·저장 | 같은 파일: `PatientMemoryStore.add/save/load/snapshot` | 완료 | 출처·종류·관측/공개시각, JSON 저장, 중복 검사 |
| 정보 접근 제한 | 같은 파일: `retrieve` | 완료 | 같은 환자, 과거 방문, 현재 방문 전 공개 기록만 허용 |
| No/Full/선택 기억 | 같은 파일: `retrieve` | 기준선 완료 | 선택 기억은 단어 중복 후 최신순 top-k. 의미 검색 아님 |
| 오래된 기록 갱신 | 같은 파일: `add`, `retrieve`; `longitudinal_runner.py`: `run_longitudinal` | 명시적 갱신 완료 | `longitudinal.memory_updates` 연결. 동일 환자·방문·공개 시점 검증. 자동 삭제·덮어쓰기 없음 |
| 공개 기록 추출 | 같은 파일: `ingest_completed_visit`; `hospital_parallel_scheduler.py`: `_apply_clinical_decision`, `_handle_test_result_event` | 완료 | 문답·검사·처치 시각 보존. 시각 없는 과거 기록은 종료 시각 사용. 완료 방문만 저장 |
| 방문 순차 실행·재개 | `app/core/longitudinal_runner.py`: `run_longitudinal`, `run_with_recovery`; CLI `save_checkpoint` | 완료 | 완료 방문 원자적 체크포인트, 설정/무결성 검사, 실패 방문 처음부터 재시도. 실패 시도와 비용 보존. CLI 기본 1회·최대 3회 재시도 |
| 모델 관측 연결 | `app/core/clinical_observation.py`: `doctor_observation` | 완료 | ER/전문과에 별도 기억 전달, none에서는 기록 개수도 비공개 |
| 상태 복원 | `app/core/hospital_case_runtime.py`: `memory_context`, `from_summary`, `to_summary` | 완료 | 조회 결과 스냅샷 보존 |
| 실행 인터페이스 | `app/scripts/run_longitudinal_research.py`: `main` | 완료 | 실제 LLM 실행, 새 출력 파일만 생성 |
| 예제 | `app/data/longitudinal_synthetic.example.json` | 완료 | 두 방문 형식 예시. 임상 평가용 아님 |
| 회귀 검증 | `tests/test_longitudinal_memory.py` | 완료 | 정보 경계·갱신 시점·저장·두 방문·세 모드 10개 검사 |
| Memory 평가 | `app/core/memory_evaluation.py`: `evaluate_memory`, `compare_memory_benefit` | 구현 완료 | Precision/Recall, stale 검색률·오용률, 쌍별 정확도 차이. 라벨 없으면 미평가, 분모 0이면 N/A |
| 기억 인용 | `app/core/hospital_llm_policy.py`: `_decision` | 구현 완료 | `memory_ids` 검증과 `llm_audit.memory_citations` 기록. 자기보고이며 실제 의미적 사용 증명 아님 |
| 고정 기억 비교 | `longitudinal_runner.py`: `run_longitudinal` | 구현 완료 | `initial_memory`, `memory_source=fixed`는 이번 실행 판단을 기억에 추가하지 않음. 입력·라우팅·모델 설정 서명 비교 |
| 추출식 요약 | `longitudinal_memory.py`: `retrieve`의 summary | 기준선 완료 | 대체되지 않은 종류별 최신 기록, top-k. 원문과 출처 보존. 생성형 요약 아님 |
| 벡터 검색·생성 | `memory_retrieval.py`: `MemoryEmbeddings`; `embedding_builder.py`: `build_embeddings`; `scripts/build_memory_embeddings.py` | 구현 완료 | lexical 해시 기준선과 실제 Ollama 임베딩, 중복 텍스트 배치 처리, CPU 옵션. embeddinggemma 768차원 산출물 생성 확인 |
| 자연어 충돌 후보 | `app/core/memory_conflicts.py`: `assertion`, `detect_conflicts`; `retrieve` | 제한 문법 완료 | reports/denies, present/absent, 있음/없음의 동일 대상 반대 극성 표시. 시간 변화일 수도 있으므로 검수 필요. 일반 의미 추론 아님 |
| 데이터·라벨 계약 | `app/core/research_dataset.py`: `validate_bundle`, `synthetic_bundle`; `scripts/prepare_research_data.py` | 구현 완료 | 6명·12방문 합성 자료, 관련성/오래된 기록 라벨, 환자 단위 3분할, 미래 라벨 차단. 임상 미검수 명시 |
| 입력 예산 | `longitudinal_memory.py`: `retrieve(max_chars=...)` | 문자 예산 완료 | 직렬화된 기억 목록만 제한, 기록 단위 제외. 전체 프롬프트 토큰 제한 아님 |
| 사후 평가 명령 | `app/scripts/evaluate_longitudinal_memory.py`: `evaluate_report`, `main` | 구현 완료 | 저장 보고서와 검수 라벨로 재평가. LLM 호출 없음 |
| 추가 회귀 검증 | `tests/test_memory_research.py` | 완료 | 고정 기억, 갱신 연결, 요약·예산·벡터·실제 시각·인용·실패·평가·비교 |

### 7번 수식

현재 사용 가능한 기억: \(M_t=\{m:p(m)=p_t,\ v(m)\ne v_t,\ t_{visit}(m)<t,\ t_{available}(m)\le t\}\).

현재 선택 점수: \(s(m,q)=|tokens(m)\cap tokens(q)|\). 명시적으로 대체된 기억 제외 → 양수 점수 → 점수 내림차순/최신순 → top-k. 임상 관련성 확률이 아니다.

구현 평가: \(Precision=|R\cap G|/|R|\), \(Recall=|R\cap G|/|G|\). R은 검색 기억, G는 검수된 관련 기억. 빈 분모는 N/A, 라벨 누락은 missing_annotation이다. \(StaleRetrieval=|R\cap S|/|R|\), \(StaleMisuse=|W|/|R\cap S|\): S는 오래된 기억, W는 검수자가 실제 오용으로 판정한 검색 기억이다.

Memory Benefit은 동일 방문 쌍의 \(Accuracy_{memory}-Accuracy_{none}\). 고정 공통 기록 비교를 지원한다. 진단은 명시적 허용 문자열과 비교하며 누락 라벨·미완료 방문이 있으면 전체 지표는 미평가다. 신뢰구간·인과 효과 검증은 포함하지 않는다.

벡터 검색: \(s(m,q)=e_m^T e_q/(\|e_m\|\|e_q\|)\). 환자·시점 필터 후 대체되지 않은 기록 중 양수 점수 top-k를 선택한다. 유사도는 임상 정확도 확률이 아니다.

## 3. 9번 기능 지도

| 기능 | 파일 / 수정 위치 | 상태 | 구현 계획 |
|---|---|---|---|
| 실제 모델 등록 | `app/core/agent_registry.py`: `AgentRegistry.__init__/get/snapshot` | 구현·테스트 완료 | ER 1개, 진료과별 1개 모델 식별자·명시 버전. 중복·잘못된 진료과 거부. 설치 여부·체크섬은 검증하지 않음 |
| 라우팅 기준선 | 같은 파일: `route` | 구현·테스트 완료 | llm/er_only/rule/random. 협진 선택지를 제한하며 의사가 협진 시점·여부는 결정 |
| 전문 모델 호출 | `app/core/hospital_llm_policy.py`: `_decision`의 departments 필터, routing_context, role_call, finally | 구현·테스트 완료 | 실제 모델 인자를 Registry에서 선택, 캐시 입력에 실행 Agent 포함, 실패에도 routing 감사 기록 |
| 연구 설정 연결 | `longitudinal_runner.py`: `run_longitudinal`; `app/scripts/run_longitudinal_research.py`: `main` | 구현·테스트 완료 | registry 경로·라우팅 모드·seed 입력, 보고서 routing_config에 manifest 보존 |
| 설정 예제 | `app/data/agent_registry.example.json` | 완료 | 현재 예제는 같은 전문 모델에 역할만 다르게 부여. 별도 LoRA 설치를 의미하지 않음 |
| 회귀 검증 | `tests/test_agent_registry.py`: `RegistryTests` | 완료 | 6개 검사. 모델 전환·정보 경계·가용 진료과·재현성·실패 로그·잘못된 설정 검증 |
| 성능 기반 Adaptive Policy | `app/core/routing_utility.py`: `fit_utility`, `RoutingUtility.score`; `agent_registry.py`: `route(adaptive)` | 구현 완료 | Jaccard 유사 사례의 Beta 평활 성능·평균 비용/지연으로 최대 효용 선택. 최소 표본 미달 후보가 있으면 기존 의사 메뉴 유지. 임상 확률 보정은 별도 |
| Routing/Regret 평가 | `app/core/routing_evaluation.py`: `decisions_from_outcomes`, `evaluate_routing`; `scripts/routing_research.py` | 구현 완료 | 학습과 다른 환자, 동일 관측의 후보별 결과 필요. 누락/라우터 기권 시 전체 Regret 미평가, coverage·부분 지표 별도 |
| 동일 관측 결과 수집 | `app/core/routing_collection.py`: `collect_outcomes`; `scripts/collect_routing_outcomes.py` | 구현 완료 | 전문과별 단일 판단 probe, 라벨은 프롬프트 제외. 모델별 연속 실행, CPU 지원. 전체 진료 경로 효용과는 구분 |
| 호출 비용 | `app/llm/role_call.py`, `ollama_client.py`, `ollama_probe_client.py`; `app/core/call_costs.py`: `summarize_costs` | 구현 완료 | 서버 토큰·실제 지연·실패 호출 포함. 사용자 단가 적용. 미확인 사용량/가격은 비용 null, 알려진 부분합 별도. 선형 토큰 가격만 지원 |

### 9번 구현 수식

\(a^*=\arg\max_a U(a\mid x_t,m_t)\), \(U=\alpha\widehat P(correct\mid a,x_t,m_t)-\beta Cost(a)-\gamma Latency(a)\).

Regret: \(U(a^*_{oracle}\mid x_t,m_t)-U(a_{chosen}\mid x_t,m_t)\). Oracle은 사후 평가 전용이며 정답·미래 결과를 실행 라우터에 전달하지 않는다. 진료과 정답 일치율과 최적 모델 선택률은 다르다.

유사도 \(w_i=|T(x)\cap T(x_i)|/|T(x)\cup T(x_i)|\), 양수 유사 사례만 사용한다. \(\widehat P=(1+\sum_i w_i y_i)/(2+\sum_i w_i)\). 비용·지연은 같은 가중 평균이다. 최소 표본은 기본 2개이며 확률 보정이나 통계적 신뢰도 보증은 아니다. 모든 등록 전문과가 동일 관측을 평가한 학습 행을 요구하며 환자 분할 중복을 거부한다.

### 이번 구현의 정확한 범위

현재 후보는 `등록된 진료과 ∩ 병원에서 가용한 진료과 ∩ 재협진 제한을 통과한 진료과`다. Registry에 없는 모델로 조용히 대체하지 않는다. ER과 전문과의 서버 주소는 기존 역할별 설정을 공유하며 Agent별 서버·인증 설정은 없다. `version`은 사용자가 선언한 식별자이며 실행 모델의 바이너리 검증값은 아니다.

| 모드 | 실제 동작 | 한계 |
|---|---|---|
| llm | 모든 적격 등록 진료과를 기존 의사 LLM에 제공 | 별도 Router LLM 호출 없음. 학습된 효용 추정기 아님 |
| er_only | 협진 선택지 제거 | 기존 호출 한도·종료 조건 유지 |
| rule | 관측 내용과 설정 keyword의 일치 개수가 최대인 진료과 하나 허용 | 양수 일치 없으면 ER only, 동점은 진료과 이름순. 임상 규칙 아님 |
| random | seed·관측 단어 집합·후보 목록의 SHA-256을 후보 수로 나눈 나머지로 하나 선택 | 같은 입력은 같은 선택. 독립 난수 추출은 아님 |
| adaptive | 학습 산출물의 유사 사례에서 추정한 효용 최대 전문과 하나 허용 | 자료 부족 시 전체 메뉴 유지. 협진 시점과 여부는 기존 의사가 결정 |

Rule 점수는 \(score(d)=\sum_{w\in keywords_d}1[tokens(w)\subseteq tokens(observed)]\)다. 현재 주호소·증상·공개 소견·알려진 문답·대체되지 않은 선택 기억만 사용한다. 정답·미공개 결과·평가 필드는 입력에서 사용하지 않는다. 이 점수는 성공 확률이 아니다. Router는 별도 LLM 호출을 만들지 않지만 선택지가 바뀌면 전체 진료 호출 수는 달라질 수 있다.

`llm_audit[].routing`에는 모드·seed·후보·허용 진료과·점수·선택 이유·Agent/모델/버전·효용 추정·학습 산출물 해시가 기록된다. 현재 구조는 **학습 효용에 따른 협진 메뉴 선택 + 진료과별 모델 배정**이다. 협진 여부를 독자적으로 실행하는 정책이나 온라인 bandit은 아니다. 결정적 증거의 종료 조건과 불확실성 시 단계 진행 정책은 유지한다.

## 4. 10번 기능 지도 — 명시적 유한 모형으로 구현

| 기능 | 신설/수정 위치 | 상태 | 선행 조건 |
|---|---|---|---|
| 진단 belief | `app/core/diagnostic_belief.py`: `distribution`, `posterior`, `entropy`, `terminal_choice` | 구현 완료 | 유한 후보·정규화·Bayes 갱신·엔트로피. 임상 보정은 별도 검증 |
| 결과 모형 | `app/core/information_outcomes.py`: `InformationOutcomes`, `observe` | 구현 완료 | 질문/검사/협진/기억의 범주별 likelihood와 공개 관측 정확 일치. 모형 밖·상충 결과는 fallback |
| 비용·효용 계약 | `app/core/information_value.py`: `action_values` | 구현 완료 | 명시적 효용 행렬과 money/minutes/tokens 환산 비용. 예측 점수와 실제 비용 분리 |
| VoI 정책 | 같은 파일 `InformationPolicy.propose`; `hospital_llm_policy.py`: `_decision` | 구현 완료 | 1~3단계 기대 효용·IG·VoI 계산, 결정적 근거 조기 종료, 기존 확진/불확실성 제약 유지, 범위 밖 기존 LLM 정책 |
| 기억 획득 | `longitudinal_runner.py`: 비공개 pool; `_decision`: retrieve_memory | 구현 완료 | 조회 선택 전 원문 비노출, 조회 후 posterior 재계산. none에서는 조회 없음 |
| 상태·복원 | `hospital_case_runtime.py`: `voi_state`, `voi_memory_pool`; runner 설정 해시 | 구현 완료 | 결정 근거·확률·후보별 예상 결과·비용 추적. 체크포인트 재개 시 같은 모형 요구 |
| 확률 추정 | `app/core/voi_evaluation.py`: `fit_outcomes` | 구현 완료 | train 방문 빈도·조건별 결과 빈도에 Dirichlet 평활. 중복 결과·학습 환자 평가 중복 차단 |
| 비교·보정 평가 | 같은 파일 `evaluate_voi`, `compare_voi` | 구현 완료 | 정확도·Brier·log loss·ECE·coverage·행동/호출 수·시간·비용. 확률 보정 품질을 측정하며 자동 임상 보정은 아님 |
| 실행·평가 CLI | `run_longitudinal_research.py`: --voi-model; `voi_research.py` | 구현 완료 | validate/fit/evaluate/compare. 기존 모형 없는 실행은 유지 |
| 예제·수동 시험 | `app/data/voi_synthetic/`; `tests/test_voi_minimal.py`; `docs/voi_research.md` | 구현 완료 | 2진단·4행동·학습 40행·별도 환자 2명. 임상 미검수. 핵심 4개 검사만 실행 |

### 10번 적용 수식

\(H(D_t)=-\sum_d P_t(d)\log P_t(d)\).

\(IG(a)=H(D_t)-\sum_o P(o\mid a,s_t)H(D_t\mid o,a)\).

\(VoI(a)=\mathbb E_o[U(s_t\mid o,a)]-U(s_t)-C(a)\), \(a^*=\arg\max_a VoI(a)\).

행동 a는 향후 기억 조회·문진·검사·전문 자문으로 확장한다. 단순 단어 점수/자기보고 confidence는 보정된 확률이 아니다. 비용을 U에 이미 반영했다면 C에서 중복 차감하지 않아야 한다. 엔트로피 감소만으로 임상 이득을 주장하지 않는다.

현재 구현은 기억 조회·문진·검사·전문 자문을 지원한다. `b'(d)=b(d)P(o|d,a)/Σ_d b(d)P(o|d,a)`, `V₀=max_decision E[U]`, `Q_h=−C+Σ_o P(o)V_(h−1)`, `V_h=max(V₀,max_a Q_h)`, `VoI_h=Q_h−V₀`를 계산한다. 최대 3단계/5,000 탐색 상태이며 조건부 독립·고정 진단 집합 가정이다. 수학적 후보가 양수 VoI를 갖지 않아도 실제 종료 조건을 통과하지 못하면 다음 단계로 진행한다. 따라서 수학적 탐색과 실제 안전한 종료는 구분한다.

## 5. 유지·제외와 공통 미완료

- 유지: 역할별 정보 경계, 실행 로그, 출력 검증, 검사 인터페이스, 호출 제한, 회귀 테스트.
- 본 실험에서 제외: 다중 환자 혼잡 비교, M/M/1·이용률 최적화, 병상 운영, 픽셀 화면 고도화. 의존 코드 자체는 아직 삭제하지 않았다.
- 공통 필요: 환자 단위 학습/검증/시험 분할, 미래 방문 차단, 전문가 기억 관련성/폐기 라벨, 모델별 실제 성능 자료.
- 현재 객관적 소견 인용 종료 조건은 과거 기억만으로 진단 종료를 허용하지 않는다. 기억의 검사 절감 효과를 측정하려면 별도 검수된 종료 계약이 필요하다.
- 실제 LLM 시간 초과 자체는 발생할 수 있다. 완료 방문 보존·실패 방문 재시도는 구현했다. 강제 프로세스 종료 시 마지막 완료 방문 이후의 미저장 호출 사용량은 복원할 수 없다. 테스트를 임상 성능 검증으로 해석하지 않는다.

## 6. 검증 기록

10번 추가: `python -m unittest discover -s tests -p test_voi_minimal.py -q` **4개 통과, 0.194초**. 계산/모형 검사, 미래 결과 차단, 실제 스케줄러의 검사 후 결정적 종료와 기억 지연 노출, 학습 환자 중복 차단을 확인했다. 합성 경로에서 LLM 호출 0. 사용자 요청에 따라 전체 회귀 140개 및 실제 LLM 실험은 다시 실행하지 않았다. 이전 140개 통과 기록은 7·9번 완료 시점 결과다.

2026-10-17 최종 추가 구현: **140개 테스트 통과**(기존 120 + 추가 20). `git diff --check` 통과. 합성 6명·12방문 계약 검증 완료. embeddinggemma를 설치하고 CPU에서 실제 768차원 벡터를 생성하여 12방문 검색·시점 경계·충돌 후보 표시를 점검했다. 전문 모델 신경과/호흡기과에서 구조화 응답 제한 적용 후 학습용 4회와 별도 환자 시험용 4회 호출 성공. 효용 학습·평가 CLI 실행 완료. toy 과제의 Regret 0, coverage 1은 파이프라인 점검 결과이며 임상 성능 증거가 아니다. GPU 시간 초과 및 최초 CPU JSON 길이 실패도 파일로 보존했다.

실제 산출물: `app/data/research_synthetic_v1/embeddings_semantic.json`, `routing_train_bounded.json`, `routing_test_bounded.json`, `routing_utility_bounded.json`, `routing_regret_smoke.json`. 학습 지연은 CPU 실행과 모델 로딩을 포함하므로 다른 장비·GPU 실행 시간 예측에 그대로 쓰지 않는다. 실제 임상 검수, 확률 보정, 복합 자연어 모순 판정은 완료로 표시하지 않는다.

2026-10-17 추가 구현 후: `python -m unittest discover -s tests -q` **120개 통과**. 7번 추가 검증 14개는 고정 기억·시점별 갱신·실제 관측 시각·추출식 요약·문자 예산·벡터 검증·인용 검증·실패 보고·평가·비교·사후 평가를 다룬다. 사후 평가 CLI 도움말 확인, `git diff --check` 통과. 이번 실행에서 실제 LLM 성능 실험은 수행하지 않았다. 아래 106개 기록은 이전 Registry 구현 시점 기록이다.

2026-10-17: `python -m unittest discover -s tests -q` — **106개 통과**(기존 100 + Registry/라우팅 6). CLI `--help`에 새 옵션 노출 확인. 테스트용 응답 클라이언트로 실제 스케줄러의 ER→검사→협진→등록된 전문 모델→진단 경로를 검증했다. 이번 작업에서는 실제 모델 추론·임상 정확도·학습된 Router 성능을 시험하지 않았다.

## 7. 실행과 다음 작업 순서

```powershell
python -m app.scripts.run_longitudinal_research --cases app/data/longitudinal_synthetic.example.json --memory-mode selective --agent-registry app/data/agent_registry.example.json --routing-mode rule --routing-seed 21 --output outputs/research/memory_rule_run.json
```

이 명령은 실제 LLM을 호출한다. 예제 모델 tag가 해당 역할 서버에 설치되어 있어야 한다. 출력 파일은 기존 파일을 덮어쓰지 않는다. 예제는 소프트웨어 동작 점검 전용이며 전문 LoRA 비교나 임상 성능 데이터로 사용하지 않는다.

다음 작업:
1. 구현된 고정 기억·관련성/갱신/오용 평가 계약에 검수 데이터를 연결하고 실제 모델로 반복 비교한다. 상세 입력 형식은 `docs/longitudinal_research.md` 참조.
2. 구현된 동일 관측 수집기로 실제 전문 모델의 충분한 자료를 모은다. 토큰·비용 계측은 연결되어 있다.
3. 구현된 9번 효용 추정·Regret 평가를 검수 자료로 검증하고 확률을 보정한다. 환자 단위 분할과 oracle 정보 경계 필수.
4. 구현된 10번 VoI를 사용자 직접 시험한 뒤 검수된 진단·행동 결과 확률과 효용 행렬로 검증한다.

기존 5장 APL의 새 처치/재평가 이벤트 연결 문제와 종료 조건은 공통 후속 과제다. 단순 이벤트 추가로 재평가와 선택 행동을 중복 계산하지 않도록 먼저 단위를 정의해야 한다.
