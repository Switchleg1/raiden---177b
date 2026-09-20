"""A projectile; ``friendly`` distinguishes player fire from enemy fire.

An enemy bullet may also be a *cluster shell*: ``frag`` counts the fragments
waiting inside and ``split_in`` is the fuse, which the game bursts (bullets
have no view of the bullet list).
"""
from __future__ import annotations

from typing import Any

import config as C
import physics as P


class Bullet:
    """A projectile. ``friendly`` distinguishes player fire from enemy fire.

    A ``pierce`` bullet (the half-moon blade) is not spent by a hit: it keeps
    flying and cuts everything else on its line. To avoid carving the same hull
    once per frame it remembers what it has already passed through.
    """

    __slots__ = ("x", "y", "vx", "vy", "r", "dmg", "friendly", "missile",
                 "alive", "split_in", "frag", "pierce", "cut")

    def __init__(self, x: float, y: float, vx: float, vy: float,
                 r: float, dmg: int, friendly: bool, missile: bool = False,
                 split_in: float = 0.0, frag: int = 0, pierce: bool = False):
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
        # Piercing shots remember the enemies they have already been through, so
        # a blade crossing a boss does not deal its damage once per frame. Held
        # by identity, never by id(): the deaths a blade causes free the very id
        # it would later mistake for a hull it has already cut, and a new grunt
        # wearing a dead grunt's number would be cut nothing. The list stays
        # empty (not even allocated) for every shot that stops on impact.
        self.pierce = pierce
        self.cut: list[Any] | None = None

    def has_cut(self, enemy: Any) -> bool:
        cut = self.cut
        return cut is not None and any(hit is enemy for hit in cut)

    def note_cut(self, enemy: Any) -> None:
        if self.cut is None:
            self.cut = [enemy]
        else:
            self.cut.append(enemy)

    def update(self, dt: float) -> None:
        P.advance(self, dt)
        if self.split_in > 0.0:
            self.split_in -= dt
        # Cull once clearly outside the play area (generous vertical margin so
        # things that spawn just above the top are not erased instantly).
        if (self.y > C.FIELD_BOTTOM + 40 or self.y < C.FIELD_TOP - 80
                or self.x < C.FIELD_LEFT - 40 or self.x > C.FIELD_RIGHT + 40):
            self.alive = False
