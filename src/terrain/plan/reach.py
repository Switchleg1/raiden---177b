"""How far beyond its own extent a feature DRAWS - the margin a window must
look past to catch everything that reaches into it.

Reach is what a feature draws, not what it is: a ridge's shading spreads past
its spine, a building's sprite and yard overhang its footprint, a green's lanes
run out to the houses. A window that used what a feature IS painted half a yard
or half a lane at a slice boundary.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

#: the floor for each kind of feature, bake px
BASE_REACH: dict[str, float] = {"ridges": 0.0, "water": 0.0, "roads": 0.0,
                                "buildings": 130.0, "fields": 30.0, "woods": 150.0,
                                "greens": 70.0}


def _ridge(f: Any, base: float) -> float:
    return f.width * 3.4 + 40.0


def _water(f: Any, base: float) -> float:
    return max(f.flood, f.half * 2.0) + 60.0


def _road(f: Any, base: float) -> float:
    return f.width * 2.0 + 90.0


def _building(f: Any, base: float) -> float:
    """A building stamps a prop sprite (256 px of art at `scale`, so it overhangs
    128*scale either way) and splats a yard (art scaled by radius/60, so about 2.1
    radii beyond the yard's edge). A guessed constant covered neither, and a
    neighbour's yard appeared in the window that happened to include it and not
    in the one painting the ground under it."""
    spread = 128.0 * float(getattr(f, "scale", 1.0)) + 40.0
    if getattr(f, "yard", None):
        spread = max(spread, 2.2 * float(f.yard[2]) + 40.0)
    return max(base, spread)


def _wood(f: Any, base: float) -> float:
    """A stand's trees are props up to 256*scale wide: its edge is the outermost
    crown, not the stand's points."""
    return max(base, 128.0 + 40.0)


def _green(f: Any, base: float) -> float:
    """A green draws its lanes too, out to the houses around it."""
    lanes = getattr(f, "lanes", None) or []
    far = max((max(abs(p[1] - f.y) for p in lane) for lane in lanes), default=0.0)
    return max(base, far + 20.0)


#: kind -> how far one feature of that kind reaches; kinds not listed use the base
REACH_OF: dict[str, Callable[[Any, float], float]] = {
    "ridges": _ridge, "water": _water, "roads": _road, "buildings": _building,
    "woods": _wood, "greens": _green,
}

__all__ = ["BASE_REACH", "REACH_OF"]
