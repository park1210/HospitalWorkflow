"""Isolated, deterministic follow-up of explicitly configured physiology.

This observes a copy after the diagnostic simulation boundary. It does not
allocate hospital resources, prescribe treatment, or authorize discharge.
"""
from copy import deepcopy

from app.core.hospital_case_runtime import HospitalCaseRuntime
from app.core.hospital_flow import HEALTH_STATES, validate_deterioration
from app.modules.deterioration_module import DeteriorationModule


def followup_report(runtimes, minutes):
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 1:
        raise ValueError("Follow-up minutes must be a positive integer")
    cases, skipped = [], []
    for original in runtimes:
        if not original.is_completed or original.final_diagnosis_min is None:
            skipped.append({"case_id": original.case_id, "reason": "diagnostic_episode_incomplete"})
            continue
        validate_deterioration(original.case_data)
        runtime = deepcopy(original)
        start = runtime.final_diagnosis_min
        if runtime.current_time_min != start:
            raise ValueError(f"Follow-up requires physiology at diagnostic completion: {runtime.case_id}")
        end = start + minutes
        profile = runtime.case_data.get("temporal_profile", {})
        for treatment in runtime.interventions:
            if treatment["id"] not in profile.get("interventions", {}):
                raise ValueError(f"Missing effect specification for administered intervention: {treatment['id']}")
        model = DeteriorationModule()
        events = []
        def sample():
            return {"minute": runtime.current_time_min, "health_state": runtime.health_state,
                    "vital_signs": deepcopy(runtime.vital_signs),
                    "current_symptoms": list(runtime.current_symptoms)}
        trajectory = [sample()]
        for now in range(start + 1, end + 1):
            previous_health = runtime.health_state
            applied = model.apply_interventions(runtime.case_data, runtime, now)
            applied += model._apply_natural_history_events(runtime.case_data, runtime,
                start_time_min=now - 1, end_time_min=now)
            applied += model._apply_configured_triggers(runtime.case_data, runtime, end_time_min=now)
            flow = profile.get("flow_deterioration", {})
            # No additional queue waiting accrues outside the hospital model.
            if flow.get("clock") == "since_arrival":
                elapsed = now - runtime.arrival_time_min
                level = (2 if elapsed >= flow["critical_after_min"] else
                         1 if elapsed >= flow["worsening_after_min"] else 0)
                if level > HEALTH_STATES.index(runtime.health_state):
                    runtime.health_state = HEALTH_STATES[level]
                    applied.append({"event_type": "flow_deterioration",
                        "reason": "Configured since-arrival threshold crossed.",
                        "health_state": runtime.health_state})
            runtime.current_time_min = now
            for event in applied:
                events.append({"observed_minute": now, **deepcopy(event)})
            if applied or now == end:
                trajectory.append(sample())
            if HEALTH_STATES.index(runtime.health_state) > HEALTH_STATES.index(previous_health):
                events.append({"observed_minute": now, "event_type": "review_needed",
                               "reason": "Configured health state worsened after diagnostic completion."})
        gaps = []
        if not any(profile.get(k) for k in ("natural_history_events", "interventions", "deterioration_model", "flow_deterioration")):
            gaps.append("No postdiagnostic dynamics provided; unchanged state does not demonstrate recovery.")
        elif not events:
            gaps.append("No configured event occurred within this horizon; unchanged state does not demonstrate recovery.")
        if profile.get("flow_deterioration", {}).get("clock") == "queue_wait":
            gaps.append("Queue-wait deterioration is excluded outside the hospital resource simulation.")
        cases.append({"case_id": runtime.case_id, "start_minute": start, "end_minute": end,
            "disposition_status": "not_assessed", "clinical_validity_verified": False,
            "trajectory": trajectory, "events": events, "data_gaps": gaps,
            "pending_interventions": [deepcopy(t) for t in runtime.interventions if t["effective_min"] > end],
            "interventions": deepcopy(runtime.interventions)})
    return {"scope": "postdiagnostic_physiology_observation", "minutes": minutes,
            "llm_calls": 0, "hospital_resources_simulated": False,
            "cases": cases, "skipped_cases": skipped}


def followup_from_summary(summary, minutes):
    sources = {case["case_id"]: case for case in summary["source_cases"]}
    rows = summary["final_state"]["cases"]
    if isinstance(rows, dict):
        rows = rows.values()
    runtimes = []
    for row in rows:
        case_id = row["case_id"]
        if case_id not in sources:
            raise ValueError(f"Missing source case: {case_id}")
        runtimes.append(HospitalCaseRuntime.from_summary(row, sources[case_id]))
    return followup_report(runtimes, minutes)
