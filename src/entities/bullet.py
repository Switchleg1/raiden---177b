"""A projectile; ``friendly`` distinguishes player fire from enemy fire.

An enemy bullet may also be a *cluster shell*: ``frag`` counts the fragments
waiting inside and ``split_in`` is the fuse, which the game bursts (bullets
have no view of the bullet list).
"""
from __future__ import annotations

import config as C
import physics as P


class Bullet:
    """A projectile. ``friendly`` distinguishes player fire from enemy fire."""

    __slots__ = ("x", "y", "vx", "vy", "r", "dmg", "friendly", "missile",
                 "alive", "split_in", "frag")

    def __init__(self, x: float, y: float, vx: float, vy: float,
                 r: float, dmg: int, friendly: bool, missile: bool = False,
                 split_in: float = 0.0, frag: int = 0):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.r = r
        self.dmg = dmg
        self.friendly = friendly
        self.missile = missile
        self.alive = True
        # Cluster shell state: `frag` bullets burst out once `split_in` hits
        # zero.  Both stay at their defaults for ordinary shots.
        self.split_in = split_in
        self.frag = frag

    def update(self, dt: float) -> None:
        P.advance(self, dt)
        if self.split_in > 0.0:
            self.split_in -= dt
        # Cull once clearly outside the play area (generous vertical margin so
        # things that spawn just above the top are not erased instantly).
        if (self.y > C.FIELD_BOTTOM + 40 or self.y < C.FIELD_TOP - 80
                or self.x < C.FIELD_LEFT - 40 or self.x > C.FIELD_RIGHT + 40):
            self.alive = False
