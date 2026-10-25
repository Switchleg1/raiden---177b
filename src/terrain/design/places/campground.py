"""A campground: tents around a fire in a clearing by the water."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .ground import _inside, add_parcel, add_road
from .shapes import _shore
from .siting import _nearest_road
from .vocabulary_table import ROAD_MAX

if TYPE_CHECKING:
    from .anchor import _Site
    from .place_spec import PlaceSpec

import math
import random

from ...plan.green import Green
from ...plan.site_plan import SitePlan
from ..art import _face, ink_size
from ..footprint import place_building
from ..geometry import (
    _in_poly,
)


def build_campground(plan: SitePlan, site: _Site, ps: PlaceSpec,
                     rng: random.Random) -> int:
    """Cabins around a fire clearing, entered from a track, kept out of the trees.

    The clearing is the point: ground worn bare by use, with the cabins turned
    INWARD toward the fire. A campground is a place where the layout says people
    sleep, and it is only legible because everything faces the middle.
    """
    hit0 = _nearest_road(plan, site.x, site.y)
    # its own reach to a road, not the water's: a camp is sited BY the water and
    # reached BY the road, and reusing one number for both left the theme with no
    # campgrounds at all (the test that checks a campground exists found none to
    # check, which is a bug reporting as a pass)
    if hit0 is None or hit0[3] > ROAD_MAX:
        # a camp with no way in is not a camp: the ground would be used by
        # nothing, and the cabins would fail the plan's own "every building is
        # reached by a road" rule after the clearing was already drawn
        return 0
    rx, ry = rng.uniform(118.0, 150.0), rng.uniform(100.0, 128.0)
    # A camp is sited BY the water, so its clearing can reach the bank - and a
    # parcel touching wet ground is refused. The clearing stops at the bank instead:
    # try it smaller before giving the camp up.
    # Pull back only the edge that reaches the water: a clearing stops at the bank
    # on that side and keeps its size on the others.
    clearing = []
    for qx, qy in _shore(site.x, site.y, rx, ry, rng, n=24):
        t = 1.0
        while t > 0.35 and plan.is_wet(site.x + (qx - site.x) * t,
                                       site.y + (qy - site.y) * t):
            t -= 0.08
        clearing.append((site.x + (qx - site.x) * t, site.y + (qy - site.y) * t))
    ground = add_parcel(plan, clearing, "grass_patchy", "clearing")
    if ground is None:
        return 0
    # the tents' ring has to fit the ground the clearing actually got
    reach = min(math.hypot(qx - site.x, qy - site.y) for qx, qy in clearing)
    rx = ry = max(60.0, reach / 0.58 * 0.95)
    # the fire clearing in the middle: bare trodden earth, and the fire on it
    hearth = Green(x=site.x, y=site.y, radius=rng.uniform(22.0, 30.0),
                   mat="earth_cracked")
    plan.greens.append(hearth)
    fire = place_building(plan, "campfire", site.x, site.y, (site.x, site.y + 1.0),
                          rng.uniform(0.16, 0.19), "campfire", air=4.0)
    kinds = ps.kinds or ("cabin",)
    # Tents on a ring inside the clearing, spaced by their own ink, every door to
    # the fire. A tent is a third the size of a house - the old camp used stilt
    # huts at house scale, which is a fishing village, not a campsite.
    # (half again true scale: at 3 m a tent is 13 px on screen and reads as a dot)
    tent_scale = (0.22, 0.27)
    ring = min(rx, ry) * 0.58
    size = max(ink_size(kinds[0], tent_scale[1]))
    n = max(3, min(9, int(math.tau * ring // (size + 10.0))))
    a0 = rng.uniform(0, math.tau)
    built = 0
    quarter = math.tau / 4.0
    for i in range(n):
        a = a0 + (i / n) * math.tau
        # A building's facing is one of the four cardinals - arbitrary angles made a
        # row of houses read as a pile, and a rotated footprint cannot be overlap-
        # tested without rotating the test. That law and a ring of cabins meet badly
        # at the diagonals: a cabin standing north-east of its fire can look west or
        # north, and one of those has the fire behind it. So the position is biased,
        # not the facing: sit the cabin on the arc whose cardinal really does look at
        # the clearing. `a cabin stands at 90 deg with the fire behind it` is what
        # happens when the ring is allowed to land on the coin-flip instead.
        cand = [a, round(a / quarter) * quarter,
                round(a / quarter) * quarter + quarter]
        placed = False
        for aa in cand:
            if placed:
                break
            for rr in (ring, ring + 14.0, ring - 10.0, ring + 26.0):
                cx = site.x + math.cos(aa) * rr
                cy = site.y + math.sin(aa) * rr
                look = _face(cx, cy, site.x, site.y)
                dx, dy = site.x - cx, site.y - cy
                ln = math.hypot(dx, dy) or 1.0
                if ((math.cos(math.radians(look)) * dx
                     + math.sin(math.radians(look)) * dy) / ln) <= 0.0:
                    continue          # this arc would turn its back on the fire
                if place_building(plan, kinds[i % len(kinds)], cx, cy,
                                  (site.x, site.y), rng.uniform(*tent_scale),
                                  "campground", air=8.0):
                    built += 1
                    placed = True
                    break
    if built == 0:
        # A camp with no tents is not a camp. Take the clearing and the fire back
        # out, or the retry builds a second camp beside an abandoned fire.
        plan.fields.remove(ground)
        plan.greens.remove(hearth)
        if fire is not None:
            plan.buildings.remove(fire)
        return 0
    # the track in, and the campers' car where it ends
    hit = _nearest_road(plan, site.x, site.y)
    if hit is not None and hit[3] < 460.0:
        (ax, ay) = hit[1]
        # the track runs from the road straight toward the fire and stops short of
        # the clearing's real edge (an outline pulled back from the water is not
        # the oval it started as, so the edge is found by walking, not assumed)
        dx, dy = site.x - ax, site.y - ay
        ln = math.hypot(dx, dy) or 1.0
        ux, uy = dx / ln, dy / ln
        t = 0.0
        while t < ln and not _in_poly(ax + ux * (t + 22.0), ay + uy * (t + 22.0),
                                      clearing):
            t += 6.0
        edge = (ax + ux * t, ay + uy * t)
        add_road(plan, "track", [(ax, ay), edge], 10.0)
        px, py = edge[0] - ux * 26.0 - uy * 22.0, edge[1] - uy * 26.0 + ux * 22.0
        if _inside(plan, px, py, 24.0):
            # the campers' car, parked where the track ends
            car = ("car_red", "car_white", "car_blue", "car_grey")[rng.randrange(4)]
            place_building(plan, car, px, py, (ax, ay), 0.15, "parking",
                           air=6.0)
    return built
