"""Shared test routing and timing contract; no disease-specific decisions."""
from __future__ import annotations

import math
import re
from typing import Any


def _minutes(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be finite positive minutes")
    return math.ceil(value)


def test_resource_type(test_name: str, case: dict[str, Any] | None = None) -> str:
    explicit = (case or {}).get("resource_profile", {}).get("test_resources", {}).get(test_name)
    if explicit is not None:
        if explicit not in {"lab_slot", "imaging_slot"}:
            raise ValueError(f"Unsupported resource for {test_name}: {explicit}")
        return explicit
    # Token boundaries avoid interpreting 'lactate' as a CT scan.
    imaging = re.search(r"\b(ct|mri|x[ -]?ray|imaging|ultrasound)\b", test_name, re.IGNORECASE)
    return "imaging_slot" if imaging else "lab_slot"


def test_timing(case: dict[str, Any], test_name: str, defaults: dict[str, Any]) -> dict[str, Any]:
    profile = case.get("resource_profile", {})
    group = test_resource_type(test_name, case)
    turnaround = profile.get("test_turnaround", {}).get(test_name, defaults[group])
    occupancy = profile.get("test_occupancy", {}).get(test_name, turnaround)
    ready = _minutes(turnaround, f"test_turnaround.{test_name}")
    busy = _minutes(occupancy, f"test_occupancy.{test_name}")
    if occupancy > turnaround:
        raise ValueError(f"Test occupancy exceeds turnaround: {test_name}")
    return {"resource_type": group, "occupancy_min": busy, "turnaround_min": ready,
            "occupancy_source": "explicit" if test_name in profile.get("test_occupancy", {}) else "turnaround_fallback",
            "turnaround_source": "explicit" if test_name in profile.get("test_turnaround", {}) else "configuration_default",
            "resource_source": "explicit" if test_name in profile.get("test_resources", {}) else "name_fallback"}


def validate_test_profile(case: dict[str, Any], defaults: dict[str, Any]) -> None:
    profile = case.get("resource_profile", {})
    if not isinstance(profile, dict):
        raise ValueError("resource_profile must be an object")
    names = set()
    for field in ("test_turnaround", "test_occupancy", "test_resources"):
        entries = profile.get(field, {})
        if not isinstance(entries, dict) or any(not isinstance(k, str) or not k.strip() for k in entries):
            raise ValueError(f"{field} must map nonempty test names to values")
        names.update(entries)
    for name in names:
        test_timing(case, name, defaults)
