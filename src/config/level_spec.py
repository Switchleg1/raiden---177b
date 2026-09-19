"""Static description of one sector."""
from __future__ import annotations

from dataclasses import dataclass

from .stage_theme import StageTheme
from .theme_phase import ThemePhase


@dataclass(frozen=True)
class LevelSpec:
    name: str
    wave_seconds: float
    spawn_interval: float                       # avg seconds between formations
    spawns: tuple[tuple[str, int], ...]         # (EnemyKind, weight)
    bullet_speed: float                          # enemy bullet speed this level
    boss_hp: int
    boss_bullet: float                           # boss bullet speed multiplier
    theme: StageTheme = StageTheme.COUNTRYSIDE
    phases: tuple[ThemePhase, ...] = ()   # () -> single-theme sector
    boss: str = "e_boss1"                 # sprite sheet for this sector's boss
