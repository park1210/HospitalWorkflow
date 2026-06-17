from __future__ import annotations

import argparse

from app.config import settings
from app.core.hospital_parallel_runner import save_parallel_scheduler_preview
from app.scripts.run_live_visual_multi_patient import load_cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the experimental parallel ER scheduler preview.")
    parser.add_argument("--max-cases", type=int, default=3, help="How many cases to load into the parallel preview.")
    parser.add_argument("--minutes", type=int, default=60, help="How many simulated minutes to run.")
    args = parser.parse_args()

    cases = load_cases()
    if not cases:
        print("[ERROR] No cases found.")
        return

    max_cases = max(1, int(args.max_cases or 1))
    selected_cases = cases[:max_cases]
    output_path = settings.REPORTS_DIR / "parallel_scheduler_preview.json"
    saved = save_parallel_scheduler_preview(selected_cases, minute_limit=int(args.minutes or 60), output_path=output_path)
    print(f"[DONE] parallel preview saved to {saved}")


if __name__ == "__main__":
    main()
