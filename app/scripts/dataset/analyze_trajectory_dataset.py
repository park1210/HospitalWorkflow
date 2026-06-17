from __future__ import annotations

import os

from app.core.trajectory_analysis import analyze_dataset_rows
from app.core.trajectory_analysis import load_dataset_rows
from app.core.trajectory_analysis import save_analysis


def main() -> None:
    dataset_name = os.getenv("TRAJECTORY_DATASET_NAME", "trajectory_steps")
    rows = load_dataset_rows(dataset_name)
    if not rows:
        print("[ERROR] No dataset rows found.")
        return

    analysis = analyze_dataset_rows(rows)
    path = save_analysis(dataset_name, analysis)
    print(f"[DONE] analysis={path}")
    print(f"[DONE] cases={analysis['case_count']} rows={analysis['row_count']}")


if __name__ == "__main__":
    main()
