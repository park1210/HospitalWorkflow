import json
from pathlib import Path
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.background_stepper import BackgroundStepper

source = {"case_id": "grounded-smoke", "patient_visible_info": {
    "chief_complaint": "Intermittent mild discomfort", "history": "Discomfort started today."},
    "doctor_visible_info": {"chief_complaint": "Intermittent mild discomfort", "initial_vitals": {"spo2": 98}},
    "available_tests": [], "temporal_profile": {"arrival_time_min": 0}}
scheduler = HospitalParallelScheduler({"clinical": {"mode": "llm_required", "max_decisions": 3, "max_questions": 1}})
state = scheduler.initialize([source])
pulses = []
try:
    with BackgroundStepper(scheduler, heartbeat_seconds=0.25) as worker:
        while state.current_minute < 60 and state.active_case_ids():
            state = worker.step(state, pulses.append)
    status = "completed" if not state.active_case_ids() else "incomplete"
except Exception as exc:
    state = getattr(exc, "failed_state", state)
    status = type(exc).__name__
result = {"status": status, "heartbeats": pulses, "state": state.snapshot()}
Path("tmp/grounded_background_smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"status": status, "heartbeat_count": len(pulses), "calls": state.case(source["case_id"]).llm_audit,
                  "questions": state.case(source["case_id"]).question_history}, ensure_ascii=False))
