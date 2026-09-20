"""Effect budgets, explosion tiers, sheet/style lookups."""
from __future__ import annotations

from config import ITEM_COLORS, ITEM_STYLE_DEFAULT_COLOR, ItemKind
from sprites.manifest import SPRITES

# ---------------------------------------------------------------------------
# Effects (bounded)
# ---------------------------------------------------------------------------
MAX_PARTICLES = 160




MAX_EXPLOSIONS = 14


SHAKE_MAX = 9.0


# Death-burst tier per enemy kind (explosion sheet families).
EXPLOSION_TIER: dict[str, str] = {
    "grunt": "explosion_small", "weaver": "explosion_small",
    "darter": "explosion_small", "gunner": "explosion_mid",
    "sentry": "explosion_mid", "heavy": "explosion_mid",
    "bomber": "explosion_mid", "splitter": "explosion_mid",
    "rammer": "explosion_small", "shard": "explosion_small",
    "boss": "explosion_big",
}


# Player-facing sheet lookup by kind for the renderer.
ENEMY_SHEET: dict[str, str] = {
    "grunt": "e_grunt", "weaver": "e_weaver", "darter": "e_darter",
    "gunner": "e_gunner", "sentry": "e_sentry", "heavy": "e_heavy",
    "bomber": "e_bomber", "splitter": "e_splitter", "rammer": "e_rammer",
    "shard": "e_shard",
    # A BOSS with no explicit sheet (hand-built enemy, attract mode) uses the
    # first sector boss; levels route their own via LevelSpec.boss.
    "boss": "e_boss1",
}


# ---- falling power-ups ----------------------------------------------------
# One sheet holds every kind (they are a family, painted from one pod recipe)
# and one shared aura sheet holds the orbiting marker that rings all of them.
# A kind owns ITEM_FRAMES consecutive tiles, in ItemKind declaration order —
# the painter iterates the same enum, so a new kind cannot ship without art
# (test_item_sheet_covers_every_kind fails instead).
ITEM_SHEET = "items"
ITEM_AURA_SHEET = "fx_item_aura"
ITEM_FRAMES = len(SPRITES[ITEM_SHEET]["anims"]["weapon"]["frames"])
ITEM_TILE: dict[str, int] = {
    kind.value: i * ITEM_FRAMES for i, kind in enumerate(ItemKind)}

# The aura is one sprite recoloured per kind, so the marker is identical for
# every pickup while still carrying the kind's colour. Hazards are told apart
# by shape (octagonal plate + their own glyph), never by colour alone.
ITEM_AURA_TINTS: dict[str, tuple[int, int, int]] = {
    kind: accent for kind, (_hull, accent) in ITEM_COLORS.items()}

# Vector-fallback glyph per kind: shape carries meaning so a hazard is never
# identified by colour alone.
ITEM_GLYPH: dict[str, str] = {
    "weapon": "up", "missile": "rocket", "bomb": "bomb", "shield": "shield",
    "medal": "medal", "extra_life": "life", "whip": "whip",
    "jammer": "jam", "mine": "mine", "moon": "moon",
}


# ---- shield ----------------------------------------------------------------
# The bubble is a baked sheet, not a drawn circle: it has to be bigger than the
# craft it protects, and the radius that makes that true lives in the sheet
# manifest so the art and the renderer agree on one number.
SHIELD_SHEET = "fx_shield"
SHIELD_FX_RADIUS = float(SPRITES[SHIELD_SHEET]["radius"])
_shield_deploy = SPRITES[SHIELD_SHEET]["anims"]["deploy"]
# How long the deploy pop plays. The renderer derives "is it deploying?" from
# the shield's own countdown, so the FX needs no extra game state and replays
# itself whenever a fresh shield stacks on top of a running one.
SHIELD_DEPLOY_TIME = len(_shield_deploy["frames"]) / float(
    _shield_deploy["fps"])

# Hulls wider than this flash by lighting up, not by turning white. A grunt
# blinks and you know you hit it; a boss drinks a stream of fire, so its flash
# window never closes and a white silhouette would hide the craft, the phase and
# the bullets leaking out from behind it.
BOSS_FLASH_RADIUS = 40.0


def _shade(c: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    return (int(round(c[0] * k)), int(round(c[1] * k)), int(round(c[2] * k)))


# Per-item visuals for the no-art fallback: (fill, edge, glyph), derived from
# the one palette the baked sheet paints with so the two cannot drift.
ITEM_STYLE: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], str]] = {
    kind: (_shade(accent, 0.22), accent, ITEM_GLYPH[kind])
    for kind, (_hull, accent) in ITEM_COLORS.items()
}


ITEM_STYLE_DEFAULT: tuple[tuple[int, int, int], tuple[int, int, int], str] = (
    _shade(ITEM_STYLE_DEFAULT_COLOR[1], 0.22), ITEM_STYLE_DEFAULT_COLOR[1],
    "medal")
