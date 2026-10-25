"""A ridge: the spine of a landform."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .geom import Point

from dataclasses import dataclass, field


@dataclass
class Ridge:
    """A ridge system seen from above: a spine, a crest profile along it, and
    flanks whose steepness differs (a hogback is steep on one side)."""

    shape: str
    spine: list[Point]
    crest: list[float]            # relative height 0..1 at each spine point
    width: float                  # flank half-width, px
    height: float                 # overall relief this ridge contributes
    asym: float = 0.0             # 0 = symmetric flanks, 1 = one sheer side
    spurs: list[list[Point]] = field(default_factory=list)
    gaps: list[tuple[float, float]] = field(default_factory=list)
