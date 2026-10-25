"""Painting a whole site, near layer and far layer."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .buildings import paint_buildings
from .cover import paint_cover, paint_scars
from .fields import paint_fields
from .relief import paint_relief
from .roads import paint_greens, paint_roads
from .sampling import _at
from .surface import _blit_wrap
from .water import paint_water

if TYPE_CHECKING:
    from .plane import Plane

import random
from typing import Any

from ..plan.site_plan import SitePlan
from ..tilekit import CW, TileKit


def paint_far(canvas: Any, kit: TileKit, plan: SitePlan,
              rng: random.Random) -> None:
    """The slow layer: the same ridge language, seen further off and softer,
    so the range the player is flying along keeps going behind it."""
    import pygame

    from ..theme_table import FAR_PAIR
    SPAN = 280
    # Placed on a lattice in **world** rows and columns, one decision per cell,
    # rather than three positions drawn from a stream belonging to this window -
    # which is what made the far layer disagree with itself across a slice
    # boundary: same patch name, different places, a seam of tone.
    y0 = int(getattr(canvas, "y0", 0))
    # `h` is PAINTED pixels and the lattice is counted in PLAN pixels, so a plane at
    # 2 plan pixels per painted one covers only HALF its world range if this is taken
    # at face value - which put no distant range at all in the lower half of every
    # strip window: slices 4-7 of eight disagreed with a one-window reference on
    # 21%-54% of their pixels, scattered, and looked like "some tiles just wrong".
    # The same unit boundary `_band` documents, arriving from the other side.
    tall = int(getattr(canvas, "h", 0) or canvas.get_height()) \
        * getattr(canvas, "scale", 1)
    y_from = y0 // SPAN * SPAN - SPAN
    y_to = y0 + tall + SPAN
    for name in FAR_PAIR[plan.theme]:
        t = pygame.transform.smoothscale(kit.patch(name), (SPAN, SPAN))
        for wy in range(y_from, y_to, SPAN):
            for wx in range(0, CW, SPAN):
                here = _at("farpatch", plan.seed, name, wx, wy)
                if here.random() >= 0.62:
                    continue
                t.set_alpha(here.randint(22, 40))
                _blit_wrap(canvas, t,
                           wx + here.uniform(-SPAN * 0.4, SPAN * 0.4),
                           wy + here.uniform(-SPAN * 0.4, SPAN * 0.4))
    paint_relief(canvas, kit, plan, rng, far=True)


def paint_site(canvas: Plane, kit: TileKit, plan: SitePlan,
               rng: random.Random) -> None:
    """The whole near layer, in the order a landscape is built up."""
    # In the order a landscape exists: ground, then the water in its hollows,
    # then whatever was cleared and enclosed on the flat parts. The old order
    # painted the relief ON TOP of fields and channels, washing out both the
    # cultivation and the elevation it was supposed to explain.
    paint_relief(canvas, kit, plan, rng)
    paint_water(canvas, kit, plan, rng)
    paint_fields(canvas, kit, plan, rng)
    paint_roads(canvas, kit, plan, rng)
    paint_greens(canvas, kit, plan, rng)
    paint_scars(canvas, kit, plan, rng)
    paint_buildings(canvas, kit, plan, rng)
    paint_cover(canvas, kit, plan, rng)
