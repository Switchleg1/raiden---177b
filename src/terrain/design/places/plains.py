"""Plains: open meadow with a few lone trees."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .ground import _claim_cells
from .shapes import _shore

if TYPE_CHECKING:
    from .anchor import _Site
    from .place_spec import PlaceSpec

import math
import random

from ...plan.field import Field
from ...plan.site_plan import SitePlan
from ...plan.wood import Wood
from ..geometry import (
    _in_poly,
)


def build_plains(plan: SitePlan, site: _Site, ps: PlaceSpec,
                 rng: random.Random) -> int:
    """Open grassland: a wide meadow with a handful of lone trees standing in it.

    The countryside used to be busy everywhere - a field, a hedge, a copse, a
    farm, another field - which is the clutter the user kept describing. Real
    country has open stretches, and they are what make the busy parts read. A
    plain CLAIMS its ground, so the field and woodland passes leave it open; what
    it holds is grass and a few big trees, each standing alone.
    """
    r = rng.uniform(380.0, 620.0)
    poly = _shore(site.x, site.y, r, r * rng.uniform(0.7, 0.95), rng, n=32)
    g = plan.geom
    poly = [(min(g.w - 4.0, max(4.0, x)), y) for x, y in poly]
    if any(plan.is_wet(x, y) for x, y in poly[::4]):
        r *= 0.7
        poly = [(site.x + (x - site.x) * 0.7, site.y + (y - site.y) * 0.7)
                for x, y in poly]
    plan.fields.insert(0, Field(poly=poly, mat="grass_lush", kind="meadow",
                                hedge=False))
    _claim_cells(plan, poly)
    items = []
    for _ in range(rng.randint(3, 7)):
        for _try in range(6):
            a, d = rng.uniform(0, math.tau), r * math.sqrt(rng.random()) * 0.8
            x, y = site.x + math.cos(a) * d, site.y + math.sin(a) * d * 0.85
            if (not _in_poly(x, y, poly) or plan.is_wet(x, y)
                    or plan.near_road(x, y, 40.0)
                    or any(math.hypot(x - ix, y - iy) < 150.0 for ix, iy, _s in items)):
                continue
            items.append((x, y, rng.uniform(0.55, 0.75)))
            break
    if items:
        plan.woods.append(Wood(kind="copse", items=items))
    return 1
