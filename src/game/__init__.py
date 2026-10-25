"""The game model: the simulation a run is, with no pygame and no state machine.

`model.Game` advances one fixed step at a time and reports what happened as event
dicts; `items` is the power-up and hazard system it drops from killed enemies.
"""
from __future__ import annotations

from .model import (
    SIG_BOMB,
    SIG_BOSS,
    SIG_GAME_OVER,
    SIG_HAZARD,
    SIG_LEVEL_CLEAR,
    SIG_LIFE_LOST,
    SIG_POWERUP,
    SIG_VICTORY,
    Game,
)

__all__ = ["Game", "SIG_BOMB", "SIG_BOSS", "SIG_GAME_OVER", "SIG_HAZARD",
           "SIG_LEVEL_CLEAR", "SIG_LIFE_LOST", "SIG_POWERUP", "SIG_VICTORY"]
