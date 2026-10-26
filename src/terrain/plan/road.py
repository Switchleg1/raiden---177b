"""A road: its line, width, bridges and shoulders."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .geom import Point

from dataclasses import dataclass, field


@dataclass
class Road:
    kind: str                     # "main" | "highway" | "ramp" | "spur" | "track"
    path: list[Point]
    width: float
    bridges: list[Point] = field(default_factory=list)
    #: paved/gravel strip either side of the carriageway. Part of the ROAD, not a
    #: row of parcels: a highway's shoulders were modelled as ~200 narrow Field
    #: polygons, which the painter paid for per slice and which the city-block
    #: rules then read as 18 px-wide "blocks".
    shoulder: float = 0.0
