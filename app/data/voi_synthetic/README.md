# 10번 VoI 합성 예제

임상 미검수 toy 모형이다. 검사 확률·비용·진단명은 실제 의학 수치를 의미하지 않는다.

- model.json: 2진단·4정보 행동의 명시적 확률/효용 모형.
- cases.json, labels.json: 별도 합성 환자 2명과 정답.
- memory.json: 선택적으로 조회할 이전 기록.
- training_outcomes.json: 조건부 확률 추정 형식을 보여주는 합성 40행.

실행·수동 테스트 방법: [10번 안내](../../../docs/voi_research.md).
