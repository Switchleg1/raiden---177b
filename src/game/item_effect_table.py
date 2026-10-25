"""What a beneficial pickup raises: (owner, attribute, step, cap).

`owner` is "player" (the craft's own stats) or "game" (the run's timed powers).
A pickup adds `step` and stops at `cap`. The moon blade is its own track: it
levels up without touching vulcan power or missile level, so a run can specialise
in the fan. Timed powers stack a block per pod instead of resetting the clock.
"""
from __future__ import annotations

import config as C

ITEM_STACKS: dict[C.ItemKind, tuple[str, str, float, float]] = {
    C.ItemKind.WEAPON: ("player", "weapon_level", 1, C.WEAPON_MAX_LEVEL),
    C.ItemKind.MISSILE: ("player", "missile_level", 1, C.MISSILE_MAX_LEVEL),
    C.ItemKind.MOON: ("player", "moon_level", 1, C.MOON_MAX_LEVEL),
    C.ItemKind.BOMB: ("player", "bomb_stock", 1, C.BOMB_MAX),
    C.ItemKind.WHIP: ("game", "whip_timer", C.WHIP_TIME, C.WHIP_MAX),
    C.ItemKind.FLAME: ("game", "flame_timer", C.FLAME_TIME, C.FLAME_MAX),
}

__all__ = ["ITEM_STACKS"]
