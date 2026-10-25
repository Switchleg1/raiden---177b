"""A plane's sampling frame, widened by a margin."""
from __future__ import annotations

from typing import Any


class _Window:
    """A plane's sampling frame, widened: `_upsample` reads only these fields."""

    def __init__(self, plane: Any, pad: int) -> None:
        self.w = plane.w + 2 * pad
        self.h = plane.h + 2 * pad
        self.x0 = plane.x0 - pad * plane.scale
        self.y0 = plane.y0 - pad * plane.scale
        self.scale = plane.scale
