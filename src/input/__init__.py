"""Input handling: letterbox viewport math, smoothed ship axes, and
the keyboard/mouse controller (same layout as Breakout Classic).
"""
from __future__ import annotations

from .actions import (
    ACT_BACK,
    ACT_BOMB,
    ACT_CONFIRM,
    ACT_FULLSCREEN,
    ACT_NAV_DOWN,
    ACT_NAV_LEFT,
    ACT_NAV_RIGHT,
    ACT_NAV_UP,
    ACT_NONE,
    ACT_PAUSE,
    ACT_QUIT,
    DEV_KEYBOARD,
    DEV_MOUSE,
)
from .controller import InputController
from .ship_axis import ShipAxis
from .viewport import Viewport, map_mouse_to_logical

__all__ = [
    "ACT_BACK",
    "ACT_BOMB",
    "ACT_CONFIRM",
    "ACT_FULLSCREEN",
    "ACT_NAV_DOWN",
    "ACT_NAV_LEFT",
    "ACT_NAV_RIGHT",
    "ACT_NAV_UP",
    "ACT_NONE",
    "ACT_PAUSE",
    "ACT_QUIT",
    "DEV_KEYBOARD",
    "DEV_MOUSE",
    "InputController",
    "ShipAxis",
    "Viewport",
    "map_mouse_to_logical",
]
