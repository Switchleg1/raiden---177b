"""How the app answers each game signal: its effects, and anything more it does.

The effects are data (`SIGNAL_FX`). Signals that change what the app is doing -
a transition, the boss music, warming a sprite sheet - name the App method that
does it (`SIGNAL_ACTIONS`). A signal may have both; the effects play first.
"""
from __future__ import annotations

from audio import effect_table as sfx
from game import (
    SIG_BOMB,
    SIG_BOSS,
    SIG_GAME_OVER,
    SIG_HAZARD,
    SIG_LEVEL_CLEAR,
    SIG_LIFE_LOST,
    SIG_POWERUP,
)

from .signal_fx import SignalFx

SHIP = (120, 210, 255)

SIGNAL_FX: dict[str, SignalFx] = {
    "shoot": SignalFx(sound=sfx.SHOOT),
    "missile": SignalFx(sound=sfx.MISSILE),
    "moon": SignalFx(sound=sfx.MOON),
    "medal": SignalFx(sound=sfx.MEDAL),
    "whip_hit": SignalFx(sound=sfx.WHIP_HIT, burst=((235, 130, 255), 3)),
    "flame_hit": SignalFx(sound=sfx.FLAME_HIT, burst=((255, 150, 62), 3)),
    "enemy_killed": SignalFx(sound=sfx.EXPLOSION),
    # SIG_BOSS is "boss_spawn". It used to have a branch of its own AND a second
    # `elif et == "boss_spawn"` further down the chain - which could never run,
    # so the boss warning siren and its shake never played. One entry, one answer.
    SIG_BOSS: SignalFx(sound=sfx.BOSS_WARN, shake=4.0),
    "boss_down": SignalFx(sound=sfx.BOSS_EXPLOSION, shake=8.0, flash=0.5,
                          explosion="explosion_big",
                          burst=((255, 220, 140), 40)),
    SIG_BOMB: SignalFx(sound=sfx.BOMB, flash=0.85, shake=6.0),
    SIG_LIFE_LOST: SignalFx(sound=sfx.LIFE_LOST, shake=7.0,
                            explosion="explosion_mid", burst=(SHIP, 30),
                            at="player"),
    SIG_LEVEL_CLEAR: SignalFx(sound=sfx.LEVEL_COMPLETE),
    SIG_GAME_OVER: SignalFx(sound=sfx.GAME_OVER, explosion="explosion_big",
                            burst=(SHIP, 30), at="player"),
    SIG_POWERUP: SignalFx(sound=sfx.POWERUP),
    SIG_HAZARD: SignalFx(sound=sfx.HAZARD, shake=5.0),
}

#: signal -> the App method (taking the event) that acts on it
SIGNAL_ACTIONS: dict[str, str] = {
    SIG_BOSS: "_on_boss_signal",
    "enemy_killed": "_on_enemy_killed",
    SIG_LIFE_LOST: "_on_life_lost",
    SIG_LEVEL_CLEAR: "_on_level_clear",
    SIG_GAME_OVER: "_on_game_over",
    SIG_POWERUP: "_on_powerup",
}

#: signals that end the flying: the caller stops processing the frame's events
ENDS_PLAY = frozenset({SIG_LIFE_LOST, SIG_LEVEL_CLEAR, SIG_GAME_OVER})

__all__ = ["ENDS_PLAY", "SIGNAL_ACTIONS", "SIGNAL_FX"]
