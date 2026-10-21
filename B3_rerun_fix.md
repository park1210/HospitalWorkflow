# B3 반복 실행 중단 원인 및 수정

## 분석한 실행

`outputs/paper_test_v4_rerun_20261017_220317`의 B3 보고서를 읽었다. 테스트, 시뮬레이션, LLM 호출은 실행하지 않았다. 기존 보고서·benchmark·모델 설정·라벨은 수정하지 않았다.

|반복|상태|중단 환자|로그에서 확인한 원인|
|---|---|---|---|
|r01|incomplete|p008 (8번째 방문)|neurology→pulmonology→T_BASE→neurology→pulmonology 협진을 반복하다 30분 상한 도달|
|r02|incomplete|p020 (20번째 방문)|pulmonology→T_CONTEXT→pulmonology→문진→neurology로 진행하다 30분 상한 도달|
|r03|failed|p022 (22번째 방문)|환자 역할에서 `unknown=true`와 fact_ids를 함께 반환하여 `Unknown response must not assert facts` 검증 오류|

이는 진단 예측 오답을 뜻하는 상태가 아니다. incomplete는 시간 상한에서 미완료, failed는 역할 호출/출력 검증 실패다. 실행기는 첫 미완료 방문에서 해당 조건·반복을 중단하므로 이후 환자는 실행되지 않는다. 그 후 다른 조건·반복 실행은 계속된다.

## 구조적 원인

- 의사 정책은 최대 의사결정 12회 예산을 보지만 방문의 30분 상한을 알지 못했다. 협진은 이동과 서비스 시간을 소비하므로 결정 예산 전에 시간이 소진될 수 있었다.
- 기존 재협진 방지는 같은 관찰 상태에서만 적용되며 검사 결과가 추가되면 전문과가 다시 후보로 들어온다. 전문의가 현재 과의 미실행 검사를 남기고 다른 과로 넘길 수 있었다.
- 환자 JSON 생성 스키마는 unknown과 사실 선택의 모순을 허용했지만 실제 검증기는 이를 거부했다. raw 응답 전체는 저장되지 않아 선택 ID의 구체적 내용은 기존 로그로 확정할 수 없다.

## 변경 파일

1. `app/core/patient_facts.py`: unknown이면 빈 ID 목록, 사실 답변이면 1~3개 고유 ID가 되도록 스키마 분기.
2. `app/agents/patient_agent.py`: 유효한 사실 ID와 unknown=true가 함께 오면 unknown을 우선하여 ID를 제거. `output_normalization.reason=unknown_overrides_fact_ids`와 제거 ID 기록. 허위 ID·잘못된 타입·기타 잘못된 출력은 계속 오류이며, 추가 호출이나 재시도는 없음.
3. `app/core/hospital_llm_policy.py`: 전문의에게 미실행 가능한 로컬 검사가 있으면 다른 과로 즉시 넘기는 행동을 제한. 검사 자체를 강제 선택하거나 숨겨진 결과를 읽지 않음. 남은 가상시간을 기준으로 완료·최종 검토 시간이 부족한 협진/검사/문진/처치를 제외하고 이유를 `decision_validation.action_constraints`에 기록.
4. `app/core/longitudinal_runner.py`: 정책에 방문 상한과 시간 설정 전달. 미완료/실패의 stop_reason 및 세부 원인 저장. 정책 계약 버전을 변경해 수정 전 checkpoint와 혼합 재개 방지.

시간이 부족하여 다른 행동이 없으면 기존 unresolved 종료를 허용하며 `visit_time_budget_exhausted`를 기록한다. 이를 정답으로 승격하지 않는다. 진행 중인 검사 결과는 기다리며, 자원 대기·긴 서비스가 있는 경우의 incomplete까지 없다고 보장하지 않는다.

이 수정은 행동 정책 변경이므로 기존 논문 frozen 결과에 덮어쓰거나 같은 조건의 무변경 반복으로 합산하지 않는다. 새 실행 디렉터리와 manifest로 구분한다. 수리 완료 여부는 아직 실행 검증하지 않았으며 사용자의 테스트 결과로 확인해야 한다.

## 사용자 실행 명령: B3만 3회

프로젝트 최상위 PowerShell에서 Ollama를 실행한 상태로:

```powershell
$runDir = "outputs/paper_test_v4_B3_fixed_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
python -u -m app.scripts.run_paper_experiments `
  --plan outputs/memory_v4_test/plan_semantic.json `
  --execute `
  --conditions B3 `
  --repeats 3 `
  --output-dir $runDir
```

40명×3회이다. 전체 비교를 새 정책으로 다시 하려면 `--conditions B0 B1 B2 B3 B4`로 바꾼다. B3만 수정 후 재실행한 결과를 이전 B0/B1/B2/B4와 동등 조건 비교로 합치지 않는다.

## 확인할 사항

- B3_r01/r02/r03의 status, 저장된 visits 수(계획은 각 40), completed 및 diagnosis_unresolved를 별도로 확인.
- 환자 모순 출력이 발생할 경우 사실을 말하지 않는 답변과 정규화 로그가 남는지 확인. 다른 검증 오류를 숨기지는 않는지 확인.
- specialist가 로컬 검사 전에 다른 과로 연속 이관하지 않는지 확인.
- 늦은 협진이 제외될 때 `visit_time_budget` 근거가 남는지, unresolved 종료가 정답으로 집계되지 않는지 확인.
- 실패가 남으면 해당 방문의 `failure_detail` 또는 `stop_detail` 확인. 완료율 상승만으로 정확도 개선을 주장하지 않음.

선택적인 기존 회귀 테스트 명령(작성자 미실행):

```powershell
python -m unittest discover -s tests -p "test_grounding_and_background.py"
python -m unittest discover -s tests -p "test_memory_research.py"
```
