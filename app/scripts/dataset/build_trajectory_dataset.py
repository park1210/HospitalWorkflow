from __future__ import annotations

import os

from app.core.trajectory_dataset import build_step_dataset
from app.core.trajectory_dataset import save_step_dataset


def main() -> None:
    raw_run_ids = os.getenv("TRAJECTORY_RUN_IDS", "").strip()
    run_ids = [item.strip() for item in raw_run_ids.split(",") if item.strip()] if raw_run_ids else None
    dataset_name = os.getenv("TRAJECTORY_DATASET_NAME", "trajectory_steps")

    rows, summary = build_step_dataset(run_ids)
    if not rows:
        print("[ERROR] No trajectory rows were found. Run the simulator first.")
        return

    jsonl_path, summary_path = save_step_dataset(dataset_name, rows, summary)
    print(f"[DONE] dataset_rows={len(rows)}")
    print(f"[DONE] jsonl={jsonl_path}")
    print(f"[DONE] summary={summary_path}")


if __name__ == "__main__":
    main()
