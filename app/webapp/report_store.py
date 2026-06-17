from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.core.logger import get_latest_run_id
from app.data.loader import load_processed_cases, load_raw_cases
from app.data.transform import transform_case


def report_run_dir(run_id: str) -> Path:
    return settings.REPORTS_DIR / str(run_id).strip()


def resolve_run_id(run_id: Optional[str] = None, *, required_file: str = "live_visual_state.json") -> str:
    normalized = str(run_id or "").strip()
    if normalized:
        return normalized
    return get_latest_run_id(settings.REPORTS_DIR, required_file=required_file)


def available_runs(*, required_file: str = "live_visual_state.json") -> list[str]:
    if not settings.REPORTS_DIR.exists():
        return []
    runs: list[str] = []
    for child in settings.REPORTS_DIR.iterdir():
        if not child.is_dir():
            continue
        if required_file and not (child / required_file).exists():
            continue
        runs.append(child.name)
    return sorted(runs, reverse=True)


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(str(path))
    last_error = None
    for _ in range(5):
        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                time.sleep(0.08)
                continue
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error = exc
            time.sleep(0.08)
    if last_error is not None:
        raise last_error
    return json.loads(path.read_text(encoding="utf-8"))


def load_snapshot(run_id: str) -> dict[str, Any]:
    payload = _load_json(report_run_dir(run_id) / "live_visual_state.json")
    return dict(payload or {})


def load_history(run_id: str) -> list[dict[str, Any]]:
    payload = _load_json(report_run_dir(run_id) / "live_visual_history.json")
    return [dict(item or {}) for item in list(payload or [])]


def load_parallel_summary(run_id: str) -> dict[str, Any]:
    path = report_run_dir(run_id) / "parallel_live_run_summary.json"
    if not path.exists():
        return {}
    payload = _load_json(path)
    return dict(payload or {})


def load_case_detail(run_id: str, case_id: str) -> dict[str, Any]:
    snapshot = load_snapshot(run_id)
    details = dict(snapshot.get("case_details", {}) or {})
    return dict(details.get(str(case_id).strip(), {}) or {})


def load_case_result(run_id: str, case_id: str) -> dict[str, Any]:
    payload = _load_json(settings.RESULTS_DIR / str(run_id).strip() / f"{str(case_id).strip()}_result.json")
    return dict(payload or {})


def load_source_cases() -> list[dict[str, Any]]:
    if settings.USE_PROCESSED_CASES and settings.PROCESSED_DATA_PATH.exists():
        return [dict(item or {}) for item in load_processed_cases(settings.PROCESSED_DATA_PATH)]
    raw_cases = load_raw_cases(settings.RAW_DATA_PATH)
    return [transform_case(case, idx) for idx, case in enumerate(raw_cases)]


def load_source_case(case_id: str) -> dict[str, Any]:
    normalized = str(case_id).strip()
    for case in load_source_cases():
        if str(case.get("case_id", "")).strip() == normalized:
            return dict(case or {})
    raise KeyError(f"Case not found in dataset: {normalized}")
