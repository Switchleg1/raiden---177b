"""The sound-effect vocabulary: every effect name and how often it may repeat.

Pure data. The synthesiser that renders these buffers lives in :mod:`audio`;
this module is what you edit when you add an effect or retune how noisy a
weapon is allowed to get. ``MIN_GAP`` is the anti-spam gate: two triggers of the
same effect inside that window collapse into one, so a four-way spread reads as
a single shot instead of four stacked copies.
"""
from __future__ import annotations

# Effect identifiers (the keys of the sample bank).
SHOOT = "shoot"
MISSILE = "missile"
EXPLOSION = "explosion"
BOSS_EXPLOSION = "boss_explosion"
BOSS_WARN = "boss_warn"
BOMB = "bomb"
MEDAL = "medal"
LIFE_LOST = "life_lost"
LEVEL_COMPLETE = "level_complete"
MENU_NAV = "menu_nav"
MENU_ACTIVATE = "menu_activate"
GAME_OVER = "game_over"
VICTORY = "victory"
POWERUP = "powerup"
HAZARD = "hazard"
WHIP_HIT = "whip_hit"

EFFECT_NAMES = (SHOOT, MISSILE, EXPLOSION, BOSS_EXPLOSION, BOSS_WARN, BOMB,
                MEDAL, LIFE_LOST, LEVEL_COMPLETE, MENU_NAV, MENU_ACTIVATE,
                GAME_OVER, VICTORY, POWERUP, HAZARD, WHIP_HIT)

# Minimum spacing between repeats of the same effect (seconds). Fast weapons
# need tight but non-zero gaps so a full spread reads as one shot.
MIN_GAP = {
    SHOOT: 0.045, MISSILE: 0.12, EXPLOSION: 0.03, BOSS_EXPLOSION: 0.2,
    BOSS_WARN: 0.5, BOMB: 0.3, MEDAL: 0.05,
    MENU_NAV: 0.05, MENU_ACTIVATE: 0.05,
    LIFE_LOST: 0.2, LEVEL_COMPLETE: 0.2, GAME_OVER: 0.3, VICTORY: 0.3,
    POWERUP: 0.05, HAZARD: 0.2, WHIP_HIT: 0.03,
}

__all__ = ["EFFECT_NAMES", "MIN_GAP",
           "BOSS_EXPLOSION", "BOSS_WARN", "BOMB", "EXPLOSION", "GAME_OVER",
           "HAZARD", "LEVEL_COMPLETE", "LIFE_LOST", "MEDAL", "MENU_ACTIVATE",
           "MENU_NAV", "MISSILE", "POWERUP", "SHOOT", "VICTORY", "WHIP_HIT"]
