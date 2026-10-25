"""A parcel of ground: a field, a lot, a clearing, a burn."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .geom import Point

from dataclasses import dataclass, field


@dataclass
class Field:
    poly: list[Point]
    mat: str
    kind: str                     # "crop" | "paddy" | "orchard" | "pasture" | "lot"
    furrows: list[tuple[Point, Point]] = field(default_factory=list)
    hedge: bool = True
