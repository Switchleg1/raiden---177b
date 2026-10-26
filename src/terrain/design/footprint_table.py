"""The ground a building takes, and what has to stay off it."""
from __future__ import annotations

#: A tree crown's radius at scale 1, bake px. The art is 254 px across and the
#: plan places it centred, so half of that is what a tree actually covers.
TREE_CROWN_REACH: float = 127.0

#: What grows, among the plan's cover: the kinds a road and a bridge must not
#: have standing on them. Rocks, craters and pylons are not trees and a road
#: may run past or through them.
TREE_KINDS: frozenset[str] = frozenset(
    {"wood", "copse", "riparian", "yard", "treeline", "orchard", "charred"})

#: How much of a crown may lean over a carriageway's edge, as a fraction of its
#: reach. A crown overhanging a verge is a lane through trees; a trunk on the
#: tarmac, or a whole crown on a bridge deck, hides the road it stands on.
CROWN_OVER_ROAD: float = 0.6

__all__ = ["CROWN_OVER_ROAD", "TREE_CROWN_REACH", "TREE_KINDS"]
