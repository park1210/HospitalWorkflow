from typing import Optional

from app.utils.diagnosis_catalog import canonicalize_diagnosis_text, match_known_diagnosis
from app.utils.department_catalog import normalize_department


def evaluate_diagnosis(predicted: str, gold: str) -> bool:
    predicted_match = match_known_diagnosis(predicted)
    gold_match = match_known_diagnosis(gold)

    if predicted_match and gold_match:
        return canonicalize_diagnosis_text(predicted_match) == canonicalize_diagnosis_text(gold_match)

    predicted_normalized = canonicalize_diagnosis_text(predicted)
    gold_normalized = canonicalize_diagnosis_text(gold)
    return predicted_normalized == gold_normalized


def evaluate_department(predicted: str, gold: str) -> Optional[bool]:
    if not str(gold).strip():
        return None
    return normalize_department(predicted) == normalize_department(gold)
