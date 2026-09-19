"""Application package: :class:`App` owns the pygame window, the game
model, the state machine, input, audio, persistence and rendering
(same fixed-timestep, letterboxed architecture as Breakout
Classic).
"""
from __future__ import annotations

from .app import App, main
from .settings_rows import SETTINGS_ROWS, SettingRow

__all__ = [
    "App",
    "SETTINGS_ROWS",
    "SettingRow",
    "main",
]
