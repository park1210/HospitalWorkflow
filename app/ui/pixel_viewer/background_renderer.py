from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SPRITE_VERSION = "v4"
BACKGROUND_VERSION = "v3"

FLOOR = (214, 214, 218)
FLOOR_ALT = (196, 198, 203)
WALL_SHADOW = (144, 146, 158)
BED = (218, 226, 255)
BED_FRAME = (112, 122, 171)
SEAT = (169, 124, 89)
SEAT_DARK = (109, 76, 54)
DESK = (181, 160, 123)
EQUIP = (123, 146, 178)
QUEUE_TILE = (191, 180, 150)
EXIT_TILE = (161, 197, 147)
SPECIAL_BG = (27, 31, 52)
SPECIAL_TILE = (56, 61, 102)
DOCTOR_COLOR = (139, 204, 255)
SKIN = (245, 217, 188)
COAT = (234, 240, 250)
PATIENT_GOWN = (145, 196, 145)
ACCENT_2 = (255, 214, 112)
LINE = (90, 106, 165)
PANEL = (42, 49, 79)
PANEL_ALT = (52, 60, 98)
ROLE_BG = (246, 243, 232)
ROLE_LINE = (120, 112, 96)
ROLE_ACCENT_ER = (239, 204, 112)
ROLE_ACCENT_SPECIAL = (146, 218, 255)
ROLE_ACCENT_ALERT = (255, 184, 107)

SPRITE_NAMES = [
    "bed",
    "chair",
    "desk",
    "imaging",
    "lab",
    "consult",
    "exit",
    "queue",
    "sidebar",
    "doctor_er",
    "doctor_specialty",
    "patient_stand",
    "patient_bed",
]


class BackgroundRenderer:
    def __init__(
        self,
        asset_dir: Path,
        repo_root: Path,
        map_origin_x: int,
        map_origin_y: int,
        map_tile: int,
        map_grid_width: int,
        map_grid_height: int,
    ) -> None:
        self.asset_dir = asset_dir
        self.repo_root = repo_root
        self.map_origin_x = map_origin_x
        self.map_origin_y = map_origin_y
        self.map_tile = map_tile
        self.map_grid_width = map_grid_width
        self.map_grid_height = map_grid_height
        self.agent_town_public_dir = self.repo_root / "external" / "agent-town" / "public"
        self.agent_town_char_dir = self.agent_town_public_dir / "characters"
        self.agent_town_tileset_dir = self.agent_town_public_dir / "tilesets"
        self.openclaw_dashboard_assets_dir = self.repo_root / "external" / "openclaw-pixel-agents-dashboard" / "public" / "assets"
        self.openclaw_dashboard_char_dir = self.openclaw_dashboard_assets_dir / "characters"
        self.atlas_png = self.asset_dir / "pixel_atlas.png"
        self.atlas_meta = self.asset_dir / "pixel_atlas.json"
        self.background_png = self.asset_dir / f"er_background_{BACKGROUND_VERSION}.png"

    def _to_screen_coords(self, x: int, y: int) -> tuple[int, int]:
        return self.map_origin_x + x * self.map_tile, self.map_origin_y + y * self.map_tile

    def _paint(self, surface: Any, scale: int, x: int, y: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        import pygame  # type: ignore

        pygame.draw.rect(surface, color, pygame.Rect(x * scale, y * scale, w * scale, h * scale))

    def _make_pixel_surface(self, pygame: Any, width: int, height: int, scale: int = 2) -> Any:
        return pygame.Surface((width * scale, height * scale), pygame.SRCALPHA)

    def _load_sheet_scaled(self, pygame: Any, path: Path) -> Any | None:
        if not path.exists():
            return None
        return pygame.image.load(str(path)).convert_alpha()

    def _crop_scaled(self, pygame: Any, sheet: Any, x: int, y: int, w: int, h: int, out_w: int, out_h: int) -> Any:
        rect = pygame.Rect(x, y, w, h)
        sprite = sheet.subsurface(rect).copy()
        return pygame.transform.scale(sprite, (out_w, out_h))

    def _try_build_reference_sprite_cache(self, pygame: Any) -> dict[str, Any]:
        cache: dict[str, Any] = {}
        char_er = self._load_sheet_scaled(pygame, self.agent_town_char_dir / "Premade_Character_48x48_04.png")
        char_special = self._load_sheet_scaled(pygame, self.agent_town_char_dir / "Premade_Character_48x48_06.png")
        char_patient = self._load_sheet_scaled(pygame, self.agent_town_char_dir / "Premade_Character_48x48_01.png")
        office = self._load_sheet_scaled(pygame, self.agent_town_tileset_dir / "Modern_Office_48x48.png")

        if char_er is not None:
            cache["doctor_er"] = self._crop_scaled(pygame, char_er, 0, 48 * 3, 48, 48, 24, 28)
            cache["doctor_er_walk_1"] = self._crop_scaled(pygame, char_er, 48, 48 * 3, 48, 48, 24, 28)
            cache["doctor_er_walk_2"] = self._crop_scaled(pygame, char_er, 96, 48 * 3, 48, 48, 24, 28)
        if char_special is not None:
            cache["doctor_specialty"] = self._crop_scaled(pygame, char_special, 0, 48 * 3, 48, 48, 24, 28)
            cache["doctor_specialty_walk_1"] = self._crop_scaled(pygame, char_special, 48, 48 * 3, 48, 48, 24, 28)
            cache["doctor_specialty_walk_2"] = self._crop_scaled(pygame, char_special, 96, 48 * 3, 48, 48, 24, 28)
        if char_patient is not None:
            cache["patient_stand"] = self._crop_scaled(pygame, char_patient, 0, 48 * 3, 48, 48, 24, 28)
            cache["patient_stand_walk_1"] = self._crop_scaled(pygame, char_patient, 48, 48 * 3, 48, 48, 24, 28)
            cache["patient_stand_walk_2"] = self._crop_scaled(pygame, char_patient, 96, 48 * 3, 48, 48, 24, 28)
            cache["patient_bed"] = self._crop_scaled(pygame, char_patient, 48 * 5, 48 * 5, 48, 48, 28, 20)

        if office is not None:
            cache["chair"] = self._crop_scaled(pygame, office, 0, 48 * 3, 48, 48, 22, 20)
            cache["desk"] = self._crop_scaled(pygame, office, 48 * 10, 48 * 3, 48, 48, 26, 22)
            cache["imaging"] = self._crop_scaled(pygame, office, 48 * 13, 48 * 17, 48, 48, 24, 24)
            cache["lab"] = self._crop_scaled(pygame, office, 48 * 10, 48 * 17, 48, 48, 24, 24)
            cache["consult"] = self._crop_scaled(pygame, office, 48 * 7, 48 * 8, 48, 48, 20, 20)
            cache["bed"] = self._crop_scaled(pygame, office, 0, 48 * 22, 48 * 3, 48, 46, 20)
            cache["queue"] = self._crop_scaled(pygame, office, 48 * 12, 48 * 9, 48, 48, 18, 18)
            cache["exit"] = self._crop_scaled(pygame, office, 48 * 15, 48 * 30, 48, 48, 18, 18)
            cache["sidebar"] = self._crop_scaled(pygame, office, 48 * 4, 48 * 0, 48, 48, 20, 20)
        return cache

    def _directional_sprite_set(self, pygame: Any, sheet: Any, out_w: int, out_h: int) -> dict[str, Any]:
        if sheet is None:
            return {}
        frame_w = 16
        frame_h = 32
        directions = {"down": 0, "up": 1, "right": 2}
        cache: dict[str, Any] = {}
        for direction, row in directions.items():
            y = row * frame_h
            cache[f"{direction}_walk_1"] = self._crop_scaled(pygame, sheet, 0 * frame_w, y, frame_w, frame_h, out_w, out_h)
            cache[f"{direction}_walk_2"] = self._crop_scaled(pygame, sheet, 1 * frame_w, y, frame_w, frame_h, out_w, out_h)
            cache[f"{direction}_walk_3"] = self._crop_scaled(pygame, sheet, 2 * frame_w, y, frame_w, frame_h, out_w, out_h)
            cache[f"{direction}_typing_1"] = self._crop_scaled(pygame, sheet, 3 * frame_w, y, frame_w, frame_h, out_w, out_h)
            cache[f"{direction}_typing_2"] = self._crop_scaled(pygame, sheet, 4 * frame_w, y, frame_w, frame_h, out_w, out_h)
            cache[f"{direction}_reading_1"] = self._crop_scaled(pygame, sheet, 5 * frame_w, y, frame_w, frame_h, out_w, out_h)
            cache[f"{direction}_reading_2"] = self._crop_scaled(pygame, sheet, 6 * frame_w, y, frame_w, frame_h, out_w, out_h)
            cache[f"{direction}_idle"] = cache[f"{direction}_walk_2"]
        for suffix in ("walk_1", "walk_2", "walk_3", "typing_1", "typing_2", "reading_1", "reading_2", "idle"):
            cache[f"left_{suffix}"] = pygame.transform.flip(cache[f"right_{suffix}"], True, False)
        return cache

    def _try_build_openclaw_dashboard_sprite_cache(self, pygame: Any) -> dict[str, Any]:
        char_files = {
            "doctor_er": "char_0.png",
            "doctor_specialty": "char_1.png",
            "patient_stand": "char_2.png",
            "nurse": "char_3.png",
            "reception": "char_4.png",
        }
        cache: dict[str, Any] = {}
        for base_key, file_name in char_files.items():
            sheet = self._load_sheet_scaled(pygame, self.openclaw_dashboard_char_dir / file_name)
            if sheet is None:
                continue
            directional = self._directional_sprite_set(pygame, sheet, 26, 48)
            for variant_key, sprite in directional.items():
                cache[f"{base_key}_{variant_key}"] = sprite
            cache[base_key] = directional.get("down_idle")
        return cache

    def _build_sprite_cache(self, pygame: Any) -> dict[str, Any]:
        scale = 2
        cache: dict[str, Any] = {}

        bed = self._make_pixel_surface(pygame, 16, 16, scale)
        self._paint(bed, scale, 1, 13, 14, 1, (84, 88, 104))
        self._paint(bed, scale, 1, 4, 14, 8, (202, 210, 235))
        self._paint(bed, scale, 2, 5, 12, 6, BED)
        self._paint(bed, scale, 2, 4, 12, 1, BED_FRAME)
        self._paint(bed, scale, 2, 11, 12, 1, BED_FRAME)
        self._paint(bed, scale, 2, 5, 1, 6, BED_FRAME)
        self._paint(bed, scale, 13, 5, 1, 6, BED_FRAME)
        self._paint(bed, scale, 3, 6, 5, 2, (248, 248, 252))
        self._paint(bed, scale, 9, 6, 3, 4, (193, 206, 240))
        self._paint(bed, scale, 3, 12, 1, 3, BED_FRAME)
        self._paint(bed, scale, 12, 12, 1, 3, BED_FRAME)
        cache["bed"] = bed

        chair = self._make_pixel_surface(pygame, 16, 16, scale)
        self._paint(chair, scale, 4, 2, 8, 2, SEAT_DARK)
        self._paint(chair, scale, 4, 4, 8, 3, SEAT)
        self._paint(chair, scale, 3, 7, 10, 1, SEAT_DARK)
        self._paint(chair, scale, 5, 8, 1, 5, SEAT_DARK)
        self._paint(chair, scale, 10, 8, 1, 5, SEAT_DARK)
        self._paint(chair, scale, 6, 8, 3, 1, (198, 154, 112))
        cache["chair"] = chair

        desk = self._make_pixel_surface(pygame, 16, 16, scale)
        self._paint(desk, scale, 2, 13, 12, 1, (102, 82, 62))
        self._paint(desk, scale, 2, 4, 12, 5, DESK)
        self._paint(desk, scale, 2, 8, 12, 1, (149, 132, 100))
        self._paint(desk, scale, 3, 9, 1, 4, WALL_SHADOW)
        self._paint(desk, scale, 12, 9, 1, 4, WALL_SHADOW)
        self._paint(desk, scale, 4, 5, 5, 3, (208, 216, 232))
        self._paint(desk, scale, 10, 5, 2, 3, (78, 107, 152))
        cache["desk"] = desk

        imaging = self._make_pixel_surface(pygame, 16, 16, scale)
        self._paint(imaging, scale, 2, 13, 12, 1, (96, 98, 112))
        self._paint(imaging, scale, 2, 3, 12, 10, EQUIP)
        self._paint(imaging, scale, 3, 4, 10, 5, (88, 120, 173))
        self._paint(imaging, scale, 5, 5, 6, 3, (176, 214, 255))
        self._paint(imaging, scale, 4, 10, 8, 2, (205, 220, 245))
        cache["imaging"] = imaging

        lab = self._make_pixel_surface(pygame, 16, 16, scale)
        self._paint(lab, scale, 2, 13, 12, 1, (96, 98, 112))
        self._paint(lab, scale, 2, 3, 12, 10, EQUIP)
        self._paint(lab, scale, 4, 4, 8, 3, (231, 239, 255))
        self._paint(lab, scale, 4, 8, 3, 3, (255, 184, 107))
        self._paint(lab, scale, 9, 8, 3, 3, (170, 222, 130))
        cache["lab"] = lab

        consult = self._make_pixel_surface(pygame, 16, 16, scale)
        self._paint(consult, scale, 2, 2, 12, 12, SPECIAL_TILE)
        self._paint(consult, scale, 4, 4, 8, 8, PANEL)
        cache["consult"] = consult

        exit_tile = self._make_pixel_surface(pygame, 16, 16, scale)
        self._paint(exit_tile, scale, 2, 2, 12, 12, EXIT_TILE)
        self._paint(exit_tile, scale, 10, 5, 2, 2, (94, 170, 88))
        self._paint(exit_tile, scale, 10, 9, 2, 2, (94, 170, 88))
        self._paint(exit_tile, scale, 6, 7, 5, 2, (94, 170, 88))
        cache["exit"] = exit_tile

        queue = self._make_pixel_surface(pygame, 16, 16, scale)
        self._paint(queue, scale, 2, 2, 12, 12, QUEUE_TILE)
        self._paint(queue, scale, 4, 4, 8, 8, (170, 160, 132))
        cache["queue"] = queue

        sidebar = self._make_pixel_surface(pygame, 16, 16, scale)
        self._paint(sidebar, scale, 2, 2, 12, 12, SPECIAL_TILE)
        self._paint(sidebar, scale, 4, 4, 8, 8, PANEL_ALT)
        cache["sidebar"] = sidebar

        doctor = self._make_pixel_surface(pygame, 18, 22, scale)
        self._paint(doctor, scale, 6, 20, 6, 1, (102, 104, 118))
        self._paint(doctor, scale, 6, 2, 6, 4, SKIN)
        self._paint(doctor, scale, 5, 1, 8, 2, (93, 67, 53))
        self._paint(doctor, scale, 4, 6, 10, 2, (73, 58, 49))
        self._paint(doctor, scale, 4, 8, 10, 9, COAT)
        self._paint(doctor, scale, 6, 10, 6, 4, DOCTOR_COLOR)
        self._paint(doctor, scale, 3, 9, 1, 6, COAT)
        self._paint(doctor, scale, 14, 9, 1, 6, COAT)
        self._paint(doctor, scale, 7, 6, 1, 1, (40, 48, 62))
        self._paint(doctor, scale, 10, 6, 1, 1, (40, 48, 62))
        self._paint(doctor, scale, 6, 17, 2, 3, LINE)
        self._paint(doctor, scale, 10, 17, 2, 3, LINE)
        cache["doctor_er"] = doctor

        specialist = self._make_pixel_surface(pygame, 18, 22, scale)
        self._paint(specialist, scale, 6, 20, 6, 1, (102, 104, 118))
        self._paint(specialist, scale, 6, 2, 6, 4, SKIN)
        self._paint(specialist, scale, 5, 1, 8, 2, (66, 61, 82))
        self._paint(specialist, scale, 4, 6, 10, 2, (60, 56, 76))
        self._paint(specialist, scale, 4, 8, 10, 9, ACCENT_2)
        self._paint(specialist, scale, 6, 10, 6, 4, PANEL_ALT)
        self._paint(specialist, scale, 14, 10, 2, 3, (245, 230, 170))
        self._paint(specialist, scale, 6, 17, 2, 3, LINE)
        self._paint(specialist, scale, 10, 17, 2, 3, LINE)
        cache["doctor_specialty"] = specialist

        patient = self._make_pixel_surface(pygame, 18, 22, scale)
        self._paint(patient, scale, 6, 20, 6, 1, (100, 102, 118))
        self._paint(patient, scale, 6, 2, 6, 4, SKIN)
        self._paint(patient, scale, 5, 1, 8, 2, (113, 77, 54))
        self._paint(patient, scale, 4, 6, 10, 2, (99, 70, 49))
        self._paint(patient, scale, 4, 8, 10, 9, PATIENT_GOWN)
        self._paint(patient, scale, 6, 10, 6, 4, (189, 228, 189))
        self._paint(patient, scale, 3, 9, 1, 5, PATIENT_GOWN)
        self._paint(patient, scale, 14, 9, 1, 5, PATIENT_GOWN)
        self._paint(patient, scale, 6, 17, 2, 3, LINE)
        self._paint(patient, scale, 10, 17, 2, 3, LINE)
        cache["patient_stand"] = patient

        patient_bed = self._make_pixel_surface(pygame, 20, 14, scale)
        self._paint(patient_bed, scale, 2, 11, 16, 1, (100, 102, 118))
        self._paint(patient_bed, scale, 2, 6, 14, 5, PATIENT_GOWN)
        self._paint(patient_bed, scale, 14, 4, 4, 4, SKIN)
        self._paint(patient_bed, scale, 3, 7, 4, 2, (188, 228, 188))
        self._paint(patient_bed, scale, 8, 5, 4, 1, (228, 239, 228))
        cache["patient_bed"] = patient_bed

        cache.update(self._try_build_reference_sprite_cache(pygame))
        cache.update(self._try_build_openclaw_dashboard_sprite_cache(pygame))
        return cache

    def _save_sprite_cache_to_disk(self, pygame: Any, sprites: dict[str, Any]) -> None:
        self.asset_dir.mkdir(parents=True, exist_ok=True)
        ordered_names = sorted([name for name in sprites.keys() if name])
        if not ordered_names:
            return
        padding = 4
        atlas_width = padding
        atlas_height = 0
        meta: dict[str, Any] = {"version": SPRITE_VERSION, "sprites": {}}
        for name in ordered_names:
            sprite = sprites[name]
            atlas_width += int(sprite.get_width()) + padding
            atlas_height = max(atlas_height, int(sprite.get_height()))
        atlas_height += padding * 2
        atlas = pygame.Surface((atlas_width, atlas_height), pygame.SRCALPHA)
        x = padding
        for name in ordered_names:
            sprite = sprites[name]
            atlas.blit(sprite, (x, padding))
            meta["sprites"][name] = {"x": x, "y": padding, "w": int(sprite.get_width()), "h": int(sprite.get_height())}
            x += int(sprite.get_width()) + padding
        pygame.image.save(atlas, str(self.atlas_png))
        self.atlas_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_sprite_cache_from_disk(self, pygame: Any) -> dict[str, Any]:
        if not self.atlas_png.exists() or not self.atlas_meta.exists():
            return {}
        try:
            meta = json.loads(self.atlas_meta.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if str(meta.get("version", "")).strip() != SPRITE_VERSION:
            return {}
        sprite_meta = dict(meta.get("sprites", {}) or {})
        atlas = pygame.image.load(str(self.atlas_png)).convert_alpha()
        cache: dict[str, Any] = {}
        for name, info_raw in sprite_meta.items():
            info = dict(info_raw or {})
            rect = pygame.Rect(int(info.get("x", 0) or 0), int(info.get("y", 0) or 0), int(info.get("w", 0) or 0), int(info.get("h", 0) or 0))
            if rect.width <= 0 or rect.height <= 0:
                return {}
            cache[name] = atlas.subsurface(rect).copy()
        return cache

    def load_or_build_sprite_cache(self, pygame: Any) -> dict[str, Any]:
        loaded = self._load_sprite_cache_from_disk(pygame)
        if loaded:
            return loaded
        built = self._build_sprite_cache(pygame)
        self._save_sprite_cache_to_disk(pygame, built)
        return built

    def _build_background_surface(self, pygame: Any, sprites: dict[str, Any]) -> Any:
        width = self.map_grid_width * self.map_tile
        height = self.map_grid_height * self.map_tile
        surface = pygame.Surface((width, height), pygame.SRCALPHA)

        def tile_rect(tx: int, ty: int, tw: int = 1, th: int = 1) -> Any:
            return pygame.Rect(tx * self.map_tile, ty * self.map_tile, tw * self.map_tile, th * self.map_tile)

        for row in range(self.map_grid_height):
            for col in range(self.map_grid_width):
                color = FLOOR if (row + col) % 2 == 0 else FLOOR_ALT
                pygame.draw.rect(surface, color, tile_rect(col, row))

        rooms = [
            (0, 0, 10, 13, (231, 229, 224)),
            (9, 0, 16, 15, (228, 228, 233)),
            (9, 15, 17, 8, (220, 223, 228)),
            (25, 0, 10, 26, (210, 214, 220)),
            (35, 0, 9, 26, SPECIAL_BG),
        ]
        for x, y, w, h, color in rooms:
            pygame.draw.rect(surface, color, tile_rect(x, y, w, h))

        for col in range(1, 9):
            pygame.draw.rect(surface, (224, 219, 208) if col % 2 == 0 else (219, 214, 204), tile_rect(col, 1, 1, 11))
        for col in range(10, 25):
            pygame.draw.rect(surface, (227, 227, 233) if col % 2 == 0 else (222, 222, 229), tile_rect(col, 1, 1, 13))
        for col in range(10, 26):
            pygame.draw.rect(surface, (214, 216, 220) if col % 2 == 0 else (210, 212, 216), tile_rect(col, 16, 1, 7))
        for col in range(26, 35):
            pygame.draw.rect(surface, (229, 230, 233) if col % 2 == 0 else (224, 225, 228), tile_rect(col, 1, 1, 24))
        for row in range(1, 25, 2):
            pygame.draw.rect(surface, (32, 37, 61), tile_rect(35, row, 8, 1))

        wall_lines = [((9, 0), (9, 23)), ((0, 13), (10, 13)), ((9, 15), (26, 15)), ((25, 0), (25, 26)), ((35, 0), (35, 26))]
        for start, end in wall_lines:
            pygame.draw.line(surface, WALL_SHADOW, self._to_screen_coords(*start), self._to_screen_coords(*end), width=3)

        reception = tile_rect(1, 10, 7, 2)
        pygame.draw.rect(surface, (208, 201, 182), reception)
        pygame.draw.rect(surface, (118, 103, 82), reception, width=2)
        for tx in (1, 4, 7):
            pygame.draw.rect(surface, (176, 188, 164), tile_rect(tx, 22, 1, 1))
            pygame.draw.rect(surface, (90, 126, 80), tile_rect(tx, 23, 1, 1))
        pygame.draw.rect(surface, (205, 208, 214), tile_rect(1, 14, 7, 8))
        for ty in (15, 18, 21):
            pygame.draw.line(surface, (190, 193, 200), self._to_screen_coords(1, ty), self._to_screen_coords(8, ty), width=1)

        for tx in (10, 15, 20):
            pygame.draw.rect(surface, (199, 205, 220), tile_rect(tx, 3, 4, 3), border_radius=4)
            pygame.draw.rect(surface, (184, 190, 210), tile_rect(tx, 8, 4, 3), border_radius=4)
            pygame.draw.rect(surface, (170, 176, 193), tile_rect(tx, 12, 4, 1))
        pygame.draw.rect(surface, (205, 209, 214), tile_rect(23, 2, 1, 11))
        pygame.draw.rect(surface, (198, 201, 206), tile_rect(24, 2, 1, 11))

        med_desk = tile_rect(11, 16, 11, 2)
        pygame.draw.rect(surface, (207, 203, 193), med_desk)
        pygame.draw.rect(surface, WALL_SHADOW, med_desk, width=2)
        pygame.draw.rect(surface, (196, 201, 208), tile_rect(22, 17, 2, 2))
        pygame.draw.rect(surface, (188, 194, 203), tile_rect(24, 17, 1, 2))
        pygame.draw.rect(surface, (204, 208, 215), tile_rect(10, 20, 14, 1))

        consult_rect = tile_rect(26, 2, 8, 20)
        pygame.draw.rect(surface, (236, 237, 240), consult_rect)
        pygame.draw.rect(surface, WALL_SHADOW, consult_rect, width=2)
        for ty in (4, 9, 14, 19):
            pygame.draw.rect(surface, (247, 248, 250), tile_rect(27, ty, 6, 3))
        for ty in (6, 11, 16):
            pygame.draw.line(surface, (160, 164, 176), self._to_screen_coords(27, ty), self._to_screen_coords(33, ty), width=2)
        for tx in (27, 31):
            pygame.draw.rect(surface, (224, 214, 196), tile_rect(tx, 3, 2, 1))
            pygame.draw.rect(surface, (210, 214, 220), tile_rect(tx + 1, 4, 1, 1))
        for ty in (8, 13, 18):
            pygame.draw.rect(surface, (216, 222, 228), tile_rect(32, ty, 1, 1))
            pygame.draw.rect(surface, (180, 196, 210), tile_rect(31, ty, 1, 1))

        wing = tile_rect(35, 1, 8, 24)
        pygame.draw.rect(surface, (25, 29, 49), wing)
        for ty in (5, 9, 13, 17, 21):
            pygame.draw.line(surface, (58, 64, 96), self._to_screen_coords(36, ty), self._to_screen_coords(42, ty), width=2)
        for tx in (36, 39, 41):
            for ty in (2, 6, 10, 14, 18, 22):
                pygame.draw.rect(surface, (44, 50, 77), tile_rect(tx, ty, 2, 1), border_radius=3)
                pygame.draw.rect(surface, (68, 76, 112), tile_rect(tx, ty + 1, 2, 1), border_radius=3)
        for tx in (37, 40):
            for ty in (4, 8, 12, 16, 20):
                pygame.draw.rect(surface, (87, 94, 126), tile_rect(tx, ty, 2, 1), border_radius=2)
                pygame.draw.rect(surface, (58, 64, 92), tile_rect(tx, ty + 1, 2, 1), border_radius=2)
        pygame.draw.line(surface, (80, 88, 124), self._to_screen_coords(38, 2), self._to_screen_coords(38, 22), width=1)
        pygame.draw.line(surface, (80, 88, 124), self._to_screen_coords(40, 2), self._to_screen_coords(40, 22), width=1)

        for tx, ty, color in ((2, 2, (154, 192, 220)), (6, 2, (201, 174, 214)), (20, 16, (173, 207, 173))):
            pygame.draw.rect(surface, (96, 100, 118), tile_rect(tx, ty, 2, 1))
            pygame.draw.rect(surface, color, tile_rect(tx, ty, 2, 1).inflate(-6, -4))
        for tx, ty in ((23, 17), (30, 4), (30, 9), (30, 14)):
            pygame.draw.circle(surface, (232, 236, 244), (self.map_origin_x + tx * self.map_tile + 9, self.map_origin_y + ty * self.map_tile + 9), 4)
            pygame.draw.circle(surface, (166, 173, 189), (self.map_origin_x + tx * self.map_tile + 9, self.map_origin_y + ty * self.map_tile + 9), 4, 1)

        try:
            layout = json.loads((self.repo_root / "app" / "data" / "hospital_scene_layout.json").read_text(encoding="utf-8"))
        except Exception:
            layout = {"locations": {}}
        for location_id, location in dict(layout.get("locations", {}) or {}).items():
            kind = str(dict(location).get("kind", "")).strip()
            tx = int(dict(location).get("x", 0) or 0)
            ty = int(dict(location).get("y", 0) or 0)
            sx, sy = tx * self.map_tile + 2, ty * self.map_tile + 2
            sprite_key = ""
            if kind == "bed":
                sprite_key = "bed"
            elif kind == "seat":
                sprite_key = "chair"
            elif kind == "desk":
                sprite_key = "desk"
            elif kind == "queue":
                sprite_key = "queue"
            elif kind == "exit":
                sprite_key = "exit"
            elif kind == "sidebar":
                sprite_key = "sidebar"
            elif kind == "consult":
                sprite_key = "consult"
            elif kind == "equipment" and "imaging" in location_id:
                sprite_key = "imaging"
            elif kind == "equipment" and "lab" in location_id:
                sprite_key = "lab"
            elif kind == "equipment":
                sprite_key = "imaging"
            elif kind == "staff_station":
                sprite_key = "desk"
            if not sprite_key or sprite_key not in sprites:
                continue
            sprite = sprites[sprite_key]
            surface.blit(sprite, sprite.get_rect(center=(sx + (self.map_tile - 4) // 2, sy + (self.map_tile - 4) // 2)).topleft)

        label_font = pygame.font.SysFont("consolas", 16, bold=True)
        small_label_font = pygame.font.SysFont("consolas", 12, bold=True)
        for text, pos, color in [
            ("Waiting", (1, 1), (239, 204, 112)),
            ("ER Beds", (11, 1), (239, 204, 112)),
            ("Observation", (11, 16), (239, 204, 112)),
            ("Consult Hall", (27, 1), (146, 218, 255)),
            ("Specialists", (36, 1), (146, 218, 255)),
        ]:
            txt = label_font.render(text, False, color)
            surface.blit(txt, self._to_screen_coords(*pos))

        def draw_role_plate(text: str, tx: int, ty: int, accent: tuple[int, int, int]) -> None:
            x, y = self._to_screen_coords(tx, ty)
            rect = pygame.Rect(x, y, 92, 18)
            pygame.draw.rect(surface, ROLE_BG, rect, border_radius=4)
            pygame.draw.rect(surface, ROLE_LINE, rect, width=2, border_radius=4)
            pygame.draw.rect(surface, accent, pygame.Rect(rect.x + 3, rect.y + 3, 10, 10), border_radius=2)
            text_surface = small_label_font.render(text, False, ROLE_LINE)
            surface.blit(text_surface, (rect.x + 18, rect.y + 2))

        draw_role_plate("RECEPTION", 1, 8, ROLE_ACCENT_ALERT)
        draw_role_plate("TRIAGE", 1, 13, ROLE_ACCENT_ALERT)
        draw_role_plate("ER WORKUP", 12, 7, ROLE_ACCENT_ER)
        draw_role_plate("IMAGING", 22, 4, ROLE_ACCENT_ALERT)
        draw_role_plate("OBS UNIT", 12, 21, ROLE_ACCENT_ER)
        draw_role_plate("CONSULT", 27, 22, ROLE_ACCENT_SPECIAL)
        draw_role_plate("SPECIALTY PODS", 35, 23, ROLE_ACCENT_SPECIAL)

        def draw_icon_cross(tx: int, ty: int, color: tuple[int, int, int]) -> None:
            x, y = self._to_screen_coords(tx, ty)
            pygame.draw.rect(surface, color, pygame.Rect(x + 10, y + 4, 4, 12))
            pygame.draw.rect(surface, color, pygame.Rect(x + 6, y + 8, 12, 4))

        def draw_icon_clipboard(tx: int, ty: int, color: tuple[int, int, int]) -> None:
            x, y = self._to_screen_coords(tx, ty)
            pygame.draw.rect(surface, color, pygame.Rect(x + 5, y + 4, 12, 14), width=2)
            pygame.draw.rect(surface, color, pygame.Rect(x + 8, y + 2, 6, 3))

        def draw_icon_scan(tx: int, ty: int, color: tuple[int, int, int]) -> None:
            x, y = self._to_screen_coords(tx, ty)
            pygame.draw.rect(surface, color, pygame.Rect(x + 4, y + 5, 14, 10), width=2)
            pygame.draw.line(surface, color, (x + 6, y + 13), (x + 16, y + 7), width=2)

        def draw_icon_door(tx: int, ty: int, color: tuple[int, int, int]) -> None:
            x, y = self._to_screen_coords(tx, ty)
            pygame.draw.rect(surface, color, pygame.Rect(x + 5, y + 3, 12, 16), width=2)
            pygame.draw.circle(surface, color, (x + 14, y + 11), 1)

        def draw_cart(tx: int, ty: int, body: tuple[int, int, int], accent: tuple[int, int, int]) -> None:
            x, y = self._to_screen_coords(tx, ty)
            pygame.draw.rect(surface, body, pygame.Rect(x + 3, y + 6, 12, 8))
            pygame.draw.rect(surface, accent, pygame.Rect(x + 5, y + 4, 8, 3))
            pygame.draw.rect(surface, body, pygame.Rect(x + 4, y + 14, 1, 4))
            pygame.draw.rect(surface, body, pygame.Rect(x + 13, y + 14, 1, 4))
            pygame.draw.circle(surface, WALL_SHADOW, (x + 5, y + 18), 1)
            pygame.draw.circle(surface, WALL_SHADOW, (x + 13, y + 18), 1)

        def draw_caution_strip(tx: int, ty: int, length: int = 2) -> None:
            x, y = self._to_screen_coords(tx, ty)
            for idx in range(length * 3):
                color = ROLE_ACCENT_ALERT if idx % 2 == 0 else (98, 98, 104)
                pygame.draw.rect(surface, color, pygame.Rect(x + idx * 6, y + 2, 6, 4))

        def draw_consult_set(tx: int, ty: int) -> None:
            x, y = self._to_screen_coords(tx, ty)
            pygame.draw.rect(surface, (188, 160, 124), pygame.Rect(x + 6, y + 6, 12, 8))
            pygame.draw.rect(surface, (118, 103, 82), pygame.Rect(x + 6, y + 14, 12, 2))
            pygame.draw.rect(surface, (176, 150, 118), pygame.Rect(x + 1, y + 8, 4, 6))
            pygame.draw.rect(surface, (176, 150, 118), pygame.Rect(x + 19, y + 8, 4, 6))
            pygame.draw.rect(surface, (118, 103, 82), pygame.Rect(x + 1, y + 14, 4, 2))
            pygame.draw.rect(surface, (118, 103, 82), pygame.Rect(x + 19, y + 14, 4, 2))

        draw_icon_clipboard(1, 9, ROLE_LINE)
        draw_icon_cross(11, 8, ROLE_ACCENT_ER)
        draw_icon_scan(22, 5, ROLE_ACCENT_ALERT)
        draw_icon_cross(11, 22, ROLE_ACCENT_ER)
        draw_icon_door(27, 23, ROLE_ACCENT_SPECIAL)
        draw_icon_door(40, 23, ROLE_ACCENT_SPECIAL)
        draw_cart(6, 12, (180, 188, 200), ROLE_ACCENT_ALERT)
        draw_cart(20, 18, (172, 182, 196), ROLE_ACCENT_ER)
        draw_caution_strip(22, 6, 2)
        draw_caution_strip(22, 11, 2)
        draw_consult_set(28, 7)
        draw_consult_set(28, 12)
        draw_consult_set(28, 17)

        return surface

    def load_or_build_background_surface(self, pygame: Any, sprites: dict[str, Any]) -> Any:
        if self.background_png.exists():
            try:
                return pygame.image.load(str(self.background_png)).convert_alpha()
            except Exception:
                pass
        background = self._build_background_surface(pygame, sprites)
        self.asset_dir.mkdir(parents=True, exist_ok=True)
        pygame.image.save(background, str(self.background_png))
        return background
