"""The ground a building takes, and what has to stay off it."""
from __future__ import annotations

#: A tree crown's radius at scale 1, bake px. The art is 254 px across and the
#: plan places it centred, so half of that is what a tree actually covers.
TREE_CROWN_REACH: float = 127.0

__all__ = ["TREE_CROWN_REACH"]
