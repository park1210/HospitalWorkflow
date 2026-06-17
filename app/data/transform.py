import re
from typing import Any, Optional

from app.utils.department_catalog import get_curated_department_assignment, infer_department_from_case

NON_INFORMATIVE_PHRASES = [
    "information not provided",
    "not provided",
    "no formal test results",
    "not clearly provided",
    "details are not provided",
    "no external skin changes described",
]


def get_first_existing_value(d: dict[str, Any], keys: list[str], default: Any = "") -> Any:
    for key in keys:
        if key in d and d[key] not in [None, ""]:
            return d[key]
    return default


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = normalize_text(value)
    return [text] if text else []


def split_sentences(text: str) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def is_non_informative_text(value: Any) -> bool:
    text = normalize_text(value).lower()
    if not text:
        return True
    return any(phrase in text for phrase in NON_INFORMATIVE_PHRASES)


def has_meaningful_content(value: Any) -> bool:
    if isinstance(value, dict):
        return any(has_meaningful_content(item) for item in value.values())
    if isinstance(value, list):
        return any(has_meaningful_content(item) for item in value)
    return not is_non_informative_text(value)


def filter_non_informative_sections(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    filtered: dict[str, Any] = {}
    for key, section_value in value.items():
        if has_meaningful_content(section_value):
            filtered[str(key).strip()] = section_value
    return filtered


def extract_available_sections(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [str(key).strip() for key in value.keys() if str(key).strip()]


def parse_numeric_token(value: Any) -> Optional[float]:
    text = normalize_text(value)
    if not text:
        return None
    match = re.search(r"-?\d+(\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def classify_temporal_risk(
    chief_complaint: str,
    history: str,
    triage_clues: list[str],
    initial_vitals: dict[str, Any],
) -> str:
    combined = " ".join(
        [
            normalize_text(chief_complaint).lower(),
            normalize_text(history).lower(),
            " ".join(str(item).strip().lower() for item in triage_clues if str(item).strip()),
        ]
    )
    systolic_bp = parse_numeric_token(initial_vitals.get("systolic_bp"))
    heart_rate = parse_numeric_token(initial_vitals.get("heart_rate"))
    respiratory_rate = parse_numeric_token(initial_vitals.get("respiratory_rate"))
    oxygen_saturation = parse_numeric_token(initial_vitals.get("oxygen_saturation"))
    temperature = parse_numeric_token(initial_vitals.get("temperature"))

    if (
        (systolic_bp is not None and systolic_bp < 90)
        or (oxygen_saturation is not None and oxygen_saturation < 92)
        or (heart_rate is not None and heart_rate >= 130)
        or (respiratory_rate is not None and respiratory_rate >= 30)
        or any(
            keyword in combined
            for keyword in [
                "shortness of breath",
                "dyspnea",
                "chest pain",
                "syncope",
                "seizure",
                "unresponsive",
                "weakness",
                "confusion",
                "hemoptysis",
                "bleeding",
            ]
        )
    ):
        return "high"

    if (
        (temperature is not None and temperature >= 38.5)
        or (heart_rate is not None and heart_rate >= 110)
        or any(
            keyword in combined
            for keyword in [
                "abdominal pain",
                "vomiting",
                "fever",
                "headache",
                "diplopia",
                "ataxia",
                "vertigo",
                "difficulty walking",
                "pelvic pain",
                "rash",
                "flank pain",
            ]
        )
    ):
        return "moderate"

    return "low"


def build_temporal_profile(
    idx: int,
    chief_complaint: str,
    history: str,
    triage_clues: list[str],
    initial_vitals: dict[str, Any],
) -> dict[str, Any]:
    risk = classify_temporal_risk(chief_complaint, history, triage_clues, initial_vitals)
    if risk == "high":
        observation_minutes = 10
        triggers = [
            {
                "if_unaddressed_for_minutes": 15,
                "effect": {"heart_rate_delta": 8, "respiratory_rate_delta": 2},
                "rationale": "High-risk ER presentations may worsen quickly if evaluation is delayed.",
            },
            {
                "if_unaddressed_for_minutes": 30,
                "effect": {"heart_rate_delta": 12, "systolic_bp_delta": -8},
                "rationale": "Continued delay can produce hemodynamic strain in high-risk presentations.",
            },
        ]
    elif risk == "moderate":
        observation_minutes = 15
        triggers = [
            {
                "if_unaddressed_for_minutes": 20,
                "effect": {"heart_rate_delta": 5, "pain_score_delta": 1},
                "rationale": "Moderate-risk ER presentations can become more symptomatic over time.",
            },
            {
                "if_unaddressed_for_minutes": 40,
                "effect": {"heart_rate_delta": 8, "temperature_delta": 0.3},
                "rationale": "Longer delays increase uncertainty and physiologic stress in moderate-risk cases.",
            },
        ]
    else:
        observation_minutes = 20
        triggers = [
            {
                "if_unaddressed_for_minutes": 45,
                "effect": {"pain_score_delta": 1},
                "rationale": "Lower-risk ER presentations may still worsen slowly if evaluation is delayed.",
            }
        ]

    return {
        "time_unit_minutes": 5,
        "arrival_time_min": idx * 5,
        "initial_acuity": 2 if risk == "high" else 3 if risk == "moderate" else 4,
        "observation_reassessment_minutes": observation_minutes,
        "deterioration_model": {
            "type": "rule_based",
            "baseline_risk": risk,
            "triggers": triggers,
        },
        "natural_history_events": [],
        "reassessment_suggestions": [
            {
                "minute": observation_minutes,
                "reason": "Repeat focused ER assessment if the case remains unresolved after short observation.",
            }
        ],
    }


def classify_test_turnaround(section_name: str) -> int:
    normalized = normalize_text(section_name).lower().replace(" ", "_")
    if any(token in normalized for token in ["mri", "ct", "scan"]):
        return 30
    if any(token in normalized for token in ["ultrasound", "xray", "x-ray", "radiograph", "imaging"]):
        return 20
    if any(token in normalized for token in ["urine", "urinalysis"]):
        return 10
    if any(token in normalized for token in ["blood", "cbc", "bmp", "cmp", "panel", "serology", "culture"]):
        return 12
    return 15


def build_resource_profile(available_test_sections: list[str], risk: str) -> dict[str, Any]:
    test_turnaround = {
        section: classify_test_turnaround(section)
        for section in available_test_sections
        if normalize_text(section)
    }
    consult_turnaround = {
        "neurology": 20 if risk in {"high", "moderate"} else 25,
        "internal_medicine": 20,
        "general_medicine": 15,
        "surgery": 20,
        "obstetrics_gynecology": 20,
    }
    return {
        "capacity": {
            "doctor": 1,
            "imaging": 1,
            "lab": 1,
            "consult": 1,
        },
        "test_turnaround": test_turnaround,
        "consult_turnaround": consult_turnaround,
    }

def build_patient_visible_info(
    demographics: str,
    history: str,
    past_history: str,
    current_medications: str,
    social_history: str,
    ros: str,
    primary_symptom: str,
    secondary_symptoms: list[str],
    associated_symptoms: list[str],
) -> dict[str, Any]:
    chief_complaint = primary_symptom
    if not chief_complaint and secondary_symptoms:
        chief_complaint = secondary_symptoms[0]
    if not chief_complaint and associated_symptoms:
        chief_complaint = associated_symptoms[0]
    if not chief_complaint and history:
        chief_complaint = history[:200]

    symptom_summary = [primary_symptom, *secondary_symptoms, *associated_symptoms]
    symptom_summary = [item for item in symptom_summary if item]

    return {
        "demographics": demographics,
        "chief_complaint": chief_complaint,
        "history": history,
        "symptoms": {
            "primary": primary_symptom,
            "secondary": secondary_symptoms,
            "associated": associated_symptoms,
            "summary": symptom_summary,
        },
        "past_medical_history": past_history,
        "current_medications": current_medications,
        "social_history": social_history,
        "review_of_systems": ros,
    }


def build_doctor_visible_info(patient_visible_info: dict[str, Any]) -> dict[str, Any]:
    summary_parts = [
        patient_visible_info.get("demographics", ""),
        patient_visible_info.get("chief_complaint", ""),
    ]
    initial_summary = " | ".join(part for part in summary_parts if str(part).strip())

    return {
        "demographics": patient_visible_info.get("demographics", ""),
        "chief_complaint": patient_visible_info.get("chief_complaint", ""),
        "initial_summary": initial_summary,
    }


def normalize_vitals(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, Any] = {}
    key_map = {
        "blood_pressure": "blood_pressure",
        "blood pressure": "blood_pressure",
        "bp": "blood_pressure",
        "systolic_bp": "systolic_bp",
        "sbp": "systolic_bp",
        "heart_rate": "heart_rate",
        "pulse": "heart_rate",
        "hr": "heart_rate",
        "respiratory_rate": "respiratory_rate",
        "rr": "respiratory_rate",
        "temperature": "temperature",
        "temp": "temperature",
        "oxygen_saturation": "oxygen_saturation",
        "spo2": "oxygen_saturation",
        "o2_sat": "oxygen_saturation",
        "mental_status": "mental_status",
        "gcs": "mental_status",
    }

    for raw_key, raw_value in value.items():
        normalized_key = key_map.get(str(raw_key).strip().lower())
        if normalized_key and str(raw_value).strip():
            normalized[normalized_key] = str(raw_value).strip()
    return normalized


def extract_initial_vitals(case_root: dict[str, Any], patient_actor: dict[str, Any]) -> dict[str, Any]:
    for source in (patient_actor, case_root):
        candidate = get_first_existing_value(
            source,
            [
                "Vital_Signs",
                "Vital Signs",
                "vital_signs",
                "Vitals",
                "vitals",
            ],
            {},
        )
        normalized = normalize_vitals(candidate)
        if normalized:
            return normalized
    return {}


def build_arrival_info(
    chief_complaint: str,
    history: str,
    associated_symptoms: list[str],
) -> str:
    parts = [chief_complaint]
    if associated_symptoms:
        parts.append(", ".join(associated_symptoms[:3]))
    if history:
        parts.append(history[:180].strip())
    return " | ".join(part for part in parts if part)


def build_triage_clues(
    chief_complaint: str,
    history: str,
    initial_vitals: dict[str, Any],
) -> list[str]:
    clues: list[str] = []
    combined = f"{chief_complaint} {history}".lower()

    for keyword in [
        "severe",
        "sudden",
        "acute",
        "chest pain",
        "shortness of breath",
        "syncope",
        "weakness",
        "fever",
        "bleeding",
    ]:
        if keyword in combined:
            clues.append(keyword)

    if initial_vitals:
        clues.append("vital signs available at ER arrival")
    return clues[:6]


def transform_case(raw_case: dict[str, Any], idx: int) -> dict[str, Any]:
    case_root = safe_dict(
        get_first_existing_value(
            raw_case,
            ["OSCE_Examination", "OSCE Examination", "osce_examination"],
            raw_case,
        )
    )
    patient_actor = safe_dict(
        get_first_existing_value(
            case_root,
            ["Patient_Actor", "Patient Actor", "patient_actor"],
            {},
        )
    )
    symptoms = safe_dict(get_first_existing_value(patient_actor, ["Symptoms", "symptoms"], {}))

    demographics = normalize_text(get_first_existing_value(patient_actor, ["Demographics", "demographics"], ""))
    history = normalize_text(get_first_existing_value(patient_actor, ["History", "history"], ""))
    past_history = normalize_text(
        get_first_existing_value(
            patient_actor,
            ["Past_Medical_History", "Past Medical History", "past_medical_history"],
            "",
        )
    )
    current_medications = normalize_text(
        get_first_existing_value(
            patient_actor,
            [
                "Current_Medications",
                "Current Medications",
                "current_medications",
                "Medications",
                "medications",
                "Drug_History",
                "drug_history",
            ],
            "",
        )
    )
    social_history = normalize_text(
        get_first_existing_value(patient_actor, ["Social_History", "Social History", "social_history"], "")
    )
    ros = normalize_text(
        get_first_existing_value(patient_actor, ["Review_of_Systems", "Review of Systems", "review_of_systems"], "")
    )
    initial_vitals = extract_initial_vitals(case_root, patient_actor)

    primary_symptom = normalize_text(
        get_first_existing_value(symptoms, ["Primary_Symptom", "Primary Symptom", "primary_symptom"], "")
    )
    secondary_symptoms = normalize_list(
        get_first_existing_value(symptoms, ["Secondary_Symptoms", "Secondary Symptoms", "secondary_symptoms"], [])
    )
    associated_symptoms = normalize_list(
        get_first_existing_value(symptoms, ["Associated_Symptoms", "Associated Symptoms", "associated_symptoms"], [])
    )

    physical_exam = filter_non_informative_sections(
        get_first_existing_value(
            case_root,
            [
                "Physical_Examination_Findings",
                "Physical Examination Findings",
                "Physical_Exam_Findings",
                "physical_exam",
                "physical_examination_findings",
            ],
            {},
        )
    )
    test_results = filter_non_informative_sections(
        get_first_existing_value(case_root, ["Test_Results", "Test Results", "test_results", "tests"], {})
    )

    correct_diagnosis = normalize_text(
        get_first_existing_value(
            case_root,
            [
                "Correct_Diagnosis",
                "Correct Diagnosis",
                "correct_diagnosis",
                "Diagnosis",
                "diagnosis",
                "answer",
            ],
            "",
        )
    )

    patient_visible_info = build_patient_visible_info(
        demographics=demographics,
        history=history,
        past_history=past_history,
        current_medications=current_medications,
        social_history=social_history,
        ros=ros,
        primary_symptom=primary_symptom,
        secondary_symptoms=secondary_symptoms,
        associated_symptoms=associated_symptoms,
    )
    doctor_visible_info = build_doctor_visible_info(patient_visible_info)
    doctor_visible_info["arrival_info"] = build_arrival_info(
        doctor_visible_info.get("chief_complaint", ""),
        history,
        associated_symptoms,
    )
    doctor_visible_info["initial_vitals"] = initial_vitals
    doctor_visible_info["triage_clues"] = build_triage_clues(
        doctor_visible_info.get("chief_complaint", ""),
        history,
        initial_vitals,
    )
    available_exam_sections = extract_available_sections(physical_exam)
    available_test_sections = extract_available_sections(test_results)
    curated_assignment = get_curated_department_assignment(correct_diagnosis)
    gold_department = (
        str(curated_assignment.get("department", "")).strip()
        if curated_assignment
        else infer_department_from_case(
            correct_diagnosis,
            [*available_exam_sections, *available_test_sections],
        )
    )
    department_evaluable = bool(gold_department)
    temporal_profile = build_temporal_profile(
        idx=idx,
        chief_complaint=doctor_visible_info.get("chief_complaint", ""),
        history=history,
        triage_clues=list(doctor_visible_info.get("triage_clues", []) or []),
        initial_vitals=initial_vitals,
    )
    resource_profile = build_resource_profile(
        available_test_sections=available_test_sections,
        risk=str(
            (temporal_profile.get("deterioration_model", {}) or {}).get("baseline_risk", "")
        ).strip().lower(),
    )

    return {
        "case_id": f"case_{idx:04d}",
        "patient_visible_info": patient_visible_info,
        "doctor_visible_info": doctor_visible_info,
        "temporal_profile": temporal_profile,
        "resource_profile": resource_profile,
        "hidden_exam_results": physical_exam,
        "hidden_test_results": test_results,
        "gold_label": {
            "diagnosis": correct_diagnosis,
            "department": gold_department,
            "department_evaluable": department_evaluable,
            "department_rationale": (
                curated_assignment["rationale"]
                if curated_assignment
                else "Heuristic fallback based on the diagnosis text and available section names."
            ),
        },
        "meta": {
            "available_exam_sections": available_exam_sections,
            "available_test_sections": available_test_sections,
            "history_sentences": split_sentences(history),
            "review_of_systems_sentences": split_sentences(ros),
        },
    }
