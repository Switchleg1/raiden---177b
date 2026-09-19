"""Rendering, widgets and visual effects for Raiden Shadow.

The renderer draws everything in logical playfield coordinates onto
a fixed 800x600 canvas which the app scales into a letterboxed
viewport (unchanged GUI from Breakout Classic). Widgets
(:class:`Button` / :class:`Menu`) and :class:`Effects` (particles,
screen shake, pickup flash) are reused verbatim in behaviour.
"""
from __future__ import annotations

from .button import Button
from .constants import (
    BOSS_FLASH_RADIUS,
    ENEMY_SHEET,
    EXPLOSION_TIER,
    ITEM_AURA_SHEET,
    ITEM_AURA_TINTS,
    ITEM_SHEET,
    ITEM_STYLE,
    ITEM_STYLE_DEFAULT,
    ITEM_TILE,
    MAX_EXPLOSIONS,
    MAX_PARTICLES,
    SHAKE_MAX,
    SHIELD_DEPLOY_TIME,
    SHIELD_FX_RADIUS,
    SHIELD_SHEET,
)
from .effects import Effects
from .explosion import Explosion
from .fonts import clear_fonts, get_font
from .menu import Menu
from .particle import Particle
from .renderer import Renderer

__all__ = [
    "BOSS_FLASH_RADIUS",
    "Button",
    "ENEMY_SHEET",
    "EXPLOSION_TIER",
    "Effects",
    "Explosion",
    "ITEM_AURA_SHEET",
    "ITEM_AURA_TINTS",
    "ITEM_SHEET",
    "ITEM_STYLE",
    "ITEM_STYLE_DEFAULT",
    "ITEM_TILE",
    "MAX_EXPLOSIONS",
    "MAX_PARTICLES",
    "Menu",
    "Particle",
    "Renderer",
    "SHAKE_MAX",
    "SHIELD_DEPLOY_TIME",
    "SHIELD_FX_RADIUS",
    "SHIELD_SHEET",
    "clear_fonts",
    "get_font",
]
