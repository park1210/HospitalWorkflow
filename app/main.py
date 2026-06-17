from app.config import settings
from app.core.logger import create_run_id, save_result, save_what_if_report
from app.core.what_if_analysis import analyze_what_if_results
from app.core.simulator import run_single_case
from app.data.loader import load_processed_cases, load_raw_cases
from app.data.transform import transform_case


def safe_console_text(text: str) -> str:
    value = str(text)
    try:
        value.encode("cp949")
        return value
    except UnicodeEncodeError:
        return value.encode("ascii", errors="replace").decode("ascii")


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
    results: list[dict] = []

    if not cases:
        print("[ERROR] No cases found. Add raw data or processed cases before running the simulator.")
        return

    if settings.MAX_CASES > 0:
        cases = cases[: settings.MAX_CASES]

    for case in cases:
        result = run_single_case(case, run_id, settings.MAX_TURNS)
        results.append(result)
        save_result(result, settings.RESULTS_DIR, run_id)
        print(
            f"[DONE] case_id={safe_console_text(result['case_id'])} | "
            f"pred={safe_console_text(result['predicted_diagnosis'])} | "
            f"gold={safe_console_text(result['ground_truth'])} | "
            f"dept={safe_console_text(result['predicted_department'])} | "
            f"service={safe_console_text(result.get('diagnostic_service', ''))} | "
            f"diag_correct={result['diagnosis_correct']}"
        )

    if settings.USE_WHAT_IF_SHADOW and results:
        report = analyze_what_if_results(results)
        report["run_id"] = run_id
        save_what_if_report(report, run_id)
        print(
            f"[WHAT-IF] run={run_id} | shadow_events={report['total_shadow_events']} | "
            f"disagreements={report['total_shadow_disagreements']}"
        )


if __name__ == "__main__":
    main()
