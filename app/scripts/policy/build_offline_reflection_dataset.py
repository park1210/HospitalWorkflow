from __future__ import annotations

import os

from app.core.offline_reflection_dataset import (
    OfflineFalseCaseReflectionRunner,
    build_false_case_rows,
    save_reflection_dataset,
    summarize_reflections,
)


def main() -> None:
    raw_run_ids = os.getenv("OFFLINE_REFLECTION_RUN_IDS", "").strip()
    run_ids = [item.strip() for item in raw_run_ids.split(",") if item.strip()] if raw_run_ids else None
    dataset_name = os.getenv("OFFLINE_REFLECTION_DATASET_NAME", "offline_false_case_reflections")

    rows = build_false_case_rows(run_ids)
    if not rows:
        print("[ERROR] No false cases were found. Run the simulator first or choose a different run.")
        return

    runner = OfflineFalseCaseReflectionRunner()
    reflected_rows = [runner.reflect_case(row) for row in rows]
    summary = summarize_reflections(reflected_rows)
    jsonl_path, summary_path = save_reflection_dataset(dataset_name, reflected_rows, summary)

    print(f"[DONE] reflection_rows={len(reflected_rows)}")
    if run_ids:
        print(f"[DONE] run_ids={','.join(run_ids)}")
    else:
        print("[DONE] run_ids=latest_only")
    print(f"[DONE] jsonl={jsonl_path}")
    print(f"[DONE] summary={summary_path}")


if __name__ == "__main__":
    main()
