"""The nine sector bosses, as personalities.

Each entry is keyed by the boss's sprite sheet (the same key ``LevelSpec.boss``
uses to pick art), so art and behaviour stay routed through one identity. The
nine habits are deliberately disjoint: no two share a movement strategy, no two
share an attack sequence, and the cadences differ enough that a returning player
hears the difference before they see it.

Bullet *speed* still scales with the sector (``LevelSpec.bullet_speed`` times
``boss_bullet``), so lateness keeps raising the pressure; what this table adds
is that lateness also raises *variety*.
"""
from __future__ import annotations

from .boss_attack import BossAttack
from .boss_habit import BossHabit

BOSS_HABITS: dict[str, BossHabit] = {
    # Sector 1 - teaches the vocabulary: it faces you, it announces every
    # volley, and it stays where you expect it.
    "e_boss1": BossHabit(
        name="Gatekeeper",
        move="strafe",
        attacks=(
            BossAttack("aimed", cd=1.15, count=3, arc=26),
            BossAttack("fan", cd=1.25, count=5, arc=64),
            BossAttack("ring", cd=1.45, count=8, param=30.0),
        ),
    ),
    # Sector 2 - slow matron hanging on a wide arc, leaking a rotating spiral
    # you have to walk around, and dropping slow eggs that linger.
    "e_boss2": BossHabit(
        name="Bog Matron",
        move="pendulum",
        speed=0.85,
        entry="top",
        attacks=(
            BossAttack("spiral", cd=0.4, count=3, param=48.0, speed=0.8),
            BossAttack("aimed", cd=1.05, count=2, arc=16),
            BossAttack("mine", cd=1.9, count=6, arc=120, param=26.0),
        ),
    ),
    # Sector 3 - slides over your head so you cannot stand still, sweeps a
    # beam you must cross, and pans spray while moving.
    "e_boss3": BossHabit(
        name="Sky Crane",
        move="hunt",
        speed=1.0,
        entry="left",
        attacks=(
            BossAttack("beam", cd=0.95, count=5, arc=34, param=30.0, speed=1.35),
            BossAttack("spray", cd=0.85, count=9, arc=78, speed=0.9),
            BossAttack("aimed", cd=0.9, count=4, arc=34),
        ),
    ),
    # Sector 4 - circles the arena and throws concentric rings; the pinwheel is
    # fast and thin, so it cuts the screen rather than filling it.
    "e_boss4": BossHabit(
        name="Frost Ring",
        move="orbit",
        speed=1.0,
        attacks=(
            BossAttack("ring", cd=1.35, count=12, param=-42.0, speed=0.75),
            BossAttack("pinwheel", cd=0.8, count=4, param=96.0, speed=1.4),
            BossAttack("fan", cd=1.1, count=7, arc=96, speed=0.95),
        ),
    ),
    # Sector 5 - judders between anchor points, so aimed fire goes stale, and
    # answers with bullet walls that have a gap you have to reach in time.
    "e_boss5": BossHabit(
        name="Citadel Bolt",
        move="hop",
        speed=1.0,
        entry="right",
        attacks=(
            BossAttack("wall", cd=1.7, count=11, param=112.0, speed=0.85),
            BossAttack("aimed", cd=0.95, count=5, arc=44),
            BossAttack("shell", cd=1.9, count=2, fuse=1.0, frag=8),
        ),
    ),
    # Sector 6 - commits: pitches down to the bottom of its band and lobs
    # cluster shells into your retreat, then empties a heavy fan up close.
    "e_boss6": BossHabit(
        name="Magma Core",
        move="lunge",
        speed=1.05,
        attacks=(
            BossAttack("shell", cd=1.6, count=3, fuse=1.25, frag=6),
            BossAttack("fan", cd=1.0, count=9, arc=120),
            BossAttack("spray", cd=0.75, count=12, arc=110, speed=0.85),
        ),
        enrage_at=0.55,
        enrage_count=2,
    ),
    # Sector 7 - traces a figure of eight while counter-rotating two spirals;
    # the beam arrives on the crossing, when you least expect a straight line.
    "e_boss7": BossHabit(
        name="Sea Bastion",
        move="eight",
        speed=1.0,
        attacks=(
            BossAttack("spiral", cd=0.38, count=5, param=-58.0, speed=0.85),
            BossAttack("ring", cd=1.3, count=10, param=52.0, speed=0.8),
            BossAttack("beam", cd=1.0, count=4, arc=28, param=-34.0, speed=1.3),
        ),
    ),
    # Sector 8 - fights from cover: darts to a wall, hugs it, and answers with
    # walls, mines and a fast pinwheel. Standing still is a losing move.
    "e_boss8": BossHabit(
        name="Iron Works",
        move="edge",
        speed=1.15,
        entry="left",
        attacks=(
            BossAttack("wall", cd=1.45, count=13, param=104.0, speed=0.9),
            BossAttack("aimed", cd=0.8, count=6, arc=54),
            BossAttack("mine", cd=1.5, count=8, arc=150, param=22.0),
            BossAttack("pinwheel", cd=0.9, count=6, param=-112.0, speed=1.35),
        ),
        enrage_at=0.5,
        enrage_cd=0.6,
    ),
    # Sector 9 - the core. It looms: it takes the bottom of its band, weaves
    # wide, and cycles six attacks so the fight never settles into a rhythm.
    "e_boss9": BossHabit(
        name="Wasteland Core",
        move="stalker",
        speed=1.1,
        attacks=(
            BossAttack("ring", cd=1.2, count=14, param=38.0, speed=0.75),
            BossAttack("spiral", cd=0.34, count=6, param=72.0, speed=0.9),
            BossAttack("aimed", cd=0.7, count=4, arc=38),
            BossAttack("wall", cd=1.6, count=15, param=118.0, speed=0.95),
            BossAttack("shell", cd=1.5, count=3, fuse=0.95, frag=10),
            BossAttack("beam", cd=0.85, count=5, arc=32, param=36.0, speed=1.4),
        ),
        enrage_at=0.55,
        enrage_cd=0.7,
        enrage_count=2,
    ),
}


# A boss with no table entry (a bare checkout, a test spawn, a designer sheet
# that has not been given a personality yet) still has to fight like the
# original sector 1 gatekeeper rather than drift and never fire.
DEFAULT_HABIT = BOSS_HABITS["e_boss1"]


def habit_for(sheet: str | None) -> BossHabit:
    """Look up a boss's habit by sprite sheet name; never fails."""
    return BOSS_HABITS.get(sheet or "", DEFAULT_HABIT)


__all__ = ["BOSS_HABITS", "DEFAULT_HABIT", "habit_for"]
