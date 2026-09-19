"""Geometry, movement and collision primitives for Raiden Shadow.

Pure functions over plain float coordinates; no pygame, fully unit-testable.
The game uses circles for entity hitboxes (cheap and forgiving for a shmup) and
axis-aligned boxes only for the player's field clamp. Fast projectiles are moved
in bounded sub-steps (see :func:`advance`) so they can never tunnel through a
small hitbox at the simulation cap.
"""

from __future__ import annotations

import math
from typing import Any

import config as C


# ---------------------------------------------------------------------------
# Motion
# ---------------------------------------------------------------------------
def advance(obj: Any, dt: float, max_step: float = C.MAX_SUBSTEP) -> None:
    """Integrate ``obj.vx/vy`` into ``obj.x/y`` using bounded sub-steps.

    ``obj`` needs float attributes ``x, y, vx, vy`` (and optionally ``alive``).
    The number of sub-steps is chosen from the largest per-frame travel so that
    no single step exceeds ``max_step`` logical units, preventing tunnelling for
    the fast player bullets and diving enemies.
    """
    vx = getattr(obj, "vx", 0.0)
    vy = getattr(obj, "vy", 0.0)
    if vx == 0.0 and vy == 0.0:
        return
    travel = math.hypot(vx, vy) * dt
    steps = 1 if travel <= max_step else min(6, int(travel // max_step) + 1)
    inv = dt / steps
    for _ in range(steps):
        obj.x += vx * inv
        obj.y += vy * inv


def clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def to_deg(adx: float, ady: float) -> float:
    """Angle (degrees) of the vector (adx, ady) measured from straight-up.

    Straight up is 0deg, positive leans to the right (+x). Used to build the
    weapon spread streams and to aim enemy fire at the player.
    """
    return math.degrees(math.atan2(adx, -ady))


def from_deg(angle_deg: float, speed: float) -> tuple[float, float]:
    """Velocity (vx, vy) for an angle measured from straight-up (deg) and speed."""
    a = math.radians(angle_deg)
    return speed * math.sin(a), -speed * math.cos(a)


# ---------------------------------------------------------------------------
# Collisions (circle vs circle)
# ---------------------------------------------------------------------------
def circle_hit(ax: float, ay: float, ar: float,
               bx: float, by: float, br: float) -> bool:
    dx = ax - bx
    dy = ay - by
    rr = (ar + br)
    return (dx * dx + dy * dy) <= rr * rr


def point_in_box(px: float, py: float,
                 x0: float, y0: float, x1: float, y1: float) -> bool:
    return x0 <= px <= x1 and y0 <= py <= y1


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------
def in_playfield(x: float, y: float, margin: float) -> bool:
    """True while an entity centre is within the play area plus ``margin``."""
    return (C.FIELD_LEFT - margin <= x <= C.FIELD_RIGHT + margin
            and C.FIELD_TOP - margin <= y <= C.FIELD_BOTTOM + margin)


def offscreen_below(y: float, margin: float) -> bool:
    return y > C.FIELD_BOTTOM + margin


def offscreen_above(y: float, margin: float) -> bool:
    return y < C.FIELD_TOP - margin


__all__ = [
    "advance", "clamp", "to_deg", "from_deg", "circle_hit", "point_in_box",
    "in_playfield", "offscreen_below", "offscreen_above",
]
