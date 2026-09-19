"""Letterbox viewport math (logical canvas <-> window pixels)."""
from __future__ import annotations

from dataclasses import dataclass

import config as C


# ---------------------------------------------------------------------------
# Pure mapping helpers
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Viewport:
    """Screen rectangle occupied by the logical playfield after scaling."""
    x: int
    y: int
    w: int
    h: int



def map_mouse_to_logical(win_x: int, win_y: int, view: Viewport,
                         log_w: int = C.LOGICAL_W,
                         log_h: int = C.LOGICAL_H) -> tuple[int, int]:
    if view.w <= 0 or view.h <= 0:
        return (log_w // 2, log_h // 2)
    fx = (win_x - view.x) / view.w
    fy = (win_y - view.y) / view.h
    fx = max(0.0, min(1.0, fx))
    fy = max(0.0, min(1.0, fy))
    lx = int(round(fx * (log_w - 1)))
    ly = int(round(fy * (log_h - 1)))
    return (lx, ly)
