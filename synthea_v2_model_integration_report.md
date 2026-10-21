# Synthea v2 모델 연결 및 offline pilot 결과

## 1. 결론

기존 Memory → RuleSimilarityRouter → registry specialty model 호출 경계까지 연결했다. **실제 LLM 호출은 0회**다. 기존 수식, 검색 알고리즘, 라우팅 알고리즘, VoI 코드를 변경하지 않았다. 이번 결과는 연결 및 데이터 경계 검증이며 전문과 LLM의 임상 성능 검증이 아니다.

두 가지 실험 제한이 확인되었다.

1. 기존 `app/data/challenge_v4/registry.json`은 neurology와 pulmonology만 제공한다. 데이터 정답 전문과인 otolaryngology/surgery/gastroenterology가 후보에 없으므로 strict/acceptable accuracy는 0%다. 정답 라벨을 이용해 binding이나 keyword를 추가하지 않았다.
2. Memory 후보 9건의 full history 입력은 382,708~1,424,208자로, 이번 파일럿의 24,000자 예산을 전부 초과했다. `context_limit_exceeded`로 기록했고 history를 자르거나 selective로 대체하지 않았다. 이 9건의 routing accuracy는 null이며 분모에서 제외했다.

## 2. 입력 및 사례 선택

- 원본: `current_symptom_presentation_benchmark_v2.jsonl`, 60개 사례.
- SHA-256: `3674b7afe90e4dfe58b7922d3572761a59c62cb6d3dcb73097a5a615f3e98729`.
- 실행 전후 원본 hash 일치.
- `routing_final_candidate=true`: **59개** (이비인후과 54, 외과 3, 소화기내과 2).
- `memory_final_candidate=true`: **9개**.
- `voi_final_candidate=true`: **0개**, final eligibility의 outcome_model 비-null: **0개**.

요청의 ‘Routing 추천 10개’ 명단은 첨부 JSONL이나 프로젝트 파일에서 식별하지 못했다. 따라서 전문과별 첫 사례 3개를 먼저 고르고, 나머지는 원본 순서로 보충한 **임시 10개**를 사용했다. 이는 원래 추천 명단이라고 주장하지 않는다. `validation.json`에 실제 ID 및 선택 기준을 저장했다. `--routing-case-ids`로 정확한 추천 ID 10개의 JSON 배열을 지정할 수 있다. Memory 9개는 실제 final flag를 그대로 사용했다.

## 3. 수정 파일과 유지한 구조

| 파일 | 작업 |
|---|---|
| `app/data/synthea_v2_adapter.py` | v2 환자 입력 allowlist, 과거 기록 시간 경계, 기존 encounter 계약으로 변환 |
| `app/agents/patient_agent.py` | `initial_utterance`, `answer_v2`; opt-in v2 입력에서만 출처 기반 발화 |
| `app/core/hospital_llm_policy.py` | v2 Ask를 실제 PatientAgent로 전달하고 grounding을 기존 audit에 기록 |
| `app/core/longitudinal_runner.py` | v2 초기 공개 objective evidence를 초기 runtime에 반영 |
| `app/scripts/run_synthea_v2_pilot.py` | 기존 실행기를 사용하는 smoke/pilot, 호출 경계, 예산, 결과 평가·저장 |
| `tests/test_synthea_v2_integration.py` | 누출·시간·grounding·예산·Ask 연결 검증 |

`PatientMemoryStore.retrieve`, `AgentRegistry.select_specialty/route`, specialty 호출 및 role_call, 기존 simulation loop를 재사용했다. VoI 모듈과 수학식은 이번 작업에서 수정하지 않았다. 기존 파일을 삭제하지 않았다.

실행 흐름:

`v2 allowlist → PatientAgent 출처 기반 발화 → 기존 encounter/runtime → memory_query → 기존 Memory 검색 → 기존 RuleSimilarityRouter → registry.get(specialty) → 기존 role_call → offline boundary 또는 live 호출`

## 4. 환자 입력과 evidence 경계

- 현재 증상은 오직 `patient_visible_state_v2.current_symptoms`에서 읽는다. PatientAgent에는 symptom name 및 opaque provenance ID만 전달한다. 원본 symptom 객체의 acceptance/evidence/module/cause 같은 내부 항목은 전달하지 않는다.
- 발화는 `My symptoms are: <원본 증상 이름 목록>.` 형식의 deterministic extractive 표현이다. 자유 생성 LLM paraphrase가 아니다. 새로운 증상·진단·중증도·발병 시점·지속 시간을 생성하지 않는다. 원본 value와 timestamp를 발화에 해석하여 넣지 않는다.
- 전체 60개 초기 발화의 `used_symptom_ids`, `source_fact_ids`, `grounded`, 실제 환자 입력을 `patient_agent_trace.jsonl`에 저장했다. grounded는 원본 문자열과의 일치이며 임상적 진실 또는 수동 검수 완료를 뜻하지 않는다.
- Ask는 증상/알레르기/약물/알려진 병력에 관한 명시적 질문만 지원한다. 알려진 사실은 v2의 허용된 fact ID/description에서만 추출한다. 없는 사실이나 지원하지 않는 상세 질문은 `I am unsure.`로 응답한다. **자유 질문 의미 매칭 기능은 이번 범위에 추가하지 않았다.**
- 의사 초기 입력은 발화, 허용 age/sex/encounter class, 공개 initial clinical evidence다. raw past history는 prompt에 직접 복사하지 않고 Memory를 거친다.
- source event store는 어댑터/environment만 읽는다. Test 후보 이름과 나중에 반환할 evidence를 분리하며, evidence는 기존 `encounter_evidence`가 availability 시점 이후에만 반환한다. 영상 획득 metadata를 임의 판독문으로 바꾸지 않는다.
- 과거 날짜만 있는 기록은 해당 날짜 다음 날 00:00 UTC를 보수적 availability 상한으로 사용한다. 이는 실제 관측 시각 추정이 아니다. cutoff 이후 또는 동일 cutoff의 기록은 검색 대상에서 제외하되 원본 과거 방문은 `source_past_visits`로 유지한다.
- evaluation은 case/model 입력에 넣지 않고 실행 결과 평가 단계에서만 참조한다. 전문과별 smoke 사례 구성에 사용한 평가 라벨도 runtime에는 전달하지 않는다.

## 5. Memory 및 Routing 설정

| 조건 | 실제 기존 mode | 처리 |
|---|---|---|
| M0 no_memory | `none` | 0개 기록 |
| M1 full_history_budgeted | `full_history` | eligible 전체 유지; 완성된 입력이 예산 초과면 호출 중단 |
| M2 selective | `selective` | 기존 lexical overlap, positive score, 최신성 tie-break, top_k=5 |

M2는 이번 실행에서 **임베딩을 사용하지 않았다**. 기존 코드의 `lexical_overlap_then_recency`를 유지했다. 새로운 retrieval 알고리즘을 추가하지 않았다. 입력 문자 수, `ceil(chars/4)` 토큰 추정치, 기록 ID/text/retrieval_score/query를 저장했다. 문자 수는 system+payload+schema 기준이다. 24,000자는 이번 CLI 기본 예산이지 실제 Ollama 모델의 검증된 context limit이 아니다. tokenizer와 출력 토큰을 포함한 실제 context 보장은 제공하지 않는다.

Routing은 utility artifact 없이 기존 registry keyword score argmax로 실행했다. No Memory/Selective는 모두 neurology를 선택했다. full history는 경계 이전에 계산된 잠정 router 결과가 pulmonology였으나 context 초과로 실행 평가에서는 제외했다. 전체 기록이 score를 바꾼 사실과 모델이 실행 가능했다는 주장을 구분한다.

실제 binding 확인:

- neurology → `qwen-neurology:latest`
- pulmonology → `qwen-pulmonology:latest`

이는 설정된 registry binding과 실제 role_call의 model 인자가 일치한다는 의미다. Ollama 설치/가용성이나 LoRA 품질은 이번 offline 실행에서 확인하지 않았다.

## 6. 실제 실행 결과

| 실행 묶음 | 조건별 사례 수 | 결과 |
|---|---:|---|
| Routing smoke | 3 × 2 = 6 | 모두 specialty 호출 직전 도달 |
| Memory smoke | 3 × 3 = 9 | none/selective 6건 경계 도달, full 3건 context 초과 |
| Routing pilot | 10 × 2 = 20 | none/selective 각각 strict 0/10, acceptable 0/10 |
| Memory pilot | 9 × 3 = 27 | none/selective 각각 strict 0/9, acceptable 0/9; full 9건 context 초과 |

Smoke와 pilot 및 두 그룹에 중복되는 case/mode는 재사용했다. **실제 고유 case/mode 실행은 43개**이며 62번 새로 실행한 것이 아니다. 모델 호출은 0회다.

Memory pilot의 selective는 각 5개 기록, full history는 630~2,308개 기록이었다. Full history의 실패는 예산 초과이고, offline의 `runner_status=failed`는 호출 직전 의도적으로 던진 sentinel 예외이다. 이를 임상 실패나 LLM 생성 실패로 해석하면 안 된다. `status`, `expected_offline_exception`, `actual_llm_calls`를 함께 확인해야 한다.

기술 smoke 통과는 경계 연결 및 context 차단의 정상 동작을 뜻한다. 전문과 coverage 확보나 full history의 실제 모델 실행 성공을 뜻하지 않는다. Precision@K, Recall@K, MRR은 계산하지 않았다.

## 7. 자동 검증

- v2 통합 검사 **8개 통과**: hidden/legacy/module/cause/value 변조 불변성, 이름 grounding/unknown, 미래 증상 차단, 미래 memory 제외와 원본 보존, full history 예산 초과 시 무대체, 미래 evidence release, metadata guard, 실제 loop에서 Ask→PatientAgent 호출.
- 기존 encounter 검사 **8개 통과**.
- 기존 mathematical alignment 검사 **12개 통과**.
- 총 **28개 검사 통과**, 실제 모델 호출 없음.
- Pilot 모든 검색 결과에서 동일 patient, 다른 visit, index 이전 availability를 검증했다. 모델 payload의 금지 metadata key도 검사했다.
- 원본 hash 불변을 검증했다.

처음 unittest를 dotted module 이름으로 실행했을 때 tests 패키지 import 오류가 발생했다. 이후 아래의 discover 방식으로 실제 검사를 실행하여 통과했다. 데이터 변환 초기의 영상 target 스키마 차이도 수정한 후 pilot을 완료했다.

## 8. 생성 결과와 재실행

`outputs/synthea_v2/`:

- `routing_smoke.json`
- `memory_smoke.json`
- `routing_pilot_results.json`
- `memory_pilot_results.json`
- `patient_agent_trace.jsonl`
- `validation.json`

기존 결과를 덮어쓰지 않으므로 재실행에는 새 출력 경로를 지정한다.

```powershell
python -m app.scripts.run_synthea_v2_pilot --output-dir outputs/synthea_v2_offline_02
python -m unittest discover -s tests -p test_synthea_v2_integration.py
```

정확한 추천 ID 목록이 있는 경우 `--routing-case-ids <JSON 배열 파일>`을 추가한다. Live 옵션은 구현했으나 이번에는 실행하지 않았다. 아래 명령은 실제 모델 요청을 발생시킨다.

```powershell
python -m app.scripts.run_synthea_v2_pilot --live --registry app/data/challenge_v4/registry.json --output-dir outputs/synthea_v2_live_01
```

Live도 기존 loop를 사용하며 selector는 `specialist_heuristic`이다. 요청/실행 selector를 기록한다. 호출 전에 중단한 offline/예산 초과는 executed_selector=null이다. Live의 case/mode당 모델 요청 상한은 8회다. VoI 성능은 평가하지 않는다.

## 9. 다음 단계

1. 정답을 보며 case별 모델을 고르지 않는 고정 registry에 이비인후과·외과·소화기내과 binding을 준비한다. 실제 전문 LoRA와 공유 base model 역할 binding을 구별하고, keyword 설정도 평가 전에 고정해야 한다.
2. Routing 추천 10개 원본 명단을 확인해 임시 선택을 대체한다.
3. Full history 처리 방침을 결정한다. 충분한 실제 context 모델을 사용하거나, 별도 명시적인 budgeted-history 비교 조건을 정의해야 한다. 이번 실행에서는 축약·fallback을 하지 않았다.
4. 위 조건을 고정한 후 live specialty pilot을 수행한다. 현재 0%는 registry 후보 불일치의 결과이므로 논문에 전문과 모델 성능으로 사용할 수 없다.
5. Memory relevance annotation이 준비된 후 검색 정확도를 평가한다. VoI는 final candidate/outcome model 확보 후 별도로 평가한다.
