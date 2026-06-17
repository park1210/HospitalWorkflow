from __future__ import annotations

from typing import Any

from app.utils.clinical_rule_loader import load_what_if_recommendation_config


def _config() -> dict[str, Any]:
    return dict(load_what_if_recommendation_config() or {})


def _section(name: str) -> dict[str, Any]:
    value = _config().get(name, {}) or {}
    return dict(value) if isinstance(value, dict) else {}


def get_routing_recommendation_policy() -> dict[str, Any]:
    return _section("routing")


def get_specialty_recommendation_policy() -> dict[str, Any]:
    return _section("specialty")


def get_combined_recommendation_policy() -> dict[str, Any]:
    return _section("combined")


def get_combined_bucket_rank(priority_bucket: str, review_subbucket: str) -> int:
    bucket_ranks = dict(get_combined_recommendation_policy().get("bucket_ranks", {}) or {})
    if priority_bucket == "priority_replay":
        return int(bucket_ranks.get("priority_replay", 0))
    if priority_bucket == "review_candidate" and review_subbucket == "review_high":
        return int(bucket_ranks.get("review_high", 1))
    if priority_bucket == "review_candidate":
        return int(bucket_ranks.get("review_low", 2))
    return int(bucket_ranks.get("low_priority", 3))


def get_combined_type_rank(recommendation_type: str, department_correct: bool) -> int:
    type_ranks = dict(get_combined_recommendation_policy().get("type_ranks", {}) or {})
    if recommendation_type == "routing":
        key = "routing_department_correct" if department_correct else "routing_department_incorrect"
        return int(type_ranks.get(key, 0 if not department_correct else 1))
    return int(type_ranks.get("specialty", 1))
