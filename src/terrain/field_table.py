"""Kinds of parcel, by what may happen to them."""
from __future__ import annotations

#: Farmland: a building put down on it takes the parcel out (real development
#: eats fields). Parcels laid by a place for its own buildings are not in here.
LIFTABLE_FIELDS = frozenset({"crop", "pasture", "orchard", "paddy"})

#: Soft ground tints rather than parcels: a meadow or a burn is the ground itself
#: changing colour, painted UNDER the roads, so a road crossing one is a road
#: across open grass - not a parcel swallowing the carriageway.
SOFT_FIELDS = frozenset({"meadow", "scorch"})

__all__ = ["LIFTABLE_FIELDS", "SOFT_FIELDS"]
