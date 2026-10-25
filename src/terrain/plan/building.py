"""A building: what stands where, facing which way."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .geom import Point

from dataclasses import dataclass


@dataclass
class Building:
    kind: str
    x: float
    y: float
    angle: int                    # facing, degrees (0 = faces up-field)
    scale: float
    group: str = ""               # "hamlet" | "farm" | "frontage" | ...
    drive: list[Point] | None = None
    yard: tuple[float, float, float] | None = None   # x, y, radius
