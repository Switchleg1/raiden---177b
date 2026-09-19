"""Sprite sheets + animation sequences (view layer only; no pygame at
import). One tiled PNG per family; animations are frame-index
sequences into the tile grid (classic arcade technique). Sheets are
painted OFFLINE by scripts/bake_sprites.py; :class:`Bank` loads PNGs
at runtime and the renderer falls back to vector art when a sheet
file is missing.
"""
from __future__ import annotations

from .anim import Anim, anim_spec
from .bank import Bank
from .manifest import SPRITES, cols_for, pygame_rect, sheet_path, tile_count
from .painters import bake, build_procedural, tile_xy

__all__ = [
    "Anim",
    "Bank",
    "SPRITES",
    "cols_for",
    "tile_xy",
    "anim_spec",
    "bake",
    "build_procedural",
    "pygame_rect",
    "sheet_path",
    "tile_count",
]
