# ClinicaTextSim Hospital Workflow

- [7·9·10번 연구 구현 현황 및 작업 지도](tracker.md)
- [한 번의 명령으로 7·9·10 빠른 데모](docs/quick_research_demo.md): `python -m app.scripts.run_research_demo`
- [KSC 논문 B0~B4 실험 방법](docs/paper_experiments.md): `python -m app.scripts.run_paper_experiments`
- [12명·24방문 도전 실험 세트와 실행 순서](docs/challenge_benchmark.md)
- [실행 중 병행할 검색·라우팅 비교 및 남은 작업](docs/component_comparison_tests.md)
- [새 UI 구성 제안](docs/new_ui_proposal.md)
- [장기 기억 연구 실행 안내](docs/longitudinal_research.md)

ER-style multi-agent clinical simulator with two what-if analysis layers:

- **routing what-if**
  - tests plausible alternative specialty handoffs from ER
- **specialty what-if**
  - tests same-department exact-diagnosis refinement decisions

This project does **not** treat what-if as arbitrary physician-error injection.
The current what-if system is designed for:

- ambiguity-gated replay
- plausible alternative comparison
- simulator policy sensitivity analysis

More detailed guidance:

- [7장 반복 실험과 연구 범위: 재현성, 부하·자원 비교, 데이터 준비도](docs/hospital_experiment_protocol.md)
- [5장 평가 프레임워크: 지표, 정답 워크플로, 실행 및 비교](docs/hospital_evaluation_framework.md)
- [6장 병원 자원·환자 흐름 모델: 설정, 수식, 데이터 요구사항](docs/hospital_flow_model.md)
- [docs/what_if_operating_guide.md](docs/what_if_operating_guide.md)

Main what-if recommendation config:

- [app/data/what_if_recommendation_config.json](app/data/what_if_recommendation_config.json)

Main specialty policy config:

- [app/data/specialty_department_config.json](app/data/specialty_department_config.json)

## Run

Full run:

```powershell
$env:MAX_CASES='0'; python -c "from app.main import main; main()"
```

Single-case smoke run:

```powershell
$env:MAX_CASES='1'; python -c "from app.main import main; main()"
```

## Live Multi-Patient Pixel Viewer

The project now includes a live Pygame-based hospital viewer for the temporal/multi-patient simulator.

Recommended end-to-end launch:

```powershell
python -m app.scripts.run_live_pixel_session --max-cases 2
```

Viewer only:

```powershell
python -m app.ui.pixel_viewer
```

Compatibility launcher:

```powershell
python -m app.scripts.run_live_pixel_viewer
```

The viewer package is organized under:

- `app/ui/pixel_viewer/`
  - `app.py`
  - `runtime.py`
  - `background_renderer.py`
  - `animation_controller.py`
  - `entity_renderer.py`
  - `panel_renderer.py`
  - `input_controller.py`

Supporting architecture and wireframe notes:

- [docs/pixel_agents_ui_architecture.md](docs/pixel_agents_ui_architecture.md)
- [docs/pixel_agents_ui_wireframe.md](docs/pixel_agents_ui_wireframe.md)

Main live viewer outputs:

- `outputs/reports/<run_id>/live_visual_state.json`
- `outputs/reports/<run_id>/live_visual_history.json`

## Main What-If Workflows

### Combined top recommendations

```powershell
python -m app.scripts.recommend_combined_what_if_cases --routing-path outputs\what_if\recommendations\routing_replay_recommendations_20260526_234422_tuned_v3.json --specialty-path outputs\what_if\recommendations\specialty_replay_recommendations_20260526_234422_tuned_v2.json --output-name combined_what_if_recommendations_20260526_234422_v2.json
python -m app.scripts.print_combined_what_if_recommendations --recommendation-path outputs\what_if\recommendations\combined_what_if_recommendations_20260526_234422_v2.json --limit 10 --markdown-out docs\reports\combined_what_if_recommendations.md
```

### Routing priority replay

```powershell
python -m app.scripts.run_routing_recommendation_batch --recommendation-path outputs\what_if\recommendations\routing_replay_recommendations_20260526_234422_tuned_v3.json --replay-prefix routing_recommendation_priority_v4 --bucket priority_replay
```

### Specialty priority replay

```powershell
python -m app.scripts.run_specialty_recommendation_batch --recommendation-path outputs\what_if\recommendations\specialty_replay_recommendations_20260526_234422_tuned_v2.json --replay-prefix specialty_recommendation_tuned --bucket priority_replay
```

## Review Candidate Tables

Routing review candidates:

```powershell
python -m app.scripts.print_what_if_review_candidates --type routing --recommendation-path outputs\what_if\recommendations\routing_replay_recommendations_20260526_234422_tuned_v3.json --bucket review_candidate --limit 8
```

Routing `review_high` only:

```powershell
python -m app.scripts.run_routing_recommendation_batch --recommendation-path outputs\what_if\recommendations\routing_replay_recommendations_20260526_234422_tuned_v3.json --replay-prefix routing_recommendation_review_high_v2 --bucket review_candidate --review-subbucket review_high --limit 2
```

Specialty review candidates:

```powershell
python -m app.scripts.print_what_if_review_candidates --type specialty --recommendation-path outputs\what_if\recommendations\specialty_replay_recommendations_20260526_234422_tuned_v2.json --bucket review_candidate --limit 8
```

Specialty `review_high` only:

```powershell
python -m app.scripts.run_specialty_recommendation_batch --recommendation-path outputs\what_if\recommendations\specialty_replay_recommendations_20260526_234422_tuned_v2.json --replay-prefix specialty_recommendation_review_high_v2 --bucket review_candidate --review-subbucket review_high --limit 1
```

Save the same table as markdown:

```powershell
python -m app.scripts.print_what_if_review_candidates --type routing --recommendation-path outputs\what_if\recommendations\routing_replay_recommendations_20260526_234422_tuned_v3.json --bucket review_candidate --limit 8 --markdown-out docs\reports\routing_review_candidates.md
python -m app.scripts.print_what_if_review_candidates --type specialty --recommendation-path outputs\what_if\recommendations\specialty_replay_recommendations_20260526_234422_tuned_v2.json --bucket review_candidate --limit 8 --markdown-out docs\reports\specialty_review_candidates.md
```

## Current Operating Rule

- `routing priority_replay`
  - directly replayable
- `routing review_candidate`
  - inspect before replay
- `specialty priority_replay`
  - directly replayable
- `specialty review_candidate`
  - inspect before replay

## Recommendation Config

Recommendation thresholds and combined ranking priorities are now managed in:

- `app/data/what_if_recommendation_config.json`

Use this file to adjust:

- routing replay thresholds
- specialty replay thresholds
- combined routing vs specialty ranking order

The old `app/data/high_signal_diagnosis_rules.json` file is now kept only as a legacy reference.
It is no longer part of the active specialty decision path.

## Outputs

- run-level what-if summary:
  - `outputs/what_if/<run_id>/what_if_report.json`
- replay result:
  - `outputs/what_if/replays/<replay_run_id>/...`
- replay comparison:
  - `outputs/what_if/comparisons/<replay_run_id>/...`
- recommendations:
  - `outputs/what_if/recommendations/...`
- batch summaries:
  - `outputs/what_if/batch_summaries/...`


## LLM 역할 통합 실행

환자·응급실·전문과 LLM을 병렬 엔진에서 사용하려면 `--clinical-mode llm_required`를 명시하세요. 기존 기본값은 `demo`입니다.

```powershell
python -m app.scripts.run_live_parallel_visual_multi_patient --fixed-demo --max-cases 1 --clinical-mode llm_required --minute-limit 60
```

[적용 구조, 악화/치료 입력 형식, 오류 기록, 검증 범위](docs/llm_role_upgrade.md)
