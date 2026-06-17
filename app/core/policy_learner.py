from __future__ import annotations

import json
from collections import Counter
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.config import settings


def confidence_bucket(value: float) -> str:
    if value < 0.4:
        return "low"
    if value < 0.75:
        return "medium"
    return "high"


def suspected_bucket(suspected: list[str]) -> str:
    count = len([item for item in suspected if str(item).strip()])
    if count <= 0:
        return "none"
    if count == 1:
        return "one"
    return "many"


def count_bucket(value: int) -> str:
    if value <= 0:
        return "none"
    if value == 1:
        return "one"
    if value <= 3:
        return "few"
    return "many"


def feature_key_from_row(row: dict[str, Any]) -> str:
    observation = row.get("observation", {}) or {}
    confidence = (
        observation.get("confidence", row.get("confidence", 0.0))
        if isinstance(observation, dict)
        else row.get("confidence", 0.0)
    )
    target_department = (
        observation.get("target_department", row.get("target_department", ""))
        if isinstance(observation, dict)
        else row.get("target_department", "")
    )
    suspected_diagnoses = (
        observation.get("suspected_diagnoses", row.get("suspected_diagnoses", []))
        if isinstance(observation, dict)
        else row.get("suspected_diagnoses", [])
    )
    recommended_tests = (
        observation.get("recommended_tests", row.get("recommended_tests", []))
        if isinstance(observation, dict)
        else row.get("recommended_tests", [])
    )
    positive_evidence_count = (
        observation.get("positive_evidence_count", row.get("positive_evidence_count", 0))
        if isinstance(observation, dict)
        else row.get("positive_evidence_count", 0)
    )
    negative_evidence_count = (
        observation.get("negative_evidence_count", row.get("negative_evidence_count", 0))
        if isinstance(observation, dict)
        else row.get("negative_evidence_count", 0)
    )
    requested_consults_count = (
        observation.get("requested_consults_count", row.get("requested_consults_count", 0))
        if isinstance(observation, dict)
        else row.get("requested_consults_count", 0)
    )
    patient_context_count = (
        observation.get("patient_context_count", row.get("patient_context_count", 0))
        if isinstance(observation, dict)
        else row.get("patient_context_count", 0)
    )
    return json.dumps(
        {
            "target_department": str(target_department).strip() or "general_medicine",
            "confidence_bucket": confidence_bucket(float(confidence or 0.0)),
            "suspected_bucket": suspected_bucket(list(suspected_diagnoses or [])),
            "has_recommended_tests": bool(recommended_tests),
            "positive_evidence_bucket": count_bucket(int(positive_evidence_count or 0)),
            "negative_evidence_bucket": count_bucket(int(negative_evidence_count or 0)),
            "has_requested_consult": bool(requested_consults_count),
            "patient_context_bucket": count_bucket(int(patient_context_count or 0)),
        },
        sort_keys=True,
    )


def feature_key_from_runtime(
    *,
    target_department: str,
    confidence: float,
    suspected_diagnoses: list[str],
    recommended_tests: list[str],
    positive_evidence_count: int = 0,
    negative_evidence_count: int = 0,
    requested_consults_count: int = 0,
    patient_context_count: int = 0,
) -> str:
    return json.dumps(
        {
            "target_department": str(target_department).strip() or "general_medicine",
            "confidence_bucket": confidence_bucket(float(confidence or 0.0)),
            "suspected_bucket": suspected_bucket(list(suspected_diagnoses or [])),
            "has_recommended_tests": bool(recommended_tests),
            "positive_evidence_bucket": count_bucket(int(positive_evidence_count or 0)),
            "negative_evidence_bucket": count_bucket(int(negative_evidence_count or 0)),
            "has_requested_consult": bool(requested_consults_count),
            "patient_context_bucket": count_bucket(int(patient_context_count or 0)),
        },
        sort_keys=True,
    )


def learn_policy_rules(
    imitation_rows: list[dict[str, Any]],
    *,
    min_support: int = 3,
    min_dominance: float = 0.85,
) -> dict[str, Any]:
    grouped_actions: dict[str, Counter[str]] = defaultdict(Counter)
    grouped_returns: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for row in imitation_rows:
        key = feature_key_from_row(row)
        action = str(row.get("action", "")).strip()
        if not action:
            continue
        grouped_actions[key][action] += 1
        grouped_returns[key][action] += float(row.get("return_to_go", 0.0) or 0.0)

    rules: dict[str, Any] = {}
    for key, counter in grouped_actions.items():
        total = sum(counter.values())
        action, count = counter.most_common(1)[0]
        dominance = count / total if total else 0.0
        if total < min_support or dominance < min_dominance:
            continue
        avg_return = grouped_returns[key][action] / count if count else 0.0
        rules[key] = {
            "action": action,
            "support": total,
            "dominance": round(dominance, 4),
            "avg_return_to_go": round(avg_return, 4),
        }

    return {
        "min_support": min_support,
        "min_dominance": min_dominance,
        "rule_count": len(rules),
        "rules": rules,
    }


def filter_policy_rules(
    policy: dict[str, Any],
    validation_rows: list[dict[str, Any]],
    *,
    min_validation_support: int = 2,
    min_return_margin: float = 0.0,
) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in validation_rows:
        key = feature_key_from_row(row)
        action = str(row.get("action", "")).strip()
        if not action:
            continue
        grouped[key][action].append(float(row.get("return_to_go", 0.0) or 0.0))

    kept_rules: dict[str, Any] = {}
    dropped_rules: dict[str, Any] = {}
    for key, rule in dict(policy.get("rules", {}) or {}).items():
        learned_action = str(rule.get("action", "")).strip()
        candidates = grouped.get(key, {})
        learned_values = candidates.get(learned_action, [])
        if len(learned_values) < min_validation_support:
            dropped_rules[key] = {
                **rule,
                "drop_reason": "insufficient_validation_support",
                "validation_support": len(learned_values),
            }
            continue

        action_means = {
            action: (sum(values) / len(values))
            for action, values in candidates.items()
            if values
        }
        if not action_means:
            dropped_rules[key] = {
                **rule,
                "drop_reason": "no_validation_actions",
                "validation_support": 0,
            }
            continue

        best_action, best_mean = max(action_means.items(), key=lambda item: item[1])
        learned_mean = action_means.get(learned_action, float("-inf"))
        if learned_action != best_action or learned_mean + min_return_margin < best_mean:
            dropped_rules[key] = {
                **rule,
                "drop_reason": "not_best_on_validation",
                "validation_support": len(learned_values),
                "validation_avg_return": round(learned_mean, 4),
                "best_validation_action": best_action,
                "best_validation_avg_return": round(best_mean, 4),
            }
            continue

        kept_rules[key] = {
            **rule,
            "validation_support": len(learned_values),
            "validation_avg_return": round(learned_mean, 4),
        }

    return {
        "min_support": policy.get("min_support", 0),
        "min_dominance": policy.get("min_dominance", 0.0),
        "rule_count": len(kept_rules),
        "rules": kept_rules,
        "dropped_rule_count": len(dropped_rules),
        "dropped_rules": dropped_rules,
        "min_validation_support": min_validation_support,
        "min_return_margin": min_return_margin,
    }


def save_policy_rules(policy: dict[str, Any], path: Path | None = None) -> Path:
    target = path or settings.LEARNED_POLICY_RULES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(policy, handle, ensure_ascii=False, indent=2)
    return target


def load_policy_rules(path: Path | None = None) -> dict[str, Any]:
    target = path or settings.LEARNED_POLICY_RULES_PATH
    if not target.exists():
        return {}
    return json.loads(target.read_text(encoding="utf-8"))
