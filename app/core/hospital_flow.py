"""Chapter 6: deterministic flow policy and finite-window accounting.

All times are simulation minutes. No clinical thresholds are inferred from labels.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import random
from statistics import mean
from typing import Any

from app.core.hospital_flow_audit import conservation_report, progress_report
from app.core.hospital_test_model import validate_test_profile
from app.core.hospital_evaluation import validate_evaluation


DEFAULT_FLOW_CONFIG = {
    "capacities": {"triage_nurses": 1, "er_doctors": 1, "er_beds": 4,
                   "lab_slots": 2, "imaging_slots": 1},
    "durations": {"triage": 1, "er_assessment": 1, "er_travel": 1,
                  "specialty_travel": 2, "specialty_consult": 4,
                  "lab_slot": 5, "imaging_slot": 6, "result_hold": 3},
    "priority": {"severity": 1.0, "waiting": 0.05, "risk": 1.0},
    "arrival": {"mode": "fixed", "rate_per_minute": 0.2, "seed": 0},
    "demand": {},
    "simulation": {"resource_mode": "constrained"},
    "clinical": {"mode": "demo", "max_decisions": 12, "max_questions": 2},
}
QUEUES = ("triage_queue", "bed_queue", "er_queue", "test_queue", "specialty_queue")
HEALTH_STATES = ("Stable", "Worsening", "Critical")


def positive_minutes(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be a finite positive number of minutes")
    return math.ceil(value)


def flow_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    result = deepcopy(DEFAULT_FLOW_CONFIG)
    for section, values in (overrides or {}).items():
        if section not in result or not isinstance(values, dict):
            raise ValueError(f"Unknown flow configuration section: {section}")
        if section == "demand":
            result[section] = deepcopy(values)
            continue
        for key, value in values.items():
            if key not in result[section]:
                raise ValueError(f"Unknown flow configuration key: {section}.{key}")
            result[section][key] = value
    for name, count in result["capacities"].items():
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"Capacity {name} must be a nonnegative integer")
    if result["clinical"]["mode"] not in {"demo", "llm_required"}:
        raise ValueError("clinical.mode must be demo or llm_required")
    for key in ("max_decisions", "max_questions"):
        value = result["clinical"][key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"clinical.{key} must be a positive integer")
    # The current scene has four physical beds. Do not invent unmapped locations.
    mode = result["simulation"]["resource_mode"]
    if mode not in {"constrained", "cohort_unconstrained"}:
        raise ValueError("Unknown resource_mode")
    if result["capacities"]["er_beds"] > 4 and mode != "cohort_unconstrained":
        raise ValueError("More than four beds requires an expanded hospital scene layout")
    for name, duration in result["durations"].items():
        result["durations"][name] = positive_minutes(duration, name)
    for name, weight in result["priority"].items():
        if isinstance(weight, bool) or not isinstance(weight, (float, int)) or not math.isfinite(weight) or weight < 0:
            raise ValueError(f"Priority weight {name} must be finite and nonnegative")
    if not any(result["priority"].values()):
        raise ValueError("At least one priority weight must be positive")
    arrival = result["arrival"]
    if arrival["mode"] not in {"fixed", "poisson"}:
        raise ValueError("Arrival mode must be fixed or poisson")
    positive_minutes(arrival["rate_per_minute"], "arrival rate")
    if isinstance(arrival["seed"], bool) or not isinstance(arrival["seed"], int):
        raise ValueError("Arrival seed must be an integer")
    for group, demand in result["demand"].items():
        if group not in result["capacities"] or not isinstance(demand, dict):
            raise ValueError(f"Unsupported demand resource group: {group}")
        if set(demand) - {"arrival_rate_per_minute", "mean_service_min", "priority_arrival_rates", "model"}:
            raise ValueError(f"Unknown demand field: {group}")
        rate = demand.get("arrival_rate_per_minute")
        if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate < 0:
            raise ValueError("Demand requires a finite nonnegative arrival rate")
        positive_minutes(demand.get("mean_service_min"), "mean service time")
        if demand.get("model", "load_only") not in {"load_only", "mm1_fixed_priority"}:
            raise ValueError("Demand model must be load_only or mm1_fixed_priority")
        rates = demand.get("priority_arrival_rates")
        if demand.get("model") == "mm1_fixed_priority":
            if not isinstance(rates, list) or not rates:
                raise ValueError("M/M/1 requires class arrival rates, highest priority first")
            if any(isinstance(r, bool) or not isinstance(r, (int, float)) or not math.isfinite(r) or r < 0 for r in rates):
                raise ValueError("Invalid class arrival rate")
            if not math.isclose(sum(rates), rate, rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError("Class arrival rates must sum to the total demand")
        elif rates is not None:
            raise ValueError("Priority rates require the explicit mm1_fixed_priority model")
    return result


def load_flow_config(path: str | Path | None = None) -> dict[str, Any]:
    return flow_config(json.loads(Path(path).read_text(encoding="utf-8")) if path else None)


def schedule_arrivals(cases: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    result = deepcopy(cases)
    rng = random.Random(config["arrival"]["seed"])
    time = 0.0
    seen: set[str] = set()
    for case in result:
        case_id = str(case.get("case_id", "")).strip()
        if not case_id or case_id in seen:
            raise ValueError(f"Missing or duplicate case_id: {case_id!r}")
        case["case_id"] = case_id
        seen.add(case_id)
        profile = case.setdefault("temporal_profile", {})
        if config["arrival"]["mode"] == "poisson":
            time += rng.expovariate(config["arrival"]["rate_per_minute"])
            profile["arrival_time_min"] = math.ceil(time)
        arrival = profile.get("arrival_time_min", case.get("arrival_time_min", len(seen) * 5 - 5))
        if isinstance(arrival, bool) or not isinstance(arrival, (int, float)) or not math.isfinite(arrival) or arrival < 0:
            raise ValueError(f"Invalid arrival time for {case_id}")
        profile["arrival_time_min"] = math.ceil(arrival)
        validate_deterioration(case)
        validate_test_profile(case, config["durations"])
        validate_evaluation(case)
    return result


def validate_deterioration(case: dict[str, Any]) -> None:
    profile = case.get("temporal_profile", {})
    def minute(value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("Physiology event times must be nonnegative integer minutes")
    def effect(value):
        if not isinstance(value, dict):
            raise ValueError("Physiology effect must be an object")
        allowed = {"sbp_delta", "systolic_bp_delta", "pain_score_delta", "heart_rate_delta", "respiratory_rate_delta", "temperature_delta", "spo2_delta",
                   "new_symptoms", "resolved_symptoms", "health_state", "vital_values"}
        if set(value) - allowed:
            raise ValueError("Unknown physiology effect")
        for key, item in value.items():
            if key == "vital_values":
                if not isinstance(item, dict) or set(item) - {"sbp", "systolic_bp", "diastolic_bp", "heart_rate", "respiratory_rate", "temperature", "spo2", "oxygen_saturation", "pain_score"}:
                    raise ValueError("Unknown absolute vital field")
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in item.values()):
                    raise ValueError("Absolute vital values must be finite and nonnegative")
            if key.endswith("_delta") and (isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)):
                raise ValueError("Vital change must be finite")
            if key.endswith("symptoms") and (not isinstance(item, list) or any(not isinstance(s, str) or not s.strip() for s in item)):
                raise ValueError("Symptoms must be nonempty strings")
            if key == "health_state" and item not in HEALTH_STATES:
                raise ValueError("Unknown health state")
    interventions = profile.get("interventions", {})
    if not isinstance(interventions, dict):
        raise ValueError("Interventions must map names to explicit effects")
    for name, spec in interventions.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(spec, dict):
            raise ValueError("Invalid intervention specification")
        minute(spec.get("delay_minutes"))
        effect(spec.get("effect"))
    for event in profile.get("natural_history_events", []):
        minute(event.get("minute"))
        effect(event.get("changes", {}))
    for trigger in profile.get("deterioration_model", {}).get("triggers", []):
        minute(trigger.get("if_unaddressed_for_minutes"))
        effect(trigger.get("effect", {}))
        if trigger.get("addressed_by") and trigger["addressed_by"] not in interventions:
            raise ValueError("Deterioration addressed_by must name a configured intervention")
    model = case.get("temporal_profile", {}).get("flow_deterioration")
    if model is None:
        return
    if not isinstance(model, dict) or set(model) - {"clock", "worsening_after_min", "critical_after_min"}:
        raise ValueError("flow_deterioration requires clock and two explicit thresholds")
    if model.get("clock") not in {"since_arrival", "queue_wait"}:
        raise ValueError("Deterioration clock must be since_arrival or queue_wait")
    low = positive_minutes(model.get("worsening_after_min"), "worsening threshold")
    high = positive_minutes(model.get("critical_after_min"), "critical threshold")
    if low >= high:
        raise ValueError("Deterioration thresholds must be strictly increasing")


def priority_components(runtime: Any, config: dict[str, Any]) -> dict[str, float]:
    weights = config["priority"]
    severity = 6 - runtime.triage_level
    baseline_risk = {"minimal": 0.0, "low": 0.0, "moderate": 0.5, "high": 1.0}.get(runtime.deterioration_risk, 0.0)
    risk = max(baseline_risk, {"Stable": 0.0, "Worsening": 0.5, "Critical": 1.0}[runtime.health_state])
    components = {"severity": weights["severity"] * severity,
                  "waiting": weights["waiting"] * runtime.queue_wait_minutes,
                  "risk": weights["risk"] * risk}
    components["score"] = sum(components.values())
    return components


def sync_queues(state: Any) -> None:
    """Observe each phase boundary, including zero-duration queue visits."""
    stats = state.flow_accounting
    if not stats:
        stats.update({"start_minute": state.current_minute, "queues": {}, "resources": {}})
    stats.setdefault("system", {"start_minute": state.current_minute, "area": 0})
    now = state.current_minute
    for name in QUEUES:
        q = stats["queues"].setdefault(name, {"entries": 0, "exits": 0, "completed_wait": 0,
                                                    "area": 0, "open": {}})
        members = set(getattr(state, name))
        for cid in set(q["open"]) - members:
            q["completed_wait"] += now - q["open"].pop(cid)
            q["exits"] += 1
        for cid in members - set(q["open"]):
            q["open"][cid] = now
            q["entries"] += 1


def account_interval(state: Any) -> None:
    """Integrate queue length and resource occupancy over [t, t+1)."""
    waiting: set[str] = set()
    state.flow_accounting["system"]["area"] += sum(
        not c.is_completed and c.workflow_state != "not_arrived" for c in state.cases.values())
    for name in QUEUES:
        members = set(getattr(state, name))
        state.flow_accounting["queues"][name]["area"] += len(members)
        waiting.update(members)
    for cid in waiting:
        state.case(cid).queue_wait_minutes += 1
    for resource in state.resources.all_resources():
        r = state.flow_accounting["resources"].setdefault(resource.resource_id,
             {"busy_minutes": 0, "resource_type": resource.resource_type})
        if resource.status != "idle":
            r["busy_minutes"] += 1


def validate_state(state: Any) -> None:
    """Fail fast on invalid allocation/state rather than silently duplicating work."""
    memberships: dict[str, str] = {}
    for group, expected in state.flow_config.get("capacities", {}).items():
        if len(getattr(state.resources, group)) != expected:
            raise ValueError(f"Resource pool differs from configured capacity: {group}")
    for c in state.cases.values():
        if c.is_completed != (c.workflow_state == "completed"):
            raise ValueError("Completion flag and workflow state disagree")
        if (c.workflow_state == "not_arrived") != (c.case_id in state.arrival_queue):
            raise ValueError("Arrival queue and patient state disagree")
        if c.health_state not in HEALTH_STATES or not 1 <= c.triage_level <= 5 or c.queue_wait_minutes < 0:
            raise ValueError(f"Invalid patient model state: {c.case_id}")
        if c.first_evaluation_min is not None and c.first_evaluation_min < c.arrival_time_min:
            raise ValueError("Evaluation cannot precede arrival")
    for name in ("arrival_queue", *QUEUES):
        queue = getattr(state, name)
        if len(queue) != len(set(queue)):
            raise ValueError(f"Duplicate patient in {name}")
        for cid in queue:
            if cid not in state.cases or state.case(cid).is_completed:
                raise ValueError(f"Invalid active patient {cid} in {name}")
            if cid in memberships:
                raise ValueError(f"Patient {cid} appears in both {memberships[cid]} and {name}")
            memberships[cid] = name
    resource_ids: set[str] = set()
    owners: set[tuple[str, str]] = set()
    for r in state.resources.all_resources():
        if r.resource_id in resource_ids:
            raise ValueError(f"Duplicate resource id: {r.resource_id}")
        resource_ids.add(r.resource_id)
        if r.status == "idle":
            if r.assigned_case_id:
                raise ValueError(f"Idle resource {r.resource_id} still has an owner")
            continue
        if r.assigned_case_id not in state.cases or state.case(r.assigned_case_id).is_completed:
            raise ValueError(f"Occupied resource {r.resource_id} has invalid owner")
        key = (r.resource_type, r.assigned_case_id)
        if key in owners:
            raise ValueError(f"Patient {r.assigned_case_id} occupies multiple {r.resource_type} units")
        owners.add(key)
        if r.resource_type == "er_bed" and state.case(r.assigned_case_id).assigned_bed_id != r.resource_id:
            raise ValueError("Bed owner and patient bed pointer disagree")
    for c in state.cases.values():
        if not c.is_completed and c.assigned_bed_id:
            bed = state.resources.find_by_id(c.assigned_bed_id)
            if bed is None or bed.assigned_case_id != c.case_id:
                raise ValueError("Patient references a bed it does not own")
    seen_events = set()
    for event in state.scheduled_events:
        if event.get("case_id") not in state.cases or state.case(event["case_id"]).is_completed:
            raise ValueError("Scheduled event references inactive patient")
        if event["execute_minute"] < state.current_minute:
            raise ValueError("Overdue scheduled event")
        key = (event["event_type"], event["case_id"])
        if key in seen_events:
            raise ValueError("Duplicate pending event for a patient")
        seen_events.add(key)
        owner_fields = {"triage_complete": "nurse_id", "er_assessment_start": "doctor_id",
                        "test_resource_release": "resource_id", "specialty_consult_start": "specialist_id",
                        "specialty_consult_complete": "specialist_id"}
        if event["event_type"] == "test_result_ready":
            matches = [p for p in state.case(event["case_id"]).pending_results
                       if p.get("test_name") == event.get("test_name")
                       and p.get("resource_id") == event.get("resource_id")
                       and p.get("ready_minute") == event["execute_minute"]]
            if not matches:
                raise ValueError("Result event does not match a pending test")
            if not event.get("separate_resource_release"):
                owner_fields["test_result_ready"] = "resource_id"
        if event["event_type"] in owner_fields:
            resource = state.resources.find_by_id(event.get(owner_fields[event["event_type"]], ""))
            if resource is None or resource.assigned_case_id != event["case_id"]:
                raise ValueError("Pending service event does not own its resource")
    scheduled_cases = {e["case_id"] for e in state.scheduled_events}
    for c in state.cases.values():
        if not c.is_completed and c.case_id not in memberships and c.case_id not in scheduled_cases:
            raise ValueError(f"Active patient has neither a queue nor a future event: {c.case_id}")


def flow_report(state: Any) -> dict[str, Any]:
    stats = state.flow_accounting
    start = stats.get("start_minute", state.current_minute)
    duration = state.current_minute - start
    queue_rows = {}
    for name, q in stats.get("queues", {}).items():
        censored_wait = sum(state.current_minute - entered for entered in q["open"].values())
        total_wait = q["completed_wait"] + censored_wait
        queue_rows[name] = {
            "entries": q["entries"], "exits": q["exits"], "open_visits": len(q["open"]),
            "arrival_rate_per_minute": q["entries"] / duration if duration else None,
            "mean_completed_wait_min": q["completed_wait"] / q["exits"] if q["exits"] else None,
            "mean_observed_wait_including_censored_min": total_wait / q["entries"] if q["entries"] else None,
            "mean_queue_length": q["area"] / duration if duration else None,
            "little_law_area_residual_patient_minutes": q["area"] - total_wait,
            "little_law_interpretation": "finite_window_conservation_not_stationary_estimate",
        }
    groups: dict[str, Any] = {}
    units = {}
    for r in state.resources.all_resources():
        busy = stats.get("resources", {}).get(r.resource_id, {}).get("busy_minutes", 0)
        count = r.meta.get("allocation_count", 0)
        work = r.meta.get("allocated_minutes", 0)
        units[r.resource_id] = {"busy_minutes": busy, "utilization": busy / duration if duration else None,
            "admitted_service_visits": count, "mean_reserved_service_min": work / count if count else None,
            "reserved_service_rate_per_minute": count / work if work else None,
            "rate_note": "reserved_work_includes_travel_and_canceled_or_unfinished_reservations; not_population_demand"}
        g = groups.setdefault(r.resource_type, {"capacity": 0, "busy_minutes": 0})
        g["capacity"] += 1
        g["busy_minutes"] += busy
    for g in groups.values():
        g["utilization"] = g["busy_minutes"] / (g["capacity"] * duration) if duration else None
    waits = [c.first_evaluation_min - c.arrival_time_min for c in state.cases.values() if c.first_evaluation_min is not None]
    critical = [c for c in state.cases.values() if c.case_data.get("evaluation", {}).get("critical_patient") is True]
    critical_waits = [c.first_evaluation_min - c.arrival_time_min for c in critical if c.first_evaluation_min is not None]
    labelled = all(isinstance(c.case_data.get("evaluation", {}).get("critical_patient"), bool) for c in state.cases.values())
    all_seen = len(waits) == len(state.cases)
    mwt = mean(waits) if waits else None
    cpwt = mean(critical_waits) if labelled and critical_waits else None
    gaps = []
    from app.core.physiology_profile import has_health_progression
    unmodelled = [c.case_id for c in state.cases.values() if not has_health_progression(c.case_data)]
    if unmodelled:
        gaps.append({"code": "missing_deterioration_thresholds", "case_ids": unmodelled})
    if not labelled:
        gaps.append({"code": "missing_independent_critical_labels"})
    timing_assumptions = []
    for event in state.event_log:
        if event.get("event_type") != "test_started":
            continue
        payload = event.get("payload", {})
        timing_assumptions.append({"case_id": event["case_id"],
            "test_name": payload.get("requested_test"),
            "occupancy_source": payload.get("occupancy_source", "legacy_unknown"),
            "turnaround_source": payload.get("turnaround_source", "legacy_unknown"),
            "resource_source": payload.get("resource_source", "legacy_unknown")})
    for field, code in (("occupancy_source", "missing_test_occupancy"),
                        ("turnaround_source", "missing_test_turnaround"),
                        ("resource_source", "inferred_test_resource")):
        affected = [{"case_id": row["case_id"], "test_name": row["test_name"]}
                    for row in timing_assumptions if row[field] != "explicit"]
        if affected:
            gaps.append({"code": code, "executed_tests": affected})
    if start:
        gaps.append({"code": "partial_accounting_window", "start_minute": start})
    for name, count in state.flow_config.get("capacities", {}).items():
        if count == 0:
            gaps.append({"code": "zero_resource_capacity", "resource_group": name})
    return {
        "measurement_start_minute": start, "measurement_end_minute": state.current_minute,
        "observation_minutes": duration, "queues": queue_rows, "resource_units": units,
        "resource_groups": groups, "mean_first_wait_min_observed": mwt,
        "evaluated_count": len(waits), "not_evaluated_count": len(state.cases) - len(waits),
        "critical_patient_wait_min_observed": cpwt,
        "wte": 1 - cpwt / mwt if labelled and all_seen and cpwt is not None and mwt else None,
        "wte_status": "available" if labelled and all_seen and cpwt is not None and mwt else "missing_labels_or_incomplete_or_zero_wait",
        "termination": "completed" if not state.active_case_ids() else "incomplete",
        "unfinished_case_ids": state.active_case_ids(), "data_gaps": gaps,
        "model_limits": ["imaging modalities share one pool", "only triage nursing is capacity-constrained",
            "test occupancy falls back to turnaround when explicit occupancy is missing",
            "no calibrated intervention-response or recovery model",
            "M/M/1 formula is a separate analytical reference, not a hospital prediction"],
        "clinical_policy": ("evidence_only_llm_roles" if state.flow_config.get("clinical", {}).get("mode") == "llm_required"
                            else "existing_demo_policy_not_independent_llm_evaluation"),
        "llm_calls": sum(len(c.llm_audit) for c in state.cases.values()),
        "llm_failures": sum(a.get("status") == "error" for c in state.cases.values() for a in c.llm_audit),
        "conservation": conservation_report(state),
        "progress": progress_report(state),
        "demand_analysis": demand_report(state.flow_config),
        "executed_test_assumptions": timing_assumptions,
    }


def demand_report(config: dict[str, Any]) -> dict[str, Any]:
    """Exogenous input is deliberately separate from capacity-censored throughput."""
    result = {}
    for group, demand in config.get("demand", {}).items():
        capacity = config["capacities"][group]
        rate, service = demand["arrival_rate_per_minute"], demand["mean_service_min"]
        work = rate * service
        rho = work / capacity if capacity else None
        row = {"arrival_rate_per_minute": rate, "service_rate_per_minute": 1 / service,
               "capacity": capacity, "offered_load": rho,
               "minimum_integer_capacity_for_load_below_one": math.floor(work) + 1 if rate else 0,
               "load_condition": "no_capacity" if not capacity else "below_one" if rho < 1 else "at_or_above_one",
               "interpretation": "input_based_necessary_load_condition; not_full_network_stability_proof"}
        if demand.get("model") == "mm1_fixed_priority":
            row["assumptions"] = "Poisson arrivals, common exponential service, one server, fixed nonpreemptive priority, steady state"
            if capacity == 1 and rho < 1:
                row["reference_wait_by_priority_min"] = mm1_priority_reference(demand["priority_arrival_rates"], 1 / service)
                row["reference_status"] = "hypothetical_reference_only"
            else:
                row["reference_wait_by_priority_min"] = None
                row["reference_status"] = "inapplicable_capacity_or_load"
        result[group] = row
    return {"resources": result, "status": "input_based" if result else "missing_exogenous_demand_data"}


def offered_load(arrival_rate: float, mean_service_minutes: float, capacity: int) -> float:
    if not math.isfinite(arrival_rate) or arrival_rate < 0:
        raise ValueError("Arrival rate must be finite and nonnegative")
    if not math.isfinite(mean_service_minutes) or mean_service_minutes <= 0:
        raise ValueError("Mean service time must be positive")
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
        raise ValueError("Capacity must be a positive integer")
    return arrival_rate * mean_service_minutes / capacity


def mm1_priority_reference(arrival_rates: list[float], service_rate: float) -> list[float]:
    """Analytical reference ONLY: Poisson, common exponential service, one server,
    fixed nonpreemptive priorities, steady state. Not a hospital prediction.
    """
    if not math.isfinite(service_rate) or service_rate <= 0:
        raise ValueError("Service rate must be positive")
    loads = [offered_load(rate, 1 / service_rate, 1) for rate in arrival_rates]
    total = sum(loads)
    if total >= 1:
        raise ValueError("M/M/1 reference requires total offered load < 1")
    result, cumulative = [], 0.0
    for load in loads:
        result.append((total / service_rate) / ((1 - cumulative) * (1 - cumulative - load)))
        cumulative += load
    return result
