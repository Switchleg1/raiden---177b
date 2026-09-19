"""Boss escort waves: which craft a boss calls in, how often, how many.

A boss fight should be a two-layer problem: read the boss's bullet patterns
while still picking off the small craft it keeps bleeding out.  Every knob
here scales with the sector index, and the mix is deliberately restricted to
the *small* kinds — a boss screen has to stay readable, so gunners, sentries
and heavies never escort.
"""
from __future__ import annotations

from .enemy_kind import EnemyKind

#: Weighted escort mix (kind, weight). Small, fast-reading craft only.
ESCORT_SPAWNS: tuple[tuple[EnemyKind, int], ...] = (
    (EnemyKind.GRUNT, 55),
    (EnemyKind.WEAVER, 28),
    (EnemyKind.DARTER, 17),
)

#: Grace period after the boss appears before the first escort wave.
ESCORT_FIRST_WAVE = 2.4

#: Seconds between escort waves in sector 1, and how much shorter each
#: sector makes them.
ESCORT_INTERVAL_0 = 3.4
ESCORT_INTERVAL_MIN = 1.5
ESCORT_INTERVAL_STEP = 0.22

#: Escorts per wave in sector 1 (+1 every N sectors).
ESCORT_GROUP_0 = 1
ESCORT_GROUP_STEP = 3
ESCORT_GROUP_MAX = 3

#: Concurrent escorts allowed in sector 1 (+1 every N sectors). The cap keeps
#: the fight readable and the entity count bounded.
ESCORT_CAP_0 = 4
ESCORT_CAP_STEP = 2
ESCORT_CAP_MAX = 8


def escort_interval(level_index: int) -> float:
    """Seconds between escort waves in this sector."""
    step = ESCORT_INTERVAL_STEP * max(0, int(level_index))
    return max(ESCORT_INTERVAL_MIN, ESCORT_INTERVAL_0 - step)


def escort_group(level_index: int) -> int:
    """Escorts launched per wave in this sector."""
    return min(ESCORT_GROUP_MAX,
               ESCORT_GROUP_0 + max(0, int(level_index)) // ESCORT_GROUP_STEP)


def escort_cap(level_index: int) -> int:
    """Max escorts alive at once in this sector."""
    return min(ESCORT_CAP_MAX,
               ESCORT_CAP_0 + max(0, int(level_index)) // ESCORT_CAP_STEP)


__all__ = ["ESCORT_SPAWNS", "ESCORT_FIRST_WAVE", "ESCORT_INTERVAL_0",
           "ESCORT_INTERVAL_MIN", "ESCORT_INTERVAL_STEP", "ESCORT_GROUP_0",
           "ESCORT_GROUP_STEP", "ESCORT_GROUP_MAX", "ESCORT_CAP_0",
           "ESCORT_CAP_STEP", "ESCORT_CAP_MAX", "escort_interval",
           "escort_group", "escort_cap"]
