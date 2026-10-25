"""A body of water: a channel, or a closed lake."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .geom import Point

from dataclasses import dataclass


@dataclass
class Water:
    kind: str                     # "river" | "wash" | "channel" | "lake"
    path: list[Point]
    half: float                   # half width, px
    flood: float                  # floodplain half width, px
    #: a body you stand IN, not a channel you cross: its outline is a shoreline and
    #: the water is INSIDE it. Without this the painter strokes the outline like a
    #: river - a ring of water, a bank line on each side of the ring, and flow
    #: glints down the middle of it - and a lake reads as a circular roadway with
    #: centre lines, which is exactly what the user reported seeing.
    closed: bool = False
    #: a point known to be inside a closed body (its anchor): what the fill asks
    #: "which side is water" with
    inside: Point | None = None
