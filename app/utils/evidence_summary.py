from __future__ import annotations

import re
from typing import Iterable


POSITIVE_KEYWORDS = [
    "present",
    "positive",
    "elevated",
    "increased",
    "decreased",
    "abnormal",
    "lesion",
    "demyelinating",
    "obstruction",
    "distended",
    "eosinophil",
    "eosinophilic",
    "ataxia",
    "mass",
]


NEGATIVE_KEYWORDS = [
    "negative",
    "normal",
    "without",
    "no ",
    "resolved",
    "not detected",
]


MEDICATION_EXPOSURE_KEYWORDS = [
    "amoxicillin",
    "cephalexin",
    "natalizumab",
    "antibiotic",
    "drug",
    "medication",
]


def _compact(text: str) -> str:
    value = str(text).strip()
    value = re.sub(r"\s+", " ", value)
    return value


def split_objective_sentences(text: str) -> list[str]:
    compact = _compact(text)
    if not compact:
        return []
    chunks = re.split(r"(?<=[.!?])\s+|;\s+|\}\s*,\s*'|\}\s*,\s*\"|,\s*'", compact)
    return [_compact(chunk) for chunk in chunks if _compact(chunk)]


def classify_evidence_line(text: str) -> str:
    lowered = _compact(text).lower()
    if any(keyword in lowered for keyword in MEDICATION_EXPOSURE_KEYWORDS):
        return "medication_or_exposure"
    if any(keyword in lowered for keyword in NEGATIVE_KEYWORDS):
        return "negative_or_excluding"
    if any(keyword in lowered for keyword in POSITIVE_KEYWORDS):
        return "positive_or_supporting"
    return "context"


def build_evidence_summary(state: dict, transcript: list[dict]) -> dict[str, list[str]]:
    objective_lines: list[str] = []
    patient_lines: list[str] = []
    reasoning_lines: list[str] = []

    for entry in transcript:
        role = str(entry.get("role", "")).strip()
        content = _compact(entry.get("content", ""))
        if not content:
            continue
        if role in {"er_test_result", "specialty_consult"}:
            objective_lines.extend(split_objective_sentences(content))
        elif role == "patient":
            patient_lines.extend(split_objective_sentences(content))
        elif role in {"er_reasoning", "er_final_decision", "chief_doctor"}:
            reasoning_lines.append(content)

    known_information = [_compact(item) for item in state.get("known_information", []) if _compact(item)]
    objective_lines.extend(
        item
        for item in known_information
        if ":" in item and item not in objective_lines
    )

    summary = {
        "positive_or_supporting": [],
        "negative_or_excluding": [],
        "medication_or_exposure": [],
        "patient_reported_context": [],
        "reasoning_context": reasoning_lines[-4:],
    }

    for line in objective_lines:
        category = classify_evidence_line(line)
        if category == "positive_or_supporting" and line not in summary["positive_or_supporting"]:
            summary["positive_or_supporting"].append(line)
        elif category == "negative_or_excluding" and line not in summary["negative_or_excluding"]:
            summary["negative_or_excluding"].append(line)
        elif category == "medication_or_exposure" and line not in summary["medication_or_exposure"]:
            summary["medication_or_exposure"].append(line)

    for line in patient_lines[-6:]:
        if line not in summary["patient_reported_context"]:
            summary["patient_reported_context"].append(line)

    return summary


def flatten_evidence_summary(summary: dict[str, Iterable[str]]) -> str:
    parts: list[str] = []
    for key in [
        "positive_or_supporting",
        "negative_or_excluding",
        "medication_or_exposure",
        "patient_reported_context",
    ]:
        items = [str(item).strip() for item in summary.get(key, []) if str(item).strip()]
        if items:
            label = key.replace("_", " ")
            parts.append(f"{label}: " + " | ".join(items))
    return "\n".join(parts)
