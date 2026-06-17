from __future__ import annotations

import json
from collections import deque
from functools import lru_cache
from typing import Any

from app.config import settings


LAYOUT_PATH = settings.PROJECT_ROOT / "app" / "data" / "hospital_scene_layout.json"

ROUTE_GRAPH: dict[str, list[str]] = {
    "triage_desk": ["hallway_waiting_entry"],
    "hallway_waiting_entry": ["triage_desk", "door_waiting_to_er"],
    "door_waiting_to_er": ["hallway_waiting_entry", "hallway_er_lower"],
    "hallway_er_lower": ["door_waiting_to_er", "hallway_er_center", "hallway_observation_entry", "hallway_diagnostics_lower"],
    "hallway_er_center": ["hallway_er_lower", "hallway_er_upper", "door_er_to_observation"],
    "hallway_er_upper": ["hallway_er_center", "door_er_to_diagnostics", "hallway_er_to_consult"],
    "door_er_to_diagnostics": ["hallway_er_upper", "hallway_diagnostics_entry"],
    "hallway_diagnostics_entry": ["door_er_to_diagnostics", "hallway_er_to_imaging", "hallway_diagnostics_lower"],
    "hallway_diagnostics_lower": ["hallway_diagnostics_entry", "hallway_er_lower"],
    "hallway_er_to_imaging": ["hallway_diagnostics_entry"],
    "door_er_to_observation": ["hallway_er_center", "hallway_observation_entry"],
    "hallway_observation_entry": ["door_er_to_observation", "hallway_er_lower"],
    "hallway_er_to_consult": ["hallway_er_upper", "hallway_consult_upper"],
    "hallway_consult_upper": ["hallway_er_to_consult", "hallway_consult_entry"],
    "hallway_consult_entry": ["hallway_consult_upper", "door_consult_entry", "hallway_consult_lower", "hallway_consult_to_er"],
    "hallway_consult_lower": ["hallway_consult_entry"],
    "door_consult_entry": ["hallway_consult_entry"],
    "hallway_consult_to_er": ["hallway_consult_entry", "hallway_er_center"],
}


@lru_cache(maxsize=1)
def load_route_layout() -> dict[str, Any]:
    with open(LAYOUT_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _location_map() -> dict[str, Any]:
    return dict(load_route_layout().get("locations", {}) or {})


def anchor_node_for_location(location_id: str) -> str:
    value = str(location_id).strip()
    if not value:
        return ""
    if value.startswith("hallway_") or value.startswith("door_"):
        return value
    if value.startswith("arrival_") or value.startswith("triage_") or value.startswith("waiting_"):
        return "hallway_waiting_entry"
    if value == "triage_desk":
        return "triage_desk"
    if value in {"er_doctor_station", "nurse_station", "chart_desk_1", "chart_desk_2"}:
        return "hallway_er_lower"
    if value in {"er_bed_1", "er_bed_2", "er_bedside_1", "er_bedside_2", "bedside_monitor_1", "bedside_monitor_2"}:
        return "hallway_er_upper"
    if value in {"er_bed_3", "er_bed_4", "er_bedside_3", "er_bedside_4", "bedside_monitor_3", "bedside_monitor_4"}:
        return "hallway_er_lower"
    if value.startswith("observation_"):
        return "hallway_observation_entry"
    if value.startswith("imaging_") or value in {"imaging_machine", "hallway_er_to_imaging"}:
        return "hallway_diagnostics_entry"
    if value.startswith("lab_") or value == "lab_station":
        return "hallway_diagnostics_lower"
    if value in {"specialty_consult_1", "specialty_chair_1"}:
        return "hallway_consult_upper"
    if value in {"specialty_consult_2", "specialty_chair_2"}:
        return "hallway_consult_entry"
    if value in {"specialty_consult_3", "specialty_chair_3"}:
        return "hallway_consult_lower"
    if value.startswith("sidebar_") or value in {"specialty_desk_1", "specialty_desk_2", "specialty_desk_3", "specialty_desk_4"}:
        return "hallway_consult_upper"
    if value in {"specialty_desk_5", "specialty_desk_6"}:
        return "hallway_consult_entry"
    if value.startswith("specialty_desk_") or value.startswith("specialty_chair_"):
        return "hallway_consult_lower"
    if value.startswith("discharge_"):
        return "hallway_waiting_entry"
    return ""


def shortest_route_nodes(start_node: str, end_node: str) -> list[str]:
    start = str(start_node).strip()
    end = str(end_node).strip()
    if not start or not end:
        return []
    if start == end:
        return [start]
    queue: deque[list[str]] = deque([[start]])
    visited = {start}
    while queue:
        path = queue.popleft()
        node = path[-1]
        for nxt in list(ROUTE_GRAPH.get(node, []) or []):
            if nxt in visited:
                continue
            next_path = path + [nxt]
            if nxt == end:
                return next_path
            visited.add(nxt)
            queue.append(next_path)
    return [start, end]


def waypoint_ids_for_route(from_location_id: str, to_location_id: str) -> list[str]:
    from_id = str(from_location_id).strip()
    to_id = str(to_location_id).strip()
    if not to_id:
        return []
    if not from_id or from_id == to_id:
        return [to_id]
    route: list[str] = [from_id]
    from_anchor = anchor_node_for_location(from_id)
    to_anchor = anchor_node_for_location(to_id)
    if from_anchor and from_anchor != from_id:
        route.append(from_anchor)
    if from_anchor and to_anchor:
        anchor_path = shortest_route_nodes(from_anchor, to_anchor)
        route.extend(anchor_path[1:] if route else anchor_path)
    elif to_anchor:
        route.append(to_anchor)
    if to_id != to_anchor:
        route.append(to_id)
    deduped: list[str] = []
    for item in route:
        if item and (not deduped or deduped[-1] != item):
            deduped.append(item)
    return deduped


def normalize_movement_path(
    movement_path: list[str] | None,
    *,
    current_location_id: str = "",
    target_location_id: str = "",
) -> list[str]:
    points = [str(item).strip() for item in list(movement_path or []) if str(item).strip()]
    if not points:
        start = str(current_location_id).strip()
        end = str(target_location_id).strip() or start
        return waypoint_ids_for_route(start, end)
    if len(points) == 1:
        start = str(current_location_id).strip()
        return waypoint_ids_for_route(start, points[0]) if start and start != points[0] else points
    normalized: list[str] = []
    for index in range(len(points) - 1):
        segment = waypoint_ids_for_route(points[index], points[index + 1])
        if not normalized:
            normalized.extend(segment)
        else:
            normalized.extend(segment[1:] if segment else [])
    deduped: list[str] = []
    for item in normalized:
        if item and (not deduped or deduped[-1] != item):
            deduped.append(item)
    return deduped or points


def route_distance(from_location_id: str, to_location_id: str) -> float:
    points = waypoint_ids_for_route(from_location_id, to_location_id)
    locations = _location_map()
    if len(points) < 2:
        return 0.0
    distance = 0.0
    previous = dict(locations.get(points[0], {}) or {})
    for location_id in points[1:]:
        current = dict(locations.get(location_id, {}) or {})
        dx = float(current.get("x", 0) or 0) - float(previous.get("x", 0) or 0)
        dy = float(current.get("y", 0) or 0) - float(previous.get("y", 0) or 0)
        distance += abs(dx) + abs(dy)
        previous = current
    return distance
