from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from app.config import settings


def _find_new_live_run(reports_dir: Path, known_dirs: set[str], timeout_sec: float) -> str:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        candidates: list[tuple[float, str]] = []
        for child in reports_dir.iterdir():
            if not child.is_dir():
                continue
            run_id = child.name
            if run_id in known_dirs:
                continue
            live_path = child / "live_visual_state.json"
            if live_path.exists():
                candidates.append((live_path.stat().st_mtime, run_id))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]
        time.sleep(0.4)
    raise TimeoutError("Timed out waiting for a new live_visual_state.json snapshot.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the live multi-patient simulation and attach the Pygame live pixel viewer."
    )
    parser.add_argument("--max-cases", type=int, default=None, help="Override MAX_CASES for the live simulation.")
    parser.add_argument(
        "--wait-timeout-sec",
        type=float,
        default=20.0,
        help="How long to wait for the live snapshot to appear before failing.",
    )
    args = parser.parse_args()

    reports_dir = settings.REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)
    known_dirs = {child.name for child in reports_dir.iterdir() if child.is_dir()}

    env = os.environ.copy()
    if args.max_cases is not None:
        env["MAX_CASES"] = str(args.max_cases)

    sim_cmd = [sys.executable, "-m", "app.scripts.run_live_visual_multi_patient"]
    viewer_cmd_base = [sys.executable, "-m", "app.scripts.run_live_pixel_viewer"]

    print("[LIVE] starting simulation process...")
    simulator = subprocess.Popen(sim_cmd, env=env)

    viewer: subprocess.Popen[str] | None = None
    try:
        run_id = _find_new_live_run(reports_dir, known_dirs, args.wait_timeout_sec)
        print(f"[LIVE] attached to run_id={run_id}")
        viewer_cmd = viewer_cmd_base + [run_id]
        viewer = subprocess.Popen(viewer_cmd, env=env)
        viewer.wait()
    finally:
        if viewer is not None and viewer.poll() is None:
            viewer.terminate()
        if simulator.poll() is None:
            simulator.terminate()
            try:
                simulator.wait(timeout=5)
            except subprocess.TimeoutExpired:
                simulator.kill()


if __name__ == "__main__":
    main()
