"""Logical playfield geometry and window/display options."""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Logical playfield (resolution independent). Kept identical to the breakout
# engine so the letterboxed GUI, scaling and menus are reused unchanged.
# ---------------------------------------------------------------------------
LOGICAL_W = 800


LOGICAL_H = 600


HUD_H = 44                    # reserved band at the top for the HUD


WALL = 8                      # side wall thickness in logical units


# Derived play bounds in logical coordinates. Enemies spawn above FIELD_TOP and
# are culled below FIELD_BOTTOM; the player is clamped inside this box.
FIELD_LEFT = WALL


FIELD_RIGHT = LOGICAL_W - WALL


FIELD_TOP = HUD_H             # top of the play area (just below the HUD band)


FIELD_BOTTOM = LOGICAL_H      # bottom of the play area


FIELD_W = FIELD_RIGHT - FIELD_LEFT


FIELD_H = FIELD_BOTTOM - FIELD_TOP


DISPLAY_MODES = ("windowed", "fullscreen")


WINDOW_SCALES = (1, 2, 3, 4)


FPS_LIMITS = (60, 120, 144, 0)


def window_size(scale: int) -> tuple[int, int]:
    scale = scale if scale in WINDOW_SCALES else 1
    return LOGICAL_W * scale, LOGICAL_H * scale
