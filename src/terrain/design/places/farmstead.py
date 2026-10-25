"""A farmstead: a barn and a house with a yard between them."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .siting import _nearest_road
from .vocabulary_table import AIR

if TYPE_CHECKING:
    from .anchor import _Site
    from .place_spec import PlaceSpec

import math
import random

from ...plan.site_plan import SitePlan
from ..art import ink_size
from ..footprint import place_building
from ..geometry import (
    _along,
)


def build_farmstead(plan: SitePlan, site: _Site, ps: PlaceSpec,
                    rng: random.Random) -> int:
    """A barn and a house with a yard between them, at the field edge."""
    hit = _nearest_road(plan, site.x, site.y)
    if hit is None or hit[3] > 340.0:
        return 0
    (ax, ay), tang = _along(hit[0].path, 0.5)
    kinds = ps.kinds or ("barn", "house")
    barn = place_building(plan, kinds[0], site.x, site.y, (ax, ay),
                          rng.uniform(0.6, 0.74), "farmstead",
                          drive=[(site.x, site.y), (ax, ay)], air=AIR)
    if barn is None:
        return 0
    bw, bh = ink_size(kinds[0], barn.scale, barn.angle)
    span = max(bw, bh) + 60.0
    built = 1
    # lay the yard's second range toward the road, not away from it: a farm
    # building nobody can walk to is scenery, and the plan says every building is
    # reached by a road
    far = _nearest_road(plan, site.x + math.cos(tang) * span,
                        site.y + math.sin(tang) * span)
    near = _nearest_road(plan, site.x - math.cos(tang) * span,
                         site.y - math.sin(tang) * span)
    if far is not None and near is not None and near[3] < far[3]:
        tang += math.pi
    hx = site.x + math.cos(tang) * span
    hy = site.y + math.sin(tang) * span
    if place_building(plan, kinds[1], hx, hy, (ax, ay),
                      rng.uniform(0.56, 0.68), "farmstead",
                      drive=[(hx, hy), (ax, ay)],
                      yard=(hx, hy + 34.0, rng.uniform(16.0, 26.0)), air=AIR):
        built += 1
    return built
