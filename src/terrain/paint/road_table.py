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

__all__ = ["BRIDGE", "BRIDGE_DECK", "SOILED_KINDS", "SOILING"]


#: A bridge, drawn from the road's own line: how far each end lands on the bank
#: (px), the kerb outside the carriageway that the parapets stand on, the
#: parapet and end-post colours, and the
#: deck's shadow on the water (offset away from the upper-left sun, and how
#: dark it makes the water).
BRIDGE: dict = {
    "landing": 16,
    "kerb": 3.0,
    "rail": (196, 190, 176),
    "rail_shade": (34, 30, 26),
    "post": (88, 82, 74),
    "shadow": (8.0, 10.0),
    "shadow_dark": 0.5,
}

#: What a bridge deck is made of, by the road's material: a paved street keeps
#: its asphalt, a gravel or dirt route crosses on a concrete slab - the change of
#: surface is half of what says "bridge" from above.
BRIDGE_DECK: dict[str, str] = {
    "gravel_rubble": "concrete_apron",
    "earth_cracked": "concrete_apron",
    "road_dirt": "concrete_apron",
}
