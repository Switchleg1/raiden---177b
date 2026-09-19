"""Manifest helpers: where a sheet lives and how its grid is laid out.

The data itself is :data:`sprites.sheet_table.SPRITES`; this module is the small
amount of logic around it (paths, tile geometry, the frozen-build override).
"""
from __future__ import annotations

import os
from pathlib import Path

from .sheet_table import SPRITES

__all__ = ["SPRITES", "cols_for", "pygame_rect", "raw_stem", "sheet_path",
           "tile_count"]


def _tex_root() -> Path:
    env = os.environ.get("RAIDEN_TEXTURE_DIR")
    base = Path(env) if env else Path(__file__).resolve().parents[2] / "data" \
        / "textures"
    return base / "sprites"


def sheet_path(name: str) -> Path:
    return _tex_root() / f"{name}.png"


def cols_for(name: str) -> int:
    """Sheet columns: the first anim's frame count, capped at 8."""
    anim = next(iter(SPRITES[name]["anims"]))
    return min(len(SPRITES[name]["anims"][anim]["frames"]), 8)


def tile_count(name: str) -> int:
    """Number of tiles the sheet must hold (highest frame index + 1)."""
    return 1 + max(f for a in SPRITES[name]["anims"].values() for f in a["frames"])


def raw_stem(name: str) -> str | None:
    """Keyed-art stem this sheet is animated from, when it has one."""
    stem: str | None = SPRITES[name].get("raw")
    return stem


def pygame_rect(x, y, w, h):
    import pygame
    return pygame.Rect(x, y, w, h)
