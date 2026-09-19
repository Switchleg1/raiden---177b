"""The :class:`State` enum: every screen the machine can be on.

The legal-movement table for these states lives in
:mod:`state.transitions`; this module only names the states.
"""
from __future__ import annotations

from enum import StrEnum


class State(StrEnum):
    BOOT = "boot"
    TITLE = "title"
    READY = "ready"
    PLAYING = "playing"
    PAUSED = "paused"
    LIFE_LOST = "life_lost"
    LEVEL_COMPLETE = "level_complete"
    GAME_OVER = "game_over"
    VICTORY = "victory"
    SETTINGS = "settings"
    HOW_TO_PLAY = "how_to_play"
    NAME_ENTRY = "name_entry"
    HIGH_SCORES = "high_scores"
    SHUTDOWN = "shutdown"
