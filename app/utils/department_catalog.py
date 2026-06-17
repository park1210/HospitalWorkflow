from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from app.config import settings
from app.utils.diagnosis_catalog import (
    canonicalize_diagnosis_text,
    extract_known_diagnoses,
    has_direct_diagnosis_support,
    infer_catalog_diagnosis_from_evidence,
    match_known_diagnosis,
    search_known_diagnoses,
)


SUPPORTED_DEPARTMENTS = [
    "general_medicine",
    "internal_medicine",
    "neurology",
    "surgery",
    "radiology",
    "cardiology",
    "gastroenterology",
    "pulmonology",
    "endocrinology",
    "nephrology",
    "hematology",
    "infectious_disease",
    "dermatology",
    "ophthalmology",
    "otolaryngology",
    "obstetrics_gynecology",
    "psychiatry",
    "urology",
    "orthopedics",
    "rheumatology",
    "pediatrics",
]


DEPARTMENT_ALIASES = {
    "er": "general_medicine",
    "emergency": "general_medicine",
    "emergency medicine": "general_medicine",
    "internal medicine": "general_medicine",
    "internal_medicine": "internal_medicine",
    "general medicine": "general_medicine",
    "medicine": "general_medicine",
    "neuro": "neurology",
    "neurological": "neurology",
    "radio": "radiology",
    "imaging": "radiology",
    "surgical": "surgery",
    "general surgery": "surgery",
    "cardiac": "cardiology",
    "gi": "gastroenterology",
    "gastro": "gastroenterology",
    "pulmonary": "pulmonology",
    "renal": "nephrology",
    "heme": "hematology",
    "hematology oncology": "hematology",
    "heme-onc": "hematology",
    "id": "infectious_disease",
    "infectious disease": "infectious_disease",
    "ent": "otolaryngology",
    "obgyn": "obstetrics_gynecology",
    "ob/gyn": "obstetrics_gynecology",
    "gyn": "obstetrics_gynecology",
    "ophtho": "ophthalmology",
    "ortho": "orthopedics",
    "psych": "psychiatry",
    "peds": "pediatrics",
}


DEPARTMENT_KEYWORDS = {
    "neurology": [
        "diplopia",
        "double vision",
        "ptosis",
        "ataxia",
        "gait ataxia",
        "limb ataxia",
        "encephalopathy",
        "demyelinating",
        "multifocal lesion",
        "brain lesion",
        "mri_brain",
        "brain mri",
        "pml",
        "weakness after activity",
        "electromyography",
        "emg",
        "cranial nerve",
        "myasthen",
        "seizure",
        "stroke",
        "neurolog",
        "radiculopathy",
        "radicular",
        "nerve root",
        "disc herniation",
        "lumbar spine",
        "spinal cord",
    ],
    "surgery": [
        "appendic",
        "right lower quadrant",
        "periton",
        "torsion",
        "bowel obstruction",
        "intestinal obstruction",
        "hirschsprung",
        "volvulus",
        "perforat",
        "acute abdomen",
        "surgical abdomen",
        "transition zone",
        "distal colon",
        "absence of gas in the rectum",
        "dilated bowel",
        "rectum",
    ],
    "radiology": [
        "ct",
        "mri",
        "x-ray",
        "xray",
        "ultrasound",
        "imaging",
        "scan",
    ],
    "cardiology": [
        "chest pain",
        "troponin",
        "stemi",
        "nstemi",
        "arrhythmia",
        "tachycardia",
        "bradycardia",
        "ecg",
        "ekg",
    ],
    "gastroenterology": [
        "hematemesis",
        "melena",
        "hematochezia",
        "hepatitis",
        "cirrhosis",
        "endoscopy",
        "colitis",
        "pancreatitis",
        "gi bleed",
        "diarrhea",
        "bowel",
        "mucus",
        "cramping",
        "abdominal discomfort",
    ],
    "pulmonology": [
        "shortness of breath",
        "hemoptysis",
        "hypoxia",
        "asthma",
        "copd",
        "pulmonary",
        "pneumonia",
        "pleural",
    ],
    "endocrinology": [
        "thyroid",
        "diabetes",
        "hyperglycemia",
        "hypoglycemia",
        "adrenal",
        "pituitary",
        "hormone",
    ],
    "nephrology": [
        "creatinine",
        "proteinuria",
        "hematuria",
        "nephrotic",
        "nephritic",
        "urinalysis",
        "urine sediment",
        "albuminuria",
        "interstitial nephritis",
        "eosinophil",
        "eosinophilic",
        "hansel",
        "dialysis",
    ],
    "hematology": [
        "anemia",
        "thrombocytopenia",
        "leukemia",
        "lymphoma",
        "coagulopathy",
        "hemolysis",
        "platelet",
        "bleeding disorder",
        "epistaxis",
        "petechiae",
        "gum bleeding",
        "gpiib",
        "giiia",
        "gpiib/iiia",
    ],
    "infectious_disease": [
        "fever",
        "bacteremia",
        "sepsis",
        "antibiotic",
        "infection",
        "infectious",
        "blood culture",
        "positive culture",
        "bacterial culture",
        "viral load",
        "tuberculosis",
        "listeria",
        "abscess",
        "cellulitis",
    ],
    "dermatology": [
        "rash",
        "skin lesion",
        "dermat",
        "psoriasis",
        "eczema",
        "itching",
        "itch",
        "pruritic",
        "red bumps",
        "bite",
    ],
    "ophthalmology": [
        "vision loss",
        "ocular",
        "eye pain",
        "retina",
        "cornea",
        "ophthalm",
        "decreased vision",
        "black spots",
        "floaters",
        "retinitis",
    ],
    "otolaryngology": [
        "hearing loss",
        "vertigo",
        "sinus",
        "epistaxis",
        "larynx",
        "tonsil",
    ],
    "obstetrics_gynecology": [
        "pregnan",
        "vaginal bleeding",
        "pelvic pain",
        "uterus",
        "ovar",
        "ectopic",
    ],
    "psychiatry": [
        "suicid",
        "psychosis",
        "hallucination",
        "mania",
        "depression",
        "anxiety",
        "nightmare",
        "sleep",
        "frightened",
        "parasomnia",
    ],
    "urology": [
        "testicular",
        "urinary retention",
        "kidney stone",
        "ureter",
        "prostate",
    ],
    "orthopedics": [
        "fracture",
        "joint",
        "bone",
        "dislocation",
        "ligament",
        "tendon",
        "lower back pain",
        "lumbar",
        "spine",
        "musculoskeletal",
    ],
    "rheumatology": [
        "arthritis",
        "autoimmune",
        "lupus",
        "vasculitis",
        "joint swelling",
    ],
    "pediatrics": [
        "child",
        "infant",
        "newborn",
        "pediatric",
    ],
}


MODALITY_DEPARTMENTS = {"radiology"}
GENERAL_FALLBACK_DEPARTMENTS = {"general_medicine", "internal_medicine"}
GENERIC_DEPARTMENT_SIGNAL_PREFIXES = (
    "possible ",
    "undifferentiated",
    "acute abdominal",
    "possible acute",
    "possible central",
    "possible multisystem",
    "possible systemic",
    "possible infectious",
    "possible pulmonary",
    "possible cardiac",
    "possible urinary",
    "possible gynecologic",
    "possible bowel",
    "possible structural",
    "possible cerebellar",
    "possible neuromuscular junction",
    "possible neurologic process",
    "possible respiratory",
    "possible cardiovascular",
)

DEPARTMENT_EVIDENCE_SOURCE_WEIGHTS = {
    "supported_diagnosis": 6.0,
    "working_diagnosis": 4.0,
    "objective_findings": 5.0,
    "consult_opinions": 3.5,
    "working_problem_list": 1.5,
    "known_information": 1.0,
    "patient_summary": 1.0,
    "chief_complaint": 1.0,
    "history": 0.75,
    "assessment_signals": 0.5,
}


DEPARTMENT_FAMILY_MAP = {
    "cardiology": "cardiorespiratory",
    "pulmonology": "cardiorespiratory",
    "gastroenterology": "abdominopelvic",
    "surgery": "abdominopelvic",
    "obstetrics_gynecology": "abdominopelvic",
    "neurology": "neurologic",
    "ophthalmology": "neurologic",
    "otolaryngology": "neurologic",
    "orthopedics": "neuromusculoskeletal",
    "rheumatology": "neuromusculoskeletal",
    "nephrology": "genitourinary",
    "urology": "genitourinary",
    "infectious_disease": "systemic_inflammatory",
    "internal_medicine": "systemic_inflammatory",
    "general_medicine": "systemic_inflammatory",
    "hematology": "hematologic_oncologic",
    "pediatrics": "pediatric_congenital",
}


FAMILY_DEPARTMENT_PRIORS = {
    "cardiorespiratory": {"cardiology": 2.4, "pulmonology": 2.4},
    "abdominopelvic": {"gastroenterology": 2.0, "surgery": 2.0, "obstetrics_gynecology": 2.0},
    "neurologic": {"neurology": 2.5, "ophthalmology": 1.8, "otolaryngology": 1.8},
    "neuromusculoskeletal": {"orthopedics": 2.5, "neurology": 1.4, "rheumatology": 1.2},
    "genitourinary": {"nephrology": 2.4, "urology": 2.0},
    "systemic_inflammatory": {"infectious_disease": 1.8, "internal_medicine": 1.2},
    "hematologic_oncologic": {"hematology": 3.0},
    "pediatric_congenital": {"pediatrics": 3.0},
}


STRUCTURED_FAMILY_KEYWORDS = {
    "hematologic_oncologic": [
        "lymphadenopathy",
        "lymph node",
        "cd20",
        "flow cytometry",
        "monoclonal b lymphocyte",
        "leukemia",
        "lymphoma",
        "high proliferative index",
        "peripheral blood smear",
        "immature cells",
        "needle shaped cytoplasmic inclusions",
        "pink elongated",
        "cytoplasmic inclusions",
    ],
    "pediatric_congenital": [
        "newborn",
        "congenital",
        "torch",
        "rubella",
        "patent ductus arteriosus",
        "sensorineural hearing loss",
    ],
    "genitourinary": [
        "proteinuria",
        "fatty_casts",
        "fatty casts",
        "albuminuria",
        "hematuria",
        "nephrotic",
        "urinalysis",
    ],
    "cardiorespiratory": [
        "lung mass",
        "upper lobe mass",
        "apex of the right lung",
        "apical lung",
        "right upper lobe density",
        "diffuse infiltrates",
        "pneumonia",
    ],
    "abdominopelvic": [
        "diarrhea",
        "mucus discharge",
        "incomplete evacuation",
        "abdominal discomfort",
        "cramping",
        "pelvic",
        "uterine",
    ],
    "neuromusculoskeletal": [
        "hip",
        "joint",
        "fracture",
        "dislocation",
        "tendon",
        "ligament",
    ],
}


EXACT_TOKEN_DEPARTMENT_KEYWORDS = {
    "ct",
    "mri",
    "ecg",
    "ekg",
    "emg",
    "pml",
}


def _keyword_matches_text(keyword: str, text: str) -> bool:
    normalized_keyword = str(keyword).strip().lower()
    normalized_text = str(text).strip().lower()
    if not normalized_keyword or not normalized_text:
        return False

    if normalized_keyword in EXACT_TOKEN_DEPARTMENT_KEYWORDS:
        pattern = r"(?<![a-z0-9])" + re.escape(normalized_keyword) + r"(?![a-z0-9])"
        return re.search(pattern, normalized_text) is not None

    return normalized_keyword in normalized_text


def canonicalize_department_text(value: str) -> str:
    return " ".join(str(value).strip().lower().replace("-", "_").split())


def normalize_department(value: str, default: str = "general_medicine") -> str:
    text = canonicalize_department_text(value)
    if not text:
        return default
    if text in SUPPORTED_DEPARTMENTS:
        return text
    if text in DEPARTMENT_ALIASES:
        return DEPARTMENT_ALIASES[text]

    compact = text.replace("_", " ")
    if compact in DEPARTMENT_ALIASES:
        return DEPARTMENT_ALIASES[compact]

    for alias, department in DEPARTMENT_ALIASES.items():
        if alias in text or alias in compact:
            return department
    return default


def infer_department_scores(
    texts: Iterable[str],
    prefer_clinical_department: bool = True,
) -> dict[str, int]:
    combined = " ".join(str(item).strip().lower() for item in texts if str(item).strip())
    if not combined:
        return {}

    scores: dict[str, int] = {}
    for department, keywords in DEPARTMENT_KEYWORDS.items():
        score = sum(1 for keyword in keywords if _keyword_matches_text(keyword, combined))
        if score:
            scores[department] = score

    if prefer_clinical_department:
        clinical_scores = {
            department: score
            for department, score in scores.items()
            if department not in MODALITY_DEPARTMENTS
        }
        if clinical_scores:
            return clinical_scores
    return scores


def infer_department_from_texts(
    texts: Iterable[str],
    default: str = "general_medicine",
    prefer_clinical_department: bool = True,
) -> str:
    scores = infer_department_scores(texts, prefer_clinical_department=prefer_clinical_department)
    if not scores:
        return default
    return max(scores.items(), key=lambda item: item[1])[0]


def combine_department_scores(*score_maps: dict[str, float]) -> dict[str, float]:
    combined: dict[str, float] = {}
    for score_map in score_maps:
        for department, value in score_map.items():
            if department not in SUPPORTED_DEPARTMENTS:
                continue
            combined[department] = combined.get(department, 0.0) + float(value)
    return combined


def build_structured_evidence_profile(
    working_diagnosis: str,
    chief_complaint: str,
    history: str,
    objective_findings: Iterable[str],
    known_information: Iterable[str],
    assessment_family_scores: Optional[dict[str, float]] = None,
) -> dict[str, object]:
    objective_items = [str(item).strip() for item in objective_findings if str(item).strip()]
    known_items = [str(item).strip() for item in known_information if str(item).strip()]
    objective_text = " ".join(objective_items).lower()
    full_text = " ".join(
        [
            str(working_diagnosis).strip(),
            str(chief_complaint).strip(),
            str(history).strip(),
            *objective_items,
            *known_items[-4:],
        ]
    ).lower()

    exact_hits: list[str] = []
    exact_department_scores: dict[str, float] = {}
    for diagnosis in extract_known_diagnoses(objective_text, limit=3):
        if diagnosis not in exact_hits and has_direct_diagnosis_support(objective_text, diagnosis):
            exact_hits.append(diagnosis)
    evidence_hint = infer_catalog_diagnosis_from_evidence(objective_text)
    if evidence_hint and evidence_hint not in exact_hits:
        exact_hits.append(evidence_hint)
    if exact_hits:
        for rank, diagnosis in enumerate(exact_hits, start=1):
            assignment = get_curated_department_assignment(diagnosis)
            if not assignment:
                continue
            department = normalize_department(str(assignment.get("department", "")).strip(), default="")
            if not department:
                continue
            exact_department_scores[department] = max(
                exact_department_scores.get(department, 0.0),
                10.0 - float(rank - 1),
            )

    family_scores: dict[str, float] = {
        str(key).strip(): float(value)
        for key, value in (assessment_family_scores or {}).items()
        if str(key).strip()
    }
    for family, keywords in STRUCTURED_FAMILY_KEYWORDS.items():
        score = sum(1 for keyword in keywords if _keyword_matches_text(keyword, full_text))
        if score:
            family_scores[family] = family_scores.get(family, 0.0) + float(score)

    for diagnosis in exact_hits:
        assignment = get_curated_department_assignment(diagnosis)
        if not assignment:
            continue
        department = normalize_department(str(assignment.get("department", "")).strip(), default="")
        family = DEPARTMENT_FAMILY_MAP.get(department, "")
        if family:
            family_scores[family] = family_scores.get(family, 0.0) + 2.5

    family_department_scores: dict[str, float] = {}
    for family, score in family_scores.items():
        priors = FAMILY_DEPARTMENT_PRIORS.get(str(family).strip(), {})
        for department, weight in priors.items():
            family_department_scores[department] = family_department_scores.get(department, 0.0) + (float(score) * float(weight))

    dominant_family = ""
    if family_scores:
        dominant_family = max(family_scores.items(), key=lambda item: item[1])[0]

    return {
        "exact_diagnosis_hits": exact_hits,
        "exact_department_scores": exact_department_scores,
        "family_scores": family_scores,
        "family_department_scores": family_department_scores,
        "dominant_family": dominant_family,
    }


def infer_department_scores_by_source(
    source_texts: dict[str, Iterable[str] | str],
    prefer_clinical_department: bool = True,
) -> dict[str, float]:
    weighted_scores: dict[str, float] = {}

    for source_name, raw_value in source_texts.items():
        weight = float(DEPARTMENT_EVIDENCE_SOURCE_WEIGHTS.get(source_name, 1.0))
        if weight <= 0:
            continue

        if isinstance(raw_value, str):
            items = [raw_value]
        else:
            items = [str(item).strip() for item in raw_value if str(item).strip()]

        for item in items:
            item_scores = infer_department_scores([item], prefer_clinical_department=False)
            item_weight = weight
            normalized_item = str(item).strip().lower()
            if source_name == "working_diagnosis" and normalized_item.startswith(GENERIC_DEPARTMENT_SIGNAL_PREFIXES):
                item_weight *= 0.4
            elif source_name == "working_problem_list" and normalized_item.startswith(GENERIC_DEPARTMENT_SIGNAL_PREFIXES):
                item_weight *= 0.5
            for department, score in item_scores.items():
                weighted_scores[department] = weighted_scores.get(department, 0.0) + (float(score) * item_weight)

    if prefer_clinical_department:
        clinical_scores = {
            department: score
            for department, score in weighted_scores.items()
            if department not in MODALITY_DEPARTMENTS
        }
        if clinical_scores:
            return clinical_scores
    return weighted_scores


def rank_department_scores(scores: dict[str, float]) -> list[tuple[str, float]]:
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def build_department_candidates(scores: dict[str, float], limit: int = 2) -> list[str]:
    candidates: list[str] = []
    for department, score in rank_department_scores(scores):
        normalized = normalize_department(department, default="")
        if not normalized or score <= 0:
            continue
        if normalized not in candidates:
            candidates.append(normalized)
        if len(candidates) >= limit:
            break
    return candidates


def prefer_specific_department(
    scores: dict[str, float],
    chosen_department: str,
    min_specific_score: float = 1.5,
    internal_margin: float = 2.5,
) -> str:
    normalized_choice = normalize_department(chosen_department, default=chosen_department)
    if normalized_choice not in GENERAL_FALLBACK_DEPARTMENTS:
        return normalized_choice

    ranked = rank_department_scores(scores)
    choice_score = 0.0
    for department, score in ranked:
        if normalize_department(department, default="") == normalized_choice:
            choice_score = float(score)
            break

    for department, score in ranked:
        normalized = normalize_department(department, default="")
        if not normalized or normalized in GENERAL_FALLBACK_DEPARTMENTS:
            continue
        if float(score) < min_specific_score:
            continue
        if normalized_choice == "general_medicine":
            return normalized
        if (choice_score - float(score)) <= internal_margin:
            return normalized
        break

    return normalized_choice


def infer_department_scores_from_catalog(
    text: str,
    limit: int = 6,
    min_score: float = 0.3,
) -> dict[str, float]:
    query = str(text).strip()
    if not query:
        return {}

    scores: dict[str, float] = {}
    for rank, diagnosis in enumerate(search_known_diagnoses(query, limit=limit, min_score=min_score), start=1):
        assignment = get_curated_department_assignment(diagnosis)
        if not assignment:
            continue
        department = normalize_department(str(assignment.get("department", "")).strip(), default="")
        if not department:
            continue
        weight = max(0.0, float(limit - rank + 1))
        scores[department] = scores.get(department, 0.0) + weight
    return scores


def choose_department_from_scores(
    scores: dict[str, float],
    default: str = "general_medicine",
    fallback_if_ambiguous: str = "internal_medicine",
    ambiguity_margin: float = 1.5,
    low_confidence_threshold: float = 2.0,
) -> str:
    ranked = rank_department_scores(scores)
    if not ranked:
        return default

    top_department, top_score = ranked[0]
    if top_score < low_confidence_threshold:
        return default

    if len(ranked) > 1:
        second_score = ranked[1][1]
        if (top_score - second_score) < ambiguity_margin:
            return fallback_if_ambiguous

    return top_department


def infer_department_from_case(correct_diagnosis: str, sections: Iterable[str]) -> str:
    curated = get_curated_department_assignment(correct_diagnosis)
    if curated:
        return curated["department"]

    diagnosis_scores = infer_department_scores_by_source(
        {
            "supported_diagnosis": correct_diagnosis,
            "objective_findings": list(sections),
        },
        prefer_clinical_department=True,
    )
    return choose_department_from_scores(
        diagnosis_scores,
        default="general_medicine",
        fallback_if_ambiguous="internal_medicine",
        ambiguity_margin=1.0,
        low_confidence_threshold=1.0,
    )


@lru_cache(maxsize=1)
def load_curated_department_map(path: Optional[Path] = None) -> dict[str, dict[str, str]]:
    map_path = path or (settings.PROJECT_ROOT / "app" / "data" / "diagnosis_department_map.json")
    if not Path(map_path).exists():
        return {}

    payload = json.loads(Path(map_path).read_text(encoding="utf-8"))
    normalized_map: dict[str, dict[str, str]] = {}
    for diagnosis_label, assignment in payload.items():
        diagnosis_key = canonicalize_diagnosis_text(diagnosis_label)
        department = normalize_department(str(assignment.get("department", "")).strip(), default="")
        rationale = str(assignment.get("rationale", "")).strip()
        if diagnosis_key:
            normalized_map[diagnosis_key] = {
                "diagnosis": str(diagnosis_label).strip(),
                "department": department,
                "rationale": rationale,
            }
    return normalized_map


def get_curated_department_assignment(diagnosis: str) -> Optional[dict[str, str]]:
    if not str(diagnosis).strip():
        return None

    normalized_map = load_curated_department_map()
    matched_diagnosis = match_known_diagnosis(diagnosis) or diagnosis
    candidate_keys = [
        canonicalize_diagnosis_text(diagnosis),
        canonicalize_diagnosis_text(matched_diagnosis),
    ]
    for key in candidate_keys:
        if key in normalized_map:
            return normalized_map[key]
    return None
