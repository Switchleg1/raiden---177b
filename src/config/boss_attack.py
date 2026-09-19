"""One volley in a boss's attack sequence."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BossAttack:
    """One volley: which shape to fire, and what it costs the player.

    ``kind`` selects a primitive implemented in :mod:`entities.bosskit`;
    the primitives read their geometry from the remaining fields so a boss's
    entire personality stays in data:

    ``cd``
        Seconds before the *next* volley. This is the rhythm knob — a boss
        that fires a big fan every 1.5 s and a boss that leaks one bolt every
        0.35 s feel completely different even with the same bullets.
    ``count``
        Bullets (or shells) in the volley.
    ``arc``
        Spread width in degrees for aimed/fan/spray shapes; sweep half-width
        for a beam.
    ``speed``
        Multiplier on the sector's boss bullet speed.
    ``param``
        Primitive-specific: rotation degrees/second for rings, spirals and
        pinwheels; sweep degrees/second for a beam; minimum gap width in
        pixels for a wall.
    ``fuse`` / ``frag``
        Cluster-shell timing and fragment count (shell volleys only).
    """

    kind: str
    cd: float
    count: int = 8
    arc: float = 60.0
    speed: float = 1.0
    param: float = 0.0
    fuse: float = 1.1
    frag: int = 0


__all__ = ["BossAttack"]
