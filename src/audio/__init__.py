"""Sound: the mixer, the generated effects, and the music player.

`AudioManager` owns the mixer; the effect names and their rate limits are a table
(`effect_table`). The music itself is composed and rendered by `music`.
"""
from __future__ import annotations

from .manager import (
    BOSS_KEY,
    LEVEL_KEY,
    MENU_KEY,
    MIXER_RATE,
    MUSIC_CHANNEL,
    AudioManager,
    build_samples,
    wav_bytes,
)

__all__ = ["AudioManager", "BOSS_KEY", "LEVEL_KEY", "MENU_KEY", "MIXER_RATE",
           "MUSIC_CHANNEL", "build_samples", "wav_bytes"]
