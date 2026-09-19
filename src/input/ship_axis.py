"""Smoothed ship movement axes (keyboard velocity, mouse follow)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ShipAxis:
    """Frame-rate-independent 2D keyboard axis (unit testable).

    Produces a normalised ``(dx, dy)`` direction in ``[-1, 1]`` (not scaled by
    dt); the game multiplies by speed. Diagonals are not magnitudes-normalised,
    matching typical arcade twin-stick feel; callers may normalise if desired.
    """
    up: bool = False
    down: bool = False
    left: bool = False
    right: bool = False

    def set(self, direction: str, held: bool) -> None:
        setattr(self, direction, held)

    def direction(self) -> tuple[float, float]:
        dx = (1 if self.right else 0) - (1 if self.left else 0)
        dy = (1 if self.down else 0) - (1 if self.up else 0)
        return float(dx), float(dy)

    def clear(self) -> None:
        self.up = self.down = self.left = self.right = False
