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
    # Ground kept under the sector once its wave ends. The boss fight is flown,
    # not paused, so the sector's ground has to outlast the wave by more than the
    # fight might take - and a streamed sector's length is exactly this number
    # plus the wave, which is why it belongs to the sector and not to a constant.
    boss_tail_seconds: float = 60.0
    # How fought-over the sector's ground is, 0..1: craters, burned ground,
    # houses left as shells (terrain.war). Sector 1 is the approach - nothing has
    # happened there yet.
    scars: float = 0.0
