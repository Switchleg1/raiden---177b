"""How fast the world moves past the craft, and what that makes "forward".

The parallax rates used to live in ``terrain/`` with no other caller. Anything
that travels through the field in world terms - the flamethrower's puffs most of
all - has to be defined against the ground rate rather than as a bare number, or
the weapon's reach is an accident of whatever the background happens to do. So
the rates are stated once here, and the view layer reads them from here.
"""
from __future__ import annotations

# Slow distant layer (px/s).
SCROLL_FAR = 60.0


# The ground layer at full scroll: the rate the world passes the craft, and
# therefore the rate a world-locked object has to beat to be going anywhere.
SCROLL_NEAR = 165.0
