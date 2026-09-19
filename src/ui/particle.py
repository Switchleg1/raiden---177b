"""One particle (sparks, smoke, debris)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    color: tuple[int, int, int]
