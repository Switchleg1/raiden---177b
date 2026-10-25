"""A lake: a closed body of water with a shore and a shed."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .ground import add_road, add_water
from .shapes import _shore
from .siting import _nearest_road
from .vocabulary_table import AIR

if TYPE_CHECKING:
    from .anchor import _Site
    from .place_spec import PlaceSpec

import math
import random

from ...plan.site_plan import SitePlan
from ...plan.water import Water
from ..footprint import place_building
from ..geometry import (
    _along,
)


def build_lake(plan: SitePlan, site: _Site, ps: PlaceSpec,
               rng: random.Random) -> int:
    """A closed body of water in the low ground, with a shore and an access track.

    Water in this engine is painted as a stroke along a path, so a lake is a
    CLOSED path stroked wide enough to cover its own interior - which is also what
    makes the shoreline a curve rather than a polygon, and what lets the later
    riparian pass ring it with trees without being told to.
    """
    # Sizes are CLASSES, weighted toward the big end, and a lake's size decides how
    # it is used: a pond is a field pond, a mere has a shed and a camp, a lake is a
    # landmark a road has to go around. The old single range (rx 70-120) made every
    # water body the size of a field, which is what the user meant by "generally way
    # bigger than the current 'lake'".
    cls = rng.choices(("pond", "mere", "lake"), weights=(2, 5, 3))[0]
    rx = {"pond": rng.uniform(110.0, 190.0),
          "mere": rng.uniform(240.0, 420.0),
          "lake": rng.uniform(480.0, 760.0)}[cls]
    ry = rx * rng.uniform(0.62, 0.95)
    poly = _shore(site.x, site.y, rx, ry, rng)
    # A lake is a REGION, not a channel: `closed` and `inside` say so, and the
    # painter fills the polygon and banks it on the outside only. Stroked like a
    # river it came out as a ring of water with a bank line on each side of the ring
    # and glints running down its middle - "lakes appear to be roadways made in a
    # circle because they still have the centre lines inside".
    # A lake goes through `add_water` like every other body. It used to append itself
    # to the plan directly and mark the wet grid by hand, which silently skipped the
    # gates that file lives behind: it drowned buildings (caught by a test), it lay
    # alongside a carriageway, and it dropped straight onto a road that cuts it in
    # half - measured, a blueprint lake with a main road, a lane and a track all
    # running through it, which is "a road going down the middle of a body of water"
    # with the water added afterward.
    lake = Water(kind="lake", path=poly, half=ry * 0.95,
                 flood=rx * 0.28, closed=True, inside=(site.x, site.y))
    if not add_water(plan, lake):
        return 0
    built = 0
    # a boat shed on the shore, reached by a track from the nearest road
    a = rng.uniform(0, math.tau)
    sx, sy = site.x + math.cos(a) * (rx + 34.0), site.y + math.sin(a) * (ry + 34.0)
    hit = _nearest_road(plan, sx, sy)
    if hit is not None and hit[3] < 520.0:
        (_rx, _ry), tang = _along(hit[0].path, 0.5)
        add_road(plan, "track", [(sx, sy), (_rx, _ry)], 10.0)
        if place_building(plan, "shed", sx, sy, (site.x, site.y),
                          rng.uniform(0.16, 0.22), "lake", air=AIR):
            built += 1
    # the water is the place; the shed is a bonus. Returning only the shed made a
    # lake without one read as "nothing built", and the sector got another lake.
    return 1 + built
