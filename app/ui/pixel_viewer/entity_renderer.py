from __future__ import annotations

from typing import Any

from app.ui.pixel_viewer.panel_renderer import draw_text


def tile_color(
    alerts: list[str],
    danger: tuple[int, int, int],
    pending: tuple[int, int, int],
    observation: tuple[int, int, int],
    accent_2: tuple[int, int, int],
    line: tuple[int, int, int],
) -> tuple[int, int, int]:
    normalized = {str(alert).strip().lower() for alert in alerts}
    if "deterioration" in normalized:
        return danger
    if "pending_result" in normalized:
        return pending
    if "observation" in normalized:
        return observation
    if "reprioritized" in normalized:
        return accent_2
    return line


def triage_color(
    level: int,
    patient_critical: tuple[int, int, int],
    patient_high: tuple[int, int, int],
    patient_med: tuple[int, int, int],
    patient_low: tuple[int, int, int],
) -> tuple[int, int, int]:
    if level <= 1:
        return patient_critical
    if level == 2:
        return patient_high
    if level == 3:
        return patient_med
    return patient_low


def to_screen_coords(x: int, y: int, map_origin_x: int, map_origin_y: int, map_tile: int) -> tuple[int, int]:
    return map_origin_x + x * map_tile, map_origin_y + y * map_tile


def _character_sprite(
    pygame: Any,
    sprites: dict[str, Any],
    base_key: str,
    direction: str,
    mode: str,
    moving: bool,
    tick_seed: int,
) -> Any:
    direction = direction if direction in {"down", "up", "left", "right"} else "down"
    if moving:
        frame_cycle = ("walk_1", "walk_2", "walk_3", "walk_2")
        frame_name = frame_cycle[(tick_seed // 4) % len(frame_cycle)]
    elif mode == "typing":
        frame_name = "typing_1" if (tick_seed // 12) % 2 == 0 else "typing_2"
    elif mode == "reading":
        frame_name = "reading_1" if (tick_seed // 16) % 2 == 0 else "reading_2"
    else:
        frame_name = "idle"
    return sprites.get(f"{base_key}_{direction}_{frame_name}") or sprites.get(base_key)


def _walk_bob(entity: dict[str, Any]) -> tuple[int, int]:
    if not bool(entity.get("moving", False)):
        return 0, 0
    tick_seed = int(entity.get("anim_tick", 0) or 0)
    facing = str(entity.get("facing", "down")).strip().lower()
    vertical = (0, -1, -2, -1)
    horizontal = (0, 1, 0, -1)
    idx = (tick_seed // 4) % 4
    if facing in {"left", "right"}:
        return horizontal[idx], vertical[idx]
    return 0, vertical[idx]


def _entity_mode(entity: dict[str, Any]) -> str:
    if bool(entity.get("moving", False)):
        return "walk"
    role = str(entity.get("role", "")).strip()
    status = str(entity.get("status", "")).strip().lower()
    location_id = str(entity.get("location_id", "")).strip().lower()
    kind = str(entity.get("location_kind", "")).strip().lower()
    if role == "patient":
        zone = str(entity.get("zone", "")).strip().lower()
        if kind == "consult" or zone in {"specialty_review", "er_workup", "awaiting_results"}:
            return "reading"
        return "idle"
    if kind == "consult":
        return "reading"
    if status in {"ask_patient", "consulting", "diagnose", "make_diagnostic_summary", "perform_assessment"}:
        return "reading"
    if "desk" in location_id or "sidebar" in location_id or "station" in location_id:
        return "typing"
    return "idle"


def _activity_caption(entity: dict[str, Any]) -> str:
    role = str(entity.get("role", "")).strip()
    status = str(entity.get("status", "")).strip().lower()
    zone = str(entity.get("zone", "")).strip().lower()
    if role == "patient":
        mapping = {
            "waiting_room": "WAIT",
            "er_workup": "ER",
            "awaiting_results": "TEST",
            "observation": "OBS",
            "specialty_review": "CONS",
            "completed": "DONE",
        }
        return mapping.get(zone, "")
    mapping = {
        "perform_triage": "TRIAGE",
        "perform_assessment": "ASSESS",
        "ask_patient": "INTERVIEW",
        "request_test": "ORDER",
        "await_test_results": "WAIT TEST",
        "observe_patient": "OBSERVE",
        "make_diagnostic_summary": "HANDOFF",
        "consulting": "CONSULT",
        "summoned": "SUMMONED",
        "diagnose": "DX",
        "refine_again": "REVIEW",
    }
    return mapping.get(status, "")


def _activity_badge(entity: dict[str, Any], palette: dict[str, tuple[int, int, int]]) -> tuple[str, tuple[int, int, int], tuple[int, int, int]]:
    role = str(entity.get("role", "")).strip().lower()
    status = str(entity.get("status", "")).strip().lower()
    zone = str(entity.get("zone", "")).strip().lower()
    location_id = str(entity.get("location_id", "")).strip().lower()

    if role == "patient":
        if location_id.startswith("arrival_lane_"):
            return "IN", palette["accent_2"], palette["line"]
        if location_id.startswith("arrival_entry_"):
            return "ARR", palette["accent_2"], palette["line"]
        if location_id.startswith("triage_queue_"):
            return "TRI", palette["pending"], palette["line"]
        if zone == "waiting_room":
            return "Q", palette["muted"], palette["line"]
        if zone == "er_workup":
            return "ER", palette["doctor_color"], palette["line"]
        if zone == "awaiting_results":
            return "...", palette["pending"], palette["line"]
        if zone == "observation":
            return "OBS", palette["obs"], palette["line"]
        if zone == "specialty_review":
            return "C", palette["accent_2"], palette["line"]
        if zone == "completed":
            return "OUT", palette["accent"], palette["line"]
        return "", palette["muted"], palette["line"]

    if status == "perform_triage":
        return "TRI", palette["pending"], palette["line"]
    if status in {"perform_assessment", "ask_patient"}:
        return "?", palette["doctor_color"] if role == "er" else palette["accent_2"], palette["line"]
    if status == "request_test":
        return "ORD", palette["pending"], palette["line"]
    if status == "await_test_results":
        return "...", palette["pending"], palette["line"]
    if status == "observe_patient":
        return "OBS", palette["obs"], palette["line"]
    if status in {"consulting", "summoned"}:
        return "C", palette["accent_2"], palette["line"]
    if status in {"diagnose", "make_diagnostic_summary"}:
        return "DX", palette["accent"], palette["line"]
    return "", palette["muted"], palette["line"]


def _draw_activity_badge(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    entity: dict[str, Any],
    label: str,
    fill: tuple[int, int, int],
    border: tuple[int, int, int],
) -> None:
    if not label:
        return
    sx = int(float(entity.get("render_x", 0.0) or 0.0))
    sy = int(float(entity.get("render_y", 0.0) or 0.0))
    text_surface = fonts["xxs"].render(label, False, (255, 252, 244))
    width = max(18, text_surface.get_width() + 8)
    badge = pygame.Rect(sx - 4, sy - 18, width, 12)
    pygame.draw.rect(screen, fill, badge, border_radius=3)
    pygame.draw.rect(screen, border, badge, width=1, border_radius=3)
    screen.blit(text_surface, (badge.x + (badge.width - text_surface.get_width()) // 2, badge.y + 1))


def _activity_icon_kind(entity: dict[str, Any]) -> str:
    role = str(entity.get("role", "")).strip().lower()
    status = str(entity.get("status", "")).strip().lower()
    zone = str(entity.get("zone", "")).strip().lower()
    location_id = str(entity.get("location_id", "")).strip().lower()
    if role == "patient":
        if location_id.startswith("triage_queue") or location_id == "triage_desk":
            return "triage"
        if zone == "awaiting_results":
            if "lab" in location_id:
                return "lab"
            return "test"
        if zone == "specialty_review":
            return "consult"
        return ""
    if status == "perform_triage":
        return "triage"
    if status in {"request_test", "await_test_results"}:
        return "lab" if "lab" in location_id else "test"
    if status in {"consulting", "summoned", "make_diagnostic_summary", "diagnose", "refine_again"}:
        return "consult"
    return ""


def _draw_activity_icon(
    screen: Any,
    pygame: Any,
    entity: dict[str, Any],
    palette: dict[str, tuple[int, int, int]],
) -> None:
    icon_kind = _activity_icon_kind(entity)
    if not icon_kind:
        return
    sx = int(float(entity.get("render_x", 0.0) or 0.0))
    sy = int(float(entity.get("render_y", 0.0) or 0.0))
    tick_seed = int(entity.get("anim_tick", 0) or 0)
    pulse = (tick_seed // 6) % 3
    icon = pygame.Rect(sx + 18, sy - 28 - pulse, 12, 12)
    fill = (34, 38, 58)
    border = palette["line"]
    accent = palette["accent_2"]
    if icon_kind == "triage":
        border = palette["pending"]
        accent = palette["pending"]
    elif icon_kind in {"test", "lab"}:
        border = palette["accent"]
        accent = palette["accent"]
    elif icon_kind == "consult":
        border = palette["obs"]
        accent = palette["obs"]
    pygame.draw.rect(screen, fill, icon, border_radius=3)
    pygame.draw.rect(screen, border, icon, width=2, border_radius=3)

    if icon_kind == "triage":
        pygame.draw.line(screen, accent, (icon.x + 3, icon.y + 6), (icon.right - 3, icon.y + 6), width=2)
        pygame.draw.line(screen, accent, (icon.x + 6, icon.y + 3), (icon.x + 6, icon.bottom - 3), width=2)
    elif icon_kind == "test":
        pygame.draw.rect(screen, accent, pygame.Rect(icon.x + 3, icon.y + 3, 6, 6), width=1)
        pygame.draw.line(screen, accent, (icon.x + 2, icon.bottom - 3), (icon.right - 2, icon.y + 2), width=2)
    elif icon_kind == "lab":
        points = [(icon.x + 4, icon.y + 2), (icon.right - 4, icon.y + 2), (icon.x + 7, icon.bottom - 3), (icon.x + 5, icon.bottom - 3)]
        pygame.draw.polygon(screen, accent, points, width=1)
        if pulse > 0:
            pygame.draw.line(screen, accent, (icon.x + 5, icon.y + 6), (icon.right - 5, icon.y + 6), width=2)
    elif icon_kind == "consult":
        bubble = pygame.Rect(icon.x + 2, icon.y + 2, 8, 6)
        pygame.draw.rect(screen, accent, bubble, width=1, border_radius=2)
        tail = [(icon.x + 5, icon.bottom - 2), (icon.x + 7, icon.y + 8), (icon.x + 3, icon.y + 8)]
        pygame.draw.polygon(screen, accent, tail)


def _patient_visuals(
    pygame: Any,
    sprites: dict[str, Any],
    entity: dict[str, Any],
    palette: dict[str, tuple[int, int, int]],
) -> tuple[Any, tuple[int, int, int], tuple[int, int, int], int, int]:
    alerts = list(entity.get("alerts", []) or [])
    triage = int(entity.get("effective_triage_level", entity.get("triage_level", 3)) or 3)
    bar_color = triage_color(
        triage,
        palette["patient_critical"],
        palette["patient_high"],
        palette["patient_med"],
        palette["patient_low"],
    )
    alert_color = tile_color(
        alerts,
        palette["danger"],
        palette["pending"],
        palette["obs"],
        palette["accent_2"],
        palette["line"],
    )
    zone = str(entity.get("zone", "")).strip()
    location_kind = str(entity.get("location_kind", "")).strip().lower()
    sprite_key = "patient_bed" if zone in {"er_workup", "observation"} else "patient_stand"
    moving = bool(entity.get("moving", False))
    tick_seed = int(entity.get("anim_tick", 0) or 0)
    direction = str(entity.get("facing", "down")).strip().lower()
    mode = _entity_mode({"role": "patient", **entity})
    sprite = sprites[sprite_key] if sprite_key == "patient_bed" else _character_sprite(pygame, sprites, sprite_key, direction, mode, moving, tick_seed)
    label_y_offset = 18 if location_kind == "consult" else (16 if sprite_key == "patient_bed" else 24)
    return sprite, bar_color, alert_color, label_y_offset, triage, _activity_caption({"role": "patient", **entity})


def _doctor_visuals(
    pygame: Any,
    sprites: dict[str, Any],
    entity: dict[str, Any],
    palette: dict[str, tuple[int, int, int]],
) -> tuple[Any, tuple[int, int, int], str, str]:
    role = str(entity.get("role", "")).strip()
    status = str(entity.get("status", "")).strip().lower()
    if status == "summoned":
        body_color = palette["pending"]
    elif role == "er":
        body_color = palette["doctor_color"]
    else:
        body_color = palette["accent_2"]
    moving = bool(entity.get("moving", False))
    tick_seed = int(entity.get("anim_tick", 0) or 0)
    direction = str(entity.get("facing", "down")).strip().lower()
    mode = _entity_mode(entity)
    base_key = "doctor_er" if role == "er" else ("nurse" if role == "nurse" else ("reception" if role == "reception" else "doctor_specialty"))
    sprite = _character_sprite(
        pygame,
        sprites,
        base_key,
        direction,
        mode,
        moving,
        tick_seed,
    )
    if role == "er":
        label = "ER"
    elif role == "nurse":
        label = "RN"
    elif role == "reception":
        label = "DESK"
    else:
        label = str(entity.get("department", "")).strip()[:4].upper()
    caption = _activity_caption(entity)
    if status == "summoned":
        eta = int(entity.get("eta_min", 0) or 0)
        caption = f"ETA {eta}"
    return sprite, body_color, label, caption


def _resource_location_status(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    status: dict[str, dict[str, Any]] = {}
    for item in list(snapshot.get("resource_occupancy", []) or []):
        resource_kind = str(item.get("resource_kind", "")).strip().lower()
        target = str(item.get("target", "")).strip().lower()
        location_id = ""
        if resource_kind == "imaging" or any(token in target for token in ("mri", "ct", "xray", "scan", "ultrasound", "imaging")):
            location_id = "imaging_machine"
        elif resource_kind in {"lab", "tests"} or any(token in target for token in ("blood", "urinalysis", "culture", "panel", "lab")):
            location_id = "lab_station"
        elif resource_kind == "doctor":
            location_id = "er_doctor_station"

        if not location_id:
            continue

        entry = status.setdefault(
            location_id,
            {
                "count": 0,
                "kind": resource_kind or "active",
                "cases": [],
            },
        )
        entry["count"] = int(entry.get("count", 0) or 0) + 1
        case_id = str(item.get("case_id", "")).strip()
        if case_id:
            entry["cases"].append(case_id)
    return status


def _draw_resource_markers(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    snapshot: dict[str, Any],
    locations: dict[str, Any],
    map_origin_x: int,
    map_origin_y: int,
    map_tile: int,
    pending: tuple[int, int, int],
    line: tuple[int, int, int],
    bg: tuple[int, int, int],
) -> None:
    resource_status = _resource_location_status(snapshot)
    for location_id, info in resource_status.items():
        location = dict(locations.get(location_id, {}) or {})
        if not location:
            continue
        x = int(location.get("x", 0) or 0)
        y = int(location.get("y", 0) or 0)
        sx, sy = to_screen_coords(x, y, map_origin_x, map_origin_y, map_tile)
        badge_rect = pygame.Rect(sx + 10, sy - 10, 22, 14)
        pygame.draw.rect(screen, pending, badge_rect)
        pygame.draw.rect(screen, line, badge_rect, width=2)
        draw_text(screen, fonts["xxs"], str(info.get("count", 1)), badge_rect.x + 7, badge_rect.y + 2, bg)
        kind = str(info.get("kind", "busy")).upper()[:4]
        draw_text(screen, fonts["xxs"], kind, sx - 2, sy - 20, pending)


def _zone_activity_summary(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {
        "triage": {"count": 0, "label": "TRIAGE", "badge": "!", "color_key": "pending", "action": ""},
        "er": {"count": 0, "label": "ER", "badge": "?", "color_key": "doctor_color", "action": ""},
        "imaging": {"count": 0, "label": "IMG", "badge": "SCAN", "color_key": "accent_2", "action": ""},
        "lab": {"count": 0, "label": "LAB", "badge": "TEST", "color_key": "accent", "action": ""},
        "consult": {"count": 0, "label": "CONSULT", "badge": "DX", "color_key": "obs", "action": ""},
        "observation": {"count": 0, "label": "OBS", "badge": "OBS", "color_key": "obs", "action": ""},
    }
    for patient in list(snapshot.get("patients", []) or []):
        zone = str(dict(patient).get("zone", "")).strip().lower()
        location_id = str(dict(patient).get("location_id", "")).strip().lower()
        if location_id.startswith("triage_queue") or location_id == "triage_desk":
            summary["triage"]["count"] += 1
        if zone == "er_workup":
            summary["er"]["count"] += 1
        if zone == "awaiting_results":
            if "lab" in location_id:
                summary["lab"]["count"] += 1
            else:
                summary["imaging"]["count"] += 1
        if zone == "specialty_review":
            summary["consult"]["count"] += 1
        if zone == "observation":
            summary["observation"]["count"] += 1
    zone_map = {
        "triage_desk": "triage",
        "er_bed_1": "er",
        "lab_station": "lab",
        "imaging_wait_1": "imaging",
        "specialty_consult_1": "consult",
        "observation_bed_1": "observation",
    }
    action_map = {
        "perform_triage": "ASSESS",
        "perform_assessment": "INTERVIEW",
        "ask_patient": "INTERVIEW",
        "request_test": "ORDER",
        "await_test_results": "RESULT",
        "consulting": "CONSULT",
        "make_diagnostic_summary": "CALL",
        "diagnose": "FINAL",
        "observe_patient": "WATCH",
    }
    recent_events = list(snapshot.get("event_log_recent", []) or [])
    for event in recent_events[-12:]:
        location_id = str(dict(event).get("location_id", "")).strip()
        zone_key = zone_map.get(location_id, "")
        if not zone_key:
            continue
        info = summary.get(zone_key)
        if not info:
            continue
        info["count"] = max(int(info.get("count", 0) or 0), 1)
        action = action_map.get(str(dict(event).get("action", "")).strip().lower(), "")
        if action:
            info["action"] = action
    return summary


def _draw_zone_activity_icons(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    snapshot: dict[str, Any],
    locations: dict[str, Any],
    map_origin_x: int,
    map_origin_y: int,
    map_tile: int,
    palette: dict[str, tuple[int, int, int]],
) -> None:
    summary = _zone_activity_summary(snapshot)
    anchors = {
        "triage": "triage_desk",
        "er": "er_bed_2",
        "imaging": "imaging_machine",
        "lab": "lab_station",
        "consult": "specialty_consult_1",
        "observation": "observation_desk_1",
    }
    current_minute = int(snapshot.get("current_time_min", 0) or 0)
    pulse = (current_minute % 3) * 2
    for zone_key, location_id in anchors.items():
        info = dict(summary.get(zone_key, {}) or {})
        location = dict(locations.get(location_id, {}) or {})
        if not location:
            continue
        x = int(location.get("x", 0) or 0)
        y = int(location.get("y", 0) or 0)
        sx, sy = to_screen_coords(x, y, map_origin_x, map_origin_y, map_tile)
        color = palette[str(info.get("color_key", "accent"))]
        active = int(info.get("count", 0) or 0) > 0
        outline = color if active else palette["line"]
        fill = (46, 54, 82) if active else (28, 32, 48)
        box = pygame.Rect(sx - 18, sy - 28 - pulse, 58, 20)
        pygame.draw.rect(screen, fill, box, border_radius=5)
        pygame.draw.rect(screen, outline, box, width=2, border_radius=5)
        badge_text = str(info.get("badge", "")).strip()
        label_text = str(info.get("label", "")).strip()
        action_text = str(info.get("action", "")).strip()
        counter_text = str(int(info.get("count", 0) or 0))
        draw_text(screen, fonts["xxs"], badge_text, box.x + 4, box.y + 3, outline)
        draw_text(screen, fonts["xxs"], counter_text, box.right - 10, box.y + 3, palette["text"])
        draw_text(screen, fonts["xxs"], label_text, sx - 10, sy - 42 - pulse, outline)
        if action_text:
            draw_text(screen, fonts["xxs"], action_text, sx - 12, sy - 14 - pulse, outline)


def _draw_motion_trail(
    screen: Any,
    pygame: Any,
    entity: dict[str, Any],
    trail_color: tuple[int, int, int],
) -> None:
    if not bool(entity.get("moving", False)):
        return
    sx = float(entity.get("render_x", 0.0) or 0.0)
    sy = float(entity.get("render_y", 0.0) or 0.0)
    dx = float(entity.get("move_dx", 0.0) or 0.0)
    dy = float(entity.get("move_dy", 0.0) or 0.0)
    distance = abs(dx) + abs(dy)
    if distance <= 0.8:
        return
    for step, alpha in ((1, 88), (2, 52), (3, 28)):
        px = int(sx - dx * 0.10 * step + 12)
        py = int(sy - dy * 0.10 * step + 18)
        radius = max(2, 5 - step)
        surface = pygame.Surface((radius * 4, radius * 4), pygame.SRCALPHA)
        pygame.draw.circle(surface, (*trail_color, alpha), (radius * 2, radius * 2), radius)
        screen.blit(surface, (px - radius * 2, py - radius * 2))


def _focus_case_id(snapshot: dict[str, Any]) -> str:
    focus = dict(snapshot.get("er_focus", {}) or {})
    return str(focus.get("case_id", "")).strip()


def _draw_focus_location(
    screen: Any,
    pygame: Any,
    snapshot: dict[str, Any],
    focus_soft: tuple[int, int, int],
) -> None:
    focus_case_id = _focus_case_id(snapshot)
    if not focus_case_id:
        return
    scene = dict(snapshot.get("scene", {}) or {})
    entities = list(scene.get("entities", []) or [])
    patient = next(
        (
            entity
            for entity in entities
            if str(entity.get("kind", "")).strip() == "patient"
            and str(entity.get("case_id", "")).strip() == focus_case_id
        ),
        None,
    )
    if patient is None:
        return
    px = int(float(patient.get("render_x", 0.0) or 0.0))
    py = int(float(patient.get("render_y", 0.0) or 0.0))
    pulse = 28 + int((snapshot.get("current_time_min", 0) or 0) % 3) * 2
    glow = pygame.Rect(px - 6, py - 6, pulse, pulse)
    pygame.draw.rect(screen, focus_soft, glow, width=3, border_radius=6)


def _draw_preview_overlay(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    snapshot: dict[str, Any],
    locations: dict[str, Any],
    preview_overlay: dict[str, Any],
    map_origin_x: int,
    map_origin_y: int,
    map_tile: int,
    accent_2: tuple[int, int, int],
    focus_soft: tuple[int, int, int],
    text: tuple[int, int, int],
    line: tuple[int, int, int],
) -> None:
    case_id = str(preview_overlay.get("case_id", "")).strip()
    target_location_id = str(preview_overlay.get("target_location_id", "")).strip()
    action_type = str(preview_overlay.get("action_type", "")).strip()
    target = str(preview_overlay.get("target", "")).strip()
    snapshot_id = str(preview_overlay.get("snapshot_id", "")).strip()
    rationale = str(preview_overlay.get("rationale", "")).strip()
    if not case_id or not target_location_id:
        return
    scene = dict(snapshot.get("scene", {}) or {})
    entities = list(scene.get("entities", []) or [])
    patient = next(
        (
            entity
            for entity in entities
            if str(entity.get("kind", "")).strip() == "patient"
            and str(entity.get("case_id", "")).strip() == case_id
        ),
        None,
    )
    target_location = dict(locations.get(target_location_id, {}) or {})
    if patient is None or not target_location:
        return
    px = int(float(patient.get("render_x", 0.0) or 0.0)) + 12
    py = int(float(patient.get("render_y", 0.0) or 0.0)) + 12
    tx = int(target_location.get("x", 0) or 0)
    ty = int(target_location.get("y", 0) or 0)
    sx, sy = to_screen_coords(tx, ty, map_origin_x, map_origin_y, map_tile)
    sx += map_tile // 2
    sy += map_tile // 2
    action_key = action_type.lower()
    preview_color = accent_2
    preview_badge = "WHAT-IF"
    if action_key == "ask_patient":
        preview_color = (139, 204, 255)
        preview_badge = "INTERVIEW"
    elif action_key == "request_test":
        preview_color = (255, 184, 107)
        preview_badge = "TEST"
    elif action_key in {"consult", "request_consult", "make_diagnostic_summary"}:
        preview_color = (200, 162, 255)
        preview_badge = "CONSULT"
    elif action_key == "observe_patient":
        preview_color = (170, 222, 130)
        preview_badge = "OBSERVE"
    elif action_key == "diagnose":
        preview_color = (112, 214, 255)
        preview_badge = "FINALIZE"
    for step in range(0, 10, 2):
        start = (int(px + (sx - px) * (step / 10.0)), int(py + (sy - py) * (step / 10.0)))
        end = (int(px + (sx - px) * ((step + 1) / 10.0)), int(py + (sy - py) * ((step + 1) / 10.0)))
        pygame.draw.line(screen, preview_color, start, end, width=3)
    ring = pygame.Rect(sx - 16, sy - 16, 32, 32)
    pygame.draw.rect(screen, preview_color, ring, width=2, border_radius=8)
    pygame.draw.rect(screen, focus_soft, ring.inflate(6, 6), width=1, border_radius=10)
    pulse_box = pygame.Surface((36, 36), pygame.SRCALPHA)
    pygame.draw.rect(pulse_box, (*preview_color, 42), pygame.Rect(0, 0, 36, 36), border_radius=9)
    screen.blit(pulse_box, (sx - 18, sy - 18))
    plate = pygame.Rect(min(px, sx) - 4, min(py, sy) - 44, 184, 30)
    pygame.draw.rect(screen, (46, 54, 82), plate, border_radius=4)
    pygame.draw.rect(screen, preview_color, plate, width=2, border_radius=4)
    label = f"{preview_badge} {action_type.upper()}"
    if target:
        label = f"{label}: {target[:14]}"
    draw_text(screen, fonts["xxs"], label, plate.x + 6, plate.y + 3, text)
    detail_line = snapshot_id or rationale
    if detail_line:
        draw_text(screen, fonts["xxs"], detail_line[:28], plate.x + 6, plate.y + 16, focus_soft)


def _draw_replay_overlay(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    snapshot: dict[str, Any],
    replay_overlay: dict[str, Any],
    accent: tuple[int, int, int],
    danger: tuple[int, int, int],
    text: tuple[int, int, int],
    muted: tuple[int, int, int],
) -> None:
    case_id = str(replay_overlay.get("case_id", "")).strip()
    comparison = dict(replay_overlay.get("comparison", {}) or {})
    if not case_id or not comparison:
        return
    scene = dict(snapshot.get("scene", {}) or {})
    entities = list(scene.get("entities", []) or [])
    patient = next(
        (
            entity
            for entity in entities
            if str(entity.get("kind", "")).strip() == "patient"
            and str(entity.get("case_id", "")).strip() == case_id
        ),
        None,
    )
    if patient is None:
        return
    px = int(float(patient.get("render_x", 0.0) or 0.0))
    py = int(float(patient.get("render_y", 0.0) or 0.0))
    original = dict(comparison.get("original", {}) or {})
    replay = dict(comparison.get("replay", {}) or {})
    selected_action = dict(replay_overlay.get("selected_action", {}) or {})
    replay_result = dict(replay_overlay.get("replay_result", {}) or {})
    improved = bool(comparison.get("improved", False))
    reward_delta = float(comparison.get("reward_delta", 0.0) or 0.0)
    color = accent if improved else danger
    box = pygame.Rect(px - 24, py - 82, 196, 62)
    pygame.draw.rect(screen, (32, 38, 58), box, border_radius=6)
    pygame.draw.rect(screen, color, box, width=2, border_radius=6)
    aura = pygame.Surface((48, 48), pygame.SRCALPHA)
    pygame.draw.circle(aura, (*color, 54), (24, 24), 22)
    screen.blit(aura, (px - 10, py - 2))
    draw_text(screen, fonts["xxs"], f"REPLAY {'UP' if improved else 'DIFF'} {reward_delta:+.2f}", box.x + 6, box.y + 4, color)
    draw_text(screen, fonts["xxs"], f"O: {str(original.get('department', '-')).strip()}", box.x + 6, box.y + 18, muted)
    draw_text(screen, fonts["xxs"], f"R: {str(replay.get('department', '-')).strip()}", box.x + 88, box.y + 18, text)
    replay_action_type = str(selected_action.get("type", "")).strip()
    replay_action_target = str(selected_action.get("target", "")).strip()
    replay_turns = int(replay_result.get("turn_count", 0) or 0)
    action_line = replay_action_type.upper() if replay_action_type else "REPLAY"
    if replay_action_target:
        action_line = f"{action_line} -> {replay_action_target[:10]}"
    draw_text(screen, fonts["xxs"], action_line[:28], box.x + 6, box.y + 31, text)
    draw_text(screen, fonts["xxs"], f"turns {replay_turns} | {str(replay.get('diagnosis', '-')).strip()[:14]}", box.x + 6, box.y + 44, muted)


def _draw_replay_entity_highlight(
    screen: Any,
    pygame: Any,
    snapshot: dict[str, Any],
    replay_overlay: dict[str, Any],
    accent: tuple[int, int, int],
    danger: tuple[int, int, int],
    focus_soft: tuple[int, int, int],
) -> None:
    case_id = str(replay_overlay.get("case_id", "")).strip()
    comparison = dict(replay_overlay.get("comparison", {}) or {})
    if not case_id or not comparison:
        return
    scene = dict(snapshot.get("scene", {}) or {})
    entities = list(scene.get("entities", []) or [])
    patient = next(
        (
            entity
            for entity in entities
            if str(entity.get("kind", "")).strip() == "patient"
            and str(entity.get("case_id", "")).strip() == case_id
        ),
        None,
    )
    if patient is None:
        return
    color = accent if bool(comparison.get("improved", False)) else danger
    px = int(float(patient.get("render_x", 0.0) or 0.0))
    py = int(float(patient.get("render_y", 0.0) or 0.0))
    patient_rect = pygame.Rect(px - 6, py - 8, 38, 46)
    pygame.draw.rect(screen, color, patient_rect, width=3, border_radius=8)
    pygame.draw.rect(screen, focus_soft, patient_rect.inflate(8, 8), width=1, border_radius=10)
    assigned_staff = str(patient.get("assigned_staff", "")).strip()
    if assigned_staff:
        staff = next(
            (entity for entity in entities if str(entity.get("id", "")).strip() == assigned_staff),
            None,
        )
        if staff is not None:
            sx = int(float(staff.get("render_x", 0.0) or 0.0))
            sy = int(float(staff.get("render_y", 0.0) or 0.0))
            staff_rect = pygame.Rect(sx - 4, sy - 6, 34, 42)
            pygame.draw.rect(screen, color, staff_rect, width=2, border_radius=8)
            pygame.draw.line(screen, color, (px + 12, py + 12), (sx + 12, sy + 12), width=3)


def draw_patient_entity(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    sprites: dict[str, Any],
    entity: dict[str, Any],
    palette: dict[str, tuple[int, int, int]],
) -> None:
    sx = int(float(entity.get("render_x", 0.0) or 0.0))
    sy = int(float(entity.get("render_y", 0.0) or 0.0))
    bob_x, bob_y = _walk_bob(entity)
    sx += bob_x
    sy += bob_y
    alerts = list(entity.get("alerts", []) or [])
    sprite, color, alert_color, label_y_offset, triage, activity = _patient_visuals(pygame, sprites, entity, palette)
    _draw_motion_trail(screen, pygame, entity, color)
    shadow_rect = pygame.Rect(sx + 6, sy + 24, 18, 4)
    if str(entity.get("location_kind", "")).strip().lower() == "bed":
        shadow_rect = pygame.Rect(sx + 4, sy + 18, 22, 3)
    elif bool(entity.get("moving", False)):
        shadow_rect = pygame.Rect(sx + 5, sy + 25, 20, 3)
    pygame.draw.rect(screen, (130, 136, 150), shadow_rect, border_radius=3)
    sprite_rect = sprite.get_rect(topleft=(sx + 1, sy + 1))
    screen.blit(sprite, sprite_rect.topleft)
    label_y = sy + label_y_offset
    draw_text(screen, fonts["xxs"], str(entity.get("case_id", "")).replace("case_", "c"), sx - 1, label_y, palette["text"])
    draw_text(screen, fonts["xxs"], f"T{triage}", sx + 12, sy - 11, alert_color)
    if activity:
        draw_text(screen, fonts["xxs"], activity, sx - 4, sy - 22, palette["accent_2"])
    badge_text, badge_fill, badge_border = _activity_badge({"role": "patient", **entity}, palette)
    _draw_activity_badge(screen, pygame, fonts, entity, badge_text, badge_fill, badge_border)
    _draw_activity_icon(screen, pygame, {"render_x": sx, "render_y": sy, **entity}, palette)
    if alerts:
        pygame.draw.circle(screen, alert_color, (sx + 22, sy + 7), 5)
    pygame.draw.rect(screen, color, pygame.Rect(sx + 7, sy + 30, 14, 2))


def draw_doctor_entity(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    sprites: dict[str, Any],
    entity: dict[str, Any],
    palette: dict[str, tuple[int, int, int]],
) -> None:
    sx = int(float(entity.get("render_x", 0.0) or 0.0))
    sy = int(float(entity.get("render_y", 0.0) or 0.0))
    bob_x, bob_y = _walk_bob(entity)
    sx += bob_x
    sy += bob_y
    sprite, body_color, label, caption = _doctor_visuals(pygame, sprites, entity, palette)
    _draw_motion_trail(screen, pygame, entity, body_color)
    shadow_rect = pygame.Rect(sx + 6, sy + 24, 16, 4)
    if bool(entity.get("moving", False)):
        shadow_rect = pygame.Rect(sx + 5, sy + 25, 18, 3)
    pygame.draw.rect(screen, (130, 136, 150), shadow_rect, border_radius=3)
    sprite_rect = sprite.get_rect(topleft=(sx + 1, sy + 1))
    screen.blit(sprite, sprite_rect.topleft)
    draw_text(screen, fonts["xxs"], label, sx - 1, sy + 25, palette["text"])
    if caption:
        draw_text(screen, fonts["xxs"], caption, sx - 10, sy - 14, body_color)
    badge_text, badge_fill, badge_border = _activity_badge(entity, palette)
    _draw_activity_badge(screen, pygame, fonts, entity, badge_text, badge_fill, badge_border)
    _draw_activity_icon(screen, pygame, {"render_x": sx, "render_y": sy, **entity}, palette)


def find_entity(snapshot: dict[str, Any], entity_id: str) -> dict[str, Any] | None:
    scene = dict(snapshot.get("scene", {}) or {})
    for entity in list(scene.get("entities", []) or []):
        if str(entity.get("id", "")).strip() == entity_id:
            return dict(entity)
    return None


def draw_speech_bubble(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    entity: dict[str, Any],
    text: str,
    bubble: tuple[int, int, int],
    bubble_text: tuple[int, int, int],
    line: tuple[int, int, int],
) -> None:
    if not text:
        return
    sx = int(float(entity.get("render_x", 0.0) or 0.0))
    sy = int(float(entity.get("render_y", 0.0) or 0.0))
    text = text[:42]
    text_surface = fonts["xxs"].render(text, False, bubble_text)
    width = max(78, text_surface.get_width() + 14)
    box = pygame.Rect(sx - 10, sy - 34, width, 20)
    pygame.draw.rect(screen, bubble, box, border_radius=4)
    pygame.draw.rect(screen, line, box, width=2, border_radius=4)
    tail = [(sx + 12, sy - 12), (sx + 18, sy - 8), (sx + 6, sy - 8)]
    pygame.draw.polygon(screen, bubble, tail)
    pygame.draw.polygon(screen, line, tail, width=2)
    screen.blit(text_surface, (box.x + 7, box.y + 4))


def _draw_pairings(
    screen: Any,
    pygame: Any,
    entities: list[dict[str, Any]],
    accent: tuple[int, int, int],
) -> None:
    entity_by_id = {str(entity.get("id", "")).strip(): entity for entity in entities}
    for entity in entities:
        if str(entity.get("kind", "")).strip() != "patient":
            continue
        assigned_staff = str(entity.get("assigned_staff", "")).strip()
        if not assigned_staff:
            continue
        staff = entity_by_id.get(assigned_staff)
        if not staff:
            continue
        px = float(entity.get("render_x", entity.get("x", 0)) or 0.0)
        py = float(entity.get("render_y", entity.get("y", 0)) or 0.0)
        sx = float(staff.get("render_x", staff.get("x", 0)) or 0.0)
        sy = float(staff.get("render_y", staff.get("y", 0)) or 0.0)
        start = (int(px) + 12, int(py) + 12)
        end = (int(sx) + 12, int(sy) + 12)
        pygame.draw.line(screen, accent, start, end, width=2)


def _selected_specialty_entity(
    entities: list[dict[str, Any]],
    selected_case_id: str,
) -> dict[str, Any] | None:
    if not selected_case_id:
        return None
    direct = next(
        (
            entity
            for entity in entities
            if str(entity.get("kind", "")).strip() == "doctor"
            and str(entity.get("role", "")).strip() == "specialty"
            and str(entity.get("case_id", "")).strip() == selected_case_id
        ),
        None,
    )
    if direct is not None:
        return direct

    patient = next(
        (
            entity
            for entity in entities
            if str(entity.get("kind", "")).strip() == "patient"
            and str(entity.get("case_id", "")).strip() == selected_case_id
        ),
        None,
    )
    if patient is None:
        return None
    department = str(patient.get("predicted_department", "")).strip().lower()
    if not department:
        return None
    return next(
        (
            entity
            for entity in entities
            if str(entity.get("kind", "")).strip() == "doctor"
            and str(entity.get("role", "")).strip() == "specialty"
            and str(entity.get("department", "")).strip().lower() == department
        ),
        None,
    )


def _draw_specialty_activity(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    entities: list[dict[str, Any]],
    locations: dict[str, Any],
    selected_case_id: str,
    current_time_min: int,
    map_origin_x: int,
    map_origin_y: int,
    map_tile: int,
    accent: tuple[int, int, int],
    accent_2: tuple[int, int, int],
    pending: tuple[int, int, int],
    focus_soft: tuple[int, int, int],
    muted: tuple[int, int, int],
) -> None:
    selected_specialist = _selected_specialty_entity(entities, selected_case_id)
    patient_by_case = {
        str(entity.get("case_id", "")).strip(): entity
        for entity in entities
        if str(entity.get("kind", "")).strip() == "patient"
    }
    consult_locations = {
        location_id: dict(location)
        for location_id, location in locations.items()
        if str(location_id).startswith("specialty_consult_")
    }

    for entity in entities:
        if str(entity.get("kind", "")).strip() != "doctor":
            continue
        if str(entity.get("role", "")).strip() != "specialty":
            continue

        sx = int(float(entity.get("render_x", entity.get("x", 0)) or 0.0))
        sy = int(float(entity.get("render_y", entity.get("y", 0)) or 0.0))
        status = str(entity.get("status", "")).strip().lower()
        case_id = str(entity.get("case_id", "")).strip()
        is_selected = selected_specialist is not None and str(entity.get("id", "")).strip() == str(selected_specialist.get("id", "")).strip()

        pod_color = None
        if status == "summoned":
            pod_color = pending
        elif status not in {"", "idle", "waiting"}:
            pod_color = accent
        if is_selected and pod_color is None:
            pod_color = accent_2

        if pod_color is not None:
            pulse = 0
            if status == "summoned":
                pulse = int(current_time_min % 3) * 2
            halo = pygame.Rect(sx - 6 - pulse, sy - 6 - pulse, 34 + pulse * 2, 40 + pulse * 2)
            pygame.draw.rect(screen, pod_color, halo, width=3, border_radius=8)
            if is_selected:
                inner = halo.inflate(6, 6)
                pygame.draw.rect(screen, focus_soft, inner, width=2, border_radius=10)
            pod_rect = pygame.Rect(sx - 12, sy - 12, 68, 50)
            tint = pygame.Surface((pod_rect.width, pod_rect.height), pygame.SRCALPHA)
            alpha = 42 if status == "summoned" else (34 if is_selected else 24)
            tint.fill((pod_color[0], pod_color[1], pod_color[2], alpha))
            screen.blit(tint, pod_rect.topleft)
            pygame.draw.rect(screen, pod_color, pod_rect, width=1, border_radius=10)

        patient = patient_by_case.get(case_id)
        consult_x = sx + 12
        consult_y = sy + 12
        target_point = None
        if patient is not None:
            target_location_id = str(patient.get("location_id", "")).strip()
            target_location = dict(consult_locations.get(target_location_id, {}) or {})
            if target_location:
                tx = int(target_location.get("x", 0) or 0)
                ty = int(target_location.get("y", 0) or 0)
                target_point = (tx, ty)
        if target_point is None and consult_locations:
            for target_location in consult_locations.values():
                tx = int(target_location.get("x", 0) or 0)
                ty = int(target_location.get("y", 0) or 0)
                target_point = (tx, ty)
                break

        if target_point is not None and status in {"summoned", "consulting", "diagnose", "request_test", "refine_again"}:
            tx, ty = target_point
            cx = map_origin_x + tx * map_tile + map_tile // 2
            cy = map_origin_y + ty * map_tile + map_tile // 2
            marker_color = pending if status == "summoned" else accent
            ring_radius = 8 + (int(current_time_min % 3) if status == "summoned" else 0)
            path_mid_x = min(consult_x, cx) - 10
            pygame.draw.line(screen, marker_color, (consult_x, consult_y), (path_mid_x, consult_y), width=2)
            pygame.draw.line(screen, marker_color, (path_mid_x, consult_y), (path_mid_x, cy), width=2)
            pygame.draw.line(screen, marker_color, (path_mid_x, cy), (cx, cy), width=2)
            pygame.draw.circle(screen, marker_color, (cx, cy), ring_radius, width=2)
            pygame.draw.circle(screen, focus_soft if is_selected else muted, (cx, cy), 3)
            draw_text(screen, fonts["xxs"], "CONS", cx - 11, cy - 18, marker_color)

        if patient is not None:
            px = int(float(patient.get("render_x", patient.get("x", 0)) or 0.0)) + 12
            py = int(float(patient.get("render_y", patient.get("y", 0)) or 0.0)) + 12
            mid_x = min(consult_x, px) - 22
            if status == "summoned":
                pygame.draw.line(screen, pending, (consult_x, consult_y), (mid_x, consult_y), width=2)
                pygame.draw.line(screen, pending, (mid_x, consult_y), (mid_x, py), width=2)
                pygame.draw.line(screen, pending, (mid_x, py), (px, py), width=2)
            elif status not in {"", "idle", "waiting"}:
                pygame.draw.line(screen, accent, (consult_x, consult_y), (mid_x, consult_y), width=3)
                pygame.draw.line(screen, accent, (mid_x, consult_y), (mid_x, py), width=3)
                pygame.draw.line(screen, accent, (mid_x, py), (px, py), width=3)

        dept = str(entity.get("department", "")).strip()[:4].upper()
        if dept:
            plate = pygame.Rect(sx + 18, sy - 14, 26, 11)
            pygame.draw.rect(screen, (40, 47, 74), plate, border_radius=3)
            pygame.draw.rect(screen, accent_2 if is_selected else muted, plate, width=1, border_radius=3)
            draw_text(screen, fonts["xxs"], dept, plate.x + 4, plate.y + 1, accent_2 if is_selected else muted)


def draw_scene(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    sprites: dict[str, Any],
    background: Any,
    snapshot: dict[str, Any],
    selected_case_id: str,
    map_origin_x: int,
    map_origin_y: int,
    map_tile: int,
    palette: dict[str, tuple[int, int, int]],
) -> None:
    scene = dict(snapshot.get("scene", {}) or {})
    locations = dict(scene.get("locations", {}) or {})
    entities = list(scene.get("entities", []) or [])
    presentation = dict(snapshot.get("presentation", {}) or {})

    screen.blit(background, (map_origin_x, map_origin_y))
    _draw_resource_markers(screen, pygame, fonts, snapshot, locations, map_origin_x, map_origin_y, map_tile, palette["pending"], palette["line"], palette["bg"])
    _draw_zone_activity_icons(screen, pygame, fonts, snapshot, locations, map_origin_x, map_origin_y, map_tile, palette)
    _draw_focus_location(screen, pygame, snapshot, palette["focus_soft"])
    preview_overlay = dict(presentation.get("preview_overlay", {}) or {})
    if preview_overlay:
        _draw_preview_overlay(
            screen,
            pygame,
            fonts,
            snapshot,
            locations,
            preview_overlay,
            map_origin_x,
            map_origin_y,
            map_tile,
            palette["accent_2"],
            palette["focus_soft"],
            palette["text"],
            palette["line"],
        )
    replay_overlay = dict(presentation.get("replay_overlay", {}) or {})
    if replay_overlay:
        _draw_replay_entity_highlight(
            screen,
            pygame,
            snapshot,
            replay_overlay,
            palette["accent"],
            palette["danger"],
            palette["focus_soft"],
        )
        _draw_replay_overlay(
            screen,
            pygame,
            fonts,
            snapshot,
            replay_overlay,
            palette["accent"],
            palette["danger"],
            palette["text"],
            palette["muted"],
        )
    _draw_specialty_activity(
        screen,
        pygame,
        fonts,
        entities,
        locations,
        selected_case_id,
        int(snapshot.get("current_time_min", 0) or 0),
        map_origin_x,
        map_origin_y,
        map_tile,
        palette["accent"],
        palette["accent_2"],
        palette["pending"],
        palette["focus_soft"],
        palette["muted"],
    )

    _draw_pairings(screen, pygame, entities, palette["accent"])
    for entity in entities:
        if str(entity.get("kind", "")).strip() == "doctor":
            draw_doctor_entity(screen, pygame, fonts, sprites, entity, palette)
    for entity in entities:
        if str(entity.get("kind", "")).strip() == "patient":
            draw_patient_entity(screen, pygame, fonts, sprites, entity, palette)

    dialogue = dict(snapshot.get("dialogue", {}) or {})
    bubble_text = str(dialogue.get("bubble_text", "")).strip()
    speaker_entity_id = str(dialogue.get("speaker_entity_id", "")).strip()
    listener_entity_id = str(dialogue.get("listener_entity_id", "")).strip()
    speaker = find_entity(snapshot, speaker_entity_id) if speaker_entity_id else None
    listener = find_entity(snapshot, listener_entity_id) if listener_entity_id else None
    if speaker is not None and bubble_text:
        draw_speech_bubble(screen, pygame, fonts, speaker, bubble_text, palette["bubble"], palette["bubble_text"], palette["line"])
    elif listener is not None and bubble_text:
        draw_speech_bubble(screen, pygame, fonts, listener, bubble_text, palette["bubble"], palette["bubble_text"], palette["line"])
