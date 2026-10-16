# Longitudinal Memory 연구 실행 안내

2026-10-17. 기능별 코드 위치·완료 여부·수식은 루트 [tracker.md](../tracker.md)를 참조한다.

합성 데이터·실제 임베딩 생성·충돌 후보·실패 재개·학습 라우팅의 최신 실행법은 [7·9번 추가 구현 안내](research_7_9_completion.md)에 정리했다.

## 실행 구조

case의 longitudinal에 patient_id, visit_id, 시간대가 있는 started_at을 지정한다. 방문을 시간순으로 정렬하고 방문마다 단일 환자 스케줄러를 만든다. 중복·동시·겹치는 동일 환자 방문은 거부한다. 병원 혼잡은 비교 요인에서 제외하며 기존 시간·자원 처리는 유지한다.

같은 환자의 이전 방문 중 현재 방문 시작까지 공개된 기록만 검색한다. ER/전문과에 별도 기억을 제공하며 환자 역할이나 현재 객관적 확진 근거에 과거 판단을 합치지 않는다. 원본 case 전체·정답·미공개 검사 결과를 기억으로 복사하지 않는다.

## 검색 모드

| 모드 | 동작 |
|---|---|
| none | 기억과 기록 개수 모두 비공개 |
| full_history | 시점 조건에 맞는 전체 기록. 대체된 기록은 표시하여 포함 |
| selective | 대체되지 않은 기록 중 주호소와 단어가 겹치는 양수 점수 top-k |
| summary | 대체되지 않은 종류별 최신 기록을 원문 그대로 추출하여 top-k |
| semantic | 외부 벡터의 코사인 유사도로 양수 점수 top-k |

summary는 추출식 기준선이며 오래된 중요 정보를 놓칠 수 있다. semantic은 미리 생성한 임베딩을 읽는다. 별도 build_memory_embeddings 명령이 실제 벡터를 생성하며 검색·요약·평가 자체는 추가 LLM 호출을 만들지 않는다.

--max-memory-chars는 직렬화된 기억 목록의 문자 예산이다. 들어가지 않는 기록을 통째로 제외하여 ID와 출처를 보존한다. 전체 프롬프트나 토큰 예산은 아니다. 미지정 시 상한이 없으므로 모델 문맥 초과 가능성이 남는다.

## 실행

```powershell
python -m app.scripts.run_longitudinal_research --cases app/data/longitudinal_synthetic.example.json --memory-mode summary --top-k 5 --max-memory-chars 8000 --output outputs/research/summary.json
```

실제 LLM을 호출한다. 합성 예제는 소프트웨어 점검용이다. 출력은 새 파일에만 저장한다. RoleCallError는 기본 1회 방문 단위 재시도하며 모두 실패하면 부분 상태·감사 기록을 status=failed로 저장하고 종료 코드 1을 반환한다. 시간 한도 내 미완료는 incomplete이다. --resume으로 완료 방문을 보존할 수 있으며 모든 종류의 예외나 진료 중간 이벤트에서의 정확한 재개는 지원하지 않는다.

### 고정 기록과 누적 기록

- 기본 --memory-source closed_loop: 완료 방문의 공개 문답·검사·판단·처치를 다음 방문 기억에 추가한다.
- --memory-source fixed --initial-memory PATH: 공통 초기 기억만 사용하며 이번 실행 판단을 추가하지 않는다. 검색 조건 비교에 적합하다.
- 초기 파일은 {"schema_version": 1, "records": [...]}이다. 각 기록 필수 필드: memory_id, patient_id, visit_id, visit_started_at, observed_at, available_at, source_id, kind, text, supersedes. 종류: history/objective_finding/prior_assessment/intervention/update. supersedes는 이전 기록 ID 목록이다.
- 누적 모드에서 case.longitudinal.memory_updates에 같은 형식의 갱신을 넣는다. 같은 환자·방문이며 종료 시점까지 공개된 갱신만 허용한다. 고정 모드의 갱신은 초기 파일에 넣는다. 자연어 충돌·약물 중단 자동 추론은 없다.
- 새 문답·검사는 관측 분, 처치는 수행 시각을 보존한다. 시각 없는 레거시 기록만 종료 시각으로 대체한다.

### 벡터 산출물

--memory-mode semantic --memory-embeddings PATH를 사용한다. JSON 최상위 필드: model_id, revision, records, queries. records의 키는 기억 ID, queries의 키는 json.dumps([patient_id, visit_id], ensure_ascii=False)로 만든 문자열이다.

각 값은 {"text_sha256": "텍스트 SHA-256", "vector": [0.1, 0.2]} 형식이다. 기억 원문과 주호소의 해시가 일치해야 한다. 벡터는 같은 차원, 유한 숫자, 0이 아닌 노름이어야 한다. 필요한 벡터가 없으면 실패한다. 누적 모드는 이후 생성될 기억의 벡터도 필요하므로 사전 고정 기억 실험이 더 간단하다. 선언한 모델 버전의 실제 가중치는 검증하지 않는다.

## 사후 평가

실행 시 --memory-annotations PATH 또는 실행 후 다음 명령으로 평가한다. 라벨은 모델 관측에 전달하지 않는다.

```powershell
python -m app.scripts.evaluate_longitudinal_memory --report outputs/research/summary.json --annotations data/memory_labels.json --output outputs/research/summary_evaluation.json
```

라벨 예시(ID는 실제 보고서 값으로 교체):

```json
{
  "[\"patient-1\", \"visit-2\"]": {
    "relevant_memory_ids": ["prior-finding-1"],
    "stale_memory_ids": ["prior-assessment-1"],
    "misused_memory_ids": []
  }
}
```

관련·오래된 기억 라벨은 해당 환자·시점에서 사용 가능한 ID만 허용한다. misused_memory_ids는 이번에 보여준 오래된 기록 중 검수자가 실제 오용으로 판정한 부분집합이다. 빈 목록은 검수 후 오용 없음, 필드 생략은 미평가다. 인용은 자기보고이며 자동으로 오용으로 간주하지 않는다. Precision/Recall과 stale 검색률·오용률을 분리한다. 라벨 누락과 0 분모를 0점으로 바꾸지 않는다.

--baseline NONE_REPORT --expected-diagnoses LABELS를 함께 주면 No Memory 대비 정확도 차이를 계산한다. 진단 라벨은 같은 방문 키에 허용 진단 문자열 목록을 매핑한다. 대소문자·공백만 정규화하며 동의어는 명시한다. 입력·초기 기억·라우팅·모델 설정 서명이 같은 보고서만 비교한다. 미완료나 라벨 누락이 있으면 전체 지표는 미평가이고 관측된 부분집합 결과를 분리한다. 서명은 실제 서버 가중치나 주입한 테스트 클라이언트의 동일성까지 보증하지 않는다.

## 남은 제한과 필요한 데이터

1. 실제 다회 방문 데이터. 합성 데이터에는 환자 단위 학습/검증/시험 분할을 제공한다.
2. 관련 기억·오래된 기억·오용·정답 진단의 검수 라벨.
3. 임상 자료에서의 검색 성능 검증. 합성 기억/질의의 실제 벡터는 생성했다.
4. 충분한 실제 LLM 반복 실험·신뢰구간. 토큰/비용 계측·방문 단위 실패 재개는 구현했다.
5. 현재 객관적 소견을 요구하는 종료 조건 때문에 과거 기억만으로 확진하지 않는다. 검사 절감 효과 전체를 검증하려면 별도 종료 계약 검토가 필요하다.

자동 테스트는 정보 경계와 코드 동작을 검증한다. 임상 정확도나 수학적 최적성을 증명하지 않는다. 9번은 유사 사례 기반 효용 라우팅·Regret 평가까지 구현했으며 임상 검증은 남았다. 10번은 명시적 유한 모형으로 구현했으며 [VoI 직접 테스트 안내](voi_research.md)를 따른다.
