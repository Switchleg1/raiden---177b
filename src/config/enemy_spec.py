"""Frozen stat block for one enemy kind."""
from __future__ import annotations

from dataclasses import dataclass

from .enemy_kind import EnemyKind


# ---------------------------------------------------------------------------
# Enemies. Stats keyed by kind. Behaviour is implemented in entities/physics.
#   hp        hit points
#   r         collision radius
#   speed     downward cruise speed (units/s)
#   score     points for a kill
#   drop      override item drop chance (else ITEM_DROP_CHANCE)
#   fires     whether the enemy shoots
#   fire_cd   base fire cooldown (s); scaled by level
#   shell_frag  > 0: shots are fat slow shells that burst into this many
#               bullets when their fuse runs out (bomber cluster munition)
#   shell_fuse  seconds a shell flies before it bursts
#   split_into  kind spawned from this enemy's corpse (None: does not split)
#   split_count how many children one death produces
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EnemySpec:
    hp: int
    r: float
    speed: float
    score: int
    drop: float
    fires: bool = False
    fire_cd: float = 1.8
    color: tuple[int, int, int] = (200, 200, 200)
    shell_frag: int = 0
    shell_fuse: float = 0.9
    split_into: EnemyKind | None = None
    split_count: int = 0
