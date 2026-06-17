from __future__ import annotations

from typing import Any

from app.ui.pixel_viewer.entity_renderer import to_screen_coords


def _preferred_facing(entity: dict[str, Any], location_id: str, kind: str, previous: str) -> str:
    role = str(entity.get("role", "")).strip()
    zone = str(entity.get("zone", "")).strip().lower()
    entity_kind = str(entity.get("kind", "")).strip()
    if role == "reception":
        return "down"
    if role == "nurse" and "triage" in location_id:
        return "down"
    if "arrival_entry" in location_id or "arrival_lane" in location_id:
        return "up"
    if "triage_queue" in location_id:
        return "up"
    if kind in {"desk", "staff_station"}:
        return "up"
    if kind == "consult":
        return "right" if entity_kind == "doctor" else "left"
    if kind == "sidebar":
        return "left"
    if kind == "bed":
        if entity_kind == "doctor":
            return "left" if "specialty" in role else "right"
        return previous or "down"
    if kind == "seat":
        if zone == "waiting_room":
            return "down"
        return "up"
    return previous or "down"


def _facing_from_delta(dx: float, dy: float, previous: str) -> str:
    if abs(dx) + abs(dy) <= 0.45:
        return previous or "down"
    if abs(dy) > abs(dx):
        return "down" if dy > 0 else "up"
    return "right" if dx > 0 else "left"


def _target_screen_position(
    entity: dict[str, Any],
    locations: dict[str, Any],
    map_origin_x: int,
    map_origin_y: int,
    map_tile: int,
) -> tuple[float, float, str]:
    location_id = str(entity.get("location_id", "")).strip()
    location = dict(locations.get(location_id, {}) or {})
    kind = str(location.get("kind", "")).strip()
    x = int(entity.get("x", 0) or 0)
    y = int(entity.get("y", 0) or 0)
    sx, sy = to_screen_coords(x, y, map_origin_x, map_origin_y, map_tile)

    offset_x = 0
    offset_y = 0
    role = str(entity.get("role", "")).strip()
    entity_kind = str(entity.get("kind", "")).strip()
    previous = str(entity.get("facing", "down"))
    facing = _preferred_facing(entity, location_id, kind, previous)

    if kind == "desk":
        if "triage" in location_id:
            offset_x, offset_y = -8, 12
            if role == "nurse":
                offset_x, offset_y = 4, 10
            elif role == "reception":
                offset_x, offset_y = -2, 12
        elif "specialty_desk" in location_id:
            offset_x, offset_y = 4, 10
        else:
            offset_x, offset_y = 4, 10
    elif kind == "staff_station":
        offset_x, offset_y = 4, 10
    elif kind == "seat":
        if "specialty_chair" in location_id:
            offset_x, offset_y = -2, 8
        else:
            offset_x, offset_y = -1, 10
    elif kind == "bed":
        if entity_kind == "patient":
            offset_x, offset_y = 1, 1
        else:
            offset_x = -10 if x >= 16 else 12
            offset_y = 5
            facing = "left" if x >= 16 else "right"
    elif kind == "consult":
        if entity_kind == "doctor":
            offset_x, offset_y = -14, 6
            facing = "right"
        else:
            offset_x, offset_y = 14, 6
            facing = "left"
    elif kind == "equipment":
        offset_x = 10 if "imaging" in location_id else -6
        offset_y = 4
    elif kind == "queue":
        if "arrival_entry" in location_id:
            offset_x, offset_y = 0, 12
        elif "arrival_lane" in location_id:
            offset_x, offset_y = 0, 8
        elif "triage_queue" in location_id:
            offset_x, offset_y = 0, 10
        else:
            offset_x, offset_y = 0, 6
    elif kind == "sidebar":
        offset_x, offset_y = 4, 4
        facing = "left"

    return float(sx + offset_x), float(sy + offset_y), facing


def update_entity_render_positions(
    snapshot: dict[str, Any],
    render_positions: dict[str, dict[str, float]],
    map_origin_x: int,
    map_origin_y: int,
    map_tile: int,
) -> None:
    scene = dict(snapshot.get("scene", {}) or {})
    entities = list(scene.get("entities", []) or [])
    locations = dict(scene.get("locations", {}) or {})
    active_ids: set[str] = set()
    for entity in entities:
        entity_id = str(entity.get("id", "")).strip()
        if not entity_id:
            continue
        active_ids.add(entity_id)
        sx, sy, preferred_facing = _target_screen_position(entity, locations, map_origin_x, map_origin_y, map_tile)
        entry = render_positions.setdefault(
            entity_id,
            {
                "current_x": float(sx),
                "current_y": float(sy),
                "target_x": float(sx),
                "target_y": float(sy),
                "facing": "down",
                "anim_tick": 0,
            },
        )
        entry["target_x"] = float(sx)
        entry["target_y"] = float(sy)
        location_id = str(entity.get("location_id", "")).strip()
        entity["location_kind"] = str(dict(locations.get(location_id, {}) or {}).get("kind", "")).strip()
        entity["render_x"] = entry["current_x"]
        entity["render_y"] = entry["current_y"]
        entity["move_dx"] = entry["target_x"] - entry["current_x"]
        entity["move_dy"] = entry["target_y"] - entry["current_y"]
        entity["moving"] = abs(entity["move_dx"]) + abs(entity["move_dy"]) > 0.45
        entry["facing"] = _facing_from_delta(float(entity["move_dx"]), float(entity["move_dy"]), preferred_facing)
        if not bool(entity["moving"]):
            entry["facing"] = preferred_facing
        entity["facing"] = str(entry.get("facing", "down"))
        entity["anim_tick"] = int(entry.get("anim_tick", 0) or 0)

    for entity_id in list(render_positions.keys()):
        if entity_id not in active_ids:
            del render_positions[entity_id]


def animate_entity_render_positions(
    snapshot: dict[str, Any],
    render_positions: dict[str, dict[str, float]],
    move_speed: float,
    map_origin_x: int,
    map_origin_y: int,
    map_tile: int,
) -> None:
    scene = dict(snapshot.get("scene", {}) or {})
    entities = list(scene.get("entities", []) or [])
    locations = dict(scene.get("locations", {}) or {})
    for entity in entities:
        entity_id = str(entity.get("id", "")).strip()
        if not entity_id:
            continue
        entry = render_positions.get(entity_id)
        if not entry:
            sx, sy, _ = _target_screen_position(entity, locations, map_origin_x, map_origin_y, map_tile)
            entry = {
                "current_x": float(sx),
                "current_y": float(sy),
                "target_x": float(sx),
                "target_y": float(sy),
                "facing": "down",
                "anim_tick": 0,
            }
            render_positions[entity_id] = entry
        target_x, target_y, preferred_facing = _target_screen_position(entity, locations, map_origin_x, map_origin_y, map_tile)
        entry["target_x"] = float(target_x)
        entry["target_y"] = float(target_y)
        location_id = str(entity.get("location_id", "")).strip()
        entity["location_kind"] = str(dict(locations.get(location_id, {}) or {}).get("kind", "")).strip()
        entry["current_x"] += (entry["target_x"] - entry["current_x"]) * move_speed
        entry["current_y"] += (entry["target_y"] - entry["current_y"]) * move_speed
        entity["render_x"] = entry["current_x"]
        entity["render_y"] = entry["current_y"]
        entity["move_dx"] = entry["target_x"] - entry["current_x"]
        entity["move_dy"] = entry["target_y"] - entry["current_y"]
        entity["moving"] = abs(entity["move_dx"]) + abs(entity["move_dy"]) > 0.45
        entry["facing"] = _facing_from_delta(float(entity["move_dx"]), float(entity["move_dy"]), preferred_facing)
        if not bool(entity["moving"]):
            entry["facing"] = preferred_facing
        entry["anim_tick"] = int(entry.get("anim_tick", 0) or 0) + 1
        entity["facing"] = str(entry.get("facing", "down"))
        entity["anim_tick"] = int(entry.get("anim_tick", 0) or 0)
