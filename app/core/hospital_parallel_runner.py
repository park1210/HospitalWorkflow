from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.hospital_flow import flow_report
from app.core.hospital_evaluation import evaluation_report


def run_parallel_scheduler_preview(
    cases: list[dict[str, Any]],
    minute_limit: int = 60,
    run_id: str = "",
    config: dict[str, Any] | None = None,
    retain_snapshots: bool = True,
) -> dict[str, Any]:
    if isinstance(minute_limit, bool) or not isinstance(minute_limit, int) or minute_limit <= 0:
        raise ValueError("minute_limit must be a positive integer")
    scheduler = HospitalParallelScheduler(config)
    state = scheduler.initialize(cases, run_id=run_id)
    snapshots: list[dict[str, Any]] = [state.snapshot()] if retain_snapshots else []
    while int(state.current_minute or 0) < int(minute_limit or 0):
        scheduler.step(state)
        if retain_snapshots:
            snapshots.append(state.snapshot())
        if not state.active_case_ids():
            break
    return {
        "minute_limit": int(minute_limit or 0),
        "final_minute": int(state.current_minute or 0),
        "snapshots": snapshots,
        "final_state": state.snapshot(),
        "flow_metrics": flow_report(state),
        "evaluation_metrics": evaluation_report(state),
        "source_cases": [c.case_data for c in state.cases.values()],
        "flow_config": state.flow_config,
        "policy_id": "parallel_llm_policy" if state.flow_config["clinical"]["mode"] == "llm_required" else "parallel_demo_policy",
    }


def save_parallel_scheduler_preview(
    cases: list[dict[str, Any]],
    minute_limit: int = 60,
    output_path: str | Path | None = None,
    run_id: str = "",
) -> Path:
    preview = run_parallel_scheduler_preview(cases, minute_limit=minute_limit, run_id=run_id)
    destination = Path(output_path) if output_path else (settings.PROJECT_ROOT / "outputs" / "parallel_scheduler_preview.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination
