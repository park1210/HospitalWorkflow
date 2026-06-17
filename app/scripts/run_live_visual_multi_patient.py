from __future__ import annotations

from app.config import settings
from app.core.live_visual_runtime import LiveVisualRuntimeWriter
from app.core.logger import create_run_id, save_report_json, save_report_markdown, save_result
from app.core.multi_patient_reporting import build_multi_patient_report, render_multi_patient_report_markdown
from app.core.multi_patient_simulator import MultiPatientERSimulator
from app.data.loader import load_processed_cases, load_raw_cases
from app.data.transform import transform_case


def load_cases() -> list[dict]:
    if settings.USE_PROCESSED_CASES and settings.PROCESSED_DATA_PATH.exists():
        return load_processed_cases(settings.PROCESSED_DATA_PATH)

    if settings.RAW_DATA_PATH.exists():
        raw_cases = load_raw_cases(settings.RAW_DATA_PATH)
        return [transform_case(case, idx) for idx, case in enumerate(raw_cases)]

    return []


def main() -> None:
    run_id = create_run_id()
    cases = load_cases()
    if not cases:
        print("[ERROR] No cases found.")
        return

    if settings.MAX_CASES > 0:
        cases = cases[: settings.MAX_CASES]

    simulator = MultiPatientERSimulator()
    runtime = LiveVisualRuntimeWriter(
        run_id=run_id,
        queue_policy="time_aware_triage_priority_with_wait_based_reprioritization",
    )
    batch_result = simulator.run_batch(
        cases,
        run_id,
        settings.MAX_TURNS,
        live_runtime=runtime,
    )
    for result in batch_result["results"]:
        save_result(result, settings.RESULTS_DIR, run_id)
        queue_metrics = dict(result.get("queue_metrics", {}) or {})
        print(
            f"[DONE] case_id={result['case_id']} | "
            f"queue_pos={queue_metrics.get('queue_position')} | "
            f"wait={queue_metrics.get('queue_wait_time_min')}m | "
            f"pred={result['predicted_diagnosis']} | "
            f"diag_correct={result['diagnosis_correct']}"
        )

    report = build_multi_patient_report(batch_result)
    save_report_json(report, "multi_patient_run_summary", run_id)
    save_report_markdown(
        render_multi_patient_report_markdown(report),
        "multi_patient_run_summary",
        run_id,
    )
    print(
        f"[LIVE-VIS] run_id={run_id} | "
        f"snapshot={settings.REPORTS_DIR / run_id / 'live_visual_state.json'} | "
        f"history={settings.REPORTS_DIR / run_id / 'live_visual_history.json'}"
    )


if __name__ == "__main__":
    main()
