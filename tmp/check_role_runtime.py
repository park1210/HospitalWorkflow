import json
from pathlib import Path
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler

source = {
    "case_id": "synthetic_llm_smoke",
    "patient_visible_info": {"chief_complaint": "Intermittent mild discomfort",
        "history": "Discomfort started today. No further history is available."},
    "doctor_visible_info": {"chief_complaint": "Intermittent mild discomfort", "initial_vitals": {"spo2": 98}},
    "available_tests": [], "temporal_profile": {"arrival_time_min": 0}}
scheduler = HospitalParallelScheduler({"clinical": {"mode": "llm_required", "max_decisions": 3, "max_questions": 1}})
state = scheduler.initialize([source])
try:
    scheduler.run_until(state, 60)
    status = "completed" if not state.active_case_ids() else "incomplete"
except Exception as exc:
    status = type(exc).__name__
Path("tmp/llm_actual_smoke_schema.json").write_text(json.dumps({"status": status, "state": state.snapshot()},
    ensure_ascii=False, indent=2), encoding="utf-8")
runtime = state.case(source["case_id"])
print(json.dumps({"status": status, "calls": runtime.llm_audit, "questions": runtime.question_history,
                  "diagnosis": runtime.assessment_summary, "alerts": runtime.alerts}, ensure_ascii=False))
