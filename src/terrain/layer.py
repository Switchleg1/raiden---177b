"""One scrolling detail layer (transparent surface, logical size)."""
from __future__ import annotations

from typing import Any

import config as C

from .common import TILE_H


class Layer:
    """One scrolling tile of detail art (transparent surface, logical size)."""
    __slots__ = ("surf", "speed", "off")

    def __init__(self, surf: Any, speed: float) -> None:
        self.surf = surf
        self.speed = speed
        self.off = 0.0

    def update(self, dt: float, scale: float) -> None:
        self.off = (self.off + self.speed * dt * scale) % TILE_H

    def draw(self, target: Any) -> None:
        y0 = C.HUD_H + self.off
        target.blit(self.surf, (0, y0 - TILE_H))
        target.blit(self.surf, (0, y0))
