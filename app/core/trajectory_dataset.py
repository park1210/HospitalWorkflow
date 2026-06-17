from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from typing import Iterable

from app.config import settings


def _resolve_run_ids(run_ids: Iterable[str] | None = None) -> list[str]:
    if run_ids:
        values = [str(item).strip() for item in run_ids if str(item).strip()]
        if values:
            return values
    if not settings.TRAJECTORIES_DIR.exists():
        return []
    return sorted(
        path.name
        for path in settings.TRAJECTORIES_DIR.iterdir()
        if path.is_dir()
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_mean(total: float, count: int) -> float:
    if count <= 0:
        return 0.0
    return round(total / count, 4)


def _is_true(value: Any) -> bool:
    return value is True


def _bucket_count(value: int) -> str:
    if value <= 0:
        return "none"
    if value == 1:
        return "one"
    if value <= 3:
        return "few"
    return "many"


def build_step_dataset(run_ids: Iterable[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    action_stats: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "immediate_reward_total": 0.0, "return_to_go_total": 0.0}
    )
    trigger_stats: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "immediate_reward_total": 0.0}
    )
    run_summaries: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "cases": 0.0,
            "steps": 0.0,
            "diagnosis_correct": 0.0,
            "department_correct": 0.0,
            "department_evaluable_cases": 0.0,
            "episode_reward_total": 0.0,
        }
    )

    for run_id in _resolve_run_ids(run_ids):
        trajectory_dir = settings.TRAJECTORIES_DIR / run_id
        result_dir = settings.RESULTS_DIR / run_id
        if not trajectory_dir.exists() or not result_dir.exists():
            continue

        for trajectory_path in sorted(trajectory_dir.glob("*_trajectory.json")):
            trajectory = _load_json(trajectory_path)
            case_id = str(trajectory.get("case_id", "")).strip()
            result_path = result_dir / f"{case_id}_result.json"
            if not case_id or not result_path.exists():
                continue

            result = _load_json(result_path)
            steps = trajectory.get("steps", []) or []
            run_summaries[run_id]["cases"] += 1
            run_summaries[run_id]["steps"] += len(steps)
            run_summaries[run_id]["diagnosis_correct"] += float(_is_true(result.get("diagnosis_correct")))
            if result.get("department_correct") is not None:
                run_summaries[run_id]["department_correct"] += float(_is_true(result.get("department_correct")))
                run_summaries[run_id]["department_evaluable_cases"] += 1.0
            run_summaries[run_id]["episode_reward_total"] += float(trajectory.get("episode_reward", 0.0) or 0.0)

            for step_index, step in enumerate(steps):
                observation = step.get("observation", {}) or {}
                evidence_summary = step.get("evidence_summary", {}) or {}
                positive_evidence = list(evidence_summary.get("positive_or_supporting", []) or [])
                negative_evidence = list(evidence_summary.get("negative_or_excluding", []) or [])
                exposure_evidence = list(evidence_summary.get("medication_or_exposure", []) or [])
                patient_context = list(evidence_summary.get("patient_reported_context", []) or [])
                reasoning_context = list(evidence_summary.get("reasoning_context", []) or [])
                known_information = list(observation.get("known_information", []) or [])
                missing_information = list(observation.get("missing_information", []) or [])
                requested_tests = list(observation.get("requested_tests", []) or [])
                requested_consults = list(observation.get("requested_consults", []) or [])
                suspected_diagnoses = list((step.get("reasoning_output", {}) or {}).get("suspected_diagnoses", []))
                recommended_tests = list((step.get("reasoning_output", {}) or {}).get("recommended_tests", []))

                row = {
                    "run_id": run_id,
                    "case_id": case_id,
                    "step_index": step_index,
                    "turn_index": int(step.get("turn_index", step_index + 1) or (step_index + 1)),
                    "action": str(step.get("action", "")).strip(),
                    "target": str(step.get("target", "")).strip(),
                    "target_department": str(
                        (step.get("reasoning_output", {}) or {}).get("target_department", "")
                    ).strip(),
                    "confidence": float(
                        ((step.get("reasoning_output", {}) or {}).get("confidence", 0.0)) or 0.0
                    ),
                    "suspected_diagnoses": suspected_diagnoses,
                    "recommended_tests": recommended_tests,
                    "decision_rationale": str(step.get("decision_rationale", "")).strip(),
                    "reflection_triggers": list(step.get("reflection_triggers", []) or []),
                    "reflection_used": bool(step.get("reflection_used")),
                    "used_reasoning_llm": bool(step.get("used_reasoning_llm")),
                    "immediate_reward": float(step.get("immediate_reward", 0.0) or 0.0),
                    "return_to_go": float(step.get("return_to_go", 0.0) or 0.0),
                    "episode_reward": float(trajectory.get("episode_reward", 0.0) or 0.0),
                    "final_decision_source": str(trajectory.get("final_decision_source", "")).strip(),
                    "predicted_diagnosis": str(result.get("predicted_diagnosis", "")).strip(),
                    "predicted_department": str(result.get("predicted_department", "")).strip(),
                    "diagnostic_service": str(result.get("diagnostic_service", "")).strip(),
                    "er_working_diagnosis": str(result.get("er_working_diagnosis", "")).strip(),
                    "diagnosis_correct": bool(result.get("diagnosis_correct")),
                    "department_correct": result.get("department_correct"),
                    "department_evaluable": result.get("department_correct") is not None,
                    "ground_truth_diagnosis": str(result.get("ground_truth", "")).strip(),
                    "ground_truth_department": str(result.get("ground_truth_department", "")).strip(),
                    "triage_level": int(observation.get("triage_level", 3) or 3),
                    "is_immediately_unstable": bool(observation.get("is_immediately_unstable")),
                    "needs_resuscitation_now": bool(observation.get("needs_resuscitation_now")),
                    "working_problem_count": len(list(observation.get("working_problem_list", []) or [])),
                    "red_flag_count": len(list(observation.get("red_flags", []) or [])),
                    "stabilization_action_count": len(list(observation.get("stabilization_actions", []) or [])),
                    "known_information_count": len(known_information),
                    "missing_information_count": len(missing_information),
                    "requested_tests_count": len(requested_tests),
                    "requested_consults_count": len(requested_consults),
                    "suspected_diagnosis_count": len([item for item in suspected_diagnoses if str(item).strip()]),
                    "recommended_test_count": len([item for item in recommended_tests if str(item).strip()]),
                    "positive_evidence_count": len(positive_evidence),
                    "negative_evidence_count": len(negative_evidence),
                    "exposure_evidence_count": len(exposure_evidence),
                    "patient_context_count": len(patient_context),
                    "reasoning_context_count": len(reasoning_context),
                    "objective_finding_count": len(positive_evidence) + len(negative_evidence),
                    "specialty_input_count": len(requested_consults),
                    "known_information_bucket": _bucket_count(len(known_information)),
                    "requested_tests_bucket": _bucket_count(len(requested_tests)),
                    "requested_consults_bucket": _bucket_count(len(requested_consults)),
                    "positive_evidence_bucket": _bucket_count(len(positive_evidence)),
                    "negative_evidence_bucket": _bucket_count(len(negative_evidence)),
                    "patient_context_bucket": _bucket_count(len(patient_context)),
                    "red_flag_bucket": _bucket_count(len(list(observation.get("red_flags", []) or []))),
                    "objective_finding_bucket": _bucket_count(len(positive_evidence) + len(negative_evidence)),
                    "has_objective_evidence": bool(positive_evidence or negative_evidence),
                    "has_counterevidence": bool(negative_evidence),
                    "has_exposure_evidence": bool(exposure_evidence),
                    "has_specialty_input": bool(requested_consults),
                    "has_requested_consult": bool(requested_consults),
                    "has_requested_test": bool(requested_tests),
                    "er_handoff_ready_signal": bool(
                        (positive_evidence or negative_evidence)
                        and (
                            requested_consults
                            or float(((step.get("reasoning_output", {}) or {}).get("confidence", 0.0) or 0.0) >= 0.75)
                        )
                    ),
                }
                rows.append(row)

                action = row["action"]
                action_stats[action]["count"] += 1
                action_stats[action]["immediate_reward_total"] += row["immediate_reward"]
                action_stats[action]["return_to_go_total"] += row["return_to_go"]

                for trigger in row["reflection_triggers"]:
                    trigger_stats[trigger]["count"] += 1
                    trigger_stats[trigger]["immediate_reward_total"] += row["immediate_reward"]

    action_summary = {}
    for action, values in sorted(action_stats.items()):
        count = int(values["count"])
        action_summary[action] = {
            "count": count,
            "avg_immediate_reward": _safe_mean(values["immediate_reward_total"], count),
            "avg_return_to_go": _safe_mean(values["return_to_go_total"], count),
        }

    trigger_summary = {}
    for trigger, values in sorted(trigger_stats.items()):
        count = int(values["count"])
        trigger_summary[trigger] = {
            "count": count,
            "avg_immediate_reward": _safe_mean(values["immediate_reward_total"], count),
        }

    run_summary = {}
    for run_id, values in sorted(run_summaries.items()):
        cases = int(values["cases"])
        department_cases = int(values["department_evaluable_cases"])
        run_summary[run_id] = {
            "cases": cases,
            "steps": int(values["steps"]),
            "diagnosis_accuracy": _safe_mean(values["diagnosis_correct"], cases),
            "department_accuracy": _safe_mean(values["department_correct"], department_cases),
            "department_evaluable_cases": department_cases,
            "avg_episode_reward": _safe_mean(values["episode_reward_total"], cases),
        }

    summary = {
        "rows": len(rows),
        "runs": run_summary,
        "actions": action_summary,
        "reflection_triggers": trigger_summary,
    }
    return rows, summary


def save_step_dataset(
    dataset_name: str,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> tuple[Path, Path]:
    settings.DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = settings.DATASETS_DIR / f"{dataset_name}.jsonl"
    summary_path = settings.DATASETS_DIR / f"{dataset_name}_summary.json"

    with open(jsonl_path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    return jsonl_path, summary_path
