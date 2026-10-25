"""How each kind of enemy flies: the Enemy method that moves it, per kind."""
from __future__ import annotations

import config as C

FLIGHT: dict[C.EnemyKind, str] = {
    C.EnemyKind.GRUNT: "_fly_grunt",
    C.EnemyKind.WEAVER: "_fly_weaver",
    C.EnemyKind.DARTER: "_fly_darter",
    C.EnemyKind.GUNNER: "_fly_gunner",
    C.EnemyKind.SENTRY: "_fly_sentry",
    C.EnemyKind.HEAVY: "_fly_heavy",
    C.EnemyKind.BOMBER: "_fly_bomber",
    C.EnemyKind.SPLITTER: "_fly_splitter",
    C.EnemyKind.RAMMER: "_fly_rammer",
    C.EnemyKind.SHARD: "_fly_shard",
    C.EnemyKind.BOSS: "_fly_boss",
}

#: kinds that hold the field and bounce off its side walls instead of leaving
WALLED = frozenset({C.EnemyKind.GUNNER, C.EnemyKind.SENTRY, C.EnemyKind.HEAVY,
                    C.EnemyKind.BOMBER, C.EnemyKind.BOSS})

__all__ = ["FLIGHT", "WALLED"]
