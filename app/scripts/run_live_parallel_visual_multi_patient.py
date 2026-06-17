from __future__ import annotations

import argparse

from app.config import settings
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.live_parallel_visual_runtime import LiveParallelVisualRuntimeWriter
from app.core.logger import create_run_id, save_report_json
from app.scripts.build_live_web_viewer import build_live_web_viewer
from app.scripts.run_live_visual_multi_patient import load_cases


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the parallel temporal ER scheduler and export the live web-viewer snapshot stream."
    )
    parser.add_argument("--max-cases", type=int, default=None, help="Override MAX_CASES for this live run.")
    parser.add_argument(
        "--minute-limit",
        type=int,
        default=None,
        help="Optional hard stop for the scheduler minute horizon. Defaults to max(60, case_count * 30).",
    )
    parser.add_argument(
        "--min-demo-minutes",
        type=int,
        default=15,
        help="Keep advancing the live timeline until at least this minute, even if all cases complete earlier.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_id = create_run_id()
    cases = load_cases()
    if not cases:
        print("[ERROR] No cases found.")
        return

    max_cases = int(args.max_cases if args.max_cases is not None else settings.MAX_CASES)
    if max_cases > 0:
        cases = cases[:max_cases]

    scheduler = HospitalParallelScheduler()
    state = scheduler.initialize(cases, run_id=run_id)
    scheduler_snapshots = [state.snapshot()]
    runtime = LiveParallelVisualRuntimeWriter(
        run_id=run_id,
        queue_policy="parallel_hospital_temporal_scheduler",
    )
    runtime.initialize(state)

    minute_limit = int(args.minute_limit if args.minute_limit is not None else max(60, len(cases) * 30))
    min_demo_minutes = max(0, int(args.min_demo_minutes or 0))
    while int(state.current_minute or 0) < int(minute_limit or 0):
        scheduler.step(state)
        scheduler_snapshots.append(state.snapshot())
        runtime.on_step(state)
        if not state.active_case_ids() and int(state.current_minute or 0) >= min_demo_minutes:
            break

    runtime.finalize(state)
    summary = {
        "run_id": run_id,
        "queue_policy": "parallel_hospital_temporal_scheduler",
        "minute_limit": minute_limit,
        "min_demo_minutes": min_demo_minutes,
        "final_minute": int(state.current_minute or 0),
        "case_count": len(cases),
        "completed_count": len([case for case in state.cases.values() if bool(case.is_completed)]),
        "snapshots": scheduler_snapshots,
        "final_state": state.snapshot(),
    }
    save_report_json(summary, "parallel_live_run_summary", run_id)
    web_viewer_path = build_live_web_viewer(run_id)
    print(
        f"[LIVE-PARALLEL] run_id={run_id} | "
        f"snapshot={settings.REPORTS_DIR / run_id / 'live_visual_state.json'} | "
        f"history={settings.REPORTS_DIR / run_id / 'live_visual_history.json'} | "
        f"web={web_viewer_path}"
    )


if __name__ == "__main__":
    main()
