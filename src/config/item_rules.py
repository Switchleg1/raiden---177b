"""Falling item sizes, speeds, groups and drop weights."""
from __future__ import annotations

from .item_kind import ItemKind

# ---------------------------------------------------------------------------
# Falling power-ups & hazards (mirrors Breakout's item system). Enable/disable
# the whole system via Settings.powerups. Beneficial items are collected by
# touching them with the craft; hazards apply their penalty on contact.
# ---------------------------------------------------------------------------
ITEM_SIZE = 20.0             # square item edge (logical units)


ITEM_FALL_SPEED = 120.0      # downward speed of falling items


ITEM_DROP_CHANCE = 0.06      # default chance a killed enemy drops an item


MAX_ITEMS = 24               # hard bound on simultaneous falling items


SHIELD_TIME = 7.0            # seconds of invulnerability (SHIELD)


# The bubble does not simply stop. For the last SHIELD_WARN_TIME seconds it
# strobes - SHIELD_FLASH_HZ cycles per second, falling to SHIELD_FLASH_DIM on
# the dark half instead of vanishing, because a bubble that blinks out entirely
# reads as "shield gone" one flash early - and over the final SHIELD_FADE_TIME
# it sinks to nothing, so the effect ends as an event rather than a cliff.
# Presentation only: the model's countdown stays a plain timer.
SHIELD_WARN_TIME = 5.0
SHIELD_FADE_TIME = 1.0
SHIELD_FLASH_HZ = 3.0
SHIELD_FLASH_DIM = 0.28


JAMMER_DROP_PENALTY = 1      # weapon levels lost to a JAMMER


BENEFICIAL: frozenset[ItemKind] = frozenset({
    ItemKind.WEAPON, ItemKind.MISSILE, ItemKind.BOMB, ItemKind.SHIELD,
    ItemKind.MEDAL, ItemKind.EXTRA_LIFE, ItemKind.WHIP, ItemKind.MOON,
})


HAZARDS: frozenset[ItemKind] = frozenset({ItemKind.JAMMER, ItemKind.MINE})


MEDAL_SCORE = 500


# ---------------------------------------------------------------------------
# Item palette — the single source of truth for what a power-up looks like.
# (hull, accent): the hull is the pod's own metal, the accent is its energy
# (symbol, rim light, and the tint of the shared orbiting aura marker). The
# vector fallback in ui/constants derives its flat fill/edge from these, and
# the baked sheet paints from them too, so the two can never drift apart.
# ---------------------------------------------------------------------------
ITEM_COLORS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "weapon":      ((42, 84, 58), (150, 240, 170)),
    "missile":     ((38, 66, 104), (150, 210, 255)),
    "bomb":        ((86, 68, 34), (250, 210, 110)),
    "shield":      ((40, 62, 104), (150, 190, 255)),
    "medal":       ((96, 78, 36), (245, 220, 140)),
    "extra_life":  ((74, 54, 104), (220, 190, 255)),
    "whip":        ((78, 40, 92), (240, 150, 255)),
    "jammer":      ((92, 34, 48), (255, 120, 140)),
    "mine":        ((88, 46, 30), (255, 150, 90)),
    # Polished steel: the palest accent on the sheet over the darkest hull, so
    # the rim contrast does the work that saturation does for the other pods.
    # Missile and shield already own mid blue, and the blade has to read as
    # *metal thrown* rather than as a third blue power-up.
    "moon":        ((34, 48, 70), (214, 240, 255)),
}


ITEM_STYLE_DEFAULT_COLOR: tuple[tuple[int, int, int], tuple[int, int, int]] = (
    (52, 56, 76), (200, 210, 235))


# (kind, relative weight). Hazards are deliberately less common than benefits.
ITEM_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("weapon", 26),
    ("missile", 20),
    ("bomb", 12),
    ("shield", 12),
    ("medal", 16),
    ("extra_life", 2),
    ("whip", 9),
    ("moon", 14),
    ("jammer", 7),
    ("mine", 5),
)
