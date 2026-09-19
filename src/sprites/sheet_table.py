"""The sprite-sheet table: one record per shipped sheet.

This is the file to edit when art is added or an animation changes - no Python
logic lives here. Each record is::

    "<sheet>": {"cell": (w, h), "anims": {name: {"frames": [...], "fps": f,
                                                 "loop": bool}}, "raw": stem}

``cell`` is the tile size in *logical* pixels (the renderer scales the whole
canvas, so art is authored at the fixed 800x600 resolution). ``frames`` are
tile indices into the sheet, laid out left-to-right, top-to-bottom.

Sizing convention: the sheet grid is derived from the FIRST anim in a record,
so a multi-animation sheet must start with an anim that declares every tile
(``items`` and ``fx_shield`` use an explicit ``"all"`` anim for that). ``raw``
names the keyed art in assets/textures/sprites_src the sheet is animated from;
records without it are painted by the vector painters in
:mod:`sprites.painters`.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Manifest: sheet -> cell size (logical px) + animation sequences.
# Tile order left-to-right, top-to-bottom, like a classic arcade sheet.
# ---------------------------------------------------------------------------
SPRITES: dict[str, dict[str, Any]] = {
    # player craft. First anim declares every tile (grid sizing convention);
    # it doubles as the title-screen demo sweep: hover, bank right, bank left.
    # The generated hero still is animated by rawkit's player path, which
    # derives the four bank poses from it the same way the vector painter did.
    "p_ship": {"cell": (64, 72), "raw": "p_ship",
               "anims": {"sweep": {"frames": [0, 1, 2, 4, 3, 5, 6, 8, 7, 9],
                                   "fps": 6, "loop": True},
                         "idle": {"frames": [0, 1], "fps": 10, "loop": True},
                         "bank_soft": {"frames": [2, 4], "fps": 10,
                                       "loop": True},
                         "bank_hard": {"frames": [3, 5], "fps": 12,
                                       "loop": True},
                         "bank_soft_l": {"frames": [6, 8], "fps": 10,
                                         "loop": True},
                         "bank_hard_l": {"frames": [7, 9], "fps": 12,
                                         "loop": True}}},
    # player weapons -----------------------------------------------------
    "shot_vulcan":  {"cell": (12, 16),
                     "anims": {"run": {"frames": [0, 1, 2, 3],
                                       "fps": 24, "loop": True}}},
    "shot_plasma":  {"cell": (16, 24),
                     "anims": {"run": {"frames": [0, 1, 2, 3],
                                       "fps": 20, "loop": True}}},
    "shot_missile": {"cell": (14, 22),
                     "anims": {"run": {"frames": [0, 1, 2, 3],
                                       "fps": 18, "loop": True}}},
    "shot_enemy":   {"cell": (12, 12),
                     "anims": {"run": {"frames": [0, 1, 2, 3],
                                       "fps": 14, "loop": True}}},
    "fx_whip":      {"cell": (26, 26),
                     "anims": {"run": {"frames": [0, 1, 2, 3],
                                       "fps": 20, "loop": True}}},
    # falling power-ups: one sheet for the whole family (they are painted from
    # one pod recipe), `ITEM_FRAMES` consecutive tiles per kind in ItemKind
    # declaration order — see ui/constants.ITEM_TILE. The first anim declares
    # every tile so it fixes the grid, and doubles as a family sweep.
    "items":        {"cell": (28, 28),
                     "anims": {"all": {"frames": list(range(36)),
                                      "fps": 20, "loop": True},
                               "weapon": {"frames": [0, 1, 2, 3],
                                          "fps": 11, "loop": True},
                               "missile": {"frames": [4, 5, 6, 7],
                                           "fps": 11, "loop": True},
                               "bomb": {"frames": [8, 9, 10, 11],
                                        "fps": 11, "loop": True},
                               "shield": {"frames": [12, 13, 14, 15],
                                          "fps": 13, "loop": True},
                               "medal": {"frames": [16, 17, 18, 19],
                                         "fps": 13, "loop": True},
                               "extra_life": {"frames": [20, 21, 22, 23],
                                              "fps": 9, "loop": True},
                               "whip": {"frames": [24, 25, 26, 27],
                                        "fps": 15, "loop": True},
                               "jammer": {"frames": [28, 29, 30, 31],
                                          "fps": 14, "loop": True},
                               "mine": {"frames": [32, 33, 34, 35],
                                        "fps": 8, "loop": True}}},
    # the orbiting pickup marker: one translucent sprite ringed around every
    # item, recoloured per kind at runtime (Bank.tinted) so a pickup is
    # identifiable as a pickup before its icon is readable
    "fx_item_aura": {"cell": (36, 36),
                     "anims": {"orbit": {"frames": list(range(12)),
                                         "fps": 24, "loop": True}}},
    # the shield bubble: a plated dome that turns (``spin``, looped) plus a
    # one-pass ``deploy`` pop for the frame the pickup lands. Cells are big
    # because the bubble has to wrap the craft with room to spare - the whole
    # point is that it reads outside the hull, not on top of it. ``all`` fixes
    # the grid the way "items" does: the first anim is the sizing anim.
    "fx_shield":    {"cell": (128, 128), "radius": 46.0,
                     "anims": {"all": {"frames": list(range(21)),
                                       "fps": 15, "loop": True},
                               "spin": {"frames": list(range(12)),
                                        "fps": 15, "loop": True},
                               "deploy": {"frames": list(range(12, 21)),
                                          "fps": 20, "loop": False}}},
    # explosions (non-looping; one shot per death) ------------------------
    "explosion_small": {"cell": (48, 48),
                        "anims": {"boom": {"frames": list(range(8)),
                                           "fps": 22, "loop": False}}},
    "explosion_mid": {"cell": (80, 80),
                      "anims": {"boom": {"frames": list(range(12)),
                                         "fps": 20, "loop": False}}},
    "explosion_big": {"cell": (160, 160),
                      "anims": {"boom": {"frames": list(range(16)),
                                         "fps": 18, "loop": False}}},
    # enemies ------------------------------------------------------------
    # `raw` names the keyed art in assets/textures/sprites_src that
    # sprites.rawkit animates (plume / glow / turbine motion).  With no raw
    # art, sprites.painters falls back to its vector painter, so a stripped
    # checkout still bakes playable sheets.  Cell is the on-screen logical
    # size; ENEMY_SPECS keeps the collision radius under half the cell so
    # wings and gun sponsons never eat bullets.
    "e_grunt":   {"cell": (48, 48), "raw": "e_grunt",
                  "anims": {"idle": {"frames": [0, 1, 2, 3],
                                     "fps": 14, "loop": True}}},
    "e_weaver":  {"cell": (52, 52), "raw": "e_weaver",
                  "anims": {"idle": {"frames": [0, 1, 2, 3],
                                     "fps": 12, "loop": True}}},
    "e_darter":  {"cell": (44, 56), "raw": "e_darter",
                  "anims": {"idle": {"frames": [0, 1, 2, 3],
                                     "fps": 18, "loop": True}}},
    "e_gunner":  {"cell": (60, 60), "raw": "e_gunner",
                  "anims": {"idle": {"frames": [0, 1, 2, 3, 4, 5],
                                     "fps": 12, "loop": True}}},
    "e_sentry":  {"cell": (56, 56), "raw": "e_sentry",
                  "anims": {"idle": {"frames": [0, 1, 2, 3, 4, 5, 6, 7],
                                     "fps": 10, "loop": True}}},
    "e_heavy":   {"cell": (84, 84), "raw": "e_heavy",
                  "anims": {"idle": {"frames": [0, 1, 2, 3, 4, 5],
                                     "fps": 10, "loop": True}}},
    # Bomber: big, slow and loaded, so the cell is wide and the cycle is long.
    "e_bomber":  {"cell": (96, 84), "raw": "e_bomber",
                  "anims": {"idle": {"frames": [0, 1, 2, 3, 4, 5],
                                     "fps": 9, "loop": True}}},
    "e_splitter": {"cell": (64, 64), "raw": "e_splitter",
                   "anims": {"idle": {"frames": [0, 1, 2, 3, 4, 5],
                                      "fps": 14, "loop": True}}},
    "e_rammer":  {"cell": (56, 72), "raw": "e_rammer",
                  "anims": {"idle": {"frames": [0, 1, 2, 3],
                                     "fps": 20, "loop": True}}},
    # Shards are the splitter's carapace read at a third of the size; same keyed
    # art, smaller cell, so the fragment is unmistakably a piece of its parent.
    "e_shard":   {"cell": (32, 32), "raw": "e_splitter",
                  "anims": {"idle": {"frames": [0, 1, 2, 3],
                                     "fps": 16, "loop": True}}},
    "e_boss1": {"cell": (208, 144), "raw": "e_boss1",
                  "anims": {"idle": {"frames": [0, 1, 2, 3, 4, 5],
                                     "fps": 8, "loop": True}}},
    "e_boss2": {"cell": (208, 144), "raw": "e_boss2",
                  "anims": {"idle": {"frames": [0, 1, 2, 3, 4, 5],
                                     "fps": 8, "loop": True}}},
    "e_boss3": {"cell": (208, 144), "raw": "e_boss3",
                  "anims": {"idle": {"frames": [0, 1, 2, 3, 4, 5],
                                     "fps": 8, "loop": True}}},
    "e_boss4": {"cell": (208, 144), "raw": "e_boss4",
                  "anims": {"idle": {"frames": [0, 1, 2, 3, 4, 5],
                                     "fps": 8, "loop": True}}},
    "e_boss5": {"cell": (208, 144), "raw": "e_boss5",
                  "anims": {"idle": {"frames": [0, 1, 2, 3, 4, 5],
                                     "fps": 8, "loop": True}}},
    "e_boss6": {"cell": (208, 144), "raw": "e_boss6",
                  "anims": {"idle": {"frames": [0, 1, 2, 3, 4, 5],
                                     "fps": 8, "loop": True}}},
    "e_boss7": {"cell": (208, 144), "raw": "e_boss7",
                  "anims": {"idle": {"frames": [0, 1, 2, 3, 4, 5],
                                     "fps": 8, "loop": True}}},
    "e_boss8": {"cell": (208, 144), "raw": "e_boss8",
                  "anims": {"idle": {"frames": [0, 1, 2, 3, 4, 5],
                                     "fps": 8, "loop": True}}},
    "e_boss9": {"cell": (208, 144), "raw": "e_boss9",
                  "anims": {"idle": {"frames": [0, 1, 2, 3, 4, 5],
                                     "fps": 8, "loop": True}}},
}

__all__ = ["SPRITES"]
