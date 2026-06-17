from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from typing import Iterable

from app.config import settings


def load_step_rows(dataset_name: str) -> list[dict[str, Any]]:
    path = settings.DATASETS_DIR / f"{dataset_name}.jsonl"
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def build_imitation_rows(
    step_rows: Iterable[dict[str, Any]],
    *,
    require_department_correct: bool = True,
    min_episode_reward: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = list(step_rows)
    if not rows:
        return [], {"selected_cases": 0, "selected_rows": 0}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        case_id = str(row.get("case_id", "")).strip()
        if case_id:
            grouped.setdefault(case_id, []).append(row)

    selected_case_ids: list[str] = []
    imitation_rows: list[dict[str, Any]] = []

    for case_id, case_rows in grouped.items():
        first = case_rows[0]
        diagnosis_correct = bool(first.get("diagnosis_correct"))
        department_correct = first.get("department_correct") is True
        episode_reward = float(first.get("episode_reward", 0.0) or 0.0)

        if not diagnosis_correct:
            continue
        if require_department_correct and not department_correct:
            continue
        if min_episode_reward is not None and episode_reward < min_episode_reward:
            continue

        selected_case_ids.append(case_id)
        for row in case_rows:
            imitation_rows.append(
                {
                    "run_id": row.get("run_id", ""),
                    "case_id": case_id,
                    "turn_index": row.get("turn_index", 0),
                    "observation": {
                        "confidence": row.get("confidence", 0.0),
                        "target_department": row.get("target_department", ""),
                        "suspected_diagnoses": row.get("suspected_diagnoses", []),
                        "recommended_tests": row.get("recommended_tests", []),
                        "known_information_count": row.get("known_information_count", 0),
                        "missing_information_count": row.get("missing_information_count", 0),
                        "requested_tests_count": row.get("requested_tests_count", 0),
                        "requested_consults_count": row.get("requested_consults_count", 0),
                        "positive_evidence_count": row.get("positive_evidence_count", 0),
                        "negative_evidence_count": row.get("negative_evidence_count", 0),
                        "exposure_evidence_count": row.get("exposure_evidence_count", 0),
                        "patient_context_count": row.get("patient_context_count", 0),
                        "positive_evidence_bucket": row.get("positive_evidence_bucket", "none"),
                        "negative_evidence_bucket": row.get("negative_evidence_bucket", "none"),
                        "patient_context_bucket": row.get("patient_context_bucket", "none"),
                        "has_counterevidence": row.get("has_counterevidence", False),
                        "has_exposure_evidence": row.get("has_exposure_evidence", False),
                        "has_requested_consult": row.get("has_requested_consult", False),
                        "has_requested_test": row.get("has_requested_test", False),
                    },
                    "action": row.get("action", ""),
                    "target": row.get("target", ""),
                    "decision_rationale": row.get("decision_rationale", ""),
                    "return_to_go": row.get("return_to_go", 0.0),
                    "episode_reward": episode_reward,
                    "final_decision_source": row.get("final_decision_source", ""),
                    "ground_truth_diagnosis": row.get("ground_truth_diagnosis", ""),
                    "ground_truth_department": row.get("ground_truth_department", ""),
                }
            )

    summary = {
        "selected_cases": len(selected_case_ids),
        "selected_rows": len(imitation_rows),
        "selected_case_ids": selected_case_ids,
        "require_department_correct": require_department_correct,
        "min_episode_reward": min_episode_reward,
    }
    return imitation_rows, summary


def save_imitation_dataset(
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
