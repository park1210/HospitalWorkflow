from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from typing import Optional

from app.config import settings


def load_dataset_rows(dataset_name: str) -> list[dict[str, Any]]:
    path = settings.DATASETS_DIR / f"{dataset_name}.jsonl"
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _confidence_bucket(value: float) -> str:
    if value < 0.4:
        return "low"
    if value < 0.75:
        return "medium"
    return "high"


def _safe_mean(total: float, count: int) -> float:
    if count <= 0:
        return 0.0
    return round(total / count, 4)


def _as_optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    return bool(value)


def analyze_dataset_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    case_summary: dict[str, dict[str, Any]] = {}
    action_by_bucket: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0.0, "return_to_go_total": 0.0, "immediate_reward_total": 0.0})
    )
    department_action_stats: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0.0, "return_to_go_total": 0.0})
    )
    reflection_rows: list[dict[str, Any]] = []

    for row in rows:
        case_id = str(row.get("case_id", "")).strip()
        if case_id and case_id not in case_summary:
            case_summary[case_id] = {
                "run_id": row.get("run_id", ""),
                "episode_reward": float(row.get("episode_reward", 0.0) or 0.0),
                "predicted_diagnosis": row.get("predicted_diagnosis", ""),
                "ground_truth_diagnosis": row.get("ground_truth_diagnosis", ""),
                "predicted_department": row.get("predicted_department", ""),
                "ground_truth_department": row.get("ground_truth_department", ""),
                "diagnosis_correct": bool(row.get("diagnosis_correct")),
                "department_correct": _as_optional_bool(row.get("department_correct")),
                "department_evaluable": row.get("department_correct") is not None,
                "final_decision_source": row.get("final_decision_source", ""),
            }

        action = str(row.get("action", "")).strip()
        bucket = _confidence_bucket(float(row.get("confidence", 0.0) or 0.0))
        bucket_stats = action_by_bucket[bucket][action]
        bucket_stats["count"] += 1
        bucket_stats["return_to_go_total"] += float(row.get("return_to_go", 0.0) or 0.0)
        bucket_stats["immediate_reward_total"] += float(row.get("immediate_reward", 0.0) or 0.0)

        department = str(row.get("target_department", "")).strip() or "unspecified"
        department_stats = department_action_stats[department][action]
        department_stats["count"] += 1
        department_stats["return_to_go_total"] += float(row.get("return_to_go", 0.0) or 0.0)

        if row.get("reflection_used") or row.get("reflection_triggers"):
            reflection_rows.append(
                {
                    "case_id": case_id,
                    "turn_index": int(row.get("turn_index", 0) or 0),
                    "action": action,
                    "confidence": float(row.get("confidence", 0.0) or 0.0),
                    "target_department": department,
                    "reflection_triggers": list(row.get("reflection_triggers", []) or []),
                    "return_to_go": float(row.get("return_to_go", 0.0) or 0.0),
                    "diagnosis_correct": bool(row.get("diagnosis_correct")),
                    "department_correct": _as_optional_bool(row.get("department_correct")),
                    "department_evaluable": row.get("department_correct") is not None,
                }
            )

    top_cases = sorted(case_summary.items(), key=lambda item: item[1]["episode_reward"], reverse=True)[:5]
    bottom_cases = sorted(case_summary.items(), key=lambda item: item[1]["episode_reward"])[:5]

    action_bucket_summary = {}
    for bucket, actions in sorted(action_by_bucket.items()):
        action_bucket_summary[bucket] = {}
        for action, values in sorted(actions.items()):
            count = int(values["count"])
            action_bucket_summary[bucket][action] = {
                "count": count,
                "avg_immediate_reward": _safe_mean(values["immediate_reward_total"], count),
                "avg_return_to_go": _safe_mean(values["return_to_go_total"], count),
            }

    department_summary = {}
    for department, actions in sorted(department_action_stats.items()):
        department_summary[department] = {}
        for action, values in sorted(actions.items()):
            count = int(values["count"])
            department_summary[department][action] = {
                "count": count,
                "avg_return_to_go": _safe_mean(values["return_to_go_total"], count),
            }

    return {
        "row_count": len(rows),
        "case_count": len(case_summary),
        "top_cases_by_episode_reward": [
            {"case_id": case_id, **payload} for case_id, payload in top_cases
        ],
        "bottom_cases_by_episode_reward": [
            {"case_id": case_id, **payload} for case_id, payload in bottom_cases
        ],
        "action_by_confidence_bucket": action_bucket_summary,
        "department_action_summary": department_summary,
        "reflection_rows": reflection_rows,
    }


def save_analysis(dataset_name: str, analysis: dict[str, Any]) -> Path:
    settings.DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    path = settings.DATASETS_DIR / f"{dataset_name}_analysis.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(analysis, handle, ensure_ascii=False, indent=2)
    return path
