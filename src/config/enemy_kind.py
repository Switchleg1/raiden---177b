"""Enemy archetypes."""
from __future__ import annotations

from enum import StrEnum


class EnemyKind(StrEnum):
    GRUNT = "grunt"        # straight descent, occasional single shot
    WEAVER = "weaver"      # sinusoidal descent
    DARTER = "darter"      # fast dive across the field
    GUNNER = "gunner"      # descends then hovers, fires aimed shots
    SENTRY = "sentry"      # near-static turret, radial spread
    HEAVY = "heavy"        # tanky slow bruiser
    BOMBER = "bomber"      # slow seeder: lobs cluster shells that burst
    SPLITTER = "splitter"  # weaves down, breaks into shards when killed
    RAMMER = "rammer"      # locks the player's column, then charges
    SHARD = "shard"        # splitter fragment: fast diverging dive
    BOSS = "boss"          # level boss
