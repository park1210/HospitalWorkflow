from __future__ import annotations

import time
from typing import Any


def wrap_text(font: Any, text: str, max_width: int) -> list[str]:
    words = str(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if font.size(candidate)[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def draw_text(
    screen: Any,
    font: Any,
    text: str,
    x: int,
    y: int,
    color: tuple[int, int, int],
) -> None:
    surface = font.render(str(text), False, color)
    screen.blit(surface, (x, y))


def draw_panel(
    screen: Any,
    pygame: Any,
    rect: Any,
    fill: tuple[int, int, int],
    border: tuple[int, int, int],
) -> None:
    pygame.draw.rect(screen, fill, rect)
    pygame.draw.rect(screen, border, rect, width=3)


def draw_badge(
    screen: Any,
    pygame: Any,
    font: Any,
    text: str,
    x: int,
    y: int,
    color: tuple[int, int, int],
    text_color: tuple[int, int, int],
    border_color: tuple[int, int, int],
) -> int:
    text_surface = font.render(text, False, text_color)
    rect = pygame.Rect(x, y, text_surface.get_width() + 12, 18)
    pygame.draw.rect(screen, color, rect)
    pygame.draw.rect(screen, border_color, rect, width=2)
    screen.blit(text_surface, (x + 6, y + 3))
    return rect.width


def compute_layout(
    window_width: int,
    window_height: int,
    map_grid_width: int,
    map_grid_height: int,
    map_tile: int,
) -> dict[str, Any]:
    outer_margin = 16
    top_y = 72
    footer_margin = 16
    sidebar_width = 320
    gap = 20
    map_width = map_grid_width * map_tile + 20
    map_height = map_grid_height * map_tile + 20

    available_scene_width = window_width - sidebar_width - gap - outer_margin * 2
    available_scene_height = window_height - top_y - footer_margin
    scene_width = min(max(map_width, 0), available_scene_width)
    scene_height = min(max(map_height, 0), available_scene_height)
    scene_panel = (outer_margin, top_y, scene_width, scene_height)
    hud_rect = (outer_margin + 12, top_y + 12, min(520, scene_width - 24), 74)

    sidebar_x = outer_margin + scene_width + gap
    remaining_h = scene_height
    usable_sidebar_h = max(480, remaining_h - gap * 5)
    overview_h = int(usable_sidebar_h * 0.14)
    controls_h = int(usable_sidebar_h * 0.24)
    patients_h = int(usable_sidebar_h * 0.14)
    comparison_h = int(usable_sidebar_h * 0.12)
    detail_h = int(usable_sidebar_h * 0.20)
    dialogue_h = max(
        120,
        usable_sidebar_h - (overview_h + controls_h + patients_h + comparison_h + detail_h),
    )

    overview_rect = (sidebar_x, top_y, sidebar_width, overview_h)
    controls_rect = (sidebar_x, top_y + overview_h + gap, sidebar_width, controls_h)
    patients_rect = (sidebar_x, top_y + overview_h + controls_h + gap * 2, sidebar_width, patients_h)
    comparison_rect = (sidebar_x, top_y + overview_h + controls_h + patients_h + gap * 3, sidebar_width, comparison_h)
    detail_rect = (sidebar_x, top_y + overview_h + controls_h + patients_h + comparison_h + gap * 4, sidebar_width, detail_h)
    dialogue_rect = (sidebar_x, top_y + overview_h + controls_h + patients_h + comparison_h + detail_h + gap * 5, sidebar_width, dialogue_h)

    return {
        "scene_panel": scene_panel,
        "hud_rect": hud_rect,
        "overview_rect": overview_rect,
        "controls_rect": controls_rect,
        "patients_rect": patients_rect,
        "comparison_rect": comparison_rect,
        "detail_rect": detail_rect,
        "dialogue_rect": dialogue_rect,
    }


def draw_hud_panel(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    snapshot: dict[str, Any],
    rect: Any,
    selected_case_id: str,
    playback: dict[str, Any],
    palette: dict[str, tuple[int, int, int]],
) -> None:
    presentation = dict(snapshot.get("presentation", {}) or {})
    current_beat = dict(presentation.get("current_beat", {}) or {})
    selected_candidate = dict(presentation.get("selected_candidate", {}) or {})
    preview_enabled = bool(presentation.get("what_if_preview_enabled", False))
    what_if_enabled = bool(presentation.get("what_if_enabled", False))
    replay_summary = dict(presentation.get("replay_summary", {}) or {})
    comparison = dict(replay_summary.get("comparison", {}) or {})
    show_replay_outcome = bool(presentation.get("show_replay_outcome", False))
    paused = bool(presentation.get("paused", False))

    overlay = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    overlay.fill((22, 28, 46, 220))
    screen.blit(overlay, rect.topleft)
    pygame.draw.rect(screen, palette["line"], rect, width=2, border_radius=8)
    draw_text(screen, fonts["sm"], "Live Controls", rect.x + 10, rect.y + 8, palette["accent"])
    draw_text(
        screen,
        fonts["xxs"],
        f"{selected_case_id or '-'} | {str(current_beat.get('label', 'ambient')).strip()[:42]}",
        rect.x + 10,
        rect.y + 30,
        palette["text"],
    )

    specs = hud_button_specs(rect, snapshot, selected_case_id, playback)
    for spec in specs:
        button_rect = pygame.Rect(*spec["rect"])
        fill = spec.get("fill", palette["bg_soft"])
        border = spec.get("border", palette["line"])
        draw_panel(screen, pygame, button_rect, fill, border)
        draw_text(screen, fonts["xxs"], str(spec["label"]).strip(), button_rect.x + 8, button_rect.y + 6, palette["text"])

    status_x = rect.x + rect.width - 190
    draw_text(screen, fonts["xxs"], f"mode: {'paused' if paused else 'auto'}", status_x, rect.y + 10, palette["muted"])
    draw_text(screen, fonts["xxs"], f"what-if: {'on' if what_if_enabled else 'off'}", status_x, rect.y + 24, palette["muted"])
    if preview_enabled and selected_candidate:
        preview_line = str(selected_candidate.get("target", "")).strip() or str(selected_candidate.get("type", "-")).strip()
        draw_text(screen, fonts["xxs"], f"preview: {preview_line[:18]}", status_x, rect.y + 38, palette["accent_2"])
    elif comparison:
        state_label = "replay view" if show_replay_outcome else "replay ready"
        draw_text(screen, fonts["xxs"], state_label, status_x, rect.y + 38, palette["accent"])


def hud_button_specs(
    rect: Any,
    snapshot: dict[str, Any],
    selected_case_id: str,
    playback: dict[str, Any],
) -> list[dict[str, Any]]:
    presentation = dict(snapshot.get("presentation", {}) or {})
    paused = bool(dict(playback or {}).get("paused", False))
    what_if_enabled = bool(presentation.get("what_if_enabled", False))
    preview_enabled = bool(presentation.get("what_if_preview_enabled", False))
    comparison = dict(dict(presentation.get("replay_summary", {}) or {}).get("comparison", {}) or {})
    show_replay_outcome = bool(presentation.get("show_replay_outcome", False))
    detail = dict((snapshot.get("case_details", {}) or {}).get(selected_case_id, {}) or {})
    decision_points = list(detail.get("decision_points", []) or [])
    selected_decision_index = int(presentation.get("selected_decision_index", 0) or 0)
    selected_decision = (
        dict(decision_points[selected_decision_index] or {})
        if decision_points and 0 <= selected_decision_index < len(decision_points)
        else {}
    )
    candidates = list(selected_decision.get("alternatives", []) or []) or list(detail.get("counterfactual_candidates", []) or [])
    can_preview = bool(what_if_enabled and candidates)

    buttons: list[dict[str, Any]] = []
    base_x = rect.x + 10
    y = rect.y + 46
    button_widths = [78, 88, 98, 106]
    entries = [
        ("toggle_pause", "Resume" if paused else "Pause", palette_fill("accent" if paused else "bg_soft"), False),
        ("toggle_what_if", "What-If", palette_fill("accent_2" if what_if_enabled else "bg_soft"), False),
        ("toggle_what_if_preview", "Preview", palette_fill("danger" if preview_enabled else "bg_soft"), not can_preview),
        ("apply_replay", "Replay", palette_fill("accent" if can_preview else "bg_soft"), not can_preview),
    ]
    cursor_x = base_x
    for idx, (action, label, fill_meta, disabled) in enumerate(entries):
        width = button_widths[idx]
        fill, border = fill_meta
        if disabled:
            fill = (42, 46, 60)
            border = (72, 78, 96)
        buttons.append(
            {
                "action": action,
                "label": label,
                "rect": (cursor_x, y, width, 24),
                "fill": fill,
                "border": border,
                "disabled": disabled,
            }
        )
        cursor_x += width + 8
    if comparison:
        buttons.append(
            {
                "action": "toggle_replay_outcome",
                "label": "Replay View" if not show_replay_outcome else "Original View",
                "rect": (cursor_x, y, 116, 24),
                "fill": (48, 58, 88) if not show_replay_outcome else (72, 108, 160),
                "border": (114, 140, 198),
                "disabled": False,
            }
        )
    return buttons


def palette_fill(kind: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    if kind == "accent":
        return (54, 96, 144), (112, 214, 255)
    if kind == "accent_2":
        return (92, 76, 34), (255, 214, 112)
    if kind == "danger":
        return (110, 48, 52), (255, 107, 107)
    return ((40, 48, 70), (90, 106, 165))


def _visible_row_count(rect: Any, top_padding: int, line_height: int, bottom_padding: int = 10) -> int:
    return max(1, int((rect.height - top_padding - bottom_padding) // max(1, line_height)))


def _scroll_bounds(total_items: int, visible_items: int) -> int:
    return max(0, int(total_items or 0) - max(0, int(visible_items or 0)))


def clamp_scroll_offset(scroll_offset: int, total_items: int, visible_items: int) -> int:
    return min(max(0, int(scroll_offset or 0)), _scroll_bounds(total_items, visible_items))


def _draw_scroll_hint(
    screen: Any,
    pygame: Any,
    rect: Any,
    scroll_offset: int,
    total_items: int,
    visible_items: int,
    palette: dict[str, tuple[int, int, int]],
) -> None:
    max_offset = _scroll_bounds(total_items, visible_items)
    if max_offset <= 0:
        return
    gutter = pygame.Rect(rect.right - 8, rect.y + 36, 4, max(24, rect.height - 46))
    pygame.draw.rect(screen, palette["line"], gutter)
    thumb_h = max(18, int(gutter.height * (visible_items / max(total_items, 1))))
    travel = max(1, gutter.height - thumb_h)
    thumb_y = gutter.y + int(travel * (scroll_offset / max(max_offset, 1)))
    thumb = pygame.Rect(gutter.x, thumb_y, gutter.width, thumb_h)
    pygame.draw.rect(screen, palette["accent"], thumb)


def control_button_specs(rect: Any, playback: dict[str, Any]) -> list[dict[str, Any]]:
    paused = bool(dict(playback or {}).get("paused", False))
    what_if_enabled = bool(dict(playback or {}).get("what_if_enabled", False))
    labels = [
        ("toggle_pause", "Resume" if paused else "Pause"),
        ("next_beat", "Next Beat"),
        ("prev_beat", "Prev Beat"),
        ("toggle_what_if", "What-If On" if what_if_enabled else "What-If"),
    ]
    button_width = (rect.width - 28) // 2
    button_height = 24
    start_x = rect.x + 10
    start_y = rect.y + 82
    specs: list[dict[str, Any]] = []
    for idx, (action, label) in enumerate(labels):
        col = idx % 2
        row = idx // 2
        specs.append(
            {
                "action": action,
                "label": label,
                "rect": (start_x + col * (button_width + 8), start_y + row * (button_height + 8), button_width, button_height),
            }
        )
    return specs


def control_interaction_specs(
    rect: Any,
    snapshot: dict[str, Any],
    selected_case_id: str,
    playback: dict[str, Any],
    scroll_offset: int = 0,
) -> list[dict[str, Any]]:
    scroll_px = max(0, int(scroll_offset or 0)) * 18
    specs = []
    for spec in control_button_specs(rect, playback):
        x, y, width, height = spec["rect"]
        specs.append({**spec, "rect": (x, y - scroll_px, width, height)})
    detail = dict((snapshot.get("case_details", {}) or {}).get(selected_case_id, {}) or {})
    presentation = dict(snapshot.get("presentation", {}) or {})
    selected_decision_index = int(presentation.get("selected_decision_index", 0) or 0)
    selected_candidate_index = int(presentation.get("selected_candidate_index", 0) or 0)
    decision_points_full = list(detail.get("decision_points", []) or [])
    decision_base_index = max(0, len(decision_points_full) - 3)
    decision_points = decision_points_full[decision_base_index:]
    selected_decision = (
        dict(decision_points_full[selected_decision_index] or {})
        if decision_points_full and 0 <= selected_decision_index < len(decision_points_full)
        else {}
    )
    candidates = list(selected_decision.get("alternatives", []) or [])[:3]
    if not candidates:
        candidates = list(detail.get("counterfactual_candidates", []) or [])[:3]

    decision_y = rect.y + 168 - scroll_px
    for idx, _decision in enumerate(decision_points):
        specs.append(
            {
                "action": f"select_decision:{decision_base_index + idx}",
                "label": f"decision_{idx}",
                "selected": (decision_base_index + idx) == selected_decision_index,
                "rect": (rect.x + 10, decision_y + idx * 24, rect.width - 20, 20),
            }
        )

    candidate_y = rect.y + 168 + len(decision_points) * 24 + 20 - scroll_px
    for idx, _candidate in enumerate(candidates):
        specs.append(
            {
                "action": f"select_candidate:{idx}",
                "label": f"candidate_{idx}",
                "selected": idx == selected_candidate_index,
                "rect": (rect.x + 10, candidate_y + idx * 24, rect.width - 20, 20),
            }
        )

    if bool(presentation.get("what_if_enabled", False)) and candidates:
        footer_start_y = candidate_y + len(candidates) * 24 + 16
        specs.append(
            {
                "action": "toggle_what_if_preview",
                "label": "preview",
                "selected": bool(presentation.get("what_if_preview_enabled", False)),
                "rect": (rect.x + 10, footer_start_y, rect.width - 20, 22),
            }
        )
        specs.append(
            {
                "action": "apply_replay",
                "label": "apply_replay",
                "selected": False,
                "rect": (rect.x + 10, footer_start_y + 28, rect.width - 20, 22),
            }
        )
    if dict(presentation.get("replay_summary", {}) or {}).get("comparison"):
        footer_start_y = candidate_y + len(candidates) * 24 + 16
        specs.append(
            {
                "action": "toggle_replay_outcome",
                "label": "toggle_replay_outcome",
                "selected": bool(presentation.get("show_replay_outcome", False)),
                "rect": (rect.x + 10, footer_start_y - 28, rect.width - 20, 22),
            }
        )
    visible_left = rect.x + 4
    visible_top = rect.y + 36
    visible_right = rect.right - 4
    visible_bottom = rect.bottom - 4
    filtered: list[dict[str, Any]] = []
    for spec in specs:
        x, y, width, height = spec["rect"]
        if (x + width) < visible_left or x > visible_right or (y + height) < visible_top or y > visible_bottom:
            continue
        filtered.append(spec)
    return filtered


def _conversation_badge_meta(
    actor: str,
    accent: tuple[int, int, int],
    accent_2: tuple[int, int, int],
    muted: tuple[int, int, int],
) -> tuple[str, tuple[int, int, int]]:
    normalized = str(actor).strip().lower()
    if normalized == "er_department":
        return "ER", accent
    if normalized and normalized not in {"system"}:
        return "SPEC", accent_2
    return "INFO", muted


def _draw_conversation_entry(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    rect: Any,
    x: int,
    y: int,
    entry: dict[str, Any],
    palette: dict[str, tuple[int, int, int]],
) -> int:
    actor = str(entry.get("actor", "")).strip() or "actor"
    case_id = str(entry.get("case_id", "")).strip() or "-"
    minute = int(entry.get("minute", 0) or 0)
    badge_text, badge_color = _conversation_badge_meta(actor, palette["accent"], palette["accent_2"], palette["muted"])
    badge_width = draw_badge(
        screen,
        pygame,
        fonts["xxs"],
        badge_text,
        x,
        y,
        badge_color,
        palette["text"],
        palette["line"],
    )
    draw_text(screen, fonts["xxs"], f"m{minute} | {case_id}", x + badge_width + 8, y + 2, palette["text"])
    y += 18
    for line in [str(line).strip() for line in list(entry.get("lines", []) or []) if str(line).strip()][:2]:
        wrapped = wrap_text(fonts["xxs"], line, rect.width - 34)
        for wrapped_line in wrapped[:2]:
            draw_text(screen, fonts["xxs"], wrapped_line, x + 4, y, palette["muted"])
            y += 15
    return y


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


def _event_summary_line(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type", "")).strip() or str(event.get("action", "")).strip() or "event"
    location_id = str(event.get("location_id", "")).strip()
    rationale = str(event.get("rationale", "")).strip()
    payload = dict(event.get("payload", {}) or {})
    if str(payload.get("question", "")).strip():
        return f"{event_type}: Q {str(payload.get('question', '')).strip()}"
    if str(payload.get("answer", "")).strip():
        return f"{event_type}: A {str(payload.get('answer', '')).strip()}"
    if str(payload.get("requested_test", "")).strip():
        return f"{event_type}: {str(payload.get('requested_test', '')).strip()}"
    if str(payload.get("diagnosis", "")).strip():
        return f"{event_type}: {str(payload.get('diagnosis', '')).strip()}"
    if rationale:
        return f"{event_type}: {rationale}"
    if location_id:
        return f"{event_type}: {location_id}"
    return event_type


def draw_overview_panel(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    snapshot: dict[str, Any],
    rect: Any,
    palette: dict[str, tuple[int, int, int]],
) -> None:
    draw_panel(screen, pygame, rect, palette["bg_soft"], palette["line"])
    draw_text(screen, fonts["sm"], "Overview", rect.x + 10, rect.y + 10, palette["accent"])

    minute = snapshot.get("current_time_min", "-")
    waiting = int(snapshot.get("waiting_count", 0) or 0)
    completed = int(snapshot.get("completed_count", 0) or 0)
    resources = len(list(snapshot.get("resource_occupancy", []) or []))
    snapshot_written_at = float(snapshot.get("snapshot_written_at_unix", 0.0) or 0.0)
    simulation_status = str(snapshot.get("simulation_status", "running")).strip() or "running"
    now_unix = time.time()
    is_stale = simulation_status != "completed" and snapshot_written_at > 0 and (now_unix - snapshot_written_at) >= 6.0
    status_label = "stalled?" if is_stale else ("completed" if simulation_status == "completed" else "live")
    status_color = palette["danger"] if is_stale else (palette["patient_low"] if simulation_status == "completed" else palette["accent"])
    focus = dict(snapshot.get("er_focus", {}) or {})
    focus_case = str(focus.get("case_id", "")).strip() or "-"
    focus_action = str(focus.get("action", "")).strip() or "-"
    focus_effective = int(focus.get("effective_triage_level", 0) or 0)

    draw_text(screen, fonts["xs"], f"minute {minute}", rect.x + 10, rect.y + 38, palette["text"])
    draw_text(screen, fonts["xs"], f"waiting {waiting}", rect.x + 10, rect.y + 58, palette["text"])
    draw_text(screen, fonts["xs"], f"completed {completed}", rect.x + 150, rect.y + 38, palette["text"])
    draw_text(screen, fonts["xs"], f"resources {resources}", rect.x + 150, rect.y + 58, palette["text"])
    draw_text(screen, fonts["xxs"], f"status {status_label}", rect.x + 10, rect.y + 76, status_color)

    badge_y = rect.y + 100
    draw_badge(screen, pygame, fonts["xxs"], "BLACK", rect.x + 10, badge_y, (60, 60, 68), palette["text"], palette["line"])
    draw_badge(screen, pygame, fonts["xxs"], "RED", rect.x + 84, badge_y, palette["patient_critical"], palette["text"], palette["line"])
    draw_badge(screen, pygame, fonts["xxs"], "YELLOW", rect.x + 142, badge_y, palette["patient_med"], palette["text"], palette["line"])
    draw_badge(screen, pygame, fonts["xxs"], "GREEN", rect.x + 224, badge_y, palette["patient_low"], palette["text"], palette["line"])

    draw_text(screen, fonts["xs"], f"ER focus: {focus_case}", rect.x + 10, rect.y + 132, palette["focus"])
    draw_text(screen, fonts["xxs"], f"T{focus_effective} | {focus_action}", rect.x + 10, rect.y + 152, palette["muted"])


def draw_patient_list(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    snapshot: dict[str, Any],
    rect: Any,
    scroll_offset: int,
    palette: dict[str, tuple[int, int, int]],
) -> None:
    draw_panel(screen, pygame, rect, palette["bg_soft"], palette["line"])
    draw_text(screen, fonts["sm"], "Patients", rect.x + 10, rect.y + 10, palette["accent"])
    previous_clip = screen.get_clip()
    screen.set_clip(pygame.Rect(rect.x + 4, rect.y + 34, rect.width - 12, rect.height - 40))
    patients = list(snapshot.get("patients", []) or [])
    visible_items = max(1, (rect.height - 48) // 38)
    scroll_offset = clamp_scroll_offset(scroll_offset, len(patients), visible_items)
    y = rect.y + 38
    for patient in patients[scroll_offset:scroll_offset + visible_items]:
        effective = patient.get("effective_triage_level", patient.get("triage_level", "-"))
        draw_text(
            screen,
            fonts["xs"],
            f"{patient.get('case_id', '')} | T{effective} | {patient.get('zone', '')}",
            rect.x + 10,
            y,
            palette["text"],
        )
        y += 16
        draw_text(
            screen,
            fonts["xxs"],
            f"{patient.get('predicted_department', '')} | alerts: {', '.join(patient.get('alerts', []) or []) or 'none'}",
            rect.x + 10,
            y,
            palette["muted"],
        )
        y += 22
    _draw_scroll_hint(screen, pygame, rect, scroll_offset, len(patients), visible_items, palette)
    screen.set_clip(previous_clip)


def draw_control_panel(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    snapshot: dict[str, Any],
    rect: Any,
    selected_case_id: str,
    playback: dict[str, Any],
    scroll_offset: int,
    palette: dict[str, tuple[int, int, int]],
) -> None:
    draw_panel(screen, pygame, rect, palette["bg_soft"], palette["line"])
    draw_text(screen, fonts["sm"], "Playback / What-If", rect.x + 10, rect.y + 10, palette["accent"])
    previous_clip = screen.get_clip()
    screen.set_clip(pygame.Rect(rect.x + 4, rect.y + 34, rect.width - 12, rect.height - 40))

    presentation = dict(snapshot.get("presentation", {}) or {})
    current_beat = dict(presentation.get("current_beat", {}) or {})
    beat_index = int(presentation.get("beat_index", 0) or 0)
    beat_count = int(presentation.get("beat_count", 0) or 0)
    paused = bool(presentation.get("paused", False))
    beat_kind = str(current_beat.get("kind", "")).strip() or "-"
    detail = dict((snapshot.get("case_details", {}) or {}).get(selected_case_id, {}) or {})
    decision_points = list(detail.get("decision_points", []) or [])
    selected_decision_index = int(presentation.get("selected_decision_index", 0) or 0)
    selected_decision = (
        dict(decision_points[selected_decision_index] or {})
        if decision_points and 0 <= selected_decision_index < len(decision_points)
        else {}
    )
    candidates = list(selected_decision.get("alternatives", []) or [])
    if not candidates:
        candidates = list(detail.get("counterfactual_candidates", []) or [])
    selected_candidate_index = int(presentation.get("selected_candidate_index", 0) or 0)
    preview_enabled = bool(presentation.get("what_if_preview_enabled", False))
    selected_candidate = dict(presentation.get("selected_candidate", {}) or {})
    replay_status = str(presentation.get("replay_status", "")).strip()
    replay_summary = dict(presentation.get("replay_summary", {}) or {})
    comparison = dict(replay_summary.get("comparison", {}) or {})
    show_replay_outcome = bool(presentation.get("show_replay_outcome", False))

    decision_points_tail = decision_points[-3:]
    scroll_px = max(0, int(scroll_offset or 0)) * 18
    base_y = rect.y + 36 - scroll_px

    draw_text(screen, fonts["xxs"], f"mode: {'paused' if paused else 'auto-play'}", rect.x + 10, base_y, palette["text"])
    draw_text(screen, fonts["xxs"], f"beat: {beat_index + 1 if beat_count else 0}/{beat_count}", rect.x + 10, base_y + 16, palette["text"])
    draw_text(screen, fonts["xxs"], f"scene: {str(current_beat.get('label', 'Ambient hospital activity')).strip()}", rect.x + 116, base_y + 16, palette["muted"])
    draw_text(screen, fonts["xxs"], f"type: {beat_kind}", rect.x + 10, base_y + 30, palette["muted"])

    flow_y = base_y + 48
    draw_text(screen, fonts["xxs"], "What-If Flow", rect.x + 10, flow_y, palette["focus"])
    flow_steps = [
        ("1 Decision", True),
        ("2 Alternative", bool(candidates)),
        ("3 Preview", preview_enabled),
        ("4 Replay", bool(comparison)),
    ]
    badge_x = rect.x + 10
    for label, active in flow_steps:
        badge_x += draw_badge(
            screen,
            pygame,
            fonts["xxs"],
            label,
            badge_x,
            flow_y + 16,
            palette["accent"] if active else palette["bg"],
            palette["text"],
            palette["line"],
        ) + 6
    pygame.draw.line(screen, palette["line"], (rect.x + 10, flow_y + 42), (rect.right - 20, flow_y + 42), width=2)

    for spec in control_button_specs(rect, playback):
        button_rect = pygame.Rect(*spec["rect"])
        button_rect.y -= scroll_px
        is_what_if = spec["action"] == "toggle_what_if"
        fill = palette["accent_2"] if is_what_if and bool(presentation.get("what_if_enabled", False)) else palette["bg"]
        draw_panel(screen, pygame, button_rect, fill, palette["line"])
        draw_text(screen, fonts["xxs"], str(spec["label"]).strip(), button_rect.x + 8, button_rect.y + 5, palette["text"])

    y = rect.y + 168 - scroll_px
    decision_box = pygame.Rect(rect.x + 8, y - 22, rect.width - 16, 90)
    pygame.draw.rect(screen, (36, 43, 66), decision_box, border_radius=6)
    pygame.draw.rect(screen, palette["line"], decision_box, width=1, border_radius=6)
    draw_text(screen, fonts["xxs"], "Decision Points", rect.x + 10, y - 16, palette["focus"])
    for idx, decision in enumerate(decision_points_tail):
        row_rect = pygame.Rect(rect.x + 10, y + idx * 24, rect.width - 20, 20)
        decision_index = max(0, len(decision_points) - len(decision_points_tail)) + idx
        fill = palette["accent_2"] if decision_index == selected_decision_index else palette["bg"]
        draw_panel(screen, pygame, row_rect, fill, palette["line"])
        node = str(dict(decision).get("node", "-")).strip()
        proposed_type = str(dict(decision).get("proposed_type", "-")).strip()
        draw_text(screen, fonts["xxs"], f"{node} -> {proposed_type}", row_rect.x + 6, row_rect.y + 4, palette["text"])

    y = y + max(1, len(decision_points_tail)) * 24 + 20
    candidate_box = pygame.Rect(rect.x + 8, y - 22, rect.width - 16, 90)
    pygame.draw.rect(screen, (36, 43, 66), candidate_box, border_radius=6)
    pygame.draw.rect(screen, palette["line"], candidate_box, width=1, border_radius=6)
    draw_text(screen, fonts["xxs"], "Alternative Actions", rect.x + 10, y - 16, palette["focus"])
    for idx, candidate in enumerate(candidates[:3]):
        row_rect = pygame.Rect(rect.x + 10, y + idx * 24, rect.width - 20, 20)
        fill = palette["accent"] if idx == selected_candidate_index else palette["bg"]
        draw_panel(screen, pygame, row_rect, fill, palette["line"])
        candidate_type = str(dict(candidate).get("type", "-")).strip()
        candidate_target = str(dict(candidate).get("target", "")).strip()
        line = candidate_type if not candidate_target else f"{candidate_type} -> {candidate_target}"
        draw_text(screen, fonts["xxs"], line, row_rect.x + 6, row_rect.y + 4, palette["text"])

    footer_y = y + max(1, len(candidates[:3])) * 24 + 16
    if bool(presentation.get("what_if_enabled", False)) and candidates:
        action_box = pygame.Rect(rect.x + 8, footer_y - 6, rect.width - 16, 88 if comparison else 58)
        pygame.draw.rect(screen, (36, 43, 66), action_box, border_radius=6)
        pygame.draw.rect(screen, palette["line"], action_box, width=1, border_radius=6)
        if comparison:
            outcome_rect = pygame.Rect(rect.x + 10, footer_y, rect.width - 20, 22)
            fill = palette["accent"] if show_replay_outcome else (48, 58, 88)
            draw_panel(screen, pygame, outcome_rect, fill, palette["line"])
            outcome_label = "Hide Replay Outcome" if show_replay_outcome else "Show Replay Outcome"
            draw_text(screen, fonts["xxs"], outcome_label, outcome_rect.x + 8, outcome_rect.y + 5, palette["text"])
            footer_y += 28
        preview_rect = pygame.Rect(rect.x + 10, footer_y, rect.width - 20, 22)
        fill = palette["danger"] if preview_enabled else (48, 58, 88)
        draw_panel(screen, pygame, preview_rect, fill, palette["line"])
        preview_label = "Disable Preview" if preview_enabled else "Preview Selected Alternative"
        draw_text(screen, fonts["xxs"], preview_label, preview_rect.x + 8, preview_rect.y + 5, palette["text"])
        replay_rect = pygame.Rect(rect.x + 10, footer_y + 28, rect.width - 20, 22)
        draw_panel(screen, pygame, replay_rect, (48, 58, 88), palette["line"])
        draw_text(screen, fonts["xxs"], "Apply / Replay", replay_rect.x + 8, replay_rect.y + 5, palette["text"])
        footer_y += 56

    footer_y += 8
    draw_text(screen, fonts["xxs"], "keys: Space / Left / Right", rect.x + 10, footer_y, palette["muted"])
    draw_text(screen, fonts["xxs"], f"decision points: {len(decision_points)}", rect.x + 10, footer_y + 16, palette["focus"])
    draw_text(screen, fonts["xxs"], f"alternatives: {len(candidates)}", rect.x + 150, footer_y + 16, palette["focus"])
    if selected_candidate:
        draw_text(
            screen,
            fonts["xxs"],
            f"preview target: {str(selected_candidate.get('target', '')).strip() or str(selected_candidate.get('type', '-')).strip()}",
            rect.x + 10,
            footer_y + 32,
            palette["muted"],
        )
    if replay_status:
        draw_text(screen, fonts["xxs"], f"replay: {replay_status}", rect.x + 170, footer_y, palette["danger"])
    if comparison:
        original = dict(comparison.get("original", {}) or {})
        replay = dict(comparison.get("replay", {}) or {})
        draw_text(
            screen,
            fonts["xxs"],
            f"orig: {str(original.get('department', '-')).strip()} / {str(original.get('diagnosis', '-')).strip()[:18]}",
            rect.x + 10,
            footer_y + 48,
            palette["muted"],
        )
        draw_text(
            screen,
            fonts["xxs"],
            f"replay: {str(replay.get('department', '-')).strip()} / {str(replay.get('diagnosis', '-')).strip()[:18]}",
            rect.x + 10,
            footer_y + 64,
            palette["text"],
        )
        footer_y += 32
    total_content_height = max(0, footer_y - rect.y + 84)
    visible_items = _visible_row_count(rect, 36, 18)
    total_items = max(1, (total_content_height + 17) // 18)
    _draw_scroll_hint(screen, pygame, rect, clamp_scroll_offset(scroll_offset, total_items, visible_items), total_items, visible_items, palette)
    screen.set_clip(previous_clip)


def draw_comparison_panel(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    snapshot: dict[str, Any],
    rect: Any,
    scroll_offset: int,
    palette: dict[str, tuple[int, int, int]],
) -> None:
    draw_panel(screen, pygame, rect, palette["bg_soft"], palette["line"])
    draw_text(screen, fonts["sm"], "Original vs Replay", rect.x + 10, rect.y + 10, palette["accent"])
    previous_clip = screen.get_clip()
    screen.set_clip(pygame.Rect(rect.x + 4, rect.y + 34, rect.width - 12, rect.height - 40))
    presentation = dict(snapshot.get("presentation", {}) or {})
    replay_summary = dict(presentation.get("replay_summary", {}) or {})
    comparison = dict(replay_summary.get("comparison", {}) or {})
    replay_status = str(presentation.get("replay_status", "")).strip()
    show_replay_outcome = bool(presentation.get("show_replay_outcome", False))
    replay_result = dict(replay_summary.get("replay_result", {}) or {})

    if not comparison:
        draw_text(screen, fonts["xs"], "Run a what-if replay to compare", rect.x + 10, rect.y + 42, palette["muted"])
        draw_text(screen, fonts["xs"], "original and alternate outcomes.", rect.x + 10, rect.y + 60, palette["muted"])
        if replay_status:
            draw_text(screen, fonts["xxs"], f"status: {replay_status}", rect.x + 10, rect.y + 88, palette["danger"])
        screen.set_clip(previous_clip)
        return

    original = dict(comparison.get("original", {}) or {})
    replay = dict(comparison.get("replay", {}) or {})
    reward_delta = float(comparison.get("reward_delta", 0.0) or 0.0)
    improved = bool(comparison.get("improved", False))
    status_color = palette["patient_low"] if improved else palette["danger"]
    selected_action = dict(comparison.get("selected_action", {}) or {})
    lines: list[tuple[str, str, tuple[int, int, int], int]] = [
        ("xxs", f"status: {replay_status or 'replay_completed'}", status_color, 0),
        ("xxs", f"scene view: {'replay outcome' if show_replay_outcome else 'original timeline'}", palette["muted"], 0),
        ("xxs", f"snapshot: {str(comparison.get('snapshot_id', '-')).strip()}", palette["muted"], 0),
        ("xxs", f"action: {str(selected_action.get('type', '-')).strip()} -> {str(selected_action.get('target', '')).strip() or '-'}", palette["focus"], 0),
        ("xxs", "Original", palette["focus"], 0),
        ("xxs", f"Dept: {str(original.get('department', '-')).strip()}", palette["muted"], 6),
        ("xxs", f"Dx: {str(original.get('diagnosis', '-')).strip()}", palette["muted"], 6),
        ("xxs", f"Correct: D={bool(original.get('diagnosis_correct', False))} / S={bool(original.get('department_correct', False))}", palette["muted"], 6),
        ("xxs", "Replay", palette["focus"], 0),
        ("xxs", f"Dept: {str(replay.get('department', '-')).strip()}", palette["text"], 6),
        ("xxs", f"Dx: {str(replay.get('diagnosis', '-')).strip()}", palette["text"], 6),
        ("xxs", f"Correct: D={bool(replay.get('diagnosis_correct', False))} / S={bool(replay.get('department_correct', False))}", palette["text"], 6),
        ("xxs", f"Reward delta: {reward_delta:+.2f}", status_color, 0),
        ("xxs", f"Improved: {improved}", status_color, 0),
    ]
    if replay_result:
        lines.append(("xxs", "Replay Summary", palette["focus"], 0))
        lines.append(("xxs", f"turns: {int(replay_result.get('turn_count', 0) or 0)}", palette["muted"], 6))
        lines.append(("xxs", f"tests: {', '.join(list(replay_result.get('tests', []) or [])[:3]) or 'none'}", palette["muted"], 6))
        lines.append(("xxs", f"questions: {len(list(replay_result.get('questions', []) or []))}", palette["muted"], 6))
        for finding in list(replay_result.get("objective_findings", []) or [])[:3]:
            for wrapped_line in wrap_text(fonts["xxs"], f"- {finding}", rect.width - 34):
                lines.append(("xxs", wrapped_line, palette["muted"], 10))

    line_height = 15
    visible_items = _visible_row_count(rect, 48, line_height)
    scroll_offset = clamp_scroll_offset(scroll_offset, len(lines), visible_items)
    y = rect.y + 38
    for font_key, text, color, indent in lines[scroll_offset:scroll_offset + visible_items]:
        draw_text(screen, fonts[font_key], text, rect.x + 10 + indent, y, color)
        y += line_height
    _draw_scroll_hint(screen, pygame, rect, scroll_offset, len(lines), visible_items, palette)
    screen.set_clip(previous_clip)


def draw_case_detail_panel(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    snapshot: dict[str, Any],
    rect: Any,
    selected_case_id: str,
    scroll_offset: int,
    palette: dict[str, tuple[int, int, int]],
) -> None:
    draw_panel(screen, pygame, rect, palette["bg_soft"], palette["line"])
    draw_text(screen, fonts["sm"], "Case Detail", rect.x + 10, rect.y + 10, palette["accent"])
    previous_clip = screen.get_clip()
    screen.set_clip(pygame.Rect(rect.x + 4, rect.y + 34, rect.width - 12, rect.height - 40))
    case_details = dict(snapshot.get("case_details", {}) or {})
    detail = dict(case_details.get(selected_case_id, {}) or {})
    if not detail:
        draw_text(screen, fonts["xs"], "Click a patient to inspect prior questions,", rect.x + 10, rect.y + 44, palette["muted"])
        draw_text(screen, fonts["xs"], "triage, objective findings, and tests.", rect.x + 10, rect.y + 62, palette["muted"])
        screen.set_clip(previous_clip)
        return
    lines: list[tuple[str, str, tuple[int, int, int], int]] = []
    lines.append(("xs", f"{selected_case_id} | T{detail.get('effective_triage_level', '-')}", palette["text"], 0))
    lines.append(("xxs", f"zone: {detail.get('zone', '-')}", palette["muted"], 0))
    lines.append(("xxs", f"risk: {detail.get('deterioration_risk', '-') or '-'}", palette["muted"], 0))
    lines.append(("xxs", f"pending results: {detail.get('pending_results_count', 0)}", palette["muted"], 0))
    current_event = dict(detail.get("current_event", {}) or {})
    lines.append(("xxs", "Current Beat", palette["focus"], 0))
    if not current_event:
        lines.append(("xxs", "No active beat overlay", palette["muted"], 6))
    else:
        lines.append((
            "xxs",
            f"m{int(current_event.get('minute', 0) or 0)} | {str(current_event.get('label', '')).strip() or str(current_event.get('event_type', '-')).strip()}",
            palette["text"],
            6,
        ))
        lines.append((
            "xxs",
            f"action: {str(current_event.get('action', '-')).strip()}",
            palette["muted"],
            6,
        ))
        rationale = str(current_event.get("rationale", "")).strip()
        if rationale:
            for line in wrap_text(fonts["xxs"], f"why: {rationale}", rect.width - 38):
                lines.append(("xxs", line, palette["muted"], 6))
        payload = dict(current_event.get("payload", {}) or {})
        if str(payload.get("question", "")).strip():
            for line in wrap_text(fonts["xxs"], f"Q: {str(payload.get('question', '')).strip()}", rect.width - 38):
                lines.append(("xxs", line, palette["text"], 6))
        if str(payload.get("answer", "")).strip():
            for line in wrap_text(fonts["xxs"], f"A: {str(payload.get('answer', '')).strip()}", rect.width - 38):
                lines.append(("xxs", line, palette["muted"], 6))
        if str(payload.get("requested_test", "")).strip():
            for line in wrap_text(fonts["xxs"], f"test: {str(payload.get('requested_test', '')).strip()}", rect.width - 38):
                lines.append(("xxs", line, palette["text"], 6))
        if str(payload.get("department", "")).strip():
            lines.append(("xxs", f"dept: {str(payload.get('department', '')).strip()}", palette["text"], 6))
        if str(payload.get("diagnosis", "")).strip():
            for line in wrap_text(fonts["xxs"], f"dx: {str(payload.get('diagnosis', '')).strip()}", rect.width - 38):
                lines.append(("xxs", line, palette["text"], 6))
    lines.append(("xxs", "Questions", palette["focus"], 0))
    questions = list(detail.get("questions", []) or [])
    if not questions:
        lines.append(("xxs", "No interview yet", palette["muted"], 6))
    else:
        for qa in questions:
            question = str(dict(qa).get("question", "")).strip()
            answer = str(dict(qa).get("answer", "")).strip()
            for line in wrap_text(fonts["xxs"], f"Q: {question}", rect.width - 38):
                lines.append(("xxs", line, palette["text"], 6))
            for line in wrap_text(fonts["xxs"], f"A: {answer}", rect.width - 38):
                lines.append(("xxs", line, palette["muted"], 6))
    lines.append(("xxs", "Tests", palette["focus"], 0))
    tests = list(detail.get("tests", []) or [])
    if not tests:
        lines.append(("xxs", "No requested tests", palette["muted"], 6))
    else:
        for test in tests:
            for line in wrap_text(fonts["xxs"], f"- {test}", rect.width - 38):
                lines.append(("xxs", line, palette["text"], 6))
    lines.append(("xxs", "Objective Findings", palette["focus"], 0))
    findings = list(detail.get("objective_findings", []) or [])
    if not findings:
        lines.append(("xxs", "No objective findings yet", palette["muted"], 6))
    else:
        for finding in findings:
            for line in wrap_text(fonts["xxs"], f"- {finding}", rect.width - 38):
                lines.append(("xxs", line, palette["muted"], 6))
    lines.append(("xxs", "Recent Events", palette["focus"], 0))
    recent_events = list(detail.get("recent_events", []) or [])
    if not recent_events:
        lines.append(("xxs", "No recent event log yet", palette["muted"], 6))
    else:
        for event in recent_events[-6:]:
            minute = int(dict(event).get("minute", 0) or 0)
            for line in wrap_text(fonts["xxs"], f"m{minute} {_event_summary_line(dict(event))}", rect.width - 38):
                lines.append(("xxs", line, palette["text"], 6))
    lines.append(("xxs", "What-If", palette["focus"], 0))
    stats = dict(detail.get("what_if_stats", {}) or {})
    decision_points = list(detail.get("decision_points", []) or [])
    lines.append((
        "xxs",
        f"snapshots: {int(stats.get('decision_snapshot_count', len(decision_points)) or len(decision_points))} | disagreements: {int(stats.get('shadow_disagreement_count', 0) or 0)}",
        palette["muted"],
        6,
    ))
    if decision_points:
        latest = dict(decision_points[-1] or {})
        lines.append(("xxs", f"latest: {str(latest.get('node', '-')).strip()} -> {str(latest.get('proposed_type', '-')).strip()}", palette["text"], 6))
    else:
        lines.append(("xxs", "No decision snapshot yet", palette["muted"], 6))

    line_height = 14
    visible_items = _visible_row_count(rect, 48, line_height)
    scroll_offset = clamp_scroll_offset(scroll_offset, len(lines), visible_items)
    y = rect.y + 38
    for font_key, text, color, indent in lines[scroll_offset:scroll_offset + visible_items]:
        draw_text(screen, fonts[font_key], text, rect.x + 10 + indent, y, color)
        y += line_height
    _draw_scroll_hint(screen, pygame, rect, scroll_offset, len(lines), visible_items, palette)
    screen.set_clip(previous_clip)


def draw_dialogue_panel(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    snapshot: dict[str, Any],
    rect: Any,
    selected_case_id: str,
    scroll_offset: int,
    palette: dict[str, tuple[int, int, int]],
) -> None:
    draw_panel(screen, pygame, rect, palette["bg_soft"], palette["line"])
    draw_text(screen, fonts["sm"], "Conversation", rect.x + 10, rect.y + 10, palette["accent"])
    previous_clip = screen.get_clip()
    screen.set_clip(pygame.Rect(rect.x + 4, rect.y + 34, rect.width - 12, rect.height - 40))
    dialogue = dict(snapshot.get("dialogue", {}) or {})
    history = _selected_recent_conversations(snapshot, selected_case_id)
    presentation = dict(snapshot.get("presentation", {}) or {})
    current_beat = dict(presentation.get("current_beat", {}) or {})
    selected_candidate = dict(presentation.get("selected_candidate", {}) or {})

    lines: list[tuple[str, str, tuple[int, int, int], int]] = []
    beat_label = str(current_beat.get("label", "")).strip()
    if beat_label:
        lines.append(("xxs", f"Scene: {beat_label}", palette["accent_2"], 0))
    if bool(presentation.get("what_if_preview_enabled", False)) and selected_candidate:
        candidate_type = str(selected_candidate.get("type", "")).strip() or "alternative"
        candidate_target = str(selected_candidate.get("target", "")).strip()
        preview_text = candidate_type if not candidate_target else f"{candidate_type} -> {candidate_target}"
        lines.append(("xxs", f"What-If Preview: {preview_text}", palette["danger"], 0))
    lines.append(("xs", "Current", palette["focus"], 0))

    current_actor = str(dialogue.get("actor", "")).strip()
    current_case = str(dialogue.get("case_id", "")).strip()
    current_lines = [str(line).strip() for line in list(dialogue.get("lines", []) or []) if str(line).strip()]
    if current_lines:
        lines.append(("xxs", f"{current_actor or 'actor'} | {current_case or '-'}", palette["text"], 4))
        for line in current_lines[:3]:
            wrapped = wrap_text(fonts["xxs"], line, rect.width - 42)
            for wrapped_line in wrapped:
                lines.append(("xxs", wrapped_line, palette["muted"], 8))
    else:
        lines.append(("xxs", "No conversation at this minute", palette["muted"], 4))
    current_event = dict(((snapshot.get("case_details", {}) or {}).get(selected_case_id, {}) or {}).get("current_event", {}) or {})
    current_payload = dict(current_event.get("payload", {}) or {})
    if not current_lines:
        if str(current_payload.get("question", "")).strip():
            lines.append(("xxs", f"ER/Spec: {str(current_payload.get('question', '')).strip()}", palette["text"], 4))
        if str(current_payload.get("answer", "")).strip():
            lines.append(("xxs", f"Patient: {str(current_payload.get('answer', '')).strip()}", palette["muted"], 8))
        if str(current_payload.get("requested_test", "")).strip():
            lines.append(("xxs", f"Test ordered: {str(current_payload.get('requested_test', '')).strip()}", palette["text"], 4))
    lines.append(("xxs", "-" * 28, palette["line"], 0))
    lines.append(("xs", f"Selected Case: {selected_case_id or '-'}", palette["accent"], 0))

    if not history:
        lines.append(("xxs", "No stored conversation history yet", palette["muted"], 4))
    else:
        visible_entries = history[-8:]
        if not visible_entries:
            lines.append(("xxs", "No stored conversation for this case yet", palette["muted"], 4))
        else:
            for entry in visible_entries:
                actor = str(entry.get("actor", "")).strip() or "actor"
                case_id = str(entry.get("case_id", "")).strip() or "-"
                minute = int(entry.get("minute", 0) or 0)
                lines.append(("xxs", f"{actor} | m{minute} | {case_id}", palette["text"], 4))
                for line in [str(line).strip() for line in list(entry.get("lines", []) or []) if str(line).strip()]:
                    for wrapped_line in wrap_text(fonts["xxs"], line, rect.width - 42):
                        lines.append(("xxs", wrapped_line, palette["muted"], 8))
                lines.append(("xxs", "", palette["muted"], 0))

    line_height = 15
    visible_items = _visible_row_count(rect, 48, line_height)
    scroll_offset = clamp_scroll_offset(scroll_offset, len(lines), visible_items)
    y = rect.y + 36
    for font_key, text, color, indent in lines[scroll_offset:scroll_offset + visible_items]:
        if set(text) == {"-"}:
            pygame.draw.line(screen, palette["line"], (rect.x + 10, y + 6), (rect.right - 10, y + 6), width=2)
        else:
            draw_text(screen, fonts[font_key], text, rect.x + 10 + indent, y, color)
        y += line_height
    _draw_scroll_hint(screen, pygame, rect, scroll_offset, len(lines), visible_items, palette)
    screen.set_clip(previous_clip)
