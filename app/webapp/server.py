from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.core.logger import create_run_id, save_what_if_comparison, save_what_if_replay
from app.core.parallel_what_if_replay import replay_parallel_case_from_snapshot
from app.core.what_if_replay import get_snapshot_by_id, replay_case_from_snapshot
from app.ui.web_viewer.builder import build_live_web_viewer_html
from app.webapp.report_store import (
    available_runs,
    load_case_detail,
    load_case_result,
    load_history,
    load_parallel_summary,
    load_snapshot,
    load_source_case,
    resolve_run_id,
)

_LIVE_SESSION_LOCK = threading.Lock()
_LIVE_SESSION_STATE: dict[str, Any] = {
    "process": None,
    "run_id": "",
    "port": None,
    "started_at": 0.0,
    "command": [],
}


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


def _get_live_process() -> Optional[subprocess.Popen[Any]]:
    process = _LIVE_SESSION_STATE.get("process")
    return process if isinstance(process, subprocess.Popen) else None


def _cleanup_finished_live_process() -> None:
    process = _get_live_process()
    if process is None:
        return
    if process.poll() is None:
        return
    _LIVE_SESSION_STATE.update(
        {
            "process": None,
            "run_id": "",
            "started_at": 0.0,
            "command": [],
        }
    )


def _live_status_payload_unlocked(*, port_override: Optional[int] = None) -> dict[str, Any]:
    _cleanup_finished_live_process()
    process = _get_live_process()
    run_id = str(_LIVE_SESSION_STATE.get("run_id", "")).strip()
    port = int(port_override or _LIVE_SESSION_STATE.get("port") or 8010)
    snapshot_exists = bool(run_id and (settings.REPORTS_DIR / run_id / "live_visual_state.json").exists())
    return {
        "running": bool(process and process.poll() is None),
        "pid": process.pid if process is not None and process.poll() is None else None,
        "run_id": run_id,
        "viewer_url": f"http://127.0.0.1:{port}/?run_id={run_id}" if run_id else "",
        "snapshot_ready": snapshot_exists,
        "started_at": _LIVE_SESSION_STATE.get("started_at") or 0.0,
        "command": list(_LIVE_SESSION_STATE.get("command", []) or []),
    }


def _live_status_payload(*, port_override: Optional[int] = None) -> dict[str, Any]:
    with _LIVE_SESSION_LOCK:
        return _live_status_payload_unlocked(port_override=port_override)


def _normalize_department_label(value: str) -> str:
    normalized = str(value).strip().replace("_", " ")
    return normalized.title() if normalized else "Specialist"


def _build_parallel_branch_transcript(
    *,
    case_id: str,
    questions: list[dict[str, Any]],
    consult_history: list[dict[str, Any]],
    replay_steps: list[dict[str, Any]],
    selected_action: dict[str, Any],
) -> list[dict[str, Any]]:
    patient_entity_id = f"patient_{str(case_id).strip()}"
    transcript: list[dict[str, Any]] = []

    for qa in questions[-4:]:
        question = str(dict(qa or {}).get("question", "")).strip()
        answer = str(dict(qa or {}).get("answer", "")).strip()
        if question:
            transcript.append(
                {
                    "speaker": "ER",
                    "text": question,
                    "speaker_entity_id": "doctor_er_0",
                    "listener_entity_id": patient_entity_id,
                }
            )
        if answer:
            transcript.append(
                {
                    "speaker": "Patient",
                    "text": answer,
                    "speaker_entity_id": patient_entity_id,
                    "listener_entity_id": "doctor_er_0",
                }
            )

    for consult in consult_history[-3:]:
        consult_dict = dict(consult or {})
        department_label = _normalize_department_label(str(consult_dict.get("department", "")).strip())
        opinion = str(consult_dict.get("opinion", "")).strip()
        if opinion:
            transcript.append(
                {
                    "speaker": department_label,
                    "text": opinion,
                    "speaker_entity_id": str(consult_dict.get("actor", "")).strip() or "specialty_consultant",
                    "listener_entity_id": patient_entity_id,
                }
            )

    if transcript:
        return transcript[-10:]

    action_type = str(selected_action.get("type", "")).strip()
    target = str(selected_action.get("target", "")).strip()
    for step in replay_steps[-4:]:
        step_dict = dict(step or {})
        action = str(step_dict.get("action", "")).strip()
        outcome = dict(step_dict.get("outcome", {}) or {})
        if action == "request_specialty":
            department_label = _normalize_department_label(target or str(outcome.get("department", "")).strip())
            transcript.append(
                {
                    "speaker": "ER",
                    "text": f"Calling {department_label} for bedside review.",
                    "speaker_entity_id": "doctor_er_0",
                    "listener_entity_id": f"specialty_{str(target or outcome.get('department', '')).strip()}",
                }
            )
            continue
        if action == "specialty_consult":
            department_label = _normalize_department_label(target or str(outcome.get("department", "")).strip())
            consult_note = str(outcome.get("consult_note", "")).strip()
            transcript.append(
                {
                    "speaker": department_label,
                    "text": consult_note or "I reviewed the bedside findings and narrowed the leading diagnosis.",
                    "speaker_entity_id": f"specialty_{str(target or outcome.get('department', '')).strip()}",
                    "listener_entity_id": patient_entity_id,
                }
            )
            continue
        if action == "request_test":
            requested_test = str(step_dict.get("target", "")).strip() or target
            transcript.append(
                {
                    "speaker": "ER",
                    "text": f"We need {requested_test} before finalizing this case.",
                    "speaker_entity_id": "doctor_er_0",
                    "listener_entity_id": patient_entity_id,
                }
            )
            continue
        if action == "await_results":
            delayed_test = str(step_dict.get("target", "")).strip() or target
            transcript.append(
                {
                    "speaker": "ER",
                    "text": f"We already have a strong clue, but I want {delayed_test} before escalating.",
                    "speaker_entity_id": "doctor_er_0",
                    "listener_entity_id": patient_entity_id,
                }
            )
            continue
        if action_type == "diagnose":
            diagnosis = str(outcome.get("diagnosis", "")).strip() or target
            if diagnosis:
                transcript.append(
                    {
                        "speaker": "ER",
                        "text": f"The current evidence is sufficient for {diagnosis}.",
                        "speaker_entity_id": "doctor_er_0",
                        "listener_entity_id": patient_entity_id,
                    }
                )

    return transcript[-10:]


def _normalize_parallel_what_if_payload(
    *,
    run_id: str,
    case_id: str,
    replay_run_id: str,
    replay_payload: dict[str, Any],
) -> dict[str, Any]:
    comparison = dict(replay_payload.get("comparison", {}) or {})
    replay_result = dict(replay_payload.get("replay_result", {}) or {})
    snapshot = dict(replay_payload.get("snapshot", {}) or {})
    scheduler_context = dict(snapshot.get("scheduler_context", {}) or {})
    case_after = dict(scheduler_context.get("case_after", {}) or {})
    timeline = dict(comparison.get("timeline", {}) or {})
    branch_events = [dict(item or {}) for item in list(timeline.get("branch_events", []) or []) if dict(item or {})]
    replay_steps = [dict(item or {}) for item in list(timeline.get("replay_steps", []) or []) if dict(item or {})]
    selected_action = dict(replay_payload.get("selected_action", {}) or {})
    questions = [dict(item or {}) for item in list(replay_result.get("questions", []) or []) if dict(item or {})]
    tests = [str(item).strip() for item in list(replay_result.get("tests", []) or []) if str(item).strip()]
    findings = [str(item).strip() for item in list(replay_result.get("objective_findings", []) or []) if str(item).strip()]
    test_results = [dict(item or {}) for item in list(case_after.get("test_results", []) or []) if dict(item or {})]
    consult_history = [dict(item or {}) for item in list(case_after.get("consult_history", []) or []) if dict(item or {})]
    transcript = _build_parallel_branch_transcript(
        case_id=case_id,
        questions=questions,
        consult_history=consult_history,
        replay_steps=replay_steps,
        selected_action=selected_action,
    )

    return {
        "run_id": run_id,
        "case_id": case_id,
        "status": str(replay_payload.get("status", "completed")).strip() or "completed",
        "replay_run_id": replay_run_id,
        "viewer_run_id": replay_run_id,
        "viewer_url": f"/?run_id={replay_run_id}",
        "snapshot_id": str(replay_payload.get("snapshot_id", "")).strip(),
        "selected_action": selected_action,
        "comparison": comparison,
        "replay": {
            "predicted_diagnosis": str(replay_result.get("predicted_diagnosis", "")).strip(),
            "predicted_department": str(replay_result.get("predicted_department", "")).strip(),
            "diagnosis_correct": bool(replay_result.get("diagnosis_correct", False)),
            "department_correct": bool(replay_result.get("department_correct", False)),
            "episode_reward": float(replay_result.get("episode_reward", 0.0) or 0.0),
        },
        "branch_detail": {
            "zone": str(replay_result.get("zone", "")).strip(),
            "questions": questions[-6:],
            "tests": tests[-6:],
            "test_results": test_results[-6:],
            "objective_findings": findings[-8:],
            "event_log": (branch_events or replay_steps)[-10:],
            "transcript": transcript,
            "consult_history": consult_history[-4:],
            "predicted_diagnosis": str(replay_result.get("predicted_diagnosis", "")).strip(),
            "predicted_department": str(replay_result.get("predicted_department", "")).strip(),
        },
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="Clinical AgentSim Live Web Viewer",
        version="0.1.0",
        description="Dynamic browser UI for the temporal ER hospital simulation.",
    )
    asset_root = Path(__file__).resolve().parents[1] / "assets" / "pixel_re"
    if asset_root.exists():
        app.mount("/pixel-re-assets", StaticFiles(directory=str(asset_root)), name="pixel-re-assets")

    @app.get("/", response_class=HTMLResponse)
    def index(run_id: Optional[str] = Query(default=None)) -> HTMLResponse:
        resolved_run_id = str(run_id or "").strip()
        html = build_live_web_viewer_html(
            run_id=resolved_run_id,
            snapshot_endpoint=(f"/api/runs/{resolved_run_id}/snapshot" if resolved_run_id else ""),
            asset_base_url="/pixel-re-assets",
        )
        return HTMLResponse(content=html)

    @app.get("/api/health")
    def health(run_id: Optional[str] = Query(default=None)) -> dict[str, Any]:
        explicit_run_id = str(run_id or "").strip()
        active_run_id = explicit_run_id or str(_LIVE_SESSION_STATE.get("run_id", "")).strip()
        return {
            "status": "ok",
            "active_run_id": active_run_id,
            "available_runs": available_runs(),
        }

    @app.get("/api/runs")
    def runs() -> dict[str, Any]:
        run_ids = available_runs()
        return {
            "runs": run_ids,
            "latest_run_id": run_ids[0] if run_ids else "",
        }

    @app.get("/api/live/status")
    def live_status(port: Optional[int] = Query(default=None)) -> dict[str, Any]:
        return _live_status_payload(port_override=port)

    @app.post("/api/live/start")
    def live_start(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        port = int(payload.get("port", 8010) or 8010)
        max_cases_value = payload.get("max_cases", 5)
        minute_limit_value = payload.get("minute_limit", 120)
        min_demo_minutes = int(payload.get("min_demo_minutes", 20) or 20)
        wait_timeout_sec = float(payload.get("wait_timeout_sec", 20.0) or 20.0)
        step_delay_sec = float(payload.get("step_delay_sec", 0.55) or 0.55)
        scenario_file = str(payload.get("scenario_file", "") or "").strip()
        fixed_demo = bool(payload.get("fixed_demo", True))

        with _LIVE_SESSION_LOCK:
            _cleanup_finished_live_process()
            existing = _get_live_process()
            if existing is not None and existing.poll() is None:
                run_id = str(_LIVE_SESSION_STATE.get("run_id", "")).strip()
                return {
                    "status": "already_running",
                    **_live_status_payload_unlocked(port_override=port),
                    "message": f"Live simulation already running for {run_id}" if run_id else "Live simulation already running",
                }

            reports_dir = settings.REPORTS_DIR
            reports_dir.mkdir(parents=True, exist_ok=True)
            known_dirs = {child.name for child in reports_dir.iterdir() if child.is_dir()}

            env = os.environ.copy()
            env["LIVE_VIS_STEP_DELAY_SEC"] = str(max(0.0, step_delay_sec))

            sim_cmd = [sys.executable, "-m", "app.scripts.run_live_parallel_visual_multi_patient"]
            if max_cases_value is not None and str(max_cases_value).strip() != "":
                sim_cmd.extend(["--max-cases", str(int(max_cases_value))])
            if minute_limit_value is not None and str(minute_limit_value).strip() != "":
                sim_cmd.extend(["--minute-limit", str(int(minute_limit_value))])
            sim_cmd.extend(["--min-demo-minutes", str(max(0, min_demo_minutes))])
            if scenario_file:
                sim_cmd.extend(["--scenario-file", scenario_file])
            if fixed_demo:
                sim_cmd.append("--fixed-demo")

            process = subprocess.Popen(sim_cmd, env=env)
            try:
                run_id = _find_new_live_run(reports_dir, known_dirs, wait_timeout_sec)
            except Exception:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                raise

            _LIVE_SESSION_STATE.update(
                {
                    "process": process,
                    "run_id": run_id,
                    "port": port,
                    "started_at": time.time(),
                    "command": sim_cmd,
                }
            )

        return {
            "status": "started",
            **_live_status_payload(port_override=port),
            "message": f"Started live simulation for {run_id}",
        }

    @app.post("/api/live/stop")
    def live_stop() -> dict[str, Any]:
        with _LIVE_SESSION_LOCK:
            _cleanup_finished_live_process()
            process = _get_live_process()
            run_id = str(_LIVE_SESSION_STATE.get("run_id", "")).strip()
            if process is None or process.poll() is not None:
                _LIVE_SESSION_STATE.update({"process": None, "run_id": "", "started_at": 0.0, "command": []})
                return {"status": "idle", "message": "No live simulation is currently running."}
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            _LIVE_SESSION_STATE.update({"process": None, "run_id": "", "started_at": 0.0, "command": []})
        return {"status": "stopped", "run_id": run_id, "message": f"Stopped live simulation for {run_id}"}

    @app.get("/api/runs/{run_id}/snapshot")
    def snapshot(run_id: str) -> dict[str, Any]:
        try:
            return load_snapshot(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Snapshot not found: {exc}") from exc

    @app.get("/api/runs/{run_id}/history")
    def history(run_id: str) -> dict[str, Any]:
        try:
            return {
                "run_id": run_id,
                "history": load_history(run_id),
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"History not found: {exc}") from exc

    @app.get("/api/runs/{run_id}/summary")
    def summary(run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "summary": load_parallel_summary(run_id),
        }

    @app.get("/api/runs/{run_id}/cases/{case_id}")
    def case_detail(run_id: str, case_id: str) -> dict[str, Any]:
        try:
            detail = load_case_detail(run_id, case_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Snapshot not found: {exc}") from exc
        if not detail:
            raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")
        return {
            "run_id": run_id,
            "case_id": case_id,
            "detail": detail,
        }

    @app.post("/api/runs/{run_id}/cases/{case_id}/what-if")
    def case_what_if(run_id: str, case_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        snapshot_id = str(payload.get("snapshot_id", "")).strip()
        action_type = str(payload.get("action_type", "")).strip()
        action_target = str(payload.get("action_target", "")).strip()
        max_turns = int(payload.get("max_turns", 12) or 12)
        if not snapshot_id or not action_type:
            raise HTTPException(status_code=400, detail="snapshot_id and action_type are required")

        parallel_summary = load_parallel_summary(run_id)
        if parallel_summary:
            selected_action = {
                "type": action_type,
                "target": action_target,
            }
            replay_run_id = create_run_id()
            try:
                replay_payload = replay_parallel_case_from_snapshot(
                    run_id=run_id,
                    case_id=case_id,
                    snapshot_id=snapshot_id,
                    selected_action=selected_action,
                    replay_run_id=replay_run_id,
                )
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

            normalized_payload = _normalize_parallel_what_if_payload(
                run_id=run_id,
                case_id=case_id,
                replay_run_id=replay_run_id,
                replay_payload=replay_payload,
            )
            save_what_if_replay(case_id, normalized_payload, replay_run_id)
            save_what_if_comparison(case_id, dict(normalized_payload.get("comparison", {}) or {}), replay_run_id)
            return normalized_payload

        try:
            original_result = load_case_result(run_id, case_id)
            source_case = load_source_case(case_id)
            snapshot = get_snapshot_by_id(original_result, snapshot_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        selected_action = {
            "type": action_type,
            "target": action_target,
        }
        replay_run_id = create_run_id()
        replay_result = replay_case_from_snapshot(
            case=source_case,
            original_result=original_result,
            snapshot=snapshot,
            selected_action=selected_action,
            run_id=replay_run_id,
            max_turns=max_turns,
        )
        comparison = dict(replay_result.get("what_if_replay", {}).get("comparison", {}) or {})
        reasoning_state = dict(replay_result.get("reasoning_state", {}) or {})
        transcript = [dict(item or {}) for item in list(replay_result.get("transcript", []) or []) if dict(item or {})]
        save_what_if_replay(case_id, replay_result, replay_run_id)
        save_what_if_comparison(case_id, comparison, replay_run_id)
        return {
            "run_id": run_id,
            "case_id": case_id,
            "replay_run_id": replay_run_id,
            "snapshot_id": snapshot_id,
            "selected_action": selected_action,
            "comparison": comparison,
            "replay": {
                "predicted_diagnosis": str(replay_result.get("predicted_diagnosis", "")).strip(),
                "predicted_department": str(replay_result.get("predicted_department", "")).strip(),
                "diagnosis_correct": bool(replay_result.get("diagnosis_correct", False)),
                "department_correct": bool(replay_result.get("department_correct", False)),
                "episode_reward": float(replay_result.get("episode_reward", 0.0) or 0.0),
            },
            "branch_detail": {
                "questions": [
                    {
                        "question": str(dict(item or {}).get("question", "")).strip(),
                        "answer": str(dict(item or {}).get("answer", "")).strip(),
                    }
                    for item in list(reasoning_state.get("question_history", []) or [])
                    if dict(item or {})
                ][-6:],
                "tests": [str(item).strip() for item in list(reasoning_state.get("recommended_tests", []) or []) if str(item).strip()][-6:],
                "objective_findings": [str(item).strip() for item in list(reasoning_state.get("objective_findings", []) or []) if str(item).strip()][-6:],
                "event_log": [dict(item or {}) for item in list(reasoning_state.get("event_log", []) or []) if dict(item or {})][-10:],
                "transcript": transcript[-10:],
            },
        }

    return app


app = create_app()
