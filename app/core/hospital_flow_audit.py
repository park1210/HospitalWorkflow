"""Exact finite-window identities and progress diagnostics, not clinical proofs."""
from __future__ import annotations

from typing import Any
from app.core.hospital_test_model import test_resource_type

QUEUE_NAMES = ("triage_queue", "bed_queue", "er_queue", "test_queue", "specialty_queue")


def observed_stay(runtime: Any, start: int, end: int) -> int:
    departure = runtime.final_diagnosis_min if runtime.is_completed else end
    # Legacy completed snapshots may not contain a recoverable departure.
    if departure is None:
        return 0
    return max(0, min(end, departure) - max(start, runtime.arrival_time_min))


def conservation_report(state: Any) -> dict[str, Any]:
    stats = state.flow_accounting
    window = stats.get("system")
    if window is None:
        return {"status": "not_measured"}
    start, end = window["start_minute"], state.current_minute
    duration = end - start
    observed = sum(observed_stay(c, start, end) for c in state.cases.values())
    queue_residuals = {}
    count_residuals = {}
    for name, q in stats["queues"].items():
        observed_wait = q["completed_wait"] + sum(end - t for t in q["open"].values())
        queue_residuals[name] = q["area"] - observed_wait
        count_residuals[name] = q["entries"] - q["exits"] - len(q["open"])
    # Partition the supplied finite cohort, including patients arriving after end.
    future = sum(c.workflow_state == "not_arrived" for c in state.cases.values())
    completed = sum(c.is_completed for c in state.cases.values())
    in_system = sum(not c.is_completed and c.workflow_state != "not_arrived" for c in state.cases.values())
    return {
        "status": "measured", "start_minute": start, "end_minute": end,
        "cohort_size": len(state.cases), "not_arrived": future,
        "in_system": in_system, "completed": completed,
        "patient_count_residual": len(state.cases) - future - completed - in_system,
        "system_area_patient_minutes": window["area"],
        "observed_stay_patient_minutes": observed,
        "system_time_residual": window["area"] - observed,
        "mean_number_in_system": window["area"] / duration if duration else None,
        "queue_time_residuals": queue_residuals,
        "queue_count_residuals": count_residuals,
        "interpretation": "exact_window_identity_including_censoring; not_steady_state_or_clinical_validation",
    }


def validate_conservation(state: Any) -> None:
    report = conservation_report(state)
    if report["status"] != "measured":
        return
    residuals = [report["patient_count_residual"], report["system_time_residual"], *report["queue_time_residuals"].values(),
                 *report["queue_count_residuals"].values()]
    if any(value != 0 for value in residuals):
        raise ValueError(f"Flow conservation violated: {report}")
    duration = state.current_minute - state.flow_accounting["start_minute"]
    for record in state.flow_accounting["resources"].values():
        if not 0 <= record["busy_minutes"] <= duration:
            raise ValueError("Resource busy time exceeds observation window")


def progress_report(state: Any) -> dict[str, Any]:
    """Explain current blockers without claiming a general deadlock proof."""
    rows = []
    groups = {"triage_queue": "triage_nurse", "bed_queue": "er_bed", "er_queue": "er_doctor"}
    for name in QUEUE_NAMES:
        for cid in getattr(state, name):
            runtime = state.case(cid)
            group = groups.get(name)
            if name == "test_queue":
                test = next((t for t in runtime.recommended_tests if t not in runtime.completed_tests), "")
                group = test_resource_type(test, runtime.case_data)
            if name == "specialty_queue":
                resources = [r for r in state.resources.specialists
                             if state.resources.specialist_department(r) == runtime.target_department]
                group = "specialist:" + runtime.target_department
            else:
                resources = state.resources.resources_by_type(group)
            available = any(r.is_available(state.current_minute) for r in resources)
            reason = "no_configured_resource" if not resources else "eligible_next_dispatch" if available else "resource_occupied"
            rows.append({"case_id": cid, "queue": name, "required_resource": group,
                         "reason": reason, "cumulative_queue_wait_min": runtime.queue_wait_minutes})
    future_event = bool(state.scheduled_events or state.arrival_queue)
    runnable = any(row["reason"] == "eligible_next_dispatch" for row in rows)
    releasable = any(r.status != "idle" and r.resource_type != "er_bed"
                     for r in state.resources.all_resources())
    stalled = bool(state.active_case_ids()) and not (future_event or runnable or releasable)
    return {"currently_stalled": stalled, "waiting": rows,
            "interpretation": "current_fixed_resources_and_existing_events; no_universal_liveness_claim"}
