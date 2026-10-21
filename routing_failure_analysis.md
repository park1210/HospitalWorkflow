# 실제 Routing 실행 실패 원인 분석

> 후속 수정 완료: 아래는 기존 `_01` 로그의 원인 분석이다. 현재 코드에는 score 계약 명시, 전문과명 진단 방지 schema, 알려진 두 계약 오류의 최대 1회 명시적 교정, 동일 입력 Router 캐시, 역할별 호출 예산, 초기 Routing 결과 별도 보존을 적용했다. 실제 Ollama 재실행은 아직 하지 않았다. 변경 내용과 `_02` 실행 명령은 [현재 실행 안내](routing_router_integration_report.md)를 따른다.

분석 대상: `outputs/routing_rule_01`, `outputs/routing_llm_01`, `outputs/routing_memory_llm_01`의 routing_smoke.json, memory_smoke.json, validation.json 및 각 case의 live_final_state.llm_audit. 기존 결과를 읽었으며 모델 재실행은 하지 않았다. 이번 작업에서 Routing/Memory/Patient/VoI 동작은 수정하지 않았다.

## 1. 실패 집계

각 명령은 Routing smoke 6조건과 Memory smoke 9조건을 실행했다. 아래는 각 폴더의 두 결과 파일에 저장된 총 15개 case/mode 행 기준이다.

| 실행 | completed | failed | model_call_limit_exceeded | 원인 |
|---|---:|---:|---:|---|
| Rule | 13 | 2 | 0 | 전문과 이름을 supported diagnosis로 제출 |
| LLM | 8 | 7 | 0 | Router score 값 검증 실패 |
| Memory-aware LLM | 5 | 9 | 1 | Router score 검증 9건 + 총 호출 한도 1건 |

Rule과 LLM의 Routing smoke는 각각 6/6 completed였다. 하지만 Memory smoke에서 실패했다. Memory-aware의 Routing smoke는 completed 3, failed 2, 호출 한도 초과 1이었다.

**failed는 정답을 틀렸다는 표시가 아니라 실행 중 응답 계약 검증 또는 호출 한도 때문에 중단됐다는 뜻이다.** completed 역시 임상 정답이라는 뜻이 아니다. strict_correct/acceptable_correct와 구분해야 한다.

세 실행 모두 smoke의 모든 행이 completed여야 하는 조건을 만족하지 못했다. `run_synthea_v2_pilot.py::main`의 smoke_ok 조건 때문에 전체 pilot 파일이 생성되지 않았다. 현재 폴더들은 전체 추천 10/9 사례 실험 완료 결과가 아니다.

## 2. Rule: 진단 칸에 전문과 이름을 제출 — 2건

- case: `symptom-v1-81b56520-bf9a-2eb4-8496-253bebaec655`
- memory mode: no_memory, selective
- 실패 role: specialty, 호출 수 각각 2
- 메시지: `A department is not a supported diagnosis`
- 근거: [Rule Memory smoke](outputs/routing_rule_01/memory_smoke.json)

`app/core/hospital_llm_policy.py::HospitalLLMPolicy._decision` 내부 validate는 Diagnose의 target을 department catalog/alias로 정규화한다. certainty가 supported이고 target이 전문과 이름에 해당하면 위 오류를 발생시킨다. 따라서 단순히 잘못된 전문과를 라우팅해서 중단한 것이 아니라, 전문의 LLM이 임상 진단과 전문과 라벨을 혼동한 응답이 검증에 걸린 것이다.

코드상 오류 조건으로 action=diagnose, certainty=supported, target의 전문과 정규화 일치가 확인된다. **실패한 원문 target 문자열은 저장되지 않아 정확한 출력 단어는 확인 불가**다. 실행 중 선택된 전문과와 실패 target 문자열이 같다고 추정하지 않는다.

## 3. LLM 계열: routing score 계약 위반 — 16건

- LLM 7건, Memory-aware 9건.
- 실패 role: router.
- 메시지: `Routing scores must be finite numbers between zero and one`.
- 근거: [LLM Memory smoke](outputs/routing_llm_01/memory_smoke.json), [Memory-aware Routing smoke](outputs/routing_memory_llm_01/routing_smoke.json), [Memory-aware Memory smoke](outputs/routing_memory_llm_01/memory_smoke.json).

`app/core/specialty_router.py::LLMRouter.select/validate`에서 각 후보 score에 다음 조건을 적용한다.

```python
type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1
```

따라서 최소 한 score가 숫자 타입/유한성/0~1 범위 중 하나를 만족하지 않았다. 이 오류까지 도달했다는 것은 JSON 파싱 및 앞선 candidate key 검증을 통과했다는 뜻이다. score는 확률이 아니지만 현재 구현의 허용 척도는 0~1이다.

**원문 score 값은 저장되지 않았다.** 따라서 100점 척도를 썼는지, 문자열 숫자를 반환했는지, 다른 잘못된 값을 반환했는지는 확인 불가다. 특정 원인을 확정해서 수치를 나누거나 문자열을 무조건 변환하는 처리는 근거가 부족하다.

구조상 확인된 개선 지점:

1. 자연어 instruction은 “scores are routing scores, not probabilities”만 말하고, 0~1 숫자·후보 전부 포함·합계 1 불필요 등의 계약을 명시하지 않는다. schema에는 minimum/maximum이 있고 Python validator는 이를 강제한다. 자연어와 schema의 요구를 명확히 맞출 여지가 있다.
2. `app/llm/ollama_client.py`는 strict JSON schema를 요청하지만 실제 응답은 Python 검증을 통과하지 못했다. schema를 보냈다는 사실만으로 서버가 수치 범위까지 보장한다고 볼 수 없다. 정확한 backend 원인은 이 로그로 확인 불가다.
3. `app/llm/role_call.py`는 오류 메시지·usage·finish_reason 등을 남기지만 실패 원문 또는 문제가 된 field/type/value는 남기지 않는다. 현재 로그만으로 응답을 정확히 재현·분류하기 어렵다.

## 4. Memory-aware: 8회 호출 제한 — 1건

- case: `symptom-v1-ddf91fab-f4b9-dc35-c903-6c623d2d5b93`, selective.
- status: `model_call_limit_exceeded`, actual_llm_calls=8.
- 근거: [Memory-aware Routing smoke](outputs/routing_memory_llm_01/routing_smoke.json).

Audit에는 Router 성공 4회와 specialty 성공 4회가 번갈아 기록돼 있다. 전문의는 Hemoglobin → Hematocrit → Creatinine → Glucose 검사를 선택했다. 그 다음 다섯 번째 Router 요청, 즉 총 아홉 번째 요청 시도에서 중단됐다. 이 마지막 요청은 서버로 전송되지 않았다.

`run_synthea_v2_pilot.py::PilotBoundary`의 max_calls 기본값은 8이다. Router LLM과 specialty LLM이 한도를 공유한다. 기존 Rule에는 Router 모델 호출이 없으므로 같은 행동 수여도 LLM Router 조건은 더 빨리 이 한도에 도달한다. 각 primary decision에서 Router를 다시 호출하는 `HospitalLLMPolicy._decision` 구조와 합쳐져 발생한 실행 예산 문제다.

## 5. 동시 실행 및 정확도와의 구분

확인한 세 폴더의 중단 원인에는 timeout, 연결 오류, output_truncated가 없다. 따라서 이번 실패를 동시 실행 또는 VRAM 부족 탓이라고 설명할 근거는 없다. 동시 부하가 다른 측정에 영향을 주었는지는 별도 문제다.

또한 Routing pilot이라는 이름과 달리 실행기는 라우팅 1회에서 끝나지 않고 기존 임상 simulation loop를 실행한다. 그래서 **Router가 정상 선택했어도 뒤의 specialty Diagnose 응답 오류로 전체 case가 failed가 될 수 있다.** 반대로 후반 Router 실패가 primary_routing을 failed/null로 갱신하면, 그 전에 성공한 라우팅이 있어도 현재 최종 routing accuracy에서 제외될 수 있다. 초기 routing 성능, 마지막 routing 결과, 전체 workflow completion을 구분해야 한다.

## 6. 분석 당시 권장 수정 순서 — 후속 구현은 상단 안내 참조

1. **오류 관측 보강:** 문제 field/type/value를 안전한 범위로 기록하고 모델 원문 재현이 가능한 진단용 로깅을 마련한다. 먼저 score 오류의 실제 형식을 확정한다.
2. **출력 계약 명확화:** Router에 0~1 숫자 척도와 후보 전체 key를 명시하고, specialty prompt/schema에 department와 Diagnose target을 분리해 설명한다. 실패를 정답으로 바꾸거나 검증을 제거하지 않는다.
3. **호출 예산 정렬:** Router/clinical 호출 수를 분리 기록하고 실험 목적에 맞게 한도를 명시한다. 동일한 관측·memory·candidate/model 설정일 때만 기존 Router 결과를 재사용하는 방안도 검토한다. 무조건 한도만 늘리면 반복 호출 문제를 숨길 수 있다.
4. **평가 단위 분리:** 초기 Router 결과와 전체 진료 workflow 결과를 각각 보존해 라우팅 정확도와 진료 실패를 혼동하지 않게 한다.
5. 실패 사례만 작게 재검증한 뒤 전체 실험을 재개한다. 기존 output을 덮어쓰지 않는다.

## 7. 문서 정리

현재 실행에 직접 필요하지 않은 이전 단계 보고서 7개를 [docs/archive](docs/archive/README.md)로 이동했다. README에 현재 안내와 archive 링크를 추가했다. 현재 Router 안내와 추천 명단, tracker, AGENTS는 최상위에 유지했다. 구형 Synthea 준비 스크립트의 보고서 출력 경로만 archive 위치로 바꿨고, 시뮬레이션 동작은 변경하지 않았다.
