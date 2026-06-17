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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start the parallel live simulation and web server together for a browser-based real-time session."
    )
    parser.add_argument("--max-cases", type=int, default=None, help="Override MAX_CASES for the live simulation.")
    parser.add_argument("--minute-limit", type=int, default=None, help="Optional hard stop for the scheduler minute horizon.")
    parser.add_argument(
        "--min-demo-minutes",
        type=int,
        default=15,
        help="Keep advancing the live timeline until at least this minute, even if cases finish earlier.",
    )
    parser.add_argument(
        "--step-delay-sec",
        type=float,
        default=0.55,
        help="Delay between live snapshot updates so the browser shows the simulation more naturally.",
    )
    parser.add_argument("--port", type=int, default=8010, help="Port for the FastAPI web server.")
    parser.add_argument(
        "--wait-timeout-sec",
        type=float,
        default=20.0,
        help="How long to wait for the first live snapshot before failing.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    reports_dir = settings.REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)
    known_dirs = {child.name for child in reports_dir.iterdir() if child.is_dir()}

    env = os.environ.copy()
    env["LIVE_VIS_STEP_DELAY_SEC"] = str(max(0.0, float(args.step_delay_sec or 0.0)))

    sim_cmd = [sys.executable, "-m", "app.scripts.run_live_parallel_visual_multi_patient"]
    if args.max_cases is not None:
        sim_cmd.extend(["--max-cases", str(args.max_cases)])
    if args.minute_limit is not None:
        sim_cmd.extend(["--minute-limit", str(args.minute_limit)])
    sim_cmd.extend(["--min-demo-minutes", str(max(0, int(args.min_demo_minutes or 0)))])

    web_cmd = [sys.executable, "-m", "app.scripts.run_live_web_server", str(int(args.port or 8010))]

    print("[LIVE-WEB] starting parallel simulation process...")
    simulator = subprocess.Popen(sim_cmd, env=env)
    web_server: subprocess.Popen[str] | None = None
    try:
        run_id = _find_new_live_run(reports_dir, known_dirs, float(args.wait_timeout_sec or 20.0))
        print(f"[LIVE-WEB] attached to run_id={run_id}")
        web_server = subprocess.Popen(web_cmd, env=env)
        print(f"[LIVE-WEB] open http://127.0.0.1:{int(args.port or 8010)}/?run_id={run_id}")
        simulator.wait()
        if web_server.poll() is None:
            web_server.wait()
    finally:
        if web_server is not None and web_server.poll() is None:
            web_server.terminate()
            try:
                web_server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                web_server.kill()
        if simulator.poll() is None:
            simulator.terminate()
            try:
                simulator.wait(timeout=5)
            except subprocess.TimeoutExpired:
                simulator.kill()


if __name__ == "__main__":
    main()
