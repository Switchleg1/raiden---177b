"""Shared geometry constants and small helpers for terrain painting."""
from __future__ import annotations

import random

import config as C

TILE_H = C.LOGICAL_H - C.HUD_H          # field band height (556)


FAR_SPEED = C.SCROLL_FAR              # slow distant layer (px/s)


NEAR_SPEED = C.SCROLL_NEAR            # ground layer at full scroll


# The rates themselves live in config: a weapon that travels the field in world
# terms has to be defined against the ground rate, and config must not import
# the view layer. These names stay so terrain callers do not change.


SS = 2                                  # BAKE scale: baked PNGs live at 2x


#   for extra detail; runtime loads them once and downscales. Procedural
#   fallback (no baked art) also paints at this scale — prefer running
#   scripts/bake_terrain.py so gameplay only ever loads + scales.

TILE2 = TILE_H * SS


W2 = C.LOGICAL_W * SS


RGB = tuple[int, int, int]


def _theme_rng(theme: str, seed: int) -> random.Random:
    idx = list(C.StageTheme).index(C.StageTheme(theme))
    return random.Random((seed & 0xFFFF) * 977 + idx * 31337 + 11)


def _blend(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore


def _scale2(v: float) -> int:
    return int(round(v * SS))


def _npmod():
    """numpy or None — texture passes no-op gracefully without it."""
    try:
        import numpy
        return numpy
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# primitives — all accept LOGICAL coords; helpers paint into the 2x surfaces.
# `seam` marks a shape that may cross the wrap seam; vertical copies are made.
# ---------------------------------------------------------------------------

def _ys(y: float, h: float = 0.0) -> list[float]:
    """Vertical positions for a shape of height h at y, incl. seam copies."""
    out = [y]
    if h > 0:
        if y + h > TILE_H:
            out.append(y - TILE_H)
        if y < 0:
            out.append(y + TILE_H)
    return out
