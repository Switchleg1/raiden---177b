"""Game entities for Raiden Shadow (pygame-free).

Plain mutable classes with ``__slots__``; each knows its own
movement / firing behaviour but performs no drawing. Keeping this
layer display-free means the whole simulation runs headless.
"""
from __future__ import annotations

from .bullet import Bullet
from .enemy import Enemy
from .player import Player
from .whip import Whip

__all__ = [
    "Bullet",
    "Enemy",
    "Player",
    "Whip",
]
