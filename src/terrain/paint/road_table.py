"""What soils the ground beside a road, by theme and by kind of road."""
from __future__ import annotations

#: the splat thrown onto a road's verges; a theme not listed throws dirt. Paved
#: ground has no dirt verge to throw - in a city every street wore a string of
#: orange blobs, which read as litter, not as wear.
SOILING: dict[str, str | None] = {
    "industrial": "splat_oil",
    "city": None,
    "airbase": None,
}

#: road kinds whose verges are worn; a highway is kerbed and kept
SOILED_KINDS: frozenset[str] = frozenset({"main", "spur", "track"})

__all__ = ["SOILED_KINDS", "SOILING"]
