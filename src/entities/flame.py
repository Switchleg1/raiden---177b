"""Flamethrower: puffs of fire that are born at the nozzle and then their own thing.

The lash (:mod:`entities.whip`) is one object - every bead is answerable to the
bead ahead of it. Fire is not like that. A puff of flame has no relationship to
the puff that follows it or to the craft that threw it: it keeps the position it
was born at plus a constant velocity, and nothing the player does afterwards
moves it.
"""
from __future__ import annotations

import config as C


class Flame:
    """One puff: ``pos = birth + velocity * age``, which is all the motion it has.

    It thins as it travels. ``fade`` runs 1 -> 0 over exactly ``life`` seconds
    and drives the picture, the radius and the damage together, so a puff that
    looks spent also *is* spent: by the moment it goes out it deals half what it
    did at the nozzle.
    """

    __slots__ = ("x0", "y0", "vx", "vy", "age", "life", "r0", "grow")

    def __init__(self, x: float, y: float, vx: float, vy: float,
                 life: float | None = None, r0: float | None = None,
                 grow: float | None = None) -> None:
        self.x0, self.y0 = x, y
        self.vx, self.vy = vx, vy
        self.age = 0.0
        self.life = C.FLAME_LIFE if life is None else life
        self.r0 = C.FLAME_R if r0 is None else r0
        self.grow = C.FLAME_GROW if grow is None else grow

    def update(self, dt: float) -> None:
        self.age += dt

    @property
    def alive(self) -> bool:
        return self.age < self.life

    @property
    def t(self) -> float:
        """Progress through the puff's life, 0 at birth, 1 as it goes out."""
        return min(1.0, self.age / self.life) if self.life > 0.0 else 1.0

    @property
    def fade(self) -> float:
        """How much of the puff is left: 1 at the nozzle, 0 when it is out."""
        return 1.0 - self.t

    @property
    def x(self) -> float:
        return self.x0 + self.vx * self.age

    @property
    def y(self) -> float:
        return self.y0 + self.vy * self.age

    @property
    def r(self) -> float:
        """A flame spreads as it cools, so the weak puff covers more ground."""
        return self.r0 + self.grow * self.t

    @property
    def dmg(self) -> int:
        """Damage on the same clock as the fade: full at birth, half at the end.

        The radius grows while this falls, which is the trade: late puffs still
        set things alight over a wider patch, they just do it less hard.
        """
        return max(1, int(round(C.FLAME_DMG * (0.5 + 0.5 * self.fade))))
