"""A boss's fighting personality: how it moves and the order it fires in."""
from __future__ import annotations

from dataclasses import dataclass

from .boss_attack import BossAttack


@dataclass(frozen=True)
class BossHabit:
    """Data-only personality, keyed by the boss's sprite sheet.

    Movement and firing were once hard-coded once for every sector, so nine
    bosses played as one boss with more hit points. Splitting the *shape* of an
    attack (``BossAttack``) from the *sequence and cadence* (here) means a
    boss's rhythm and positioning are as much part of its identity as its
    sprite, and adding sector ten is a table entry, not new code.
    """

    name: str
    move: str
    attacks: tuple[BossAttack, ...]
    # Movement envelope multiplier (1.0 = the tuned default for that strategy).
    speed: float = 1.0
    # How the boss comes on screen before its habit starts: "top", "left",
    # "right". Sector 1 glides in like always; later sectors surprise you.
    entry: str = "top"
    # Bosses stop playing nice under this hp fraction...
    enrage_at: float = 0.5
    # ...firing this much faster, and with this many extra bullets per volley.
    enrage_cd: float = 0.65
    enrage_count: int = 0


__all__ = ["BossHabit"]
