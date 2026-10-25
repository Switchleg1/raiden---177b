"""A place's claimed ground."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Claim:
    """A place's claimed ground: an anchor disc it owns outright.

    `keep` is the ground the place OCCUPIES. The old record also carried `reach`, the
    place's radius of influence, and siting tested against that - which for a
    woodland (reach 760 in a 1600 px-wide sector) meant nothing else could be sited
    anywhere near a forest. Influence is a preference about spacing; occupancy is the
    thing another place would contradict, so this carries occupancy."""

    x: float
    y: float
    keep: float = 0.0
    name: str = ""
