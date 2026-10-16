from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.utils.department_catalog import normalize_department


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _list_text(values: Any) -> list[str]:
    if isinstance(values, list):
        return [_text(item) for item in values if _text(item)]
    text = _text(values)
    return [text] if text else []


def _bp_parts(value: str) -> tuple[str, str]:
    text = _text(value)
    if "/" not in text:
        return text, ""
    systolic, diastolic = text.split("/", 1)
    return systolic.strip(), diastolic.strip()


def _normalize_vitals(vitals: dict[str, Any]) -> dict[str, Any]:
    payload = dict(vitals or {})
    systolic_bp, diastolic_bp = _bp_parts(_text(payload.get("BP")))
    return {
        "blood_pressure": _text(payload.get("BP")),
        "systolic_bp": systolic_bp,
        "diastolic_bp": diastolic_bp,
        "heart_rate": _text(payload.get("HR")),
        "respiratory_rate": _text(payload.get("RR")),
        "temperature": _text(payload.get("Temp_C")),
        "oxygen_saturation": _text(payload.get("SpO2")),
        "mental_status": _text(payload.get("mental_status")),
    }


def _history_lines(patient: dict[str, Any]) -> list[str]:
    history = dict(patient.get("history", {}) or {})
    answer_rules = dict(patient.get("patient_answer_rules", {}) or {})
    lines: list[str] = []

    if _text(patient.get("chief_complaint")):
        lines.append(f"Chief complaint: {_text(patient.get('chief_complaint'))}.")
    if _text(answer_rules.get("open_question")):
        lines.append(_text(answer_rules.get("open_question")))

    for key, value in answer_rules.items():
        if key == "open_question":
            continue
        if isinstance(value, list):
            rendered = ", ".join(_list_text(value))
            if rendered:
                lines.append(f"{key.replace('_', ' ').title()}: {rendered}.")
        else:
            rendered = _text(value)
            if rendered:
                lines.append(f"{key.replace('_', ' ').title()}: {rendered}.")

    for label, key in (
        ("Past history", "past_history"),
        ("Risk factors", "risk_factors"),
        ("Medications", "medications"),
    ):
        rendered = ", ".join(_list_text(history.get(key)))
        if rendered:
            lines.append(f"{label}: {rendered}.")

    allergies = _text(history.get("allergies"))
    if allergies:
        lines.append(f"Allergies: {allergies}.")
    recent_issue = _text(history.get("recent_issue"))
    if recent_issue:
        lines.append(f"Recent issue: {recent_issue}.")
    return lines


def _triage_clues(patient: dict[str, Any]) -> list[str]:
    clues = [_text(dict(patient.get("initial_triage", {}) or {}).get("triage_reason"))]
    complaint = _text(patient.get("chief_complaint"))
    if complaint:
        clues.append(complaint)
    for item in _list_text(dict(patient.get("patient_answer_rules", {}) or {}).get("associated_symptoms"))[:3]:
        clues.append(item)
    return [item for item in clues if item][:6]


def _risk_from_esi(esi_level: int) -> str:
    if int(esi_level or 3) <= 2:
        return "high"
    if int(esi_level or 3) == 3:
        return "moderate"
    return "low"


def _natural_history(patient: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in list(patient.get("time_progression", []) or []):
        event = dict(item or {})
        time_min = int(event.get("time_min", 0) or 0)
        if time_min <= 0:
            continue
        vitals = _normalize_vitals(dict(event.get("vitals", {}) or {}))
        numeric = {}
        for key, value in vitals.items():
            if key in {"blood_pressure", "mental_status"} or not value:
                continue
            numeric[key] = float(value)
        changes = {"vital_values": numeric}
        if _text(event.get("symptom_change")):
            changes["new_symptoms"] = [_text(event["symptom_change"])]
        health = {"worse": "Worsening", "urgent": "Worsening", "critical": "Critical", "stable": "Stable"}.get(_text(event.get("condition")).lower())
        if health:
            changes["health_state"] = health
        events.append(
            {
                "minute": time_min,
                "changes": changes,
                "condition": _text(event.get("condition")),
                "symptom_change": _text(event.get("symptom_change")),
                "vitals": _normalize_vitals(dict(event.get("vitals", {}) or {})),
            }
        )
    return events


def _demo_control(patient: dict[str, Any]) -> dict[str, Any]:
    explicit = dict(patient.get("demo_control", {}) or {})
    if explicit:
        return explicit

    patient_id = _text(patient.get("patient_id"))
    if patient_id == "P01":
        return {
            "role": "main_what_if_case",
            "decisive_tests": ["ECG"],
            "decisive_test_count": 1,
            "demo_test_plan": ["ECG"],
            "primary_what_if": {
                "type": "await_results",
                "target": "Troponin I",
                "label": "Wait for Troponin before calling Cardiology",
                "impact": "Diagnosis stays the same, but Cardiology handoff is delayed.",
            },
        }
    if patient_id == "P02":
        return {
            "role": "waiting_room_deterioration",
            "decisive_tests": ["D-dimer", "CT Pulmonary Angiography"],
            "decisive_test_count": 1,
            "demo_test_plan": ["D-dimer", "CT Pulmonary Angiography"],
        }
    if patient_id == "P03":
        return {
            "role": "lower_priority_but_worsens",
            "decisive_tests": ["CBC", "Abdominal CT"],
            "decisive_test_count": 1,
            "demo_test_plan": ["CBC", "Abdominal CT"],
        }
    if patient_id == "P04":
        return {
            "role": "rapid_metabolic_confirmation",
            "decisive_tests": ["Glucose", "ABG"],
            "decisive_test_count": 1,
            "demo_test_plan": ["Glucose", "ABG"],
        }
    if patient_id == "P05":
        return {
            "role": "delayed_neuro_infectious_consult",
            "decisive_tests": ["Brain CT", "CSF analysis"],
            "decisive_test_count": 1,
            "demo_test_plan": ["Brain CT", "CSF analysis"],
        }
    return {}


def _case_from_patient(patient: dict[str, Any], scenario: dict[str, Any], patient_index: int) -> dict[str, Any]:
    patient_id = _text(patient.get("patient_id")) or f"P{patient_index + 1:02d}"
    age = _text(dict(patient.get("demographics", {}) or {}).get("age"))
    sex = _text(dict(patient.get("demographics", {}) or {}).get("sex"))
    demographics = " ".join(
        part for part in [f"{age}-year-old" if age else "", sex] if part
    ).strip()

    triage = dict(patient.get("initial_triage", {}) or {})
    esi_level = int(triage.get("esi_level", 3) or 3)
    available_tests = dict(patient.get("available_tests", {}) or {})
    demo_control = _demo_control(patient)
    gold_department = normalize_department(_text(patient.get("correct_specialty")), default="general_medicine")
    hidden_test_results = {
        _text(test_name): {
            "result": _text(dict(test_payload or {}).get("result")),
            "result_delay_min": int(dict(test_payload or {}).get("result_delay_min", 0) or 0),
        }
        for test_name, test_payload in available_tests.items()
        if _text(test_name)
    }

    history_lines = _history_lines(patient)
    initial_vitals = _normalize_vitals(dict(patient.get("initial_vitals", {}) or {}))
    natural_history = _natural_history(patient)
    observation_minutes = min([item["minute"] for item in natural_history], default=15)

    return {
        "case_id": patient_id,
        "patient_visible_info": {
            "demographics": demographics,
            "chief_complaint": _text(patient.get("chief_complaint")),
            "history": " ".join(history_lines),
            "symptoms": {
                "primary": _text(patient.get("chief_complaint")),
                "secondary": _list_text(dict(patient.get("patient_answer_rules", {}) or {}).get("associated_symptoms")),
                "associated": _list_text(dict(patient.get("history", {}) or {}).get("risk_factors")),
                "summary": [_text(patient.get("chief_complaint")), *_list_text(dict(patient.get("patient_answer_rules", {}) or {}).get("associated_symptoms"))],
            },
            "past_medical_history": ", ".join(_list_text(dict(patient.get("history", {}) or {}).get("past_history"))),
            "current_medications": ", ".join(_list_text(dict(patient.get("history", {}) or {}).get("medications"))),
            "social_history": ", ".join(_list_text(dict(patient.get("history", {}) or {}).get("risk_factors"))),
            "review_of_systems": " ".join(history_lines[-4:]),
        },
        "doctor_visible_info": {
            "demographics": demographics,
            "chief_complaint": _text(patient.get("chief_complaint")),
            "initial_summary": f"{demographics} | {_text(patient.get('chief_complaint'))}".strip(" |"),
            "arrival_info": f"{_text(patient.get('chief_complaint'))} | {', '.join(_list_text(dict(patient.get('patient_answer_rules', {}) or {}).get('associated_symptoms'))[:3])}".strip(" |"),
            "initial_vitals": initial_vitals,
            "triage_clues": _triage_clues(patient),
        },
        "temporal_profile": {
            "time_unit_minutes": 1,
            "arrival_time_min": int(patient.get("arrival_time_min", patient_index * 4) or 0),
            "initial_acuity": esi_level,
            "observation_reassessment_minutes": observation_minutes,
            "deterioration_model": {
                "type": "rule_based",
                "baseline_risk": _risk_from_esi(esi_level),
                "triggers": [],
            },
            "natural_history_events": natural_history,
            "reassessment_suggestions": [
                {
                    "minute": int(item.get("minute", 0) or 0),
                    "reason": _text(item.get("symptom_change")) or "Repeat ER reassessment.",
                }
                for item in natural_history
            ],
        },
        "resource_profile": {
            "capacity": {
                "doctor": int(dict(scenario.get("global_config", {}) or {}).get("er_doctor_count", 1) or 1),
                "imaging": 1,
                "lab": 1,
                "consult": 1,
            },
            "test_turnaround": {
                _text(test_name): int(dict(test_payload or {}).get("result_delay_min", 0) or 0)
                for test_name, test_payload in available_tests.items()
                if _text(test_name)
            },
            "consult_turnaround": {
                gold_department: 2,
            },
        },
        "hidden_exam_results": dict(patient.get("examine_findings", {}) or {}),
        "hidden_test_results": hidden_test_results,
        "gold_label": {
            "diagnosis": _text(patient.get("final_diagnosis") or patient.get("hidden_true_diagnosis")),
            "department": gold_department,
            "department_evaluable": True,
            "department_rationale": f"{_text(patient.get('correct_specialty'))} is the intended specialty in the fixed demo scenario.",
        },
        "meta": {
            "available_exam_sections": list(dict(patient.get("examine_findings", {}) or {}).keys()),
            "available_test_sections": list(hidden_test_results.keys()),
            "history_sentences": history_lines,
            "review_of_systems_sentences": _list_text(dict(patient.get("patient_answer_rules", {}) or {}).get("associated_symptoms")),
            "demo": {
                "scenario_id": _text(scenario.get("scenario_id")),
                "scenario_title": _text(scenario.get("scenario_title")),
                "role": _text(demo_control.get("role")),
                "expected_er_path": list(patient.get("expected_er_path", []) or []),
                "primary_what_if": dict(demo_control.get("primary_what_if", {}) or {}),
                "decisive_tests": _list_text(demo_control.get("decisive_tests")),
                "decisive_test_count": int(demo_control.get("decisive_test_count", 1) or 1),
                "timeline_events": [
                    dict(item or {})
                    for item in list(scenario.get("timeline_events", []) or [])
                    if _text(dict(item or {}).get("patient_id")) == patient_id
                ],
            },
        },
    }


def load_demo_scenario(path: Path) -> dict[str, Any]:
    return dict(json.loads(Path(path).read_text(encoding="utf-8")) or {})


def load_demo_scenario_cases(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scenario = load_demo_scenario(path)
    patients = [dict(item or {}) for item in list(scenario.get("patients", []) or []) if dict(item or {})]
    cases = [_case_from_patient(patient, scenario, index) for index, patient in enumerate(patients)]
    demo_config = dict(scenario.get("demo_config", {}) or {})
    context = {
        "scenario_id": _text(scenario.get("scenario_id")),
        "scenario_title": _text(scenario.get("scenario_title")),
        "fixed_demo": True,
        "default_case_id": _text(demo_config.get("default_case_id")) or (cases[0]["case_id"] if cases else ""),
        "primary_what_if_case_id": _text(demo_config.get("primary_what_if_case_id")) or "P01",
        "timeline_events": [dict(item or {}) for item in list(scenario.get("timeline_events", []) or []) if dict(item or {})],
    }
    return cases, context
