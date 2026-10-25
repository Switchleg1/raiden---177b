"""A chosen anchor for a place."""
from __future__ import annotations

from dataclasses import dataclass

from ...plan.geom import Point


@dataclass
class _Site:
    """A chosen anchor, plus the thing it was chosen against."""

    x: float
    y: float
    near: Point | None = None
    tangent: float = 0.0
