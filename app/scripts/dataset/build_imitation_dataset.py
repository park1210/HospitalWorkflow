from __future__ import annotations

import os

from app.core.imitation_dataset import build_imitation_rows
from app.core.imitation_dataset import load_step_rows
from app.core.imitation_dataset import save_imitation_dataset


def main() -> None:
    source_dataset = os.getenv("SOURCE_TRAJECTORY_DATASET", "trajectory_steps")
    output_dataset = os.getenv("IMITATION_DATASET_NAME", f"{source_dataset}_imitation")
    require_department_correct = os.getenv("IMITATION_REQUIRE_DEPARTMENT_CORRECT", "true").lower() == "true"

    min_episode_reward_raw = os.getenv("IMITATION_MIN_EPISODE_REWARD", "").strip()
    min_episode_reward = float(min_episode_reward_raw) if min_episode_reward_raw else None

    step_rows = load_step_rows(source_dataset)
    if not step_rows:
        print("[ERROR] No source step rows found.")
        return

    rows, summary = build_imitation_rows(
        step_rows,
        require_department_correct=require_department_correct,
        min_episode_reward=min_episode_reward,
    )
    if not rows:
        print("[ERROR] No imitation rows were selected.")
        return

    jsonl_path, summary_path = save_imitation_dataset(output_dataset, rows, summary)
    print(f"[DONE] imitation_rows={len(rows)}")
    print(f"[DONE] jsonl={jsonl_path}")
    print(f"[DONE] summary={summary_path}")


if __name__ == "__main__":
    main()
