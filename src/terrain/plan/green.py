"""A green: a plaza or a hearth, and the lanes into it."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .geom import Point

from dataclasses import dataclass, field


@dataclass
class Green:
    """A hamlet core: a plaza the houses stand around, and the lanes into it."""

    x: float
    y: float
    radius: float
    mat: str
    lanes: list[list[Point]] = field(default_factory=list)
