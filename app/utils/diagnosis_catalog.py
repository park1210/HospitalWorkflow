import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from app.config import settings
from app.utils.clinical_rule_loader import load_evidence_diagnosis_hints


DIAGNOSIS_EQUIVALENCE_MAP = {
    "hirschsprung disease": "hirschsprung disease",
    "hirschsprungs disease": "hirschsprung disease",
    "hirschsprung?? disease": "hirschsprung disease",
    "hirschsprung???disease": "hirschsprung disease",
    "benign paroxysmal positional vertigo": "benign paroxysmal positional vertigo bppv",
    "benign paroxysmal positional vertigo bppv": "benign paroxysmal positional vertigo bppv",
    "progressive multifocal encephalopathy pml": "progressive multifocal leukoencephalopathy pml",
    "progressive multifocal encephalopathy": "progressive multifocal leukoencephalopathy pml",
    "progressive multifocal leukoencephalopathy": "progressive multifocal leukoencephalopathy pml",
    "progressive multifocal leukoencephalopathy pml": "progressive multifocal leukoencephalopathy pml",
    "respiratory distress syndrome": "neonatal respiratory distress syndrome nrds",
    "neonatal respiratory distress syndrome": "neonatal respiratory distress syndrome nrds",
    "neonatal respiratory distress syndrome nrds": "neonatal respiratory distress syndrome nrds",
    "glanzmann???thrombasthenia": "glanzmann thrombasthenia",
    "glanzmann?셲 thrombasthenia": "glanzmann thrombasthenia",
    "glanzmann’s thrombasthenia": "glanzmann thrombasthenia",
    "glanzmann thrombasthenia": "glanzmann thrombasthenia",
    "legg calv챕 perthes disease lcpd": "legg calve perthes disease lcpd",
    "legg calv梨 perthes disease lcpd": "legg calve perthes disease lcpd",
    "legg calve perthes disease lcpd": "legg calve perthes disease lcpd",
    "spinal cord syrinx": "syringomyelia",
    "syrinx": "syringomyelia",
    "syrinx cavity": "syringomyelia",
    "syringomyelia": "syringomyelia",
}


def _phrase_matches_normalized_text(phrase: str, normalized_text: str) -> bool:
    candidate = normalize_diagnosis_text(phrase)
    if not candidate or not normalized_text:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(candidate) + r"(?![a-z0-9])"
    return re.search(pattern, normalized_text) is not None


def normalize_diagnosis_text(text: str) -> str:
    normalized = str(text).strip().lower()
    normalized = normalized.replace("`", "'").replace("’", "'").replace("‘", "'")
    normalized = normalized.replace("'s", "s").replace("'", "")
    normalized = re.sub(r"[\(\)\[\],.:;]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def canonicalize_diagnosis_text(text: str) -> str:
    normalized = normalize_diagnosis_text(text)
    return DIAGNOSIS_EQUIVALENCE_MAP.get(normalized, normalized)


def infer_catalog_diagnosis_from_evidence(text: str) -> Optional[str]:
    normalized = normalize_diagnosis_text(text)
    if not normalized:
        return None

    for rule in load_evidence_diagnosis_hints():
        matched_groups = 0
        for group in rule["keyword_groups"]:
            if any(_phrase_matches_normalized_text(keyword, normalized) for keyword in group):
                matched_groups += 1
        if matched_groups >= int(rule.get("min_groups", len(rule["keyword_groups"]))):
            return str(rule["diagnosis"]).strip()

    if "syrinx" in normalized and "spinal cord" in normalized:
        return "Syringomyelia"

    return None


def _extract_correct_diagnosis(obj: dict) -> str:
    ground_truth = obj.get("ground_truth", {})
    if isinstance(ground_truth, dict):
        diagnosis = str(ground_truth.get("diagnosis", "")).strip()
        if diagnosis:
            return diagnosis

    case_root = obj.get("OSCE_Examination", obj)
    if not isinstance(case_root, dict):
        return ""
    return str(case_root.get("Correct_Diagnosis", "")).strip()


@lru_cache(maxsize=1)
def load_diagnosis_catalog(path: Optional[Path] = None) -> list[str]:
    catalog_path = path or settings.RAW_DATA_PATH
    diagnoses: list[str] = []

    if not Path(catalog_path).exists():
        return []

    with open(catalog_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            diagnosis = _extract_correct_diagnosis(payload)
            if diagnosis:
                diagnoses.append(diagnosis)

    return sorted(set(diagnoses), key=lambda value: normalize_diagnosis_text(value))


@lru_cache(maxsize=1)
def load_normalized_catalog(path: Optional[Path] = None) -> dict[str, str]:
    catalog = load_diagnosis_catalog(path)
    normalized_catalog: dict[str, str] = {}
    for label in catalog:
        normalized_catalog[normalize_diagnosis_text(label)] = label
        normalized_catalog[canonicalize_diagnosis_text(label)] = label
    return normalized_catalog


@lru_cache(maxsize=1)
def load_diagnosis_prototypes(path: Optional[Path] = None) -> list[tuple[str, str]]:
    catalog_path = path or settings.RAW_DATA_PATH
    if not Path(catalog_path).exists():
        return []

    prototypes: list[tuple[str, str]] = []
    with open(catalog_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            diagnosis = _extract_correct_diagnosis(payload)
            if not diagnosis:
                continue

            case_root = payload.get("OSCE_Examination", payload)
            if not isinstance(case_root, dict):
                continue

            patient_actor = case_root.get("Patient_Actor", {})
            if not isinstance(patient_actor, dict):
                patient_actor = {}
            symptoms = patient_actor.get("Symptoms", {})
            if not isinstance(symptoms, dict):
                symptoms = {}

            prototype_text = " ".join(
                [
                    str(case_root.get("Objective_for_Doctor", "")).strip(),
                    str(patient_actor.get("History", "")).strip(),
                    str(patient_actor.get("Demographics", "")).strip(),
                    str(patient_actor.get("Review_of_Systems", "")).strip(),
                    str(symptoms.get("Primary_Symptom", "")).strip(),
                    " ".join(str(item).strip() for item in symptoms.get("Secondary_Symptoms", []) if str(item).strip()),
                    json.dumps(case_root.get("Physical_Examination_Findings", {}), ensure_ascii=False),
                    json.dumps(case_root.get("Test_Results", {}), ensure_ascii=False),
                ]
            ).strip()
            normalized_text = normalize_diagnosis_text(prototype_text)
            if normalized_text:
                prototypes.append((diagnosis, normalized_text))

    return prototypes


def _token_overlap_score(a: str, b: str) -> float:
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def _token_containment_score(query: str, label: str) -> float:
    query_tokens = set(query.split())
    label_tokens = set(label.split())
    if not query_tokens or not label_tokens:
        return 0.0
    return len(query_tokens & label_tokens) / len(label_tokens)


def _prototype_similarity_score(query: str, prototype_text: str) -> float:
    query_tokens = _meaningful_tokens(query)
    prototype_tokens = _meaningful_tokens(prototype_text)
    if not query_tokens or not prototype_tokens:
        return 0.0

    overlap_count = len(query_tokens & prototype_tokens)
    if overlap_count < 3:
        return 0.0

    overlap_score = overlap_count / len(query_tokens | prototype_tokens)
    containment_score = overlap_count / len(query_tokens)
    return max(overlap_score * 2.4, containment_score * 1.15)


def match_known_diagnosis(text: str) -> Optional[str]:
    evidence_hint = infer_catalog_diagnosis_from_evidence(text)
    candidate = canonicalize_diagnosis_text(evidence_hint or text)
    if not candidate or candidate == "unknown":
        return None

    normalized_catalog = load_normalized_catalog()
    if candidate in normalized_catalog:
        return normalized_catalog[candidate]

    best_label = None
    best_score = 0.0

    for normalized_label, original_label in normalized_catalog.items():
        sequence_score = SequenceMatcher(None, candidate, normalized_label).ratio()
        overlap_score = _token_overlap_score(candidate, normalized_label)
        score = max(sequence_score, overlap_score)

        if normalized_label in candidate or candidate in normalized_label:
            score = max(score, 0.92)

        if score > best_score:
            best_score = score
            best_label = original_label

    if best_score >= 0.78:
        return best_label

    return None


def _meaningful_tokens(text: str) -> set[str]:
    tokens = {
        token
        for token in normalize_diagnosis_text(text).split()
        if len(token) >= 4 and token not in {"possible", "acute", "chronic", "disease", "syndrome", "right", "left"}
    }
    return tokens


def has_direct_diagnosis_support(text: str, diagnosis: str) -> bool:
    raw_text = str(text).strip()
    candidate_diagnosis = str(diagnosis).strip()
    if not raw_text or not candidate_diagnosis:
        return False

    normalized_text = canonicalize_diagnosis_text(raw_text)
    normalized_diagnosis = canonicalize_diagnosis_text(candidate_diagnosis)

    if normalized_diagnosis and normalized_diagnosis in normalized_text:
        return True

    evidence_hint = infer_catalog_diagnosis_from_evidence(raw_text)
    if evidence_hint and canonicalize_diagnosis_text(evidence_hint) == normalized_diagnosis:
        return True

    overlap = _token_overlap_score(raw_text, candidate_diagnosis)
    containment = _token_containment_score(raw_text, candidate_diagnosis)
    meaningful_overlap = len(_meaningful_tokens(raw_text) & _meaningful_tokens(candidate_diagnosis))
    return meaningful_overlap >= 2 and (overlap >= 0.22 or containment >= 0.45)


def search_known_diagnoses(
    text: str,
    limit: int = 8,
    min_score: float = 0.24,
    allowed_departments: Optional[Iterable[str]] = None,
) -> list[str]:
    evidence_hint = infer_catalog_diagnosis_from_evidence(text)
    query = canonicalize_diagnosis_text(evidence_hint or text)
    if not query:
        return []

    catalog = load_diagnosis_catalog()
    if not catalog:
        return []

    allowed_department_set = {str(item).strip() for item in (allowed_departments or []) if str(item).strip()}
    curated_map = None
    if allowed_department_set:
        from app.utils.department_catalog import get_curated_department_assignment

        curated_map = get_curated_department_assignment

    query_tokens = _meaningful_tokens(query)

    scored: list[tuple[float, str]] = []
    seen: set[str] = set()

    if evidence_hint:
        scored.append((0.99, evidence_hint))
        seen.add(canonicalize_diagnosis_text(evidence_hint))

    for label in catalog:
        if curated_map is not None:
            assignment = curated_map(label)
            if not assignment or str(assignment.get("department", "")).strip() not in allowed_department_set:
                continue

        normalized_label = canonicalize_diagnosis_text(label)
        if not normalized_label or normalized_label in seen:
            continue
        seen.add(normalized_label)

        overlap_score = _token_overlap_score(query, normalized_label)
        containment_score = _token_containment_score(query, normalized_label)
        sequence_score = SequenceMatcher(None, query, normalized_label).ratio()
        score = max(overlap_score, sequence_score * 0.45, containment_score * 0.9)

        label_tokens = _meaningful_tokens(normalized_label)
        meaningful_overlap = len(query_tokens & label_tokens)
        if query_tokens and label_tokens and meaningful_overlap == 0:
            score *= 0.35
        elif len(query_tokens) >= 6 and meaningful_overlap < 2:
            score *= 0.55

        if normalized_label in query or query in normalized_label:
            score = max(score, 0.88)

        scored.append((score, label))

    ranked = sorted(scored, key=lambda item: (-item[0], normalize_diagnosis_text(item[1])))
    standard_results = [label for score, label in ranked if score >= min_score][:limit]
    if standard_results:
        return standard_results

    if allowed_department_set and len(query_tokens) >= 4:
        prototype_scores: dict[str, float] = {}
        for diagnosis, prototype_text in load_diagnosis_prototypes():
            if curated_map is not None:
                assignment = curated_map(diagnosis)
                if not assignment or str(assignment.get("department", "")).strip() not in allowed_department_set:
                    continue

            score = _prototype_similarity_score(query, prototype_text)
            if score > prototype_scores.get(diagnosis, 0.0):
                prototype_scores[diagnosis] = score

        prototype_ranked = sorted(
            prototype_scores.items(),
            key=lambda item: (-item[1], normalize_diagnosis_text(item[0])),
        )
        return [diagnosis for diagnosis, score in prototype_ranked if score >= max(min_score, 0.42)][:limit]

    return []


def extract_known_diagnoses(text: str, limit: int = 3) -> list[str]:
    raw_text = str(text).strip()
    if not raw_text:
        return []

    normalized_text = canonicalize_diagnosis_text(raw_text)
    normalized_catalog = load_normalized_catalog()
    found: list[str] = []
    seen: set[str] = set()

    matched_full_text = match_known_diagnosis(raw_text)
    if matched_full_text and matched_full_text not in seen:
        found.append(matched_full_text)
        seen.add(matched_full_text)
        if len(found) >= limit:
            return found

    for normalized_label, original_label in normalized_catalog.items():
        if not normalized_label or len(normalized_label) < 4:
            continue
        if normalized_label in normalized_text and original_label not in seen:
            found.append(original_label)
            seen.add(original_label)
            if len(found) >= limit:
                return found

    candidate_chunks = re.split(r"[\n\r,;/\-]+", raw_text)
    for chunk in candidate_chunks:
        if not _meaningful_tokens(chunk):
            continue
        matched = match_known_diagnosis(chunk)
        if matched and matched not in seen:
            if _token_overlap_score(chunk, matched) <= 0 and _token_containment_score(chunk, matched) < 0.2:
                continue
            found.append(matched)
            seen.add(matched)
            if len(found) >= limit:
                return found

    return found
