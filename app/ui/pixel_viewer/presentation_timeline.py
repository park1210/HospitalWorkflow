from __future__ import annotations

from copy import deepcopy
import os
from typing import Any


BEAT_SCALE = max(0.25, float(os.getenv("LIVE_VIS_BEAT_SCALE", "1.35") or 1.35))


def initial_playback_state() -> dict[str, Any]:
    return {
        "paused": False,
        "what_if_enabled": False,
        "what_if_preview_enabled": False,
        "selected_decision_index": 0,
        "selected_candidate_index": 0,
        "replay_status": "",
        "replay_summary": {},
        "show_replay_outcome": False,
        "beat_index": 0,
        "last_advance_ms": 0,
        "source_key": "",
        "beats": [],
    }


def _active_beats(state: dict[str, Any]) -> list[dict[str, Any]]:
    replay_summary = dict(state.get("replay_summary", {}) or {})
    replay_beats = list(replay_summary.get("presentation_beats", []) or [])
    if bool(state.get("show_replay_outcome", False)) and replay_beats:
        return replay_beats
    return list(state.get("beats", []) or [])


def _source_key(snapshot: dict[str, Any], selected_case_id: str) -> str:
    return "|".join(
        [
            str(selected_case_id).strip(),
            str(snapshot.get("phase", "")).strip(),
            str(snapshot.get("actor", "")).strip(),
            str(snapshot.get("action", "")).strip(),
            str(snapshot.get("snapshot_written_at_unix", "")).strip(),
        ]
    )


def _speaker_and_listener(actor: str, case_id: str, line: str) -> tuple[str, str]:
    normalized_actor = str(actor).strip()
    normalized_line = str(line).strip().lower()
    if normalized_actor == "er_department":
        if normalized_line.startswith("patient:"):
            return f"patient_{case_id}", "doctor_er_0"
        return "doctor_er_0", f"patient_{case_id}"
    if normalized_actor and normalized_actor not in {"system"}:
        if normalized_line.startswith("patient:"):
            return f"patient_{case_id}", f"specialty_{normalized_actor}"
        return f"specialty_{normalized_actor}", f"patient_{case_id}"
    return "", ""


def _current_case_detail(snapshot: dict[str, Any], selected_case_id: str) -> dict[str, Any]:
    case_details = dict(snapshot.get("case_details", {}) or {})
    return dict(case_details.get(selected_case_id, {}) or {})


def _selected_recent_conversations(snapshot: dict[str, Any], selected_case_id: str) -> list[dict[str, Any]]:
    selected_case_id = str(selected_case_id).strip()
    recent = list(snapshot.get("conversation_log_recent", []) or [])
    history = list(snapshot.get("conversation_history", []) or [])
    source = recent or history
    entries = [
        dict(entry)
        for entry in source
        if str(entry.get("case_id", "")).strip() == selected_case_id
    ]
    entries.sort(key=lambda entry: (int(entry.get("minute", 0) or 0), str(entry.get("actor", "")).strip()))
    return entries


def _normalize_selection_state(state: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    next_state = dict(state or {})
    decision_points = list(detail.get("decision_points", []) or [])
    if decision_points:
        next_state["selected_decision_index"] = min(
            max(int(next_state.get("selected_decision_index", len(decision_points) - 1) or 0), 0),
            len(decision_points) - 1,
        )
    else:
        next_state["selected_decision_index"] = 0
    selected_decision = (
        dict(decision_points[int(next_state.get("selected_decision_index", 0) or 0)] or {})
        if decision_points
        else {}
    )
    candidates = list(selected_decision.get("alternatives", []) or []) or list(detail.get("counterfactual_candidates", []) or [])
    if candidates:
        next_state["selected_candidate_index"] = min(
            max(int(next_state.get("selected_candidate_index", 0) or 0), 0),
            len(candidates) - 1,
        )
    else:
        next_state["selected_candidate_index"] = 0
        next_state["what_if_preview_enabled"] = False
    return next_state


def _dialogue_beat(
    *,
    case_id: str,
    actor: str,
    action: str,
    label: str,
    lines: list[str],
    duration_ms: int,
) -> dict[str, Any]:
    cleaned_lines = [str(line).strip() for line in lines if str(line).strip()]
    speaker, listener = _speaker_and_listener(actor, case_id, cleaned_lines[-1] if cleaned_lines else "")
    return {
        "kind": "conversation",
        "label": str(label).strip(),
        "duration_ms": int(duration_ms or 2200),
        "dialogue": {
            "case_id": str(case_id).strip(),
            "actor": str(actor).strip(),
            "action": str(action).strip(),
            "lines": cleaned_lines[-2:],
            "speaker_entity_id": speaker,
            "listener_entity_id": listener,
            "bubble_text": cleaned_lines[-1].split(": ", 1)[-1][:72] if cleaned_lines else "",
        },
    }


def _question_answer_beats(detail: dict[str, Any], selected_case_id: str) -> list[dict[str, Any]]:
    beats: list[dict[str, Any]] = []
    for qa in list(detail.get("questions", []) or [])[-3:]:
        question = str(dict(qa).get("question", "")).strip()
        answer = str(dict(qa).get("answer", "")).strip()
        if question:
            beats.append(
                _dialogue_beat(
                    case_id=selected_case_id,
                    actor="er_department",
                    action="ask_patient",
                    label="ER interviewing patient",
                    lines=[f"ER: {question}"],
                    duration_ms=1800,
                )
            )
        if answer:
            beats.append(
                _dialogue_beat(
                    case_id=selected_case_id,
                    actor="er_department",
                    action="ask_patient",
                    label="Patient answering ER",
                    lines=[f"Patient: {answer}"],
                    duration_ms=2200,
                )
            )
    return beats


def _test_beats(detail: dict[str, Any], selected_case_id: str) -> list[dict[str, Any]]:
    beats: list[dict[str, Any]] = []
    tests = [str(item).strip() for item in list(detail.get("tests", []) or []) if str(item).strip()]
    if not tests:
        return beats
    latest_test = tests[-1]
    beats.append(
        _dialogue_beat(
            case_id=selected_case_id,
            actor="er_department",
            action="request_test",
            label="ER explains test plan",
            lines=[f"ER: We need {latest_test} to clarify the diagnosis."],
            duration_ms=2000,
        )
    )
    beats.append({"kind": "move_to_test_hall", "label": f"Walk to {latest_test}", "duration_ms": 1200})
    beats.append({"kind": "move_to_test", "label": f"Move to {latest_test}", "duration_ms": 1600})
    beats.append({"kind": "test", "label": f"{latest_test} in progress", "duration_ms": 2200})
    beats.append({"kind": "wait", "label": f"Waiting for {latest_test} result", "duration_ms": 2400})
    return beats


def _consult_beats(detail: dict[str, Any], selected_case_id: str) -> list[dict[str, Any]]:
    beats: list[dict[str, Any]] = []
    department = str(detail.get("predicted_department", "")).strip()
    if not department:
        return beats
    beats.append(
        _dialogue_beat(
            case_id=selected_case_id,
            actor="er_department",
            action="make_diagnostic_summary",
            label="ER requests specialty consult",
            lines=[f"ER: Please evaluate this patient from {department} perspective."],
            duration_ms=1800,
        )
    )
    beats.append({"kind": "consult_call", "label": f"{department} specialist walking in", "duration_ms": 1200})
    beats.append({"kind": "move_to_consult_hall", "label": f"Move toward {department} consult room", "duration_ms": 1200})
    beats.append(
        _dialogue_beat(
            case_id=selected_case_id,
            actor=department,
            action="consulting",
            label=f"{department} specialist assessment",
            lines=[f"Specialist: I will review the ER findings and examine the patient."],
            duration_ms=2200,
        )
    )
    return beats


def _flow_beats(detail: dict[str, Any], selected_case_id: str) -> list[dict[str, Any]]:
    zone = str(detail.get("zone", "")).strip().lower()
    department = str(detail.get("predicted_department", "")).strip()
    beats: list[dict[str, Any]] = []

    if zone == "waiting_room":
        beats.append({"kind": "arrival", "label": "Patient entering ER", "duration_ms": 1400})
        beats.append({"kind": "queue", "label": "Arrival triage queue", "duration_ms": 1400})
        beats.append({"kind": "triage_walk", "label": "Walk to triage desk", "duration_ms": 1200})
        beats.append(
            _dialogue_beat(
                case_id=selected_case_id,
                actor="er_department",
                action="perform_triage",
                label="Triage starts",
                lines=["ER: We will assess your condition first."],
                duration_ms=1800,
            )
        )
    elif zone == "er_workup":
        beats.append({"kind": "move_to_bed", "label": "Move to ER bed", "duration_ms": 1400})
        beats.append({"kind": "assessment", "label": "ER interview / assessment", "duration_ms": 1600})
        beats.extend(_question_answer_beats(detail, selected_case_id))
        beats.extend(_test_beats(detail, selected_case_id))
        if department:
            beats.extend(_consult_beats(detail, selected_case_id))
    elif zone == "awaiting_results":
        beats.extend(_question_answer_beats(detail, selected_case_id))
        beats.extend(_test_beats(detail, selected_case_id))
        beats.append({"kind": "wait", "label": "ER monitoring while results are pending", "duration_ms": 2400})
        if department:
            beats.extend(_consult_beats(detail, selected_case_id))
    elif zone == "observation":
        beats.append({"kind": "observe", "label": "Observation / reassessment", "duration_ms": 1800})
        beats.append(
            _dialogue_beat(
                case_id=selected_case_id,
                actor="er_department",
                action="observe_patient",
                label="ER reassessment",
                lines=["ER: We are watching your condition and reassessing your response."],
                duration_ms=2200,
            )
        )
    elif zone == "specialty_review":
        beats.extend(_consult_beats(detail, selected_case_id))
        beats.append(
            _dialogue_beat(
                case_id=selected_case_id,
                actor=department or "specialist",
                action="diagnose",
                label="Specialty diagnostic discussion",
                lines=["Specialist: Based on the interview and objective findings, we can narrow the diagnosis."],
                duration_ms=2200,
            )
        )
    elif zone == "completed":
        beats.append(
            _dialogue_beat(
                case_id=selected_case_id,
                actor="er_department",
                action="discharge",
                label="Final explanation / discharge",
                lines=["ER: We have finalized the assessment and will explain the next steps."],
                duration_ms=2200,
            )
        )
        beats.append({"kind": "complete", "label": "Diagnosis complete / discharge", "duration_ms": 1800})

    return beats


def _conversation_beats(snapshot: dict[str, Any], selected_case_id: str) -> list[dict[str, Any]]:
    beats: list[dict[str, Any]] = []
    selected_entries = _selected_recent_conversations(snapshot, selected_case_id)
    for entry in selected_entries[-3:]:
        lines = [str(line).strip() for line in list(entry.get("lines", []) or []) if str(line).strip()]
        if not lines:
            continue
        beats.append(
            _dialogue_beat(
                case_id=selected_case_id,
                actor=str(entry.get("actor", "")).strip(),
                action=str(entry.get("action", "")).strip(),
                label=f"{str(entry.get('actor', '')).strip() or 'dialogue'} live exchange",
                lines=lines[-2:],
                duration_ms=2200,
            )
        )
    return beats


def _event_dialogue_lines(event: dict[str, Any]) -> list[str]:
    payload = dict(event.get("payload", {}) or {})
    event_type = str(event.get("event_type", "")).strip().lower()
    actor = str(dict(event.get("actor", {}) or {}).get("id", "")).strip()
    target = str(dict(event.get("target", {}) or {}).get("id", "")).strip()
    department = str(payload.get("department", "")).strip()
    question = str(payload.get("question", "")).strip()
    answer = str(payload.get("answer", "")).strip()
    requested_test = str(payload.get("requested_test", "")).strip()
    diagnosis = str(payload.get("diagnosis", "")).strip() or str(payload.get("final_diagnosis", "")).strip()
    final_department = str(payload.get("final_department", "")).strip()
    rationale = str(event.get("rationale", "")).strip()

    if event_type == "question_asked" and question:
        speaker = "ER" if "doctor_er" in actor else "Specialist"
        return [f"{speaker}: {question}"]
    if event_type == "answer_received" and answer:
        return [f"Patient: {answer}"]
    if event_type == "test_ordered" and requested_test:
        speaker = "ER" if "doctor_er" in actor else "Specialist"
        return [f"{speaker}: We need {requested_test} to narrow this down."]
    if event_type == "consult_requested" and department:
        return [f"ER: Please evaluate this patient from {department} perspective."]
    if event_type in {"consult_started", "consult_note_added"}:
        if rationale:
            return [f"Specialist: {rationale}"]
        if department or target:
            return [f"Specialist: I am reviewing the case for {department or target}."]
    if event_type == "result_received":
        if rationale:
            return [f"ER: {rationale}"]
        pending = payload.get("pending_results_count", "")
        return [f"ER: We are reviewing the latest results. pending={pending}"]
    if event_type == "diagnosis_finalized" and diagnosis:
        speaker = "ER" if "doctor_er" in actor else "Specialist"
        return [f"{speaker}: The working diagnosis is {diagnosis}."]
    if event_type == "case_completed":
        return [
            f"ER: Final diagnosis is {diagnosis or '-'}.",
            f"ER: Final department is {final_department or '-'}."
        ]
    return []


def _event_beat_kind(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type", "")).strip().lower()
    action = str(event.get("action", "")).strip().lower()
    location_id = str(event.get("location_id", "")).strip().lower()
    state_delta = dict(event.get("state_delta", {}) or {})
    zone = str(state_delta.get("zone", "")).strip().lower()
    if event_type == "case_started":
        return "arrival"
    if event_type == "triage_completed":
        return "triage_walk"
    if event_type == "assessment_completed":
        return "assessment"
    if event_type in {"question_asked", "answer_received"}:
        if zone == "specialty_review" or "specialty" in location_id:
            return "consult"
        return "assessment"
    if event_type == "test_ordered":
        return "move_to_test_hall"
    if event_type == "result_received":
        return "wait"
    if event_type == "consult_requested":
        return "consult_call"
    if event_type in {"consult_started", "consult_note_added"}:
        return "consult" if action == "consulting" else "move_to_consult_hall"
    if event_type == "observation_started":
        return "observe"
    if event_type in {"diagnosis_finalized", "case_completed"}:
        return "complete"
    return "idle"


def _event_label(event: dict[str, Any], beat_kind: str) -> str:
    payload = dict(event.get("payload", {}) or {})
    event_type = str(event.get("event_type", "")).strip().lower()
    action = str(event.get("action", "")).strip()
    department = str(payload.get("department", "")).strip()
    requested_test = str(payload.get("requested_test", "")).strip()
    diagnosis = str(payload.get("diagnosis", "")).strip() or str(payload.get("final_diagnosis", "")).strip()
    if event_type == "case_started":
        return "Patient arriving at ER"
    if event_type == "triage_completed":
        return "Triage complete / move to ER"
    if event_type == "assessment_completed":
        return "ER assessment underway"
    if event_type == "test_ordered":
        return f"Order {requested_test or 'test'}"
    if event_type == "result_received":
        return "Reviewing test results"
    if event_type == "consult_requested":
        return f"Call {department or 'specialty'} consult"
    if event_type in {"consult_started", "consult_note_added"}:
        return f"{department or 'Specialty'} consult in progress" if department else f"{action or 'consult'} in progress"
    if event_type == "diagnosis_finalized":
        return f"Diagnosis finalized: {diagnosis or '-'}"
    if event_type == "case_completed":
        return "Case completed / discharge"
    return action or beat_kind.replace("_", " ")


def _event_duration_ms(event: dict[str, Any], beat_kind: str, has_dialogue: bool) -> int:
    base = {
        "arrival": 1800,
        "triage_walk": 1800,
        "assessment": 2600,
        "move_to_test_hall": 1600,
        "move_to_test": 1700,
        "test": 2600,
        "wait": 2600,
        "consult_call": 1700,
        "move_to_consult_hall": 1700,
        "consult": 2600,
        "observe": 2200,
        "complete": 2200,
        "idle": 1500,
    }.get(beat_kind, 1500)
    if has_dialogue:
        return max(base, 2600)
    return base


def _event_dialogue_actor(event: dict[str, Any]) -> str:
    actor_info = dict(event.get("actor", {}) or {})
    actor_id = str(actor_info.get("id", "")).strip()
    actor_role = str(actor_info.get("role", "")).strip()
    return "er_department" if actor_role == "er" or "doctor_er" in actor_id else actor_id.replace("specialty_", "") or actor_role


def _event_dialogue_payload(event: dict[str, Any], selected_case_id: str, dialogue_lines: list[str]) -> dict[str, Any]:
    dialogue_actor = _event_dialogue_actor(event)
    return {
        "case_id": selected_case_id,
        "actor": dialogue_actor,
        "action": str(event.get("action", "")).strip(),
        "lines": dialogue_lines[-2:],
        "speaker_entity_id": "doctor_er_0" if dialogue_actor == "er_department" else (
            f"specialty_{dialogue_actor}" if dialogue_actor not in {"system", "patient"} else f"patient_{selected_case_id}"
        ),
        "listener_entity_id": f"patient_{selected_case_id}",
        "bubble_text": dialogue_lines[-1].split(": ", 1)[-1][:72],
    }


def _append_event_beat(
    beats: list[dict[str, Any]],
    event: dict[str, Any],
    selected_case_id: str,
    *,
    kind: str,
    label: str | None = None,
    dialogue_lines: list[str] | None = None,
    duration_ms: int | None = None,
) -> None:
    lines = list(dialogue_lines or [])
    beat: dict[str, Any] = {
        "kind": str(kind).strip(),
        "label": str(label or _event_label(event, kind)).strip(),
        "duration_ms": int(duration_ms or _event_duration_ms(event, kind, bool(lines))),
        "event": event,
    }
    if lines:
        beat["dialogue"] = _event_dialogue_payload(event, selected_case_id, lines)
    beats.append(beat)


def _event_beats(snapshot: dict[str, Any], selected_case_id: str) -> list[dict[str, Any]]:
    selected_case_id = str(selected_case_id).strip()
    events = [
        dict(event)
        for event in list(snapshot.get("event_log_recent", []) or [])
        if str(event.get("case_id", "")).strip() == selected_case_id
    ]
    events.sort(
        key=lambda event: (
            int(event.get("minute", 0) or 0),
            int(event.get("tick", 0) or 0),
            str(event.get("event_id", "")).strip(),
        )
    )
    beats: list[dict[str, Any]] = []
    for event in events[-10:]:
        beat_kind = _event_beat_kind(event)
        dialogue_lines = _event_dialogue_lines(event)
        event_type = str(event.get("event_type", "")).strip().lower()
        payload = dict(event.get("payload", {}) or {})
        requested_test = str(payload.get("requested_test", "")).strip()
        department = str(payload.get("department", "")).strip()
        diagnosis = str(payload.get("diagnosis", "")).strip() or str(payload.get("final_diagnosis", "")).strip()

        if event_type == "test_ordered":
            _append_event_beat(
                beats,
                event,
                selected_case_id,
                kind="assessment",
                label=f"ER explains {requested_test or 'test'} plan",
                dialogue_lines=dialogue_lines,
            )
            _append_event_beat(
                beats,
                event,
                selected_case_id,
                kind="move_to_test_hall",
                label=f"Walking toward {requested_test or 'test'}",
            )
            _append_event_beat(
                beats,
                event,
                selected_case_id,
                kind="move_to_test",
                label=f"Entering {requested_test or 'test'} area",
            )
            _append_event_beat(
                beats,
                event,
                selected_case_id,
                kind="test",
                label=f"{requested_test or 'Test'} running",
            )
            continue

        if event_type == "consult_requested":
            _append_event_beat(
                beats,
                event,
                selected_case_id,
                kind="assessment",
                label=f"ER calls {department or 'specialty'} consult",
                dialogue_lines=dialogue_lines,
            )
            _append_event_beat(
                beats,
                event,
                selected_case_id,
                kind="consult_call",
                label=f"{department or 'Specialty'} specialist notified",
            )
            _append_event_beat(
                beats,
                event,
                selected_case_id,
                kind="move_to_consult_hall",
                label=f"{department or 'Specialist'} heading to consult room",
            )
            continue

        if event_type in {"consult_started", "consult_note_added"}:
            _append_event_beat(
                beats,
                event,
                selected_case_id,
                kind="consult",
                label=f"{department or 'Specialty'} consult in progress",
                dialogue_lines=dialogue_lines,
            )
            continue

        if event_type == "diagnosis_finalized":
            _append_event_beat(
                beats,
                event,
                selected_case_id,
                kind="consult",
                label=f"Final diagnostic explanation: {diagnosis or '-'}",
                dialogue_lines=dialogue_lines,
            )
            _append_event_beat(
                beats,
                event,
                selected_case_id,
                kind="complete",
                label="Preparing discharge / final handoff",
            )
            continue

        _append_event_beat(
            beats,
            event,
            selected_case_id,
            kind=beat_kind,
            dialogue_lines=dialogue_lines,
        )
    return beats


def _synthetic_beats(snapshot: dict[str, Any], selected_case_id: str) -> list[dict[str, Any]]:
    detail = _current_case_detail(snapshot, selected_case_id)
    if not detail:
        return []
    return _flow_beats(detail, selected_case_id)


def build_beats(snapshot: dict[str, Any], selected_case_id: str) -> list[dict[str, Any]]:
    beats = _event_beats(snapshot, selected_case_id)
    if not beats:
        beats = _conversation_beats(snapshot, selected_case_id)
    if not beats:
        beats.extend(_synthetic_beats(snapshot, selected_case_id))
    if not beats:
        beats.append({"kind": "idle", "label": "Ambient hospital activity", "duration_ms": 1500})
    for beat in beats:
        beat["duration_ms"] = max(600, int(float(beat.get("duration_ms", 1500) or 1500) * BEAT_SCALE))
    return beats


def _build_replay_beats(replay_summary: dict[str, Any], selected_case_id: str) -> list[dict[str, Any]]:
    replay_result = dict(replay_summary.get("replay_result", {}) or {})
    trajectory_steps = list(replay_result.get("trajectory_steps", []) or [])
    beats: list[dict[str, Any]] = []
    department = str(replay_result.get("predicted_department", "")).strip()
    cumulative_questions: list[dict[str, str]] = []
    cumulative_tests: list[str] = []
    objective_findings = list(replay_result.get("objective_findings", []) or [])

    def _detail_update(*, zone: str, pending_results_count: int, include_findings: bool = False) -> dict[str, Any]:
        return {
            "zone": zone,
            "questions": [dict(item) for item in cumulative_questions],
            "tests": list(cumulative_tests),
            "objective_findings": list(objective_findings if include_findings else []),
            "pending_results_count": int(pending_results_count),
            "predicted_department": str(replay_result.get("predicted_department", "")).strip(),
            "predicted_diagnosis": str(replay_result.get("predicted_diagnosis", "")).strip(),
        }

    for step in trajectory_steps:
        step_data = dict(step or {})
        action = str(step_data.get("action", "")).strip()
        target = str(step_data.get("target", "")).strip()
        outcome = dict(step_data.get("outcome", {}) or {})
        decision_rationale = str(step_data.get("decision_rationale", "")).strip()
        if action == "ask_patient":
            question = str(outcome.get("question", "")).strip()
            answer = str(outcome.get("answer", "")).strip()
            if question or answer:
                cumulative_questions.append({"question": question, "answer": answer})
            if question:
                beat = _dialogue_beat(
                    case_id=selected_case_id,
                    actor="er_department",
                    action="ask_patient",
                    label="Replay: ER question",
                    lines=[f"ER: {question}"],
                    duration_ms=1800,
                )
                beat["detail_update"] = _detail_update(zone="er_workup", pending_results_count=0)
                beats.append(beat)
            if answer:
                beat = _dialogue_beat(
                    case_id=selected_case_id,
                    actor="er_department",
                    action="ask_patient",
                    label="Replay: patient answer",
                    lines=[f"Patient: {answer}"],
                    duration_ms=2200,
                )
                beat["detail_update"] = _detail_update(zone="er_workup", pending_results_count=0)
                beats.append(beat)
        elif action == "request_test":
            if target and target not in cumulative_tests:
                cumulative_tests.append(target)
            rationale_line = decision_rationale or f"We need {target} to confirm the diagnosis."
            beat = _dialogue_beat(
                case_id=selected_case_id,
                actor="er_department",
                action="request_test",
                label=f"Replay: order {target or 'test'}",
                lines=[f"ER: {rationale_line}"],
                duration_ms=1800,
            )
            beat["detail_update"] = _detail_update(zone="er_workup", pending_results_count=1)
            beats.append(beat)
            beats.append(
                {
                    "kind": "move_to_test_hall",
                    "label": f"Replay: walk to {target or 'test'}",
                    "duration_ms": 1000,
                    "detail_update": _detail_update(zone="er_workup", pending_results_count=1),
                }
            )
            beats.append(
                {
                    "kind": "move_to_test",
                    "label": f"Replay: move to {target or 'test'}",
                    "duration_ms": 1400,
                    "detail_update": _detail_update(zone="er_workup", pending_results_count=1),
                }
            )
            beats.append(
                {
                    "kind": "test",
                    "label": f"Replay: {target or 'test'} running",
                    "duration_ms": 1800,
                    "detail_update": _detail_update(zone="awaiting_results", pending_results_count=1),
                }
            )
            beats.append(
                {
                    "kind": "wait",
                    "label": f"Replay: waiting for {target or 'test'}",
                    "duration_ms": 1800,
                    "detail_update": _detail_update(zone="awaiting_results", pending_results_count=1),
                }
            )
        elif action in {"make_diagnostic_summary", "request_consult", "consult"}:
            beat = _dialogue_beat(
                case_id=selected_case_id,
                actor="er_department",
                action="make_diagnostic_summary",
                label="Replay: ER requests consult",
                lines=[f"ER: {decision_rationale or 'Please review this patient with the specialty team.'}"],
                duration_ms=1800,
            )
            beat["detail_update"] = _detail_update(zone="specialty_review", pending_results_count=0)
            beats.append(beat)
            beats.append(
                {
                    "kind": "consult_call",
                    "label": f"Replay: {department or 'specialty'} specialist arrives",
                    "duration_ms": 1200,
                    "detail_update": _detail_update(zone="specialty_review", pending_results_count=0),
                }
            )
            beats.append(
                {
                    "kind": "move_to_consult_hall",
                    "label": f"Replay: move to {department or 'specialty'} consult",
                    "duration_ms": 1200,
                    "detail_update": _detail_update(zone="specialty_review", pending_results_count=0),
                }
            )
        elif action == "diagnose":
            beat = _dialogue_beat(
                case_id=selected_case_id,
                actor=department or "specialist",
                action="diagnose",
                label="Replay: specialty diagnosis",
                lines=[
                    f"Specialist: {decision_rationale or 'The evidence now supports a final diagnosis.'}",
                    f"Specialist: Final diagnosis is {str(replay_result.get('predicted_diagnosis', '')).strip() or 'pending'}."
                ],
                duration_ms=2400,
            )
            beat["detail_update"] = _detail_update(zone="specialty_review", pending_results_count=0, include_findings=True)
            beats.append(beat)
    if replay_result:
        beat = _dialogue_beat(
            case_id=selected_case_id,
            actor="er_department",
            action="discharge",
            label="Replay: final explanation",
            lines=[
                f"ER: Replay outcome department is {str(replay_result.get('predicted_department', '')).strip() or '-'}."
            ],
            duration_ms=1800,
        )
        beat["detail_update"] = _detail_update(zone="completed", pending_results_count=0, include_findings=True)
        beats.append(beat)
        beats.append(
            {
                "kind": "complete",
                "label": "Replay: case completed",
                "duration_ms": 1600,
                "detail_update": _detail_update(zone="completed", pending_results_count=0, include_findings=True),
            }
        )
    for beat in beats:
        beat["duration_ms"] = max(600, int(float(beat.get("duration_ms", 1500) or 1500) * BEAT_SCALE))
    return beats


def sync_playback_state(playback_state: dict[str, Any], snapshot: dict[str, Any], selected_case_id: str, now_ms: int) -> dict[str, Any]:
    state = dict(playback_state or {})
    next_source_key = _source_key(snapshot, selected_case_id)
    detail = _current_case_detail(snapshot, selected_case_id)
    replay_summary = dict(state.get("replay_summary", {}) or {})
    if replay_summary.get("replay_result") and not replay_summary.get("presentation_beats"):
        replay_summary["presentation_beats"] = _build_replay_beats(replay_summary, selected_case_id)
        state["replay_summary"] = replay_summary
    if state.get("source_key") != next_source_key:
        state["source_key"] = next_source_key
        state["beats"] = build_beats(snapshot, selected_case_id)
        state["beat_index"] = 0
        state["last_advance_ms"] = int(now_ms or 0)
    active_beats = _active_beats(state)
    if active_beats:
        state["beat_index"] = min(max(int(state.get("beat_index", 0) or 0), 0), len(active_beats) - 1)
    else:
        state["beat_index"] = 0
    return _normalize_selection_state(state, detail)


def advance_playback_state(playback_state: dict[str, Any], now_ms: int) -> dict[str, Any]:
    state = dict(playback_state or {})
    beats = _active_beats(state)
    if not beats or bool(state.get("paused", False)):
        return state
    beat_index = int(state.get("beat_index", 0) or 0)
    beat = dict(beats[min(max(beat_index, 0), len(beats) - 1)] or {})
    duration_ms = int(beat.get("duration_ms", 1600) or 1600)
    last_advance_ms = int(state.get("last_advance_ms", 0) or 0)
    if int(now_ms or 0) - last_advance_ms >= duration_ms and beat_index < len(beats) - 1:
        state["beat_index"] = beat_index + 1
        state["last_advance_ms"] = int(now_ms or 0)
    return state


def handle_action(playback_state: dict[str, Any], action: str, now_ms: int) -> dict[str, Any]:
    state = dict(playback_state or {})
    beats = _active_beats(state)
    beat_index = int(state.get("beat_index", 0) or 0)
    if action == "toggle_pause":
        state["paused"] = not bool(state.get("paused", False))
        state["last_advance_ms"] = int(now_ms or 0)
    elif action == "next_beat" and beats:
        state["paused"] = True
        state["beat_index"] = min(len(beats) - 1, beat_index + 1)
        state["last_advance_ms"] = int(now_ms or 0)
    elif action == "prev_beat" and beats:
        state["paused"] = True
        state["beat_index"] = max(0, beat_index - 1)
        state["last_advance_ms"] = int(now_ms or 0)
    elif action == "toggle_what_if":
        state["what_if_enabled"] = not bool(state.get("what_if_enabled", False))
        if not bool(state.get("what_if_enabled", False)):
            state["what_if_preview_enabled"] = False
    elif action == "toggle_what_if_preview":
        state["what_if_preview_enabled"] = not bool(state.get("what_if_preview_enabled", False))
    elif action.startswith("select_decision:"):
        state["selected_decision_index"] = max(0, int(action.split(":", 1)[1] or 0))
        state["what_if_preview_enabled"] = False
    elif action.startswith("select_candidate:"):
        state["selected_candidate_index"] = max(0, int(action.split(":", 1)[1] or 0))
    elif action == "apply_replay":
        state["replay_status"] = "queued_preview_replay"
    elif action == "toggle_replay_outcome":
        state["show_replay_outcome"] = not bool(state.get("show_replay_outcome", False))
        state["beat_index"] = 0
        state["paused"] = False
        state["last_advance_ms"] = int(now_ms or 0)
    return state


def _scene_entities(view: dict[str, Any]) -> list[dict[str, Any]]:
    scene = dict(view.get("scene", {}) or {})
    return list(scene.get("entities", []) or [])


def _scene_locations(view: dict[str, Any]) -> dict[str, Any]:
    scene = dict(view.get("scene", {}) or {})
    return dict(scene.get("locations", {}) or {})


def _entity_by_id(entities: list[dict[str, Any]], entity_id: str) -> dict[str, Any] | None:
    for entity in entities:
        if str(entity.get("id", "")).strip() == str(entity_id).strip():
            return entity
    return None


def _entity_by_case(entities: list[dict[str, Any]], case_id: str) -> dict[str, Any] | None:
    for entity in entities:
        if str(entity.get("kind", "")).strip() == "patient" and str(entity.get("case_id", "")).strip() == str(case_id).strip():
            return entity
    return None


def _specialty_department_from_event(event: dict[str, Any], detail: dict[str, Any]) -> str:
    actor = dict(event.get("actor", {}) or {})
    target = dict(event.get("target", {}) or {})
    actor_id = str(actor.get("id", "")).strip()
    target_id = str(target.get("id", "")).strip()
    payload = dict(event.get("payload", {}) or {})
    department = str(payload.get("department", "")).strip()
    if department:
        return department
    if actor_id.startswith("specialty_"):
        return actor_id.replace("specialty_", "", 1).strip()
    if target_id.startswith("specialty_"):
        return target_id.replace("specialty_", "", 1).strip()
    return str(detail.get("predicted_department", "")).strip()


def _specialty_sidebar_location_id(department: str, locations: dict[str, Any]) -> str:
    normalized = str(department).strip().lower()
    candidate = f"sidebar_{normalized}"
    if candidate in locations:
        return candidate
    if normalized == "obstetrics_gynecology" and "sidebar_obgyn" in locations:
        return "sidebar_obgyn"
    return ""


def _event_location(event: dict[str, Any], fallback_location_id: str = "") -> str:
    location_id = str(event.get("location_id", "")).strip()
    if location_id:
        return location_id
    return str(fallback_location_id).strip()


def _preview_target_location_id(selected_candidate: dict[str, Any]) -> str:
    action_type = str(selected_candidate.get("type", "")).strip().lower()
    target = str(selected_candidate.get("target", "")).strip().lower()
    if action_type == "ask_patient":
        return "er_bed_1"
    if action_type == "request_test":
        if any(token in target for token in ("blood", "lab", "panel", "culture", "urine")):
            return "lab_station"
        return "imaging_wait_1"
    if action_type in {"consult", "request_consult", "make_diagnostic_summary"}:
        return "specialty_consult_1"
    if action_type == "observe_patient":
        return "observation_bed_1"
    if action_type == "diagnose":
        return "discharge_1"
    return ""


def _move_entity(entity: dict[str, Any] | None, location_id: str, locations: dict[str, Any], *, status: str | None = None) -> None:
    if entity is None:
        return
    location = dict(locations.get(str(location_id).strip(), {}) or {})
    if not location:
        return
    entity["location_id"] = str(location_id).strip()
    entity["x"] = location.get("x")
    entity["y"] = location.get("y")
    if status is not None:
        entity["status"] = str(status).strip()


def _apply_beat_scene(view: dict[str, Any], beat: dict[str, Any], selected_case_id: str) -> None:
    entities = _scene_entities(view)
    locations = _scene_locations(view)
    patient = _entity_by_case(entities, selected_case_id)
    er_doctor = _entity_by_id(entities, "doctor_er_0")
    dialogue = dict(beat.get("dialogue", {}) or {})
    event = dict(beat.get("event", {}) or {})
    detail = _current_case_detail(view, selected_case_id)
    department = _specialty_department_from_event(event, detail)
    specialist = _entity_by_id(entities, f"specialty_{department}") if department else None
    beat_kind = str(beat.get("kind", "")).strip().lower()

    if patient is None:
        return

    patient["assigned_staff"] = ""
    if specialist is not None:
        specialist["case_id"] = selected_case_id
        sidebar_location_id = _specialty_sidebar_location_id(department, locations)
        if sidebar_location_id and beat_kind not in {"consult_call", "move_to_consult_hall", "consult"}:
            _move_entity(specialist, sidebar_location_id, locations, status="idle")

    if beat_kind in {"arrival", "queue"}:
        _move_entity(patient, "arrival_lane_1" if beat_kind == "queue" else "arrival_entry_1", locations)
    elif beat_kind == "triage_walk":
        _move_entity(patient, "triage_queue_1", locations)
        _move_entity(er_doctor, "triage_desk", locations, status="perform_triage")
    elif beat_kind in {"move_to_bed", "assessment"}:
        _move_entity(patient, _event_location(event, "er_bed_1"), locations)
        _move_entity(er_doctor, "er_bed_1", locations, status="perform_assessment")
        patient["assigned_staff"] = "doctor_er_0"
    elif beat_kind == "move_to_test_hall":
        _move_entity(patient, "hallway_er_to_imaging", locations)
        _move_entity(er_doctor, "nurse_station", locations, status="request_test")
        patient["assigned_staff"] = "doctor_er_0"
    elif beat_kind == "move_to_test":
        _move_entity(patient, _event_location(event, "imaging_wait_1"), locations)
        _move_entity(er_doctor, "nurse_station", locations, status="request_test")
        patient["assigned_staff"] = "doctor_er_0"
    elif beat_kind in {"test", "wait"}:
        _move_entity(patient, _event_location(event, "imaging_wait_1"), locations)
        _move_entity(er_doctor, "nurse_station", locations, status="await_test_results")
        patient["assigned_staff"] = "doctor_er_0"
    elif beat_kind == "observe":
        _move_entity(patient, _event_location(event, "observation_bed_1"), locations)
        _move_entity(er_doctor, "observation_desk_1", locations, status="observe_patient")
        patient["assigned_staff"] = "doctor_er_0"
    elif beat_kind == "consult_call":
        _move_entity(patient, "er_bed_1", locations)
        _move_entity(er_doctor, "er_bed_1", locations, status="make_diagnostic_summary")
        if specialist is not None:
            sidebar_location_id = _specialty_sidebar_location_id(department, locations)
            if sidebar_location_id:
                _move_entity(specialist, sidebar_location_id, locations, status="summoned")
        patient["assigned_staff"] = str(f"specialty_{department}") if department else ""
    elif beat_kind == "move_to_consult_hall":
        if specialist is not None:
            _move_entity(specialist, "hallway_er_to_consult", locations, status="walking")
        _move_entity(patient, "hallway_er_to_consult", locations)
        patient["assigned_staff"] = str(f"specialty_{department}") if department else ""
    elif beat_kind == "consult":
        if specialist is not None:
            _move_entity(specialist, _event_location(event, "specialty_consult_1"), locations, status="consulting")
        _move_entity(patient, _event_location(event, "specialty_consult_1"), locations)
        patient["assigned_staff"] = str(f"specialty_{department}") if department else ""
    elif beat_kind == "complete":
        _move_entity(patient, "discharge_1", locations)
        _move_entity(er_doctor, "er_doctor_station", locations, status="idle")
        patient["assigned_staff"] = ""

    if dialogue:
        actor = str(dialogue.get("actor", "")).strip()
        action = str(dialogue.get("action", "")).strip() or "ask_patient"
        if actor == "er_department":
            if action == "perform_triage":
                _move_entity(patient, "triage_desk", locations)
                _move_entity(er_doctor, "triage_desk", locations, status="perform_triage")
            elif action in {"ask_patient", "request_test", "make_diagnostic_summary", "observe_patient", "discharge"}:
                target_location = _event_location(event, "er_bed_1") if beat_kind not in {"move_to_test_hall", "move_to_test", "test", "wait"} else (
                    "hallway_er_to_imaging" if beat_kind == "move_to_test_hall" else "imaging_wait_1"
                )
                _move_entity(patient, target_location, locations)
                doctor_target = target_location if action == "ask_patient" else ("er_doctor_station" if action == "discharge" else "nurse_station")
                _move_entity(er_doctor, doctor_target, locations, status=action)
                patient["assigned_staff"] = "doctor_er_0"
        elif actor and actor not in {"system"} and specialist is not None:
            _move_entity(patient, _event_location(event, "specialty_consult_1"), locations)
            _move_entity(specialist, _event_location(event, "specialty_consult_1"), locations, status=action or "consulting")
            patient["assigned_staff"] = str(specialist.get("id", "")).strip()


def _apply_replay_outcome_view(view: dict[str, Any], selected_case_id: str, comparison: dict[str, Any]) -> None:
    entities = _scene_entities(view)
    locations = _scene_locations(view)
    patient = _entity_by_case(entities, selected_case_id)
    if patient is not None:
        _move_entity(patient, "discharge_1", locations)
        patient["zone"] = "completed"
        patient["assigned_staff"] = ""
        replay = dict(comparison.get("replay", {}) or {})
        patient["predicted_department"] = str(replay.get("department", "")).strip()
    case_details = dict(view.get("case_details", {}) or {})
    detail = dict(case_details.get(selected_case_id, {}) or {})
    if detail:
        replay = dict(comparison.get("replay", {}) or {})
        detail["zone"] = "completed"
        detail["predicted_department"] = str(replay.get("department", "")).strip()
        detail["predicted_diagnosis"] = str(replay.get("diagnosis", "")).strip()
        case_details[selected_case_id] = detail
        view["case_details"] = case_details
    for patient_row in list(view.get("patients", []) or []):
        if str(dict(patient_row).get("case_id", "")).strip() != str(selected_case_id).strip():
            continue
        patient_row["zone"] = "completed"
        patient_row["predicted_department"] = str(dict(comparison.get("replay", {}) or {}).get("department", "")).strip()
        patient_row["predicted_diagnosis"] = str(dict(comparison.get("replay", {}) or {}).get("diagnosis", "")).strip()
        break
    view["dialogue"] = {
        "case_id": str(selected_case_id).strip(),
        "actor": "what_if_replay",
        "action": "replay_outcome",
        "lines": [
            f"Replay Department: {str(dict(comparison.get('replay', {}) or {}).get('department', '')).strip() or '-'}",
            f"Replay Diagnosis: {str(dict(comparison.get('replay', {}) or {}).get('diagnosis', '')).strip() or '-'}",
        ],
        "speaker_entity_id": f"patient_{selected_case_id}",
        "listener_entity_id": "",
        "bubble_text": "Replay outcome ready",
    }


def _apply_event_case_view(
    view: dict[str, Any],
    selected_case_id: str,
    beat: dict[str, Any],
) -> None:
    event = dict(beat.get("event", {}) or {})
    if not event:
        return
    case_details = dict(view.get("case_details", {}) or {})
    detail = dict(case_details.get(selected_case_id, {}) or {})
    state_delta = dict(event.get("state_delta", {}) or {})
    payload = dict(event.get("payload", {}) or {})
    if detail:
        for key in ("zone", "pending_results_count", "triage_level", "effective_triage_level"):
            if key in state_delta:
                detail[key] = state_delta.get(key)
        if str(payload.get("department", "")).strip():
            detail["predicted_department"] = str(payload.get("department", "")).strip()
        if str(payload.get("diagnosis", "")).strip():
            detail["predicted_diagnosis"] = str(payload.get("diagnosis", "")).strip()
        detail["current_event"] = {
            "minute": int(event.get("minute", 0) or 0),
            "event_type": str(event.get("event_type", "")).strip(),
            "action": str(event.get("action", "")).strip(),
            "label": str(beat.get("label", "")).strip(),
            "rationale": str(event.get("rationale", "")).strip(),
            "payload": payload,
        }
        case_details[selected_case_id] = detail
        view["case_details"] = case_details
    for patient_row in list(view.get("patients", []) or []):
        if str(dict(patient_row).get("case_id", "")).strip() != str(selected_case_id).strip():
            continue
        for key in ("zone", "triage_level", "effective_triage_level"):
            if key in state_delta:
                patient_row[key] = state_delta.get(key)
        if str(payload.get("department", "")).strip():
            patient_row["predicted_department"] = str(payload.get("department", "")).strip()
        if str(payload.get("diagnosis", "")).strip():
            patient_row["predicted_diagnosis"] = str(payload.get("diagnosis", "")).strip()
        break


def _apply_replay_case_view(
    view: dict[str, Any],
    selected_case_id: str,
    replay_summary: dict[str, Any],
    beat: dict[str, Any],
) -> None:
    replay_result = dict(replay_summary.get("replay_result", {}) or {})
    comparison = dict(replay_summary.get("comparison", {}) or {})
    case_details = dict(view.get("case_details", {}) or {})
    detail = dict(case_details.get(selected_case_id, {}) or {})
    detail_update = dict(beat.get("detail_update", {}) or {})
    if detail and replay_result:
        detail["questions"] = list(detail_update.get("questions", replay_result.get("questions", [])) or [])
        detail["tests"] = list(detail_update.get("tests", replay_result.get("tests", [])) or [])
        detail["objective_findings"] = list(detail_update.get("objective_findings", replay_result.get("objective_findings", [])) or [])
        detail["predicted_department"] = str(detail_update.get("predicted_department", replay_result.get("predicted_department", ""))).strip()
        detail["predicted_diagnosis"] = str(detail_update.get("predicted_diagnosis", replay_result.get("predicted_diagnosis", ""))).strip()
        detail["pending_results_count"] = int(detail_update.get("pending_results_count", 0) or 0)
        detail["zone"] = str(detail_update.get("zone", detail.get("zone", ""))).strip() or str(detail.get("zone", "")).strip()
        case_details[selected_case_id] = detail
        view["case_details"] = case_details
    for patient_row in list(view.get("patients", []) or []):
        if str(dict(patient_row).get("case_id", "")).strip() != str(selected_case_id).strip():
            continue
        if replay_result:
            patient_row["predicted_department"] = str(detail_update.get("predicted_department", replay_result.get("predicted_department", ""))).strip()
            patient_row["predicted_diagnosis"] = str(detail_update.get("predicted_diagnosis", replay_result.get("predicted_diagnosis", ""))).strip()
        patient_row["zone"] = str(detail_update.get("zone", patient_row.get("zone", ""))).strip() or str(patient_row.get("zone", "")).strip()
        break
    if str(beat.get("kind", "")).strip() == "complete" and comparison:
        _apply_replay_outcome_view(view, selected_case_id, comparison)


def presented_snapshot(snapshot: dict[str, Any], playback_state: dict[str, Any], selected_case_id: str) -> dict[str, Any]:
    view = deepcopy(snapshot)
    state = dict(playback_state or {})
    detail = _current_case_detail(view, selected_case_id)
    state = _normalize_selection_state(state, detail)
    if dict(state.get("replay_summary", {}) or {}).get("replay_result") and not dict(state.get("replay_summary", {}) or {}).get("presentation_beats"):
        replay_summary = dict(state.get("replay_summary", {}) or {})
        replay_summary["presentation_beats"] = _build_replay_beats(replay_summary, selected_case_id)
        state["replay_summary"] = replay_summary
    beats = _active_beats(state)
    beat_index = min(max(int(state.get("beat_index", 0) or 0), 0), max(len(beats) - 1, 0))
    beat = dict(beats[beat_index] or {}) if beats else {}
    decision_points = list(detail.get("decision_points", []) or [])
    selected_decision = (
        dict(decision_points[int(state.get("selected_decision_index", 0) or 0)] or {})
        if decision_points
        else {}
    )
    candidates = list(selected_decision.get("alternatives", []) or []) or list(detail.get("counterfactual_candidates", []) or [])
    selected_candidate = (
        dict(candidates[int(state.get("selected_candidate_index", 0) or 0)] or {})
        if candidates
        else {}
    )
    if beat.get("dialogue"):
        view["dialogue"] = dict(beat.get("dialogue", {}) or {})
    _apply_beat_scene(view, beat, selected_case_id)
    _apply_event_case_view(view, selected_case_id, beat)
    view["presentation"] = {
        "paused": bool(state.get("paused", False)),
        "what_if_enabled": bool(state.get("what_if_enabled", False)),
        "what_if_preview_enabled": bool(state.get("what_if_preview_enabled", False)),
        "beat_index": beat_index,
        "beat_count": len(beats),
        "current_beat": beat,
        "selected_case_id": str(selected_case_id).strip(),
        "selected_decision_index": int(state.get("selected_decision_index", 0) or 0),
        "selected_decision": selected_decision,
        "selected_candidate_index": int(state.get("selected_candidate_index", 0) or 0),
        "selected_candidate": selected_candidate,
        "replay_status": str(state.get("replay_status", "")).strip(),
        "replay_summary": dict(state.get("replay_summary", {}) or {}),
        "show_replay_outcome": bool(state.get("show_replay_outcome", False)),
    }
    if bool(state.get("what_if_preview_enabled", False)) and selected_candidate:
        beat_label = str(beat.get("label", "Scene")).strip()
        candidate_type = str(selected_candidate.get("type", "")).strip() or "alternative"
        candidate_target = str(selected_candidate.get("target", "")).strip()
        candidate_rationale = str(selected_candidate.get("rationale", "")).strip() or str(selected_decision.get("rationale", "")).strip()
        preview_label = f"What-If Preview: {candidate_type}"
        if candidate_target:
            preview_label = f"{preview_label} -> {candidate_target}"
        view["presentation"]["current_beat"] = {
            **beat,
            "label": f"{beat_label} | {preview_label}",
            "preview_action": selected_candidate,
        }
        view["presentation"]["preview_overlay"] = {
            "case_id": str(selected_case_id).strip(),
            "action_type": candidate_type,
            "target": candidate_target,
            "target_location_id": _preview_target_location_id(selected_candidate),
            "snapshot_id": str(selected_decision.get("snapshot_id", "")).strip(),
            "rationale": candidate_rationale,
        }
    replay_summary = dict(state.get("replay_summary", {}) or {})
    comparison = dict(replay_summary.get("comparison", {}) or {})
    if bool(state.get("show_replay_outcome", False)) and replay_summary:
        _apply_replay_case_view(
            view,
            selected_case_id,
            replay_summary,
            beat,
        )
    if bool(state.get("show_replay_outcome", False)) and comparison:
        current_beat = dict(view["presentation"].get("current_beat", {}) or {})
        view["presentation"]["current_beat"] = {
            **current_beat,
            "label": f"{str(current_beat.get('label', 'Scene')).strip()} | Replay Outcome",
            "kind": "replay_outcome" if str(current_beat.get("kind", "")).strip() == "complete" else str(current_beat.get("kind", "")).strip(),
        }
        view["presentation"]["replay_overlay"] = {
            "case_id": str(selected_case_id).strip(),
            "comparison": comparison,
            "selected_action": dict(replay_summary.get("selected_action", {}) or {}),
            "replay_result": dict(replay_summary.get("replay_result", {}) or {}),
        }
    return view
