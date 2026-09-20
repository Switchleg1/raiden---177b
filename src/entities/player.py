"""The player craft: position, power levels, effect timers."""
from __future__ import annotations

import config as C
import physics as P


class Player:
    """The player's craft: 2D position, power levels, and effect timers."""

    __slots__ = ("x", "y", "vx", "vy", "r", "half", "alive",
                 "weapon_level", "missile_level", "moon_level", "bomb_stock",
                 "fire_timer", "missile_timer", "moon_timer", "invuln",
                 "shield")

    # The power tracks, as one value. Clearing a sector carries them, dying
    # wipes them. They used to be copied by hand, two names at a time, and when
    # the blade track arrived it was simply not in the copy: a sector clear ate
    # it. Named once, here, and read/written by name, so a fourth track is
    # carried the moment it exists (tests/test_entities.py walks __slots__ and
    # fails if a level ever sits outside the loadout).
    LOADOUT_SLOTS = ("weapon_level", "missile_level", "moon_level")

    def loadout(self) -> tuple[int, ...]:
        """The power tracks, in LOADOUT_SLOTS order."""
        return tuple(getattr(self, name) for name in self.LOADOUT_SLOTS)

    def apply_loadout(self, loadout: tuple[int, ...]) -> None:
        """Restore a loadout taken from loadout()."""
        for name, value in zip(self.LOADOUT_SLOTS, loadout, strict=True):
            setattr(self, name, value)

    def __init__(self) -> None:
        self.half = C.PLAYER_HALF
        self.r = C.PLAYER_HITBOX_R
        self.reset_position()
        self.weapon_level = C.WEAPON_BASE_LEVEL
        self.missile_level = C.MISSILE_BASE_LEVEL
        self.moon_level = C.MOON_BASE_LEVEL
        self.bomb_stock = C.BOMB_START
        self.alive = True
        self.invuln = 0.0
        self.shield = 0.0
        self.fire_timer = 0.0
        self.missile_timer = 0.0
        self.moon_timer = 0.0

    def reset_position(self) -> None:
        self.x = (C.FIELD_LEFT + C.FIELD_RIGHT) / 2.0
        self.y = C.PLAYER_START_Y
        self.vx = 0.0
        self.vy = 0.0

    def full_restore(self) -> None:
        """Reset for a fresh craft (after death the power levels drop)."""
        self.reset_position()
        self.weapon_level = C.WEAPON_BASE_LEVEL
        self.missile_level = C.MISSILE_BASE_LEVEL
        self.moon_level = C.MOON_BASE_LEVEL
        self.alive = True
        self.invuln = C.PLAYER_INVULN
        self.shield = 0.0
        self.fire_timer = 0.0
        self.missile_timer = 0.0
        self.moon_timer = 0.0

    @property
    def protected(self) -> bool:
        return self.invuln > 0.0 or self.shield > 0.0

    def clamp_to_field(self) -> None:
        m = self.half
        self.x = P.clamp(self.x, C.FIELD_LEFT + m, C.FIELD_RIGHT - m)
        self.y = P.clamp(self.y, C.FIELD_TOP + m, C.FIELD_BOTTOM - m)

    def tick_timers(self, dt: float) -> None:
        if self.invuln > 0.0:
            self.invuln = max(0.0, self.invuln - dt)
        if self.shield > 0.0:
            self.shield = max(0.0, self.shield - dt)
        if self.fire_timer > 0.0:
            self.fire_timer = max(0.0, self.fire_timer - dt)
        if self.missile_timer > 0.0:
            self.missile_timer = max(0.0, self.missile_timer - dt)
        if self.moon_timer > 0.0:
            self.moon_timer = max(0.0, self.moon_timer - dt)
