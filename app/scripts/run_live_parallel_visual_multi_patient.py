from __future__ import annotations

import argparse
from pathlib import Path

from app.config import settings
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.core.background_stepper import BackgroundStepper
from app.core.clinical_preflight import clinical_preflight
from app.core.postdiagnostic_followup import followup_report
from app.core.hospital_flow import load_flow_config, flow_report
from app.core.hospital_evaluation import evaluation_report
from app.core.live_parallel_visual_runtime import LiveParallelVisualRuntimeWriter
from app.core.logger import create_run_id, save_report_json
from app.scripts.build_live_web_viewer import build_live_web_viewer
from app.scripts.run_live_visual_multi_patient import load_cases_with_context


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the parallel temporal ER scheduler and export the live web-viewer snapshot stream."
    )
    parser.add_argument("--max-cases", type=int, default=None, help="Override MAX_CASES for this live run.")
    parser.add_argument("--preflight-only", action="store_true", help="Write missing-input inventory without model calls or simulation.")
    parser.add_argument("--followup-minutes", type=int, default=0,
                        help="Export separate postdiagnostic physiology observation, without additional LLM calls (0 disables).")
    parser.add_argument("--clinical-mode", choices=["demo", "llm_required"], default=None,
                        help="llm_required runs patient/ER/specialty model roles; errors stop the run.")
    parser.add_argument("--flow-config", type=Path, default=None, help="Chapter 6 capacity, duration, arrival and priority configuration.")
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
    parser.add_argument(
        "--scenario-file",
        type=str,
        default="",
        help="Optional fixed demo scenario JSON file under data/raw.",
    )
    parser.add_argument(
        "--fixed-demo",
        action="store_true",
        help="Run the fixed ER crowding demo scenario from data/raw/er_multi_patient_simulation_scenario.json.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.followup_minutes < 0:
        raise ValueError("followup-minutes must be nonnegative")
    run_id = create_run_id()
    scenario_path: Path | None = None
    if str(args.scenario_file or "").strip():
        scenario_path = Path(str(args.scenario_file).strip())
    elif bool(args.fixed_demo):
        scenario_path = settings.PROJECT_ROOT / "data" / "raw" / "er_multi_patient_simulation_scenario.json"

    cases, demo_context = load_cases_with_context(source_path=scenario_path)
    if not cases:
        print("[ERROR] No cases found.")
        return

    if args.max_cases is not None:
        max_cases = int(args.max_cases)
    elif bool(args.fixed_demo) or scenario_path is not None:
        max_cases = len(cases)
    else:
        max_cases = int(settings.MAX_CASES)
    if max_cases > 0:
        cases = cases[:max_cases]
    preflight = clinical_preflight(cases)
    save_report_json(preflight, "clinical_preflight", run_id)
    print(f"[PREFLIGHT] {preflight['gap_count']} input gaps; report run_id={run_id}")
    if args.preflight_only:
        return

    minute_limit = int(args.minute_limit if args.minute_limit is not None else max(60, len(cases) * 30))
    min_demo_minutes = max(0, int(args.min_demo_minutes or 0))
    if minute_limit <= 0:
        raise ValueError("minute-limit must be positive")
    scheduler_horizon = minute_limit
    grace_window_minutes = 0
    grace_horizon = scheduler_horizon + grace_window_minutes
    runtime_demo_context = dict(demo_context or {})
    runtime_demo_context.update(
        {
            "display_minute_limit": minute_limit,
            "scheduler_horizon_minute": scheduler_horizon,
            "grace_window_minutes": grace_window_minutes,
            "grace_completion_enabled": bool(grace_window_minutes),
        }
    )

    config = load_flow_config(args.flow_config)
    if args.clinical_mode:
        config["clinical"]["mode"] = args.clinical_mode
    print(f"[CLINICAL-MODE] {config['clinical']['mode']}")
    if config["simulation"]["resource_mode"] != "constrained":
        raise ValueError("Cohort-unconstrained resources require the headless experiment runner; no physical scene layout exists")
    scheduler = HospitalParallelScheduler(config)
    state = scheduler.initialize(cases, run_id=run_id)
    scheduler_snapshots = [state.snapshot()]
    runtime = LiveParallelVisualRuntimeWriter(
        run_id=run_id,
        queue_policy="parallel_hospital_temporal_scheduler",
        demo_context=runtime_demo_context,
    )
    runtime.initialize(state)
    with BackgroundStepper(scheduler) as stepper:
        while int(state.current_minute or 0) < grace_horizon:
            try:
                state = stepper.step(state, runtime.on_inference_wait)
            except Exception as exc:
                failed_state = getattr(exc, "failed_state", state)
                save_report_json({"status": "failed", "error_type": type(exc).__name__,
                                  "final_state": failed_state.snapshot(), "flow_config": state.flow_config},
                                 "hospital_failed_run", run_id)
                runtime.on_inference_wait({"error_type": type(exc).__name__}, failed=True)
                raise
            scheduler_snapshots.append(state.snapshot())
            runtime.on_step(state)
            if not state.active_case_ids() and int(state.current_minute or 0) >= min_demo_minutes:
                break

    runtime.finalize(state)
    model_report = flow_report(state)
    save_report_json(model_report, "hospital_flow_metrics", run_id)
    clinical_report = evaluation_report(state)
    save_report_json(clinical_report, "hospital_evaluation_metrics", run_id)
    for gap in model_report["data_gaps"]:
        print(f"[DATA-GAP] {gap}")
    summary = {
        "run_id": run_id,
        "queue_policy": "parallel_hospital_temporal_scheduler",
        "minute_limit": minute_limit,
        "display_minute_limit": minute_limit,
        "min_demo_minutes": min_demo_minutes,
        "scheduler_horizon_minute": scheduler_horizon,
        "grace_window_minutes": grace_window_minutes,
        "final_minute": int(state.current_minute or 0),
        "case_count": len(cases),
        "completed_count": len([case for case in state.cases.values() if bool(case.is_completed)]),
        "demo_context": runtime_demo_context,
        "source_cases": [runtime.case_data for runtime in state.cases.values()],
        "flow_config": state.flow_config,
        "flow_metrics": model_report,
        "evaluation_metrics": clinical_report,
        "termination": model_report["termination"],
        "snapshots": scheduler_snapshots,
        "final_state": state.snapshot(),
    }
    save_report_json(summary, "parallel_live_run_summary", run_id)
    if args.followup_minutes:
        save_report_json(followup_report(state.cases.values(), args.followup_minutes),
                         "postdiagnostic_followup", run_id)
    web_viewer_path = build_live_web_viewer(run_id)
    print(
        f"[LIVE-PARALLEL] run_id={run_id} | "
        f"snapshot={settings.REPORTS_DIR / run_id / 'live_visual_state.json'} | "
        f"history={settings.REPORTS_DIR / run_id / 'live_visual_history.json'} | "
        f"web={web_viewer_path}"
    )


if __name__ == "__main__":
    main()
