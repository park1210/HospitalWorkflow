from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings


def _data_path(filename: str) -> Path:
    return settings.PROJECT_ROOT / "app" / "data" / filename


@lru_cache(maxsize=1)
def load_evidence_diagnosis_hints() -> list[dict[str, Any]]:
    path = _data_path("evidence_diagnosis_hints.json")
    if not path.exists():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def load_department_ownership_rules() -> list[dict[str, Any]]:
    path = _data_path("department_ownership_rules.json")
    if not path.exists():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def load_specialty_department_config() -> dict[str, Any]:
    path = _data_path("specialty_department_config.json")
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def load_what_if_recommendation_config() -> dict[str, Any]:
    path = _data_path("what_if_recommendation_config.json")
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, dict) else {}
