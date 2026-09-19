"""Falling power-up / hazard kinds."""
from __future__ import annotations

from enum import StrEnum


class ItemKind(StrEnum):
    WEAPON = "weapon"        # +1 weapon power level (capped)
    MISSILE = "missile"      # +1 missile level (capped)
    BOMB = "bomb"            # +1 smart bomb (capped)
    SHIELD = "shield"        # timed invulnerability
    MEDAL = "medal"          # instant score bonus
    EXTRA_LIFE = "extra_life"    # +1 life (rare)
    WHIP = "whip"            # timed energy-whip primary (replaces vulcan)
    JAMMER = "jammer"        # hazard: downgrade weapon level
    MINE = "mine"            # hazard: costs a life on contact
