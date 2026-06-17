from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.hospital_route_graph import normalize_movement_path


LAYOUT_PATH = settings.PROJECT_ROOT / "app" / "data" / "hospital_scene_layout.json"


@lru_cache(maxsize=1)
def load_hospital_scene_layout() -> dict[str, Any]:
    with open(LAYOUT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _zone_slots(layout: dict[str, Any], zone_key: str) -> list[str]:
    zone_slots = dict(layout.get("zone_slots", {}) or {})
    return [str(value).strip() for value in list(zone_slots.get(zone_key, []) or []) if str(value).strip()]


def _location(layout: dict[str, Any], location_id: str) -> dict[str, Any]:
    locations = dict(layout.get("locations", {}) or {})
    return dict(locations.get(location_id, {}) or {})


def _bedside_location_id(location_id: str) -> str:
    value = str(location_id).strip()
    if value.startswith("er_bed_"):
        suffix = value.split("er_bed_", 1)[-1]
        return f"er_bedside_{suffix}"
    return value


def _assigned_slot(runtime_scene_state: dict[str, Any], case_id: str) -> str:
    for key in ("waiting_seats", "er_beds", "observation_beds", "await_slots", "specialty_consults", "discharge_slots"):
        slot_map = dict(runtime_scene_state.get(key, {}) or {})
        for slot_id, assigned_case_id in slot_map.items():
            if assigned_case_id == case_id:
                return str(slot_id).strip()
    return ""


def _assign_patient_entities(layout: dict[str, Any], patients: list[dict[str, Any]], runtime_scene_state: dict[str, Any]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    zone_counters: dict[str, int] = {}
    patient_overrides = dict(runtime_scene_state.get("patient_overrides", {}) or {})
    for patient in patients:
        zone = str(patient.get("zone", "waiting_room")).strip() or "waiting_room"
        case_id = str(patient.get("case_id", "")).strip()
        location_id = str(patient_overrides.get(case_id, "")).strip() or _assigned_slot(runtime_scene_state, case_id)
        if not location_id:
            index = zone_counters.get(zone, 0)
            zone_counters[zone] = index + 1
            slots = _zone_slots(layout, zone)
            location_id = slots[index] if index < len(slots) else (slots[-1] if slots else zone)
        location = _location(layout, location_id)
        entities.append(
            {
                "id": f"patient_{case_id}",
                "kind": "patient",
                "case_id": case_id,
                "zone": zone,
                "location_id": location_id,
                "x": location.get("x"),
                "y": location.get("y"),
                "predicted_department": str(patient.get("predicted_department", "")).strip(),
                "triage_level": int(patient.get("triage_level", 3) or 3),
                "effective_triage_level": int(patient.get("effective_triage_level", 3) or 3),
                "alerts": list(patient.get("alerts", []) or []),
                "last_action": str(patient.get("last_action", "")).strip(),
                "last_actor": str(patient.get("actor", "")).strip(),
                "assigned_staff": str(patient.get("assigned_staff", "")).strip(),
                "movement_target_id": str(patient.get("movement_target_id", "")).strip(),
                "current_location_id": str(patient.get("current_location_id", "")).strip(),
                "target_location_id": str(patient.get("target_location_id", "")).strip(),
                "interaction_location_id": str(patient.get("interaction_location_id", "")).strip(),
                "movement_path": normalize_movement_path(
                    [str(item).strip() for item in list(patient.get("movement_path", []) or []) if str(item).strip()],
                    current_location_id=str(patient.get("current_location_id", "")).strip(),
                    target_location_id=str(patient.get("target_location_id", "")).strip() or location_id,
                ),
                "pending_interaction": dict(patient.get("pending_interaction", {}) or {}),
            }
        )
    return entities


def _latest_active_case(case_state_map: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    active_items = []
    for item in case_state_map.values():
        state = dict(item.get("state", {}) or {})
        active_items.append(
            (
                int(state.get("current_time_min", 0) or 0),
                dict(item),
            )
        )
    if not active_items:
        return None
    active_items.sort(key=lambda pair: pair[0], reverse=True)
    return active_items[0][1]


def _build_er_doctor_entity(
    layout: dict[str, Any],
    case_state_map: dict[str, dict[str, Any]],
    patient_entities: list[dict[str, Any]],
    runtime_scene_state: dict[str, Any],
) -> dict[str, Any]:
    staff_slots = dict(layout.get("staff_slots", {}) or {})
    default_location_id = str(staff_slots.get("er_doctor", "er_doctor_station")).strip()
    location_id = default_location_id
    status = "idle"
    paired_case_id = str((runtime_scene_state.get("doctor_pairings", {}) or {}).get("er", "")).strip()
    doctor_overrides = dict(runtime_scene_state.get("doctor_overrides", {}) or {})
    override_payload = doctor_overrides.get("er", {})
    if isinstance(override_payload, str):
        override_payload = {"location_id": str(override_payload).strip()}
    else:
        override_payload = dict(override_payload or {})
    override_location_id = str(override_payload.get("location_id", "")).strip()
    if override_location_id:
        location_id = override_location_id

    active = _latest_active_case(case_state_map)
    active_state: dict[str, Any] = {}
    if active is not None:
        actor = str(active.get("actor", "")).strip()
        assigned_bed_id = str(active.get("assigned_bed_id", "")).strip()
        bedside_location_id = _bedside_location_id(assigned_bed_id) if assigned_bed_id else default_location_id
        active_state = dict(active.get("state", {}) or {})
        if actor == "er_department":
            action = str(active.get("action", "")).strip()
            status = action or "active"
            if paired_case_id and action in {"ask_history", "perform_assessment", "order_test", "request_specialty", "review_results", "await_results"}:
                location_id = bedside_location_id
            else:
                location_id = default_location_id

    location = _location(layout, location_id)
    target_location_id = str(override_payload.get("location_id", "")).strip() or location_id
    current_location_id = str(override_payload.get("current_location_id", "")).strip() or default_location_id
    interaction_location_id = str(override_payload.get("interaction_location_id", "")).strip()
    movement_path: list[str] = [str(item).strip() for item in list(override_payload.get("movement_path", []) or []) if str(item).strip()]
    pending_interaction: dict[str, Any] = {}
    if active is not None:
        active_action = str(active.get("action", "")).strip()
        interaction_location_id = str(override_payload.get("interaction_location_id", "")).strip() or str(active_state.get("interaction_location_id", "")).strip()
        pending_interaction = dict(active_state.get("pending_interaction", {}) or {})
        if paired_case_id and active_action in {"dispatch_er", "perform_assessment", "ask_history", "order_test", "request_specialty", "review_results", "await_results", "er_finalize"}:
            target_location_id = str(override_payload.get("location_id", "")).strip() or interaction_location_id or bedside_location_id
            current_location_id = str(override_payload.get("current_location_id", "")).strip() or current_location_id
            movement_path = [str(item).strip() for item in list(override_payload.get("movement_path", []) or []) if str(item).strip()]
            if not movement_path:
                movement_path = [current_location_id, target_location_id] if target_location_id and target_location_id != current_location_id else [target_location_id]
        else:
            target_location_id = location_id
            current_location_id = location_id
            movement_path = [location_id] if location_id else []
    elif not movement_path:
        movement_path = [current_location_id, target_location_id] if target_location_id and target_location_id != current_location_id else [target_location_id]
    return {
        "id": "doctor_er_0",
        "kind": "doctor",
        "role": "er",
        "location_id": location_id,
        "x": location.get("x"),
        "y": location.get("y"),
        "status": status,
        "case_id": paired_case_id,
        "current_location_id": current_location_id,
        "target_location_id": target_location_id,
        "interaction_location_id": interaction_location_id,
        "movement_path": normalize_movement_path(
            movement_path,
            current_location_id=current_location_id,
            target_location_id=target_location_id,
        ),
        "pending_interaction": pending_interaction,
    }


def _build_specialty_entities(
    layout: dict[str, Any],
    case_state_map: dict[str, dict[str, Any]],
    patient_entities: list[dict[str, Any]],
    runtime_scene_state: dict[str, Any],
    current_time_min: int,
) -> list[dict[str, Any]]:
    staff_slots = dict(layout.get("staff_slots", {}) or {})
    specialty_sidebar = dict(staff_slots.get("specialty_sidebar", {}) or {})
    consult_slots = [str(value).strip() for value in list(staff_slots.get("specialty_consult_slots", []) or []) if str(value).strip()]
    specialty_calls = dict(runtime_scene_state.get("specialty_calls", {}) or {})
    specialty_consults = dict(runtime_scene_state.get("specialty_consults", {}) or {})

    active_by_department: dict[str, dict[str, Any]] = {}
    for item in case_state_map.values():
        actor = str(item.get("actor", "")).strip()
        if not actor or actor in {"system", "er_department"}:
            continue
        active_by_department[actor] = dict(item)

    entities: list[dict[str, Any]] = []
    consult_index = 0
    for department, sidebar_location_id in specialty_sidebar.items():
        location_id = str(sidebar_location_id).strip()
        status = "waiting"
        case_id = ""
        target_location_id = location_id
        current_location_id = location_id
        interaction_location_id = ""
        movement_path: list[str] = [location_id] if location_id else []
        pending_interaction: dict[str, Any] = {}
        active = active_by_department.get(department)
        call = dict(specialty_calls.get(department, {}) or {})
        if call:
            case_id = str(call.get("case_id", "")).strip()
            arrival_min = int(call.get("arrival_min", 0) or 0)
            status = str(call.get("status", "")).strip() or "summoned"
            case_state = dict(dict(case_state_map.get(case_id, {}) or {}).get("state", {}) or {})
            interaction_location_id = str(case_state.get("interaction_location_id", "")).strip()
            pending_interaction = dict(case_state.get("pending_interaction", {}) or {})
            resource_current_location_id = str(call.get("current_location_id", "")).strip() or str(sidebar_location_id).strip()
            if status == "summoned" and current_time_min < arrival_min:
                location_id = str(sidebar_location_id).strip()
            else:
                patient_entity = next((entity for entity in patient_entities if entity.get("case_id") == case_id), None)
                if patient_entity is not None:
                    patient_location = str(patient_entity.get("location_id", "")).strip() or location_id
                    location_id = _bedside_location_id(patient_location)
                else:
                    assigned_slot = next(
                        (slot_id for slot_id, assigned_case_id in specialty_consults.items() if assigned_case_id == case_id),
                        "",
                    )
                    if assigned_slot:
                        location_id = str(assigned_slot).strip()
                    elif consult_index < len(consult_slots):
                        location_id = consult_slots[consult_index]
                        consult_index += 1
                if active is not None:
                    status = str(active.get("action", "")).strip() or "consulting"
            target_location_id = interaction_location_id or location_id
            current_location_id = resource_current_location_id
            movement_path = [current_location_id, target_location_id] if target_location_id and target_location_id != current_location_id else [target_location_id]

        location = _location(layout, location_id)
        entities.append(
            {
                "id": f"specialty_{department}",
                "kind": "doctor",
                "role": "specialty",
                "department": department,
                "location_id": location_id,
                "x": location.get("x"),
                "y": location.get("y"),
                "status": status,
                "case_id": case_id,
                "summoned_min": int(call.get("summoned_min", 0) or 0),
                "arrival_min": int(call.get("arrival_min", 0) or 0),
                "eta_min": max(0, int(call.get("arrival_min", 0) or 0) - current_time_min) if status == "summoned" else 0,
                "current_location_id": current_location_id,
                "target_location_id": target_location_id,
                "interaction_location_id": interaction_location_id,
                "movement_path": normalize_movement_path(
                    movement_path,
                    current_location_id=current_location_id,
                    target_location_id=target_location_id,
                ),
                "pending_interaction": pending_interaction,
            }
        )

    return entities


def _build_support_staff_entities(layout: dict[str, Any]) -> list[dict[str, Any]]:
    support_specs = [
        ("nurse_triage", "nurse", "triage_desk"),
        ("nurse_bed_1", "nurse", "nurse_base_1"),
        ("nurse_bed_2", "nurse", "nurse_base_2"),
        ("nurse_bed_3", "nurse", "nurse_base_3"),
        ("nurse_bed_4", "nurse", "nurse_base_4"),
        ("reception_staff", "reception", "waiting_side_table_1"),
    ]
    entities: list[dict[str, Any]] = []
    for entity_id, role, location_id in support_specs:
        location = _location(layout, location_id)
        if not location:
            continue
        entities.append(
            {
                "id": entity_id,
                "kind": "doctor",
                "role": role,
                "department": "",
                "location_id": location_id,
                "x": location.get("x"),
                "y": location.get("y"),
                "status": "idle",
                "case_id": "",
                "current_location_id": location_id,
                "target_location_id": location_id,
                "interaction_location_id": "",
                "movement_path": normalize_movement_path(
                    [location_id],
                    current_location_id=location_id,
                    target_location_id=location_id,
                ),
                "pending_interaction": {},
            }
        )
    return entities


def _apply_support_staff_runtime(
    layout: dict[str, Any],
    support_entities: list[dict[str, Any]],
    runtime_scene_state: dict[str, Any],
) -> list[dict[str, Any]]:
    nurse_overrides = dict(runtime_scene_state.get("nurse_overrides", {}) or {})
    for entity in support_entities:
        entity_id = str(entity.get("id", "")).strip()
        override = dict(nurse_overrides.get(entity_id, {}) or {})
        if not override:
            continue
        override_location_id = str(override.get("location_id", "")).strip()
        if not override_location_id:
            continue
        location = _location(layout, override_location_id)
        if not location:
            continue
        current_location_id = str(override.get("current_location_id", "")).strip() or str(entity.get("current_location_id", "")).strip() or str(entity.get("location_id", "")).strip()
        target_location_id = override_location_id
        interaction_location_id = str(override.get("interaction_location_id", "")).strip()
        movement_path = [str(item).strip() for item in list(override.get("movement_path", []) or []) if str(item).strip()]
        if not movement_path:
            if current_location_id and target_location_id and current_location_id != target_location_id:
                movement_path = [current_location_id, target_location_id]
            elif target_location_id:
                movement_path = [target_location_id]
        entity["location_id"] = override_location_id
        entity["x"] = location.get("x")
        entity["y"] = location.get("y")
        entity["status"] = str(override.get("status", "")).strip() or "escort"
        entity["case_id"] = str(override.get("case_id", "")).strip()
        entity["current_location_id"] = current_location_id
        entity["target_location_id"] = target_location_id
        entity["interaction_location_id"] = interaction_location_id
        entity["movement_path"] = normalize_movement_path(
            movement_path,
            current_location_id=current_location_id,
            target_location_id=target_location_id,
        )
        entity["pending_interaction"] = dict(override.get("pending_interaction", {}) or {})
    return support_entities


def build_hospital_scene_snapshot(
    *,
    patients: list[dict[str, Any]],
    case_state_map: dict[str, dict[str, Any]],
    runtime_scene_state: dict[str, Any],
    current_time_min: int,
) -> dict[str, Any]:
    layout = load_hospital_scene_layout()
    patient_entities = _assign_patient_entities(layout, patients, runtime_scene_state)
    support_entities = _apply_support_staff_runtime(
        layout,
        _build_support_staff_entities(layout),
        runtime_scene_state,
    )
    staff_entities = [
        _build_er_doctor_entity(layout, case_state_map, patient_entities, runtime_scene_state),
        *_build_specialty_entities(layout, case_state_map, patient_entities, runtime_scene_state, current_time_min),
        *support_entities,
    ]
    return {
        "layout_id": str(layout.get("layout_id", "")).strip(),
        "tile_size": int(layout.get("tile_size", 16) or 16),
        "zone_slots": dict(layout.get("zone_slots", {}) or {}),
        "locations": dict(layout.get("locations", {}) or {}),
        "entities": [
            *patient_entities,
            *staff_entities,
        ],
    }
