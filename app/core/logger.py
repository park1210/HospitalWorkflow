import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from app.config import settings


def create_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def get_run_dir(base_dir: Path, run_id: str) -> Path:
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def get_latest_run_id(base_dir: Path, required_file: Optional[str] = None) -> str:
    if not base_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {base_dir}")

    candidates: list[Path] = []
    for child in base_dir.iterdir():
        if not child.is_dir():
            continue
        if required_file and not (child / required_file).exists():
            continue
        candidates.append(child)

    if not candidates:
        suffix = f" containing {required_file}" if required_file else ""
        raise FileNotFoundError(f"No run directories found in {base_dir}{suffix}")

    return max(candidates, key=lambda path: path.name).name


def save_transcript(case_id: str, transcript: list[dict], run_id: str) -> None:
    run_dir = get_run_dir(settings.TRANSCRIPTS_DIR, run_id)
    path = run_dir / f"{case_id}_transcript.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)


def save_result(result: dict, results_dir: Path, run_id: str) -> None:
    run_dir = get_run_dir(results_dir, run_id)
    path = run_dir / f"{result['case_id']}_result.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def save_reasoning_state(case_id: str, reasoning_state: dict, run_id: str) -> None:
    run_dir = get_run_dir(settings.LOGS_DIR, run_id)
    path = run_dir / f"{case_id}_reasoning_state.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(reasoning_state, f, ensure_ascii=False, indent=2)


def save_trajectory(case_id: str, trajectory: dict, run_id: str) -> None:
    run_dir = get_run_dir(settings.TRAJECTORIES_DIR, run_id)
    path = run_dir / f"{case_id}_trajectory.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trajectory, f, ensure_ascii=False, indent=2)


def save_what_if_report(report: dict, run_id: str) -> None:
    run_dir = get_run_dir(settings.WHAT_IF_DIR, run_id)
    path = run_dir / "what_if_report.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def save_what_if_replay(case_id: str, replay_result: dict, run_id: str) -> None:
    run_dir = get_run_dir(settings.WHAT_IF_DIR / "replays", run_id)
    path = run_dir / f"{case_id}_replay.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(replay_result, f, ensure_ascii=False, indent=2)


def save_what_if_comparison(case_id: str, comparison: dict, run_id: str) -> None:
    run_dir = get_run_dir(settings.WHAT_IF_DIR / "comparisons", run_id)
    path = run_dir / f"{case_id}_comparison.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)


def save_report_json(report: dict, report_name: str, run_id: str) -> None:
    run_dir = get_run_dir(settings.REPORTS_DIR, run_id)
    path = run_dir / f"{report_name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def save_report_markdown(content: str, report_name: str, run_id: str) -> None:
    run_dir = get_run_dir(settings.REPORTS_DIR, run_id)
    path = run_dir / f"{report_name}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
