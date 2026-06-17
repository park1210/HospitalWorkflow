from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler


def run_parallel_scheduler_preview(
    cases: list[dict[str, Any]],
    minute_limit: int = 60,
    run_id: str = "",
) -> dict[str, Any]:
    scheduler = HospitalParallelScheduler()
    state = scheduler.initialize(cases, run_id=run_id)
    snapshots: list[dict[str, Any]] = [state.snapshot()]
    while int(state.current_minute or 0) < int(minute_limit or 0):
        scheduler.step(state)
        snapshots.append(state.snapshot())
        if not state.active_case_ids():
            break
    return {
        "minute_limit": int(minute_limit or 0),
        "final_minute": int(state.current_minute or 0),
        "snapshots": snapshots,
        "final_state": state.snapshot(),
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
