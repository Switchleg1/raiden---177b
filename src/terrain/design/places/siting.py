"""Where a place may go."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .anchor import _Site
from .claim import _Claim
from .vocabulary_table import CLAIM_PAD

if TYPE_CHECKING:
    from .place_spec import PlaceSpec

import bisect
import math
import random

from ...plan.geom import Point
from ...plan.road import Road
from ...plan.site_plan import SitePlan
from ..geometry import (
    _along,
    _in_strip,
    _near_path,
    _nearest_on_path,
    _span,
)


def _free(plan: SitePlan, claims: list[_Claim], x: float, y: float,
          r: float) -> bool:
    """Is this ground free - of another place, and of the built ground the
    settlement pass already claimed?"""
    g = plan.geom
    if x - r < 10.0 or x + r > g.w - 10.0:
        return False
    if not _in_strip(g, y - r) or not _in_strip(g, y + r):
        return False
    for c in claims:
        # the reservation it OWNS (`keep`), not its influence radius (`reach`). A
        # woodland's reach is 760 px in a 1600 px-wide sector, and gating siting on
        # that meant a campground, a farmstead or a second neighborhood could not
        # exist anywhere near a forest - measured, 19 of the campground's rejections
        # were "a forest's influence reaches here". Places must not stand in each
        # other's ground; standing near one another is what a sector is.
        if math.hypot(c.x - x, c.y - y) < c.keep + r:
            return False
    # a place must not stand in ground that buildings already occupy, nor in water
    j0, j1 = _span(y - r, y + r, g.rows, g.cell)
    i0, i1 = _span(x - r, x + r, g.cols, g.cell)
    hits = 0
    cells = (j1 - j0 + 1) * (i1 - i0 + 1)
    # A PROPORTION, not a count of three. The old test asked a 470 px box to hold at
    # most three occupied cells - about half a percent of a field-and-hedge country -
    # so almost every anchor in the sector was refused and the themes built almost no
    # neighborhoods at all (measured: seeds 3, 11, 19, 27 built zero). A place may
    # stand in working country; what it may not do is stand IN it, and that is what
    # the footprint test in `place_building` decides, cell by cell, later.
    budget = max(3, int(cells * 0.12))
    for j in range(j0, j1 + 1):
        row_p = plan.place[j] if plan.place else None
        for i in range(i0, i1 + 1):
            if (row_p is not None and row_p[i]) or plan.built[j][i]:
                hits += 1
                if hits > budget:
                    return False
    for w in plan.water:
        if w.closed:
            # A closed body is kept off by its own shoreline, not by a radius scaled
            # from its size. Measured on the big-lake blueprints: a lake half 740 px
            # wide demanded an anchor 780 px from the water while the blueprint was
            # simultaneously sited BY the water (against_max 330) - the two rules
            # cannot both hold, so the campground simply stopped existing. Standing IN
            # the water is the thing that must be refused, and `is_wet` says that.
            if _near_path(g, x, y, w.path, 24.0):
                return False
            continue
        # off the CHANNEL, not off a radius scaled from the place's own influence:
        # the old rule put every anchor 165 px from every stream, which is the
        # floodplain, and a sector's rivers thread the whole map. What a blueprint
        # must not do is build IN water, and `is_wet` / the corridor test say that.
        if _near_path(g, x, y, w.path, max(56.0, w.half + 40.0)):
            return False
    return True


def _nearest_road(plan: SitePlan, x: float, y: float
                  ) -> tuple[Road, Point, float, float] | None:
    """The road a place hangs off: nearest point, the tangent there, and how far."""
    best = None
    for r in plan.roads:
        hit = _nearest_on_path(r.path, x, y)
        if best is None or hit[2] < best[3]:
            best = (r, hit[0], hit[1], hit[2])
    return best


def _nearest_water(plan: SitePlan, x: float, y: float) -> tuple[Point, float]:
    best: tuple[Point, float] | None = None
    for w in plan.water:
        for p in w.path[::2]:
            d = math.hypot(p[0] - x, p[1] - y)
            if best is None or d < best[1]:
                best = (p, d)
    return best or ((x, y), 1e9)


def _satisfies(plan: SitePlan, x: float, y: float, ps: PlaceSpec) -> bool:
    if "flat" in ps.needs and plan.relief_at(x, y) > 0.34:
        return False
    if "dry" in ps.needs and plan.is_wet(x, y):
        return False
    if "offroad" in ps.needs and plan.near_road(x, y, ps.offroad):
        return False
    return True


def _choose(plan: SitePlan, claims: list[_Claim], ps: PlaceSpec,
            rng: random.Random) -> _Site | None:
    """Pick an anchor for a place: score candidates, take the best legal one.

    Candidates are sampled and scored, not placed from a formula, because the
    answer depends on everything planned so far - and because a scored choice is
    the same answer every time the same ground is planned, whichever pass asked
    for it.
    """
    g = plan.geom
    best: tuple[float, _Site] | None = None
    if ps.against == "road":
        # see `_site_from_road`: the network IS the siting rule for these
        return _site_from_road(plan, claims, ps, rng)
    for _ in range(ps.tries):
        x = rng.uniform(60.0, g.w - 60.0)
        y = rng.uniform(40.0, g.h - 40.0)
        if not _satisfies(plan, x, y, ps):
            continue
        # `reach` is how much ground a place RESERVES once built; it is not how
        # much empty ground it needs before being sited. Capping the siting radius
        # is what lets a neighborhood find a lane in country that is already
        # farmed: the reservation still applies afterwards.
        if not _free(plan, claims, x, y, min(ps.reach * 0.5, 150.0)):
            continue
        if _shunned(claims, ps, x, y, ps.keep):
            continue
        if ps.road_max:
            hit = _nearest_road(plan, x, y)
            if hit is None or hit[3] > ps.road_max:
                continue
        site = _Site(x, y)
        score = 0.0
        if ps.against == "road":
            hit = _nearest_road(plan, x, y)
            if hit is None or hit[3] > ps.against_max:
                continue
            site.near = hit[1]
            site.tangent = hit[2]
            score -= hit[3]                     # closer to the road is better
        elif ps.against == "water":
            p, d = _nearest_water(plan, x, y)
            if d > ps.against_max:
                continue
            site.near = p
            score -= d
        if best is None or score > best[0]:
            best = (score, site)
    return best[1] if best else None


def _site_from_road(plan: SitePlan, claims: list[_Claim], ps: PlaceSpec,
                    rng: random.Random) -> _Site | None:
    """Site a road-side place by picking a point ON the network, not a point in
    the sector and then asking whether a road is nearby.

    The difference is what makes neighborhoods exist at all. Sampling the map and
    then filtering (flat, dry, off-road, unclaimed, clear of every watercourse, and
    within `against_max` of a road) and THEN requiring the whole lane corridor to be
    free asks for an empty pasture the size of a subdivision, in a sector whose
    ground is already carved up by water corridors, roads and fields. Measured on
    five seeds: four seeds built no neighborhood at all. A lane is a LINEAR thing
    along a road; the corridor test is the decision that matters, so the candidate
    is generated on the road and only that test decides.
    """
    roads = [r for r in plan.roads if len(r.path) > 1]
    if not roads:
        return None
    lens = []
    tot = 0.0
    for r in roads:
        ln = sum(math.hypot(r.path[i + 1][0] - r.path[i][0],
                            r.path[i + 1][1] - r.path[i][1])
                 for i in range(len(r.path) - 1))
        tot += ln
        lens.append(tot)
    if tot < 200.0:
        return None
    for _ in range(ps.tries):
        u = rng.random() * tot
        ri = bisect.bisect_left(lens, u)
        if ri >= len(roads):
            continue
        road = roads[ri]
        span = lens[ri] - (lens[ri - 1] if ri else 0.0)
        frac = (u - (lens[ri - 1] if ri else 0.0)) / span if span else 0.5
        frac = min(0.9, max(0.1, frac))
        (x, y), tang = _along(road.path, frac)
        if any(math.hypot(c.x - x, c.y - y) < c.keep + ps.keep
               for c in claims):
            continue
        site = _Site(x, y)
        site.near = (x, y)
        site.tangent = tang
        return site
    return None


def _shunned(claims: list[_Claim], ps: PlaceSpec, x: float, y: float,
             r: float) -> bool:
    """Would a place of this kind stand too near a kind it keeps away from?"""
    for name, gap in ps.shun:
        for c in claims:
            if c.name == name and math.hypot(c.x - x, c.y - y) < c.keep + gap + r:
                return True
    return False


def _claim(claims: list[_Claim], plan: SitePlan, site: _Site, ps: PlaceSpec,
           name: str) -> None:
    """Reserve a place's ground so the passes after it keep out."""
    claims.append(_Claim(site.x, site.y, ps.keep, name))
    g = plan.geom
    if plan.place is None:
        plan.place = [[False] * g.cols for _ in range(g.rows)]
    r = ps.keep
    j0, j1 = _span(site.y - r, site.y + r, g.rows, g.cell)
    i0, i1 = _span(site.x - r, site.x + r, g.cols, g.cell)
    for j in range(j0, j1 + 1):
        cy = j * g.cell + g.cell / 2
        for i in range(i0, i1 + 1):
            cx = i * g.cell + g.cell / 2
            if math.hypot(cx - site.x, cy - site.y) <= r + CLAIM_PAD:
                plan.place[j][i] = True
