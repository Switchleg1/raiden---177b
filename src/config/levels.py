"""The nine-sector campaign table + boss entry geometry.

Every sector cross-fades between two terrain zones (``phases``); ``theme`` is
the sector's primary theme and drives the briefing title.  Enemy mix escalates
sector by sector: grunts thin out as gunners, sentries and heavies arrive,
then splitters (sector 2), rammers (sector 3) and bombers (sector 4) join the
rotation.  Shards never appear in a table; they only come out of a splitter.
"""
from __future__ import annotations

from .level_spec import LevelSpec
from .stage_theme import StageTheme
from .theme_phase import ThemePhase

LEVELS: tuple[LevelSpec, ...] = (
    LevelSpec(
        name="Sector 1: Countryside Approach", wave_seconds=34.0,
        spawn_interval=0.95,
        spawns=(("grunt", 60), ("weaver", 26), ("darter", 14)),
        bullet_speed=210.0, boss_hp=180, boss_bullet=0.9,
        boss="e_boss1",
        theme=StageTheme.COUNTRYSIDE,
        phases=(ThemePhase(StageTheme.COUNTRYSIDE, 0.55),
                ThemePhase(StageTheme.FARMLAND, 0.45))),
    LevelSpec(
        name="Sector 2: Bayou Marsh", wave_seconds=36.0,
        spawn_interval=0.92,
        spawns=(("grunt", 42), ("weaver", 22), ("darter", 16),
                ("gunner", 12), ("splitter", 8)),
        bullet_speed=225.0, boss_hp=210, boss_bullet=0.95,
        boss="e_boss2",
        theme=StageTheme.SWAMP,
        phases=(ThemePhase(StageTheme.SWAMP, 0.62),
                ThemePhase(StageTheme.FARMLAND, 0.38))),
    LevelSpec(
        name="Sector 3: City Gauntlet", wave_seconds=38.0,
        spawn_interval=0.88,
        spawns=(("grunt", 34), ("weaver", 20), ("darter", 16),
                ("gunner", 16), ("sentry", 8), ("splitter", 10),
                ("rammer", 8)),
        bullet_speed=240.0, boss_hp=250, boss_bullet=1.0,
        boss="e_boss3",
        theme=StageTheme.CITY,
        phases=(ThemePhase(StageTheme.CITY, 0.62),
                ThemePhase(StageTheme.RUINS, 0.38))),
    LevelSpec(
        name="Sector 4: Frozen Approach", wave_seconds=40.0,
        spawn_interval=0.85,
        spawns=(("grunt", 26), ("weaver", 18), ("darter", 16),
                ("gunner", 18), ("sentry", 12), ("heavy", 4),
                ("splitter", 10), ("rammer", 8), ("bomber", 6)),
        bullet_speed=255.0, boss_hp=290, boss_bullet=1.05,
        boss="e_boss4",
        theme=StageTheme.GLACIER,
        phases=(ThemePhase(StageTheme.GLACIER, 0.62),
                ThemePhase(StageTheme.OCEAN, 0.38))),
    LevelSpec(
        name="Sector 5: Ruins Citadel", wave_seconds=42.0,
        spawn_interval=0.82,
        spawns=(("grunt", 22), ("weaver", 18), ("darter", 16),
                ("gunner", 20), ("sentry", 14), ("heavy", 6),
                ("splitter", 12), ("rammer", 10), ("bomber", 8)),
        bullet_speed=270.0, boss_hp=340, boss_bullet=1.1,
        boss="e_boss5",
        theme=StageTheme.RUINS,
        phases=(ThemePhase(StageTheme.RUINS, 0.55),
                ThemePhase(StageTheme.CANYON, 0.45))),
    LevelSpec(
        name="Sector 6: Molten Shelf", wave_seconds=44.0,
        spawn_interval=0.78,
        spawns=(("grunt", 18), ("weaver", 16), ("darter", 16),
                ("gunner", 22), ("sentry", 16), ("heavy", 8),
                ("splitter", 12), ("rammer", 12), ("bomber", 10)),
        bullet_speed=285.0, boss_hp=390, boss_bullet=1.15,
        boss="e_boss6",
        theme=StageTheme.VOLCANIC,
        phases=(ThemePhase(StageTheme.VOLCANIC, 0.62),
                ThemePhase(StageTheme.CANYON, 0.38))),
    LevelSpec(
        name="Sector 7: Ocean Bulwark", wave_seconds=46.0,
        spawn_interval=0.74,
        spawns=(("grunt", 16), ("weaver", 16), ("darter", 16),
                ("gunner", 22), ("sentry", 18), ("heavy", 10),
                ("splitter", 14), ("rammer", 12), ("bomber", 12)),
        bullet_speed=300.0, boss_hp=440, boss_bullet=1.2,
        boss="e_boss7",
        theme=StageTheme.OCEAN,
        phases=(ThemePhase(StageTheme.OCEAN, 0.55),
                ThemePhase(StageTheme.AIRBASE, 0.45))),
    LevelSpec(
        name="Sector 8: Iron Works", wave_seconds=48.0,
        spawn_interval=0.70,
        spawns=(("grunt", 14), ("weaver", 14), ("darter", 16),
                ("gunner", 24), ("sentry", 18), ("heavy", 12),
                ("splitter", 14), ("rammer", 14), ("bomber", 14)),
        bullet_speed=315.0, boss_hp=510, boss_bullet=1.25,
        boss="e_boss8",
        theme=StageTheme.INDUSTRIAL,
        phases=(ThemePhase(StageTheme.INDUSTRIAL, 0.60),
                ThemePhase(StageTheme.AIRBASE, 0.40))),
    LevelSpec(
        name="Sector 9: Wasteland Core", wave_seconds=50.0,
        spawn_interval=0.66,
        spawns=(("grunt", 12), ("weaver", 14), ("darter", 16),
                ("gunner", 24), ("sentry", 20), ("heavy", 14),
                ("splitter", 16), ("rammer", 16), ("bomber", 16)),
        bullet_speed=330.0, boss_hp=600, boss_bullet=1.3,
        boss="e_boss9",
        theme=StageTheme.WASTELAND,
        phases=(ThemePhase(StageTheme.WASTELAND, 0.60),
                ThemePhase(StageTheme.CANYON, 0.40))),
)


FINAL_LEVEL_INDEX = len(LEVELS) - 1


# Boss entry: glides in from the top to this y, then strafes.
BOSS_ENTRY_Y = 130.0


BOSS_TOP = 90.0


BOSS_BOTTOM = 200.0


def level_speed(bullet_speed: float, index: int) -> float:
    """Enemy bullet speed for a level (kept for callers that pass index)."""
    return float(bullet_speed) + 18.0 * max(0, index)
