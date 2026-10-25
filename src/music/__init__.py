"""Music: cues composed from tables and rendered to PCM.

`engine` renders a cue (`render_track`) and owns the cue tables' lookups;
`instruments` and `drum_kit` are the voices it plays with; `content_table` is the
music itself - every cue as data.
"""
from __future__ import annotations

from .engine import (
    BOSS_THEMES,
    LEVEL_CUES,
    MENU_THEME,
    MENU_THEMES,
    THEMES,
    cue_names,
    level_cues,
    levels_for_cue,
    pick_level_cue,
    render_track,
    theme_by_name,
)

__all__ = ["BOSS_THEMES", "LEVEL_CUES", "MENU_THEME", "MENU_THEMES", "THEMES",
           "cue_names", "level_cues", "levels_for_cue", "pick_level_cue",
           "render_track", "theme_by_name"]
