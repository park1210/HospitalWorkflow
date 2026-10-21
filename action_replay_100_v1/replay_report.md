# 원본 기반 Ask/Test 연결 결과

100명·100개 case, Ask 100개, Test 4399개를 저장했다. Test가 있는 case는 97개다. 과별 분포는 기존 표본 그대로이며 최대 20%다.

문진 질문은 새 interaction template이며 응답은 실제 환자 보고 observation의 값/단위/기록 시각을 JSON으로 투영했다. 원본 의사–환자 대화록이 아니며, 없는 onset/duration/부위/active 상태를 추가하지 않았다. 초기에는 symptom 이름만 제시하고 score는 Ask 응답으로 분리했다.

기본 cases.json은 같은 index 내부 최신 Test값을 요청 후 반환하는 snapshot이다. available_minute=0은 재생 가정이며 실제 검사 공개 시각이 아니다. 결과는 initial state에 넣지 않았다. 다른 환자/다른 방문/후속 방문은 섞지 않았다. 대체 cases_recorded_time_proxy.json은 원본 시각 구간 상한을 분으로 올린 proxy이며 실제 release timing이 아니다.

검사 evidence는 원본 observation 값이며 diagnostic procedure는 수행 사실만 있다. 없는 영상 판독·치료 반응·협진 note를 만들지 않았다. 모든 원본과 earlier update는 environment/provenance/audit에 유지했다.

현재 모델 prepare_encounter는 연결된 Test 이름 전체를 available_tests로 공개한다. native 호환 파일은 이 동작을 따른다. 이 목록은 실제 수행 검사에 의존하므로 action availability로 인한 편향이 남는다. strict projection을 원하면 replay_loader의 doctor_input을 사용해야 하며 모델 측 연결이 별도로 필요하다. model/simulator 수정 없이 이 내부 동작을 없앴다고 주장하지 않는다.

임상 정답 검수, Memory relevance, routing 성능 artifact, Bayesian VoI 모델은 여전히 미확보다. snapshot으로 입력 가능성이 개선된 것이며 B0~B4 연구용 검증 완료를 의미하지 않는다. 모델·simulator·LLM·테스트는 실행하지 않았다.
