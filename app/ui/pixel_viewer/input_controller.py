from __future__ import annotations

from typing import Any


def default_selected_case(snapshot: dict[str, Any]) -> str:
    focus_case = str((snapshot.get("er_focus", {}) or {}).get("case_id", "")).strip()
    if focus_case:
        return focus_case
    dialogue_case = str((snapshot.get("dialogue", {}) or {}).get("case_id", "")).strip()
    if dialogue_case:
        return dialogue_case
    patients = list(snapshot.get("patients", []) or [])
    if patients:
        return str(dict(patients[0]).get("case_id", "")).strip()
    return ""


def scene_patient_hitboxes(
    snapshot: dict[str, Any],
    pygame: Any,
) -> list[tuple[Any, str]]:
    hitboxes: list[tuple[Any, str]] = []
    scene = dict(snapshot.get("scene", {}) or {})
    for entity in list(scene.get("entities", []) or []):
        if str(entity.get("kind", "")).strip() != "patient":
            continue
        case_id = str(entity.get("case_id", "")).strip()
        sx = int(float(entity.get("render_x", 0.0) or 0.0))
        sy = int(float(entity.get("render_y", 0.0) or 0.0))
        hitboxes.append((pygame.Rect(sx - 2, sy - 2, 34, 38), case_id))
    return hitboxes


def list_patient_hitboxes(
    snapshot: dict[str, Any],
    patients_rect: Any,
    pygame: Any,
) -> list[tuple[Any, str]]:
    hitboxes: list[tuple[Any, str]] = []
    y = patients_rect.y + 38
    for patient in list(snapshot.get("patients", []) or [])[:8]:
        case_id = str(dict(patient).get("case_id", "")).strip()
        row_rect = pygame.Rect(patients_rect.x + 8, y - 2, patients_rect.width - 16, 34)
        hitboxes.append((row_rect, case_id))
        y += 38
        if y > patients_rect.bottom - 20:
            break
    return hitboxes


def patient_hitboxes(
    snapshot: dict[str, Any],
    patients_rect: Any,
    pygame: Any,
) -> list[tuple[Any, str]]:
    return scene_patient_hitboxes(snapshot, pygame) + list_patient_hitboxes(snapshot, patients_rect, pygame)
