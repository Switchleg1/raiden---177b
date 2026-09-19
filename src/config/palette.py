"""Colour palettes (normal + high contrast)."""
from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Colours (original, high-contrast palette). Space-themed for a shmup.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Palette:
    bg: tuple[int, int, int]
    field_bg: tuple[int, int, int]
    wall: tuple[int, int, int]
    player: tuple[int, int, int]
    player_bullet: tuple[int, int, int]
    enemy_bullet: tuple[int, int, int]
    hud_text: tuple[int, int, int]
    ui_text: tuple[int, int, int]
    ui_focus: tuple[int, int, int]
    ui_selected: tuple[int, int, int]


PALETTE = Palette(
    bg=(8, 9, 16),
    field_bg=(12, 16, 30),
    wall=(60, 74, 108),
    player=(120, 210, 255),
    player_bullet=(150, 255, 210),
    enemy_bullet=(255, 120, 150),
    hud_text=(200, 214, 238),
    ui_text=(222, 228, 240),
    ui_focus=(255, 214, 92),
    ui_selected=(120, 200, 255),
)


PALETTE_HC = Palette(
    bg=(0, 0, 0),
    field_bg=(0, 0, 0),
    wall=(255, 255, 255),
    player=(0, 255, 255),
    player_bullet=(0, 255, 0),
    enemy_bullet=(255, 255, 0),
    hud_text=(255, 255, 255),
    ui_text=(255, 255, 255),
    ui_focus=(255, 255, 0),
    ui_selected=(0, 255, 255),
)
