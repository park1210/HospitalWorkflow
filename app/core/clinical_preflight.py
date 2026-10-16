"""Read-only inventory of missing simulation inputs, not clinical certification."""
from app.core.clinical_observation import patient_observation
from app.core.patient_facts import patient_facts
from app.modules.deterioration_module import DeteriorationModule


def clinical_preflight(cases):
    rows = []
    model = DeteriorationModule()
    for case in cases:
        gaps = []
        profile = case.get("temporal_profile", {})
        initial = case.get("doctor_visible_info", {}).get("initial_vitals", {})
        if not patient_facts(patient_observation(case)):
            gaps.append({"code": "missing_patient_facts", "field": "patient_visible_info"})
        if not initial:
            gaps.append({"code": "missing_initial_vitals", "field": "doctor_visible_info.initial_vitals"})
        if "available_tests" not in case:
            gaps.append({"code": "case_specific_test_catalog_fallback", "field": "available_tests"})
        names = case.get("available_tests", list(case.get("hidden_test_results", {})))
        for name in names:
            if not case.get("hidden_test_results", {}).get(name, {}).get("result"):
                gaps.append({"code": "missing_test_result", "test": name})
            for field in ("test_occupancy", "test_turnaround", "test_resources"):
                if name not in case.get("resource_profile", {}).get(field, {}):
                    gaps.append({"code": "missing_" + field, "test": name})
        events = [e.get("changes", {}) for e in profile.get("natural_history_events", [])]
        triggers = profile.get("deterioration_model", {}).get("triggers", [])
        events += [t.get("effect", {}) for t in triggers]
        events += [i.get("effect", {}) for i in profile.get("interventions", {}).values()]
        if not events and not profile.get("flow_deterioration"):
            gaps.append({"code": "missing_progression_model", "field": "temporal_profile"})
        for effect in events:
            for key, aliases in model.VITAL_DELTA_KEYS.items():
                if key in effect and not any(model._to_float(initial.get(alias)) is not None for alias in aliases):
                    gaps.append({"code": "missing_initial_delta_baseline", "field": aliases[0]})
        if not profile.get("interventions"):
            gaps.append({"code": "missing_intervention_response", "field": "temporal_profile.interventions"})
        if any(not t.get("addressed_by") for t in triggers):
            gaps.append({"code": "unconditional_time_triggers", "field": "deterioration_model.triggers.addressed_by"})
        if not case.get("model_provenance"):
            gaps.append({"code": "missing_calibration_provenance", "field": "model_provenance"})
        rows.append({"case_id": case.get("case_id", ""), "gaps": gaps})
    return {"schema_version": 1, "case_count": len(rows), "cases": rows,
            "gap_count": sum(len(r["gaps"]) for r in rows),
            "clinical_validation": "not_performed", "llm_calls": 0,
            "interpretation": "input_inventory_only; missing baselines may be supplied by later events; provenance content is not independently verified"}
