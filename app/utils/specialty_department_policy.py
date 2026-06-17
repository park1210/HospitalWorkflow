from __future__ import annotations

from typing import Any

from app.utils.clinical_rule_loader import load_specialty_department_config


def _policy_config() -> dict[str, Any]:
    return dict(load_specialty_department_config() or {})


def _section(name: str) -> dict[str, Any]:
    value = _policy_config().get(name, {}) or {}
    return dict(value) if isinstance(value, dict) else {}


def get_specialty_keywords(department: str) -> list[str]:
    value = _section("keywords").get(department, []) or []
    return [str(item).strip() for item in value if str(item).strip()]


def specialty_matches_keywords(department: str, text: str) -> bool:
    lowered = str(text or "").lower()
    return any(keyword.lower() in lowered for keyword in get_specialty_keywords(department))


def get_specialty_diagnostic_focus(department: str, default: str) -> str:
    value = str(_section("diagnostic_focus").get(department, "")).strip()
    return value or default


def get_specialty_next_step_prompt(department: str, default: str) -> str:
    value = str(_section("next_steps").get(department, "")).strip()
    return value or default


def get_specialty_test_priorities(department: str) -> list[str]:
    value = _section("test_priorities").get(department, []) or []
    return [str(item).strip() for item in value if str(item).strip()]


def get_specialty_interview_question(department: str, default: str) -> str:
    value = str(_section("interview_questions").get(department, "")).strip()
    return value or default


def get_specialty_generic_fallback_rules(department: str) -> list[dict[str, Any]]:
    value = _section("generic_fallback_rules").get(department, []) or []
    return [dict(item) for item in value if isinstance(item, dict)]
