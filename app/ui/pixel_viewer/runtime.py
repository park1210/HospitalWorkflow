from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.core.logger import get_latest_run_id
from app.ui.pixel_viewer.background_renderer import BackgroundRenderer
from app.ui.pixel_viewer import animation_controller
from app.ui.pixel_viewer import entity_renderer
from app.ui.pixel_viewer import input_controller
from app.ui.pixel_viewer import panel_renderer
from app.ui.pixel_viewer import presentation_timeline
from app.ui.pixel_viewer.what_if_runtime import run_case_replay


DEFAULT_WINDOW_WIDTH = 1400
DEFAULT_WINDOW_HEIGHT = 820
FPS = 30
POLL_INTERVAL_MS = 350
MOVE_SPEED = 0.18

BG = (18, 20, 33)
BG_SOFT = (30, 35, 54)
LINE = (90, 106, 165)
TEXT = (242, 243, 248)
MUTED = (180, 188, 220)
ACCENT = (112, 214, 255)
ACCENT_2 = (255, 214, 112)
DANGER = (255, 107, 107)
PENDING = (255, 184, 107)
OBS = (200, 162, 255)
DOCTOR_COLOR = (139, 204, 255)
BUBBLE = (249, 251, 255)
BUBBLE_TEXT = (35, 39, 58)
PATIENT_CRITICAL = (255, 97, 97)
PATIENT_HIGH = (255, 170, 88)
PATIENT_MED = (255, 222, 120)
PATIENT_LOW = (170, 222, 130)
FOCUS = (255, 246, 133)
FOCUS_SOFT = (255, 236, 170)

MAP_ORIGIN_X = 18
MAP_ORIGIN_Y = 78
MAP_TILE = 18
MAP_GRID_WIDTH = 44
MAP_GRID_HEIGHT = 26
ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "pixel"
REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_run_id(argv: list[str]) -> str:
    if len(argv) >= 2 and str(argv[1]).strip():
        return str(argv[1]).strip()
    return get_latest_run_id(settings.REPORTS_DIR, required_file="live_visual_state.json")


def _snapshot_path(run_id: str) -> Path:
    return settings.REPORTS_DIR / run_id / "live_visual_state.json"


def _load_snapshot(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _render(
    screen: Any,
    pygame: Any,
    fonts: dict[str, Any],
    sprites: dict[str, Any],
    background: Any,
    snapshot: dict[str, Any],
    selected_case_id: str,
    playback_state: dict[str, Any],
    panel_scroll: dict[str, int],
) -> None:
    palette = {
        "bg": BG,
        "bg_soft": BG_SOFT,
        "line": LINE,
        "text": TEXT,
        "muted": MUTED,
        "accent": ACCENT,
        "accent_2": ACCENT_2,
        "danger": DANGER,
        "pending": PENDING,
        "obs": OBS,
        "doctor_color": DOCTOR_COLOR,
        "bubble": BUBBLE,
        "bubble_text": BUBBLE_TEXT,
        "patient_low": PATIENT_LOW,
        "patient_high": PATIENT_HIGH,
        "patient_med": PATIENT_MED,
        "patient_critical": PATIENT_CRITICAL,
        "focus": FOCUS,
        "focus_soft": FOCUS_SOFT,
    }
    screen.fill(BG)
    panel_renderer.draw_text(screen, fonts["lg"], "Live Pixel ER Viewer", 24, 18, TEXT)
    panel_renderer.draw_text(
        screen,
        fonts["xs"],
        "Rendering hospital scene from live_visual_state.json while simulation is running",
        24,
        48,
        MUTED,
    )

    width, height = screen.get_size()
    layout = panel_renderer.compute_layout(width, height, MAP_GRID_WIDTH, MAP_GRID_HEIGHT, MAP_TILE)
    scene_panel = pygame.Rect(*layout["scene_panel"])
    hud_rect = pygame.Rect(*layout["hud_rect"])
    overview_rect = pygame.Rect(*layout["overview_rect"])
    controls_rect = pygame.Rect(*layout["controls_rect"])
    patients_rect = pygame.Rect(*layout["patients_rect"])
    comparison_rect = pygame.Rect(*layout["comparison_rect"])
    detail_rect = pygame.Rect(*layout["detail_rect"])
    dialogue_rect = pygame.Rect(*layout["dialogue_rect"])

    panel_renderer.draw_panel(screen, pygame, scene_panel, BG_SOFT, LINE)
    previous_clip = screen.get_clip()
    screen.set_clip(scene_panel.inflate(-6, -6))
    entity_renderer.draw_scene(
        screen,
        pygame,
        fonts,
        sprites,
        background,
        snapshot,
        selected_case_id,
        MAP_ORIGIN_X,
        MAP_ORIGIN_Y,
        MAP_TILE,
        palette,
    )
    screen.set_clip(previous_clip)
    panel_renderer.draw_hud_panel(
        screen,
        pygame,
        fonts,
        snapshot,
        hud_rect,
        selected_case_id,
        playback_state,
        palette,
    )
    panel_renderer.draw_overview_panel(screen, pygame, fonts, snapshot, overview_rect, palette)
    panel_renderer.draw_control_panel(
        screen,
        pygame,
        fonts,
        snapshot,
        controls_rect,
        selected_case_id,
        playback_state,
        int(panel_scroll.get("controls", 0) or 0),
        palette,
    )
    panel_renderer.draw_patient_list(
        screen,
        pygame,
        fonts,
        snapshot,
        patients_rect,
        int(panel_scroll.get("patients", 0) or 0),
        palette,
    )
    panel_renderer.draw_comparison_panel(
        screen,
        pygame,
        fonts,
        snapshot,
        comparison_rect,
        int(panel_scroll.get("comparison", 0) or 0),
        palette,
    )
    panel_renderer.draw_case_detail_panel(
        screen,
        pygame,
        fonts,
        snapshot,
        detail_rect,
        selected_case_id,
        int(panel_scroll.get("detail", 0) or 0),
        palette,
    )
    panel_renderer.draw_dialogue_panel(
        screen,
        pygame,
        fonts,
        snapshot,
        dialogue_rect,
        selected_case_id,
        int(panel_scroll.get("dialogue", 0) or 0),
        palette,
    )


def main(argv: list[str] | None = None) -> None:
    try:
        import pygame  # type: ignore
    except ImportError:
        print("pygame is not installed. Install it with: python -m pip install pygame")
        raise SystemExit(1)

    args = list(sys.argv if argv is None else argv)
    run_id = _resolve_run_id(args)
    snapshot_path = _snapshot_path(run_id)
    if not snapshot_path.exists():
        print(f"Live snapshot not found: {snapshot_path}")
        raise SystemExit(1)

    pygame.init()
    pygame.display.set_caption("Live Pixel ER Viewer")
    display_info = pygame.display.Info()
    window_width = min(DEFAULT_WINDOW_WIDTH, max(1280, int(display_info.current_w) - 80))
    window_height = min(DEFAULT_WINDOW_HEIGHT, max(820, int(display_info.current_h) - 120))
    screen = pygame.display.set_mode((window_width, window_height))
    clock = pygame.time.Clock()
    fonts = {
        "lg": pygame.font.SysFont("consolas", 32, bold=True),
        "sm": pygame.font.SysFont("consolas", 19, bold=True),
        "xs": pygame.font.SysFont("consolas", 15),
        "xxs": pygame.font.SysFont("consolas", 13),
    }
    background_renderer = BackgroundRenderer(
        asset_dir=ASSET_DIR,
        repo_root=REPO_ROOT,
        map_origin_x=MAP_ORIGIN_X,
        map_origin_y=MAP_ORIGIN_Y,
        map_tile=MAP_TILE,
        map_grid_width=MAP_GRID_WIDTH,
        map_grid_height=MAP_GRID_HEIGHT,
    )
    sprites = background_renderer.load_or_build_sprite_cache(pygame)
    background = background_renderer.load_or_build_background_surface(pygame, sprites)

    last_mtime: Optional[float] = None
    next_poll_ms = 0
    snapshot = _load_snapshot(snapshot_path)
    render_positions: dict[str, dict[str, float]] = {}
    selected_case_id = input_controller.default_selected_case(snapshot)
    playback_state = presentation_timeline.sync_playback_state(
        presentation_timeline.initial_playback_state(),
        snapshot,
        selected_case_id,
        pygame.time.get_ticks(),
    )
    presented_snapshot = presentation_timeline.presented_snapshot(snapshot, playback_state, selected_case_id)
    animation_controller.update_entity_render_positions(presented_snapshot, render_positions, MAP_ORIGIN_X, MAP_ORIGIN_Y, MAP_TILE)
    panel_scroll = {
        "controls": 0,
        "patients": 0,
        "comparison": 0,
        "detail": 0,
        "dialogue": 0,
    }
    replay_worker: Optional[threading.Thread] = None
    replay_feedback: dict[str, Any] = {}

    def _start_replay_job(case_id: str, presented: dict[str, Any]) -> None:
        nonlocal replay_worker, replay_feedback, playback_state
        presentation = dict(presented.get("presentation", {}) or {})
        selected_decision = dict(presentation.get("selected_decision", {}) or {})
        selected_candidate = dict(presentation.get("selected_candidate", {}) or {})
        snapshot_id = str(selected_decision.get("snapshot_id", "")).strip()
        action_type = str(selected_candidate.get("type", "")).strip()
        if not case_id or not snapshot_id or not action_type:
            playback_state["replay_status"] = "missing_snapshot_or_action"
            return
        if replay_worker is not None and replay_worker.is_alive():
            playback_state["replay_status"] = "replay_in_progress"
            return

        playback_state["replay_status"] = "replay_running"
        playback_state["replay_summary"] = {}
        replay_feedback = {}

        def _worker() -> None:
            nonlocal replay_feedback
            try:
                replay_feedback = run_case_replay(
                    run_id=run_id,
                    case_id=case_id,
                    snapshot_id=snapshot_id,
                    selected_action=selected_candidate,
                )
            except Exception as exc:
                replay_feedback = {
                    "status": "failed",
                    "error": str(exc),
                }

        replay_worker = threading.Thread(target=_worker, daemon=True)
        replay_worker.start()

    running = True
    while running:
        now_ms = pygame.time.get_ticks()
        width, height = screen.get_size()
        layout = panel_renderer.compute_layout(width, height, MAP_GRID_WIDTH, MAP_GRID_HEIGHT, MAP_TILE)
        scene_panel = pygame.Rect(*layout["scene_panel"])
        controls_rect = pygame.Rect(*layout["controls_rect"])
        hud_rect = pygame.Rect(*layout["hud_rect"])
        patients_rect = pygame.Rect(*layout["patients_rect"])
        comparison_rect = pygame.Rect(*layout["comparison_rect"])
        detail_rect = pygame.Rect(*layout["detail_rect"])
        dialogue_rect = pygame.Rect(*layout["dialogue_rect"])
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                playback_state = presentation_timeline.handle_action(playback_state, "toggle_pause", now_ms)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_RIGHT:
                playback_state = presentation_timeline.handle_action(playback_state, "next_beat", now_ms)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_LEFT:
                playback_state = presentation_timeline.handle_action(playback_state, "prev_beat", now_ms)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                handled = False
                presented_snapshot = presentation_timeline.presented_snapshot(snapshot, playback_state, selected_case_id)
                for spec in panel_renderer.hud_button_specs(
                    hud_rect,
                    presented_snapshot,
                    selected_case_id,
                    playback_state,
                ):
                    if bool(spec.get("disabled", False)):
                        continue
                    if pygame.Rect(*spec["rect"]).collidepoint(event.pos):
                        playback_state = presentation_timeline.handle_action(
                            playback_state,
                            str(spec["action"]).strip(),
                            now_ms,
                        )
                        if str(spec["action"]).strip() == "apply_replay":
                            _start_replay_job(selected_case_id, presented_snapshot)
                        handled = True
                        break
                if handled:
                    continue
                for spec in panel_renderer.control_interaction_specs(
                    controls_rect,
                    presented_snapshot,
                    selected_case_id,
                    playback_state,
                    int(panel_scroll.get("controls", 0) or 0),
                ):
                    if pygame.Rect(*spec["rect"]).collidepoint(event.pos):
                        playback_state = presentation_timeline.handle_action(
                            playback_state,
                            str(spec["action"]).strip(),
                            now_ms,
                        )
                        if str(spec["action"]).strip() == "apply_replay":
                            _start_replay_job(selected_case_id, presented_snapshot)
                        handled = True
                        break
                if handled:
                    continue
                if scene_panel.inflate(-6, -6).collidepoint(event.pos):
                    for hitbox, case_id in input_controller.scene_patient_hitboxes(presented_snapshot, pygame):
                        if hitbox.collidepoint(event.pos):
                            selected_case_id = case_id
                            playback_state = presentation_timeline.sync_playback_state(playback_state, snapshot, selected_case_id, now_ms)
                            panel_scroll["detail"] = 0
                            panel_scroll["dialogue"] = 0
                            handled = True
                            break
                if handled:
                    continue
                for hitbox, case_id in input_controller.list_patient_hitboxes(snapshot, patients_rect, pygame):
                    if hitbox.collidepoint(event.pos):
                        selected_case_id = case_id
                        playback_state = presentation_timeline.sync_playback_state(playback_state, snapshot, selected_case_id, now_ms)
                        panel_scroll["detail"] = 0
                        panel_scroll["dialogue"] = 0
                        break
            elif event.type == pygame.MOUSEWHEEL:
                mouse_pos = pygame.mouse.get_pos()
                delta = -int(event.y or 0)
                if controls_rect.collidepoint(mouse_pos):
                    panel_scroll["controls"] = max(0, int(panel_scroll.get("controls", 0) or 0) + delta)
                elif patients_rect.collidepoint(mouse_pos):
                    panel_scroll["patients"] = max(0, int(panel_scroll.get("patients", 0) or 0) + delta)
                elif comparison_rect.collidepoint(mouse_pos):
                    panel_scroll["comparison"] = max(0, int(panel_scroll.get("comparison", 0) or 0) + delta)
                elif detail_rect.collidepoint(mouse_pos):
                    panel_scroll["detail"] = max(0, int(panel_scroll.get("detail", 0) or 0) + delta)
                elif dialogue_rect.collidepoint(mouse_pos):
                    panel_scroll["dialogue"] = max(0, int(panel_scroll.get("dialogue", 0) or 0) + delta)

        if now_ms >= next_poll_ms:
            next_poll_ms = now_ms + POLL_INTERVAL_MS
            if snapshot_path.exists():
                mtime = snapshot_path.stat().st_mtime
                if last_mtime is None or mtime != last_mtime:
                    snapshot = _load_snapshot(snapshot_path)
                    case_details = dict(snapshot.get("case_details", {}) or {})
                    if not selected_case_id or selected_case_id not in case_details:
                        selected_case_id = input_controller.default_selected_case(snapshot)
                    playback_state = presentation_timeline.sync_playback_state(playback_state, snapshot, selected_case_id, now_ms)
                    presented_snapshot = presentation_timeline.presented_snapshot(snapshot, playback_state, selected_case_id)
                    animation_controller.update_entity_render_positions(presented_snapshot, render_positions, MAP_ORIGIN_X, MAP_ORIGIN_Y, MAP_TILE)
                    last_mtime = mtime

        if replay_feedback:
            if str(replay_feedback.get("status", "")).strip() == "completed":
                playback_state["replay_status"] = "replay_completed"
                playback_state["replay_summary"] = dict(replay_feedback or {})
            else:
                playback_state["replay_status"] = str(replay_feedback.get("status", "")).strip() or "replay_failed"
                playback_state["replay_summary"] = dict(replay_feedback or {})
            replay_feedback = {}

        playback_state = presentation_timeline.sync_playback_state(playback_state, snapshot, selected_case_id, now_ms)
        playback_state = presentation_timeline.advance_playback_state(playback_state, now_ms)
        presented_snapshot = presentation_timeline.presented_snapshot(snapshot, playback_state, selected_case_id)
        animation_controller.animate_entity_render_positions(
            presented_snapshot,
            render_positions,
            MOVE_SPEED,
            MAP_ORIGIN_X,
            MAP_ORIGIN_Y,
            MAP_TILE,
        )
        _render(screen, pygame, fonts, sprites, background, presented_snapshot, selected_case_id, playback_state, panel_scroll)
        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
