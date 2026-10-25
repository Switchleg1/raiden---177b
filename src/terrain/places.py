"""Places: how a landscape is BUILT, as opposed to what it is made of.

``siteplan`` answers where the ground permits a thing. It never had a notion of a
*neighborhood*: a row of houses that shares a lane, faces it, and keeps its own
gardens clear of the next roof. Without that knowledge the planner could only
scatter legal objects, which is what it did - and the result was houses standing on
each other, a barn in the middle of a crop field, and nothing a player could read
as a settled place.

A place is a **blueprint**: the elements it is made of, the order they depend on,
and the ground it claims while it exists.

    neighborhood   a lane off the main road, a cul-de-sac at its end, and houses
                   along it - each facing the lane, with a drive, a lot and air
                   between the roofs
    highway        a straight multi-lane run with shoulders, pylons along one side
                   and a rest stop; nothing is allowed to build in its corridor
    lake           a closed body of water with a shore, an access track and a boat
                   shed, sitting in the low ground it collects in
    campground     a worn clearing with cabins around a fire clearing, entered by a
                   track, tucked against the water or the woods
    farmstead      a barn and a house with a yard between them, at the field edge

Sizes come from the ART (`siteplan.ink_size`), never from a wish: every spacing in
this module is derived from how wide the thing being placed actually is, which is
the rule whose absence produced "houses piled on top of each other randomly".

Deterministic from the plan's seed, and every anchor is chosen from a sorted sample,
so a place is a function of the ground it sits on - not of the order the planner
happened to iterate, and not of which window is painting it.
"""
from __future__ import annotations

import bisect
import math
import random
from collections.abc import Callable
from dataclasses import dataclass

from .siteplan import (
    Field,
    Green,
    Point,
    Road,
    SitePlan,
    Water,
    Wood,
    _along,
    _clip_poly,
    _face,
    _in_poly,
    _in_strip,
    _near_path,
    _nearest_on_path,
    _span,
    _vpath,
    _water_mark_body,
    ink_size,
    place_building,
)

# How much air a place keeps between its own footprints, bake px. Slightly larger
# than the building-to-building margin in `siteplan`: a place should read as a
# pattern of objects, and objects touching each other read as one blob.
AIR = 22.0

# A place's claimed disc also keeps the later passes off its ground: `cover` will
# not grow a tree in a cul-de-sac, `fields` will not enclose a campsite.
CLAIM_PAD = 12.0

# how far a place will go to find a way in, bake px
ROAD_MAX = 430.0


@dataclass(frozen=True)
class PlaceSpec:
    """What a kind of place IS: how many, where it sits, and what it claims."""

    name: str
    #: how many per screen of strip (a 6-screen sector gets 6x these counts)
    per: tuple[int, int] = (1, 1)
    #: the ground it claims around its anchor, bake px. Two places may not overlap
    #: discs, which is what stops a campground standing inside a neighborhood.
    reach: float = 260.0
    #: the ground it actually OCCUPIES - what gets painted into the `place` grid.
    #: Kept separate from `reach` because one number cannot do both jobs: at
    #: reach x 0.62 a neighborhood's reservation is a 534 px disc in a 1460 px-wide
    #: sector, so three of them cover the map end to end, and every lane the next
    #: neighborhood tries crosses someone's reservation and is refused. Measured:
    #: four sites chosen, thirty-six lanes refused, zero houses built.
    keep: float = 150.0
    #: siting rules, all must hold: "flat" (low relief), "dry" (not wet ground),
    #: "offroad" (not on a carriageway)
    needs: tuple[str, ...] = ("flat", "dry", "offroad")
    #: what it leans against, and how far it will walk to find it
    against: str = ""             # "road" | "water" | "wood" | ""
    against_max: float = 420.0
    #: prop kinds it is allowed to build with (theme-free: these are plan kinds)
    kinds: tuple[str, ...] = ()
    #: how many candidate anchors to score before giving up on one
    tries: int = 24
    #: who lays first. A neighborhood needs the roadside more than a campground
    #: needs a clearing, so it asks first; sorted (order, name) keeps that
    #: deterministic instead of dependent on dict or theme-tuple order.
    order: int = 1


#: The vocabulary. A theme picks a subset in `SPEC.places`; the blueprints live here.
VOCABULARY: dict[str, PlaceSpec] = {
    "neighborhood": PlaceSpec(
        name="neighborhood", per=(1, 2), reach=430.0, keep=210.0, order=0,
        against="road",
        against_max=260.0,
        kinds=("house", "house", "house", "cabin")),
    "highway": PlaceSpec(
        # order -1: a highway forbids more ground than anything else in the
        # vocabulary, so it asks first. Laid after a neighborhood it drove through
        # the houses that were already standing there - the corridor test guards
        # NEW buildings, not old ones - and a building ended up 14 px inside the
        # carriageway.
        name="highway", per=(1, 1), reach=240.0, keep=150.0, order=-1,
        needs=("flat", "offroad"),
        kinds=("depot", "container", "pylon")),
    "lake": PlaceSpec(
        name="lake", per=(1, 1), reach=330.0, keep=210.0,
        needs=("flat", "offroad"),
        kinds=("shed",)),
    "campground": PlaceSpec(
        name="campground", per=(1, 1), reach=250.0, keep=140.0, order=3,
        needs=("flat", "dry"),
        against="water", against_max=330.0, kinds=("cabin", "container")),
    "farmstead": PlaceSpec(
        # against_max 220, not 300: the plan's own rule is that every building is
        # reached by a road (within 260 px), and a farmstead's second range is
        # laid a barn-length further along the yard - at 300 px of slack the barn
        # itself was already out of reach of the lane it served.
        name="farmstead", per=(1, 2), reach=300.0, keep=150.0, order=2,
        against="road",
        against_max=210.0, kinds=("barn", "house")),
}


@dataclass
class _Claim:
    """A place's claimed ground: an anchor disc it owns outright."""

    x: float
    y: float
    r: float
    name: str


@dataclass
class _Site:
    """A chosen anchor, plus the thing it was chosen against."""

    x: float
    y: float
    near: Point | None = None
    tangent: float = 0.0


# ---------------------------------------------------------------------------
# siting: where a place may go
# ---------------------------------------------------------------------------

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
        if math.hypot(c.x - x, c.y - y) < c.r + r:
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
    if "offroad" in ps.needs and plan.near_road(x, y, 70.0):
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
        if any(math.hypot(c.x - x, c.y - y) < c.r + ps.keep for c in claims):
            continue
        site = _Site(x, y)
        site.near = (x, y)
        site.tangent = tang
        return site
    return None


def _claim(claims: list[_Claim], plan: SitePlan, site: _Site, ps: PlaceSpec,
           name: str) -> None:
    """Reserve a place's ground so the passes after it keep out."""
    claims.append(_Claim(site.x, site.y, ps.reach, name))
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


# ---------------------------------------------------------------------------
# helpers the blueprints share
# ---------------------------------------------------------------------------

def add_parcel(plan: SitePlan, poly: list[Point], mat: str, kind: str,
               hedge: bool = False) -> Field | None:
    """Register a parcel a place is laying, if it is a parcel at all.

    Two rules every pass already obeys and a blueprint must not skip: the parcel
    is inside the ground being planned, and it does not stand in wet ground. A
    neighborhood lot or a rest-stop apron placed by offset arithmetic breaks both
    without being asked.
    """
    poly = _clip_poly(plan.geom, poly)
    if len(poly) < 3:
        return None
    xs = [q[0] for q in poly]
    ys = [q[1] for q in poly]
    if max(xs) - min(xs) < 24.0 or max(ys) - min(ys) < 24.0:
        return None
    # inside the ground being planned: `_clip_poly` follows y (that is where the
    # wrapping happens) and leaves x alone, so a lot hung off a lane near the edge
    # kept a vertex at x = -41 and the plan shipped it
    if min(xs) < 0.0 or max(xs) > plan.geom.w:
        return None
    if any(plan.is_wet(qx, qy) for qx, qy in poly):
        return None
    # and clear of the carriageways: a parcel that grows over a road hides it,
    # which is what "field swallows the road" measured. A highway's own shoulder
    # starts outside that band, so this does not forbid shoulders - it forbids
    # paving over the carriageway. Corners alone are not enough: a parcel can
    # cover a road between vertices, so the interior is sampled too.
    from .siteplan import _in_poly, _near_path
    x0, y0 = min(xs), min(ys)
    probe = list(poly)
    gx = int((max(xs) - x0) // 40) + 1
    gy = int((max(ys) - y0) // 40) + 1
    probe += [(x0 + (i + 0.5) * 40.0, y0 + (j + 0.5) * 40.0)
              for i in range(gx)
              for j in range(gy)
              if _in_poly(x0 + (i + 0.5) * 40.0, y0 + (j + 0.5) * 40.0, poly)]
    for qx, qy in probe:
        for r in plan.roads:
            lo = min(pt[1] for pt in r.path)
            hi = max(pt[1] for pt in r.path)
            if not (lo - 30.0 <= qy <= hi + 30.0):
                continue
            if _near_path(plan.geom, qx, qy, r.path, r.width * 0.5 + 6.0):
                return None
    f = Field(poly=poly, mat=mat, kind=kind, hedge=hedge)
    plan.fields.append(f)
    return f


def _inside(plan: SitePlan, x: float, y: float, pad: float = 14.0) -> bool:
    """Is a point inside the strip the plan covers?

    A campground's parked block, a lake's dock or a cul-de-sac head placed by
    offset arithmetic can end up outside the ground being designed. Measured: a
    car park at x = -41, which the painter then tried to draw - and a test that
    asks whether every planned point is inside the strip caught it.
    """
    g = plan.geom
    return (pad <= x <= g.w - pad) and _in_strip(g, y)


def _claim_cells(plan: SitePlan, poly: list[Point]) -> None:
    """Reserve the cells a parcel polygon covers (see `SitePlan.place`)."""
    g = plan.geom
    if plan.place is None:
        plan.place = [[False] * g.cols for _ in range(g.rows)]
    xs = [q[0] for q in poly]
    ys = [q[1] for q in poly]
    j0, j1 = _span(min(ys), max(ys), g.rows, g.cell)
    i0, i1 = _span(min(xs), max(xs), g.cols, g.cell)
    for j in range(j0, j1 + 1):
        cy = j * g.cell + g.cell / 2
        for i in range(i0, i1 + 1):
            cx = i * g.cell + g.cell / 2
            if _in_poly(cx, cy, poly):
                plan.place[j][i] = True


def _road_ok(r: Road) -> Road | None:
    """Decline a road that is not a route (see :func:`add_road`)."""
    if len(r.path) < 2:
        return None
    if sum(math.hypot(r.path[i + 1][0] - r.path[i][0],
                      r.path[i + 1][1] - r.path[i][1])
           for i in range(len(r.path) - 1)) < 8.0:
        return None
    return r


def add_road(plan: SitePlan, kind: str, path: list[Point],
             width: float) -> Road | None:
    """Register a road the place is laying, if it is a road at all.

    A route needs two distinct points to be a route. A horizontal highway next to
    the strip's edge has nowhere to run and produced a one-point path, which the
    painter then rejected with "points argument must contain 2 or more points" -
    a crash coming out of the paint workers, in a band, at runtime. The blueprint
    that cannot draw its road should decline, and say so by returning nothing.
    """
    if len(path) < 2:
        return None
    if sum(math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
           for i in range(len(path) - 1)) < 8.0:
        return None
    r = Road(kind=kind, path=path, width=width)
    # a lane that crosses a channel needs a deck, exactly like the routed roads:
    # this was the "road fords the river" artifact, and a blueprint that adds a
    # road without asking the water about it puts it straight back
    from .siteplan import _add_decks, _bridge_spans
    _add_decks(r, _bridge_spans(plan.geom, path, plan.water))
    plan.roads.append(r)
    return r


def _quad(x: float, y: float, w: float, h: float, ang: float = 0.0
          ) -> list[Point]:
    """An axis-aligned-ish rectangle as a parcel polygon."""
    c, s = math.cos(ang), math.sin(ang)
    out = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2),
                   (-w / 2, h / 2)):
        out.append((x + dx * c - dy * s, y + dx * s + dy * c))
    return out


def _ellipse(x: float, y: float, rx: float, ry: float, n: int = 9,
             wob: float = 0.0, rng: random.Random | None = None) -> list[Point]:
    """A closed blob (the last point repeats the first): water and clearings."""
    pts = []
    for i in range(n):
        a = (i / n) * math.tau
        k = 1.0 + (wob * rng.uniform(-1.0, 1.0) if rng and wob else 0.0)
        pts.append((x + math.cos(a) * rx * k, y + math.sin(a) * ry * k))
    pts.append(pts[0])
    return pts


def _lane_from(plan: SitePlan, at: Point, tang: float, side: float,
               length: float, rng: random.Random, wind: float = 0.0) -> list[Point]:
    """A lane leaving a road at `at`, bending gently away from it.

    `wind` adds a sway across the direction of travel, so some lanes are straight
    and some curl: a row of houses on a straight lane and a row on a winding lane
    are both "houses along a road facing it", and only the second kind stops every
    neighborhood in the game looking like the same street."""
    ang = tang + side * math.pi / 2
    pts = [at]
    n = max(3, int(length / 40))
    bend = rng.uniform(-0.5, 0.5)
    for i in range(1, n + 1):
        t = i / n
        a = ang + bend * t
        sway = wind * math.sin(t * math.pi * rng.uniform(0.7, 1.3))
        d = length * t
        nx = (at[0] + math.cos(a) * d + math.cos(a + math.pi / 2) * sway)
        ny = (at[1] + math.sin(a) * d + math.sin(a + math.pi / 2) * sway)
        if not (14.0 < nx < plan.geom.w - 14.0) or not _in_strip(plan.geom, ny):
            # TRIM, do not refuse: nine of thirty-six lane attempts on one seed died
            # because a 780 px lane drawn from a point on the network ran off the end
            # of the sector. A lane that fits in 400 px is still a lane; a lane that
            # leaves the map is nobody's neighborhood.
            break
        pts.append((nx, ny))
    return pts


def _lane_grow(plan: SitePlan, at: Point, ang: float, max_len: float,
               rng: random.Random, wind: float = 0.0) -> list[Point]:
    """Draw a lane by walking off the road until the ground stops.

    The alternative - pick a length, draw it, then reject the whole lane if anything
    in it is unsuitable - is why four of five seeds had no neighborhoods at all: the
    lane was a wish, the sector was already carved up by water corridors and roads,
    and the corridor test said no to thirty-six attempts in a row. A lane is whatever
    buildable ground runs off this point on this road, so it is generated to fit and
    the length is an upper bound, not a demand. 200 px is the floor: shorter than
    that and there is no row of houses to put on it.
    """
    g = plan.geom
    pts = [at]
    bend = rng.uniform(-0.5, 0.5)
    step = 40.0
    n = max(2, int(max_len / step))
    wet_run = 0
    for i in range(1, n + 1):
        t = i / n
        a = ang + bend * t
        d = step * i
        sway = wind * math.sin(t * math.pi * 1.1)
        x = at[0] + math.cos(a) * d + math.cos(a + math.pi / 2) * sway
        y = at[1] + math.sin(a) * d + math.sin(a + math.pi / 2) * sway
        if not (14.0 < x < g.w - 14.0) or not _in_strip(g, y):
            break
        if plan.is_place(x, y) or plan.relief_at(x, y) > 0.55:
            break
        if plan.is_wet(x, y):
            # a lane crosses a stream (the bridge pass gives it decks afterwards);
            # a lane that chases a floodplain is a track through a bog
            wet_run += 1
            if wet_run > 4:
                break
        else:
            wet_run = 0
        pts.append((x, y))
    return pts if len(pts) >= 5 else []


def _corridor_free(plan: SitePlan, path: list[Point], half: float,
                   built_allow: int = 2) -> bool:
    """Is the ground a road or a row of houses needs free of other claims?

    Sampling the corridor (not just the anchor) is the point: a lane can start on
    free ground and run straight through a campground someone else already built,
    and then every house on it is refused - which is what "the neighborhood laid a
    lane and lost every house" looked like.
    """
    g = plan.geom
    arc = sum(math.hypot(path[i + 1][0] - path[i][0],
                         path[i + 1][1] - path[i][1])
              for i in range(len(path) - 1)) or 1.0
    hits = 0
    soft = 0
    wet_run = 0
    wet_tot = 0
    s = 0.0
    steps = 0
    while s <= arc:
        (px, py), tang = _along(path, s / arc)
        steps += 1
        for off in (-half, 0.0, half):
            cx = px + math.cos(tang + math.pi / 2) * off
            cy = py + math.sin(tang + math.pi / 2) * off
            outside = not (12.0 < cx < g.w - 12.0) or not _in_strip(g, cy)
            if outside and off == 0.0:
                return False
            if outside:
                # the house band runs past the edge of the ground: that side simply
                # has no houses there, which is what a lane along a map edge IS
                soft += 1
                continue
            if off == 0.0:
                # The carriageway may climb, and it may CROSS water. Refusing a
                # lane the moment its centre touched wet ground refused 35 of 36
                # attempts on one seed: a sector's drains and streams thread every
                # valley, and a 400-780 px lane crosses one of them almost always.
                # Real lanes cross streams - on a culvert or a bridge - and this
                # planner already puts decks on every road after the places are
                # laid. What a lane may not do is RUN ALONG the wet ground: a
                # crossing is a few samples, a chase along a floodplain is many in
                # a row.
                if plan.is_wet(cx, cy):
                    wet_run += 1
                    wet_tot += 1
                    if wet_run > 5 or wet_tot > max(3, int(steps * 0.30)):
                        return False
                else:
                    wet_run = 0
                if plan.relief_at(cx, cy) > 0.55:
                    return False
                if plan.is_place(cx, cy):
                    return False
                continue
            # The house band is a THIRD of the samples and used to be held to the
            # same absolute rule as the carriageway: one wet spot or one ridge
            # crossing 110 px to the side and the whole lane was refused - measured
            # nine refusals out of nine attempts on four of five seeds, which is
            # why "neighborhoods" looked like single houses here and there. Country
            # that a lane can be built through has ditches and rises in it. A house
            # may not stand in either, and `place_building` decides that per
            # footprint; the corridor only has to say the lane is buildable and the
            # row is not already taken.
            if plan.is_wet(cx, cy) or plan.relief_at(cx, cy) > 0.52:
                soft += 1
                continue
            if plan.is_place(cx, cy):
                return False
            if plan.is_built(cx, cy):
                hits += 1
                if hits > built_allow:
                    return False
        s += 40.0
    # Most of the band still has to be buildable ground. Set to 100% by mistake when
    # the carriageway rule was relaxed, and the result was a lane that could be
    # drawn through a bog and hold not one house - the plan shipped the road and
    # refused every footprint beside it (measured: 432 footprint refusals for wet on
    # one study run, four lanes built, zero houses).
    return soft <= max(2, int(steps * 0.40))



def _row_candidates(plan: SitePlan, rng: random.Random, lane: list[Point],
                    kinds: tuple[str, ...], scale: tuple[float, float],
                    front: float) -> list[dict]:
    """Where the houses on a lane would stand, before any of it is committed.

    Generated separately from the act of building so a lane can be ASKED whether it
    holds a street before it is laid. Laying a road and then failing to place a
    single house beside it is what produced thirty-odd empty lanes in one sector:
    the road got drawn because the ground was walkable, and the houses were refused
    afterwards because the ground beside it was wet or claimed.

    Two rows, one per side of the lane, each walked by arc and stepped by `what this
    house occupies along the lane + AIR` - the one rule that keeps a row from merging
    into one roof (it used to be a fixed arc fraction, which put a centre every
    56-100 px against a 150-220 px house). It used to be ONE walker alternating
    sides, which is why neighborhoods read as "single houses here and there": the
    step was spent whether or not the alternating side produced a house, so a 450 px
    lane against 190 px houses held two steps total.
    """
    arc = sum(math.hypot(lane[i + 1][0] - lane[i][0], lane[i + 1][1] - lane[i][1])
              for i in range(len(lane) - 1))
    out: list[dict] = []
    for side in (1.0, -1.0):
        # the two rows are not required to line up: a house opposite a gap is a
        # street, a house opposite a house is a hedge
        s = rng.uniform(18.0, 70.0)
        while s < arc - 24.0:
            (px, py), tang = _along(lane, s / arc)
            sc = rng.uniform(*scale)
            kind = kinds[len(out) % len(kinds)]
            ang_face = _face(px, py, px + math.cos(tang + math.pi / 2 * side),
                             py + math.sin(tang + math.pi / 2 * side))
            w, h = ink_size(kind, sc, ang_face)
            along = w * abs(math.cos(tang)) + h * abs(math.sin(tang))
            depth = h * abs(math.sin(tang)) + w * abs(math.cos(tang))
            nx_, ny_ = math.cos(tang + math.pi / 2 * side), \
                math.sin(tang + math.pi / 2 * side)
            out.append({
                "kind": kind, "scale": sc, "angle": ang_face,
                "x": px + nx_ * (front + depth * 0.5),
                "y": py + ny_ * (front + depth * 0.5),
                "px": px, "py": py,
                "w": w, "h": h, "along": along, "depth": depth,
                "nx": nx_, "ny": ny_, "tang": tang,
            })
            s += along + AIR + rng.uniform(6.0, 26.0)
    return out


def _row_place(plan: SitePlan, rng: random.Random, sp: Road, lane: list[Point],
               cands: list[dict], group: str, lots: str | None) -> int:
    """Build the row. `place_building` is the only thing that says no here - it owns
    the footprint rules (wet, steep, claimed, off the carriageway), and every refusal
    is that rule rather than an extra filter invented on the spot."""
    built = 0
    for c in cands:
        hx, hy = c["x"], c["y"]
        # clear of every OTHER road: a lane hanging off a highway must not put a
        # front door on the carriageway. Measured: a neighborhood house stood 14 px
        # inside a 29 px highway, which the corridor test could not see because it
        # only ever looked at the lane being built.
        if any(_near_path(plan.geom, hx, hy, other.path,
                         other.width * 0.5 + 30.0)
               for other in plan.roads if other.path is not lane):
            continue
        b = place_building(plan, c["kind"], hx, hy, (c["px"], c["py"]),
                           c["scale"], group,
                           drive=[(hx, hy), (c["px"], c["py"])], air=AIR)
        if b is None:
            continue
        built += 1
        if lots:
            # the lot is the ground BEHIND the house: a hedge row along its front
            # edge is what makes a lane read as owned parcels rather than houses
            # dropped in grass
            lw = max(c["w"], c["h"]) + 46.0
            lot = _clip_poly(plan.geom,
                             _quad(hx + c["nx"] * (c["depth"] * 0.5 + 26.0),
                                   hy + c["ny"] * (c["depth"] * 0.5 + 26.0),
                                   c["along"] + 40.0, lw, c["tang"]))
            # own the lot's ground whether or not the parcel survives its own rules,
            # or the next pass plants a tree in the garden
            _claim_cells(plan, lot)
            if len(lot) >= 3:
                add_parcel(plan, lot, lots, "lot", hedge=True)
            tx = hx + c["nx"] * (c["depth"] * 0.5 + lw * 0.5) + \
                math.cos(c["tang"]) * (c["along"] * 0.5 + 14.0)
            ty = hy + c["ny"] * (c["depth"] * 0.5 + lw * 0.5) + \
                math.sin(c["tang"]) * (c["along"] * 0.5 + 14.0)
            # inside the ground being planned: the tree sits at the far corner of
            # the lot, and a lot whose house is near the strip's edge puts that
            # corner off the map (`a_strip_is_designed_not_stretched` measured one
            # at x = -53). A tree that is not on the map is not on the map.
            if (12.0 < tx < plan.geom.w - 12.0 and _in_strip(plan.geom, ty)
                    and not plan.is_wet(tx, ty)):
                plan.woods.append(Wood(kind="wood",
                                       items=[(tx, ty, rng.uniform(0.34, 0.5))]))
    return built

# ---------------------------------------------------------------------------
# the blueprints
# ---------------------------------------------------------------------------

def build_neighborhood(plan: SitePlan, site: _Site, ps: PlaceSpec,
                       rng: random.Random) -> int:
    """A lane, a cul-de-sac, and houses that face the lane.

    Everything downstream hangs off the lane: the houses are placed along it and
    turned to face it, their drives meet it, their lots sit behind them, and the
    cul-de-sac is where the lane ends. That dependency is the point - a
    neighborhood is not a group of nearby houses, it is a group of houses that
    share a road.
    """
    hit = _nearest_road(plan, site.x, site.y)
    if hit is None:
        return 0
    road, (ax0, ay0), tang0, dist = hit
    # Several lanes are attempted, not one: a lane is a corridor, and whether it
    # fits is a property of the corridor, not of the anchor. One fixed attempt made
    # a neighborhood either work completely or produce a road with no houses.
    for _ in range(9):
        (ax, ay), tang = _along(road.path, rng.uniform(0.1, 0.9))
        side = 1.0 if rng.random() < 0.5 else -1.0
        # 380-780, not 320-560: a row of houses needs the room on BOTH sides of the
        # step, and the old lane was shorter than two houses plus their air
        length = rng.uniform(380.0, 780.0)
        # some lanes curl, some run straight - the user asked for "a winding or
        # straight road with the houses facing the road", and only the first kind
        # keeps every neighborhood in the game from looking like the same street
        wind = rng.uniform(30.0, 90.0) if rng.random() < 0.5 else 0.0
        lane = _lane_grow(plan, (ax, ay), tang + side * math.pi / 2, length,
                          rng, wind=wind)
        if not lane:
            # no buildable ground runs off this point on this road: try another
            continue
        # Ask the lane whether it holds a street BEFORE paving it: generate the
        # row, try every footprint on the ground, and only lay the lane if the
        # street fits. Lay-then-hope is what filled one sector with 32 lanes and no
        # houses beside any of them.
        cands = _row_candidates(plan, rng, lane, ps.kinds or ("house",),
                                (0.5, 0.62), front=rng.uniform(26.0, 40.0))
        fits = [c for c in cands
                if place_building(plan, c["kind"], c["x"], c["y"],
                                  (c["px"], c["py"]), c["scale"], "neighborhood",
                                  drive=[(c["x"], c["y"]), (c["px"], c["py"])],
                                  air=AIR, commit=False) is not None]
        if len(fits) < 3:
            continue
        sp = add_road(plan, "spur", lane, 13.0)
        if sp is None:
            continue
        # the cul-de-sac: a head the houses turn around
        ex, ey = lane[-1]
        plan.greens.append(Green(x=ex, y=ey, radius=26.0, mat="road_asphalt"))
        return _row_place(plan, rng, sp, lane, fits, "neighborhood",
                          "grass_lush" if plan.theme != "city"
                          else "concrete_apron")
    return 0


def build_highway(plan: SitePlan, site: _Site, ps: PlaceSpec,
                  rng: random.Random) -> int:
    """A straight run with shoulders, pylons and a rest stop.

    A highway is defined by what it does NOT allow: a corridor nothing builds in,
    which is the only reason it reads as a highway rather than as another road
    with houses on it.
    """
    g = plan.geom
    # a highway goes the way the ground goes: mostly along the strip's length
    vert = rng.random() < 0.75
    y0 = max(40.0, site.y - rng.uniform(0.6, 1.3) * g.h * 0.5)
    y1 = min(g.h - 40.0, site.y + rng.uniform(0.6, 1.3) * g.h * 0.5)
    if y1 - y0 < 500.0:
        return 0
    terms = [(1, rng.uniform(0.005, 0.02), rng.uniform(0, 6.28))]
    path = _vpath(g, site.x, terms, step=60, y_lo=y0, y_hi=y1) if vert else \
        [(x, site.y + math.sin(x / 900.0) * 60.0)
         for x in range(int(max(40.0, site.x - 700.0)),
                        int(min(g.w - 40.0, site.x + 700.0)), 60)]
    width = rng.uniform(26.0, 34.0)
    hr = Road(kind="highway", path=path, width=width, shoulder=16.0)
    if _road_ok(hr) is None:
        return 0
    from .siteplan import _add_decks, _bridge_spans
    _add_decks(hr, _bridge_spans(plan.geom, path, plan.water))
    plan.roads.append(hr)
    # Shoulders are the road's own (`Road.shoulder`), painted by the road painter:
    # modelling them as parcels produced a highway of ~200 narrow polygons per
    # attempt, and the city rules then read every one of them as a block.
    arc = sum(math.hypot(path[i + 1][0] - path[i][0],
                         path[i + 1][1] - path[i][1])
              for i in range(len(path) - 1)) or 1.0
    # pylons along one side at a fixed pitch: tall thin markers are what let the
    # eye measure a road's speed, and a highway without them is a wide dirt band
    masts: list[tuple[float, float, float]] = []
    s = 90.0
    while s < arc - 90.0:
        (px, py), tang = _along(path, s / arc)
        nx_, ny_ = math.cos(tang - math.pi / 2), math.sin(tang - math.pi / 2)
        mx, my = px + nx_ * (width * 0.5 + 52.0), py + ny_ * (width * 0.5 + 52.0)
        if 12.0 < mx < g.w - 12.0 and not plan.is_wet(mx, my):
            masts.append((mx, my, rng.uniform(0.24, 0.32)))
        s += rng.uniform(210.0, 300.0)
    if len(masts) >= 3:
        plan.woods.append(Wood(kind="pylon_row", items=masts))
    # the rest stop: a depot with containers on an apron, reached by a short spur
    pad = None
    for _ in range(6):
        (px, py), tang = _along(path, rng.uniform(0.25, 0.75))
        side = 1.0 if rng.random() < 0.5 else -1.0
        nx_, ny_ = math.cos(tang + math.pi / 2 * side), \
            math.sin(tang + math.pi / 2 * side)
        cand = (px + nx_ * 92.0, py + ny_ * 92.0)
        if plan.is_wet(cand[0], cand[1]) or plan.relief_at(cand[0], cand[1]) > 0.42:
            continue
        pad = (cand[0], cand[1], tang, px, py)
        break
    if pad is None:
        return 0
    px, py, tang = pad[3], pad[4], pad[2]
    apron = _quad(pad[0], pad[1], 210.0, 150.0, tang)
    if add_parcel(plan, apron, "concrete_apron", "lot") is None:
        return 0
    _claim_cells(plan, apron)
    add_road(plan, "track", [(px, py), (pad[0], pad[1])], 11.0)
    built = 0
    d = place_building(plan, "depot", pad[0] + math.cos(tang) * 40.0,
                       pad[1] + math.sin(tang) * 40.0, (px, py),
                       rng.uniform(0.42, 0.56), "highway", air=AIR)
    if d is not None:
        built += 1
        dw, dh = ink_size("depot", d.scale, d.angle)
        for i in range(rng.randint(2, 3)):
            cx = pad[0] - math.cos(tang) * (dw * 0.5 + 34.0 * (i + 1))
            cy = pad[1] - math.sin(tang) * (dw * 0.5 + 34.0 * (i + 1))
            if place_building(plan, "container", cx, cy, (px, py),
                              rng.uniform(0.16, 0.22), "highway", air=12.0):
                built += 1
    return built


def build_lake(plan: SitePlan, site: _Site, ps: PlaceSpec,
               rng: random.Random) -> int:
    """A closed body of water in the low ground, with a shore and an access track.

    Water in this engine is painted as a stroke along a path, so a lake is a
    CLOSED path stroked wide enough to cover its own interior - which is also what
    makes the shoreline a curve rather than a polygon, and what lets the later
    riparian pass ring it with trees without being told to.
    """
    rx = rng.uniform(70.0, 120.0)
    ry = rx * rng.uniform(0.62, 0.95)
    poly = _ellipse(site.x, site.y, rx, ry, n=10, wob=0.1, rng=rng)
    # A lake is a REGION, not a channel: `closed` and `inside` say so, and the
    # painter fills the polygon and banks it on the outside only. Stroked like a
    # river it came out as a ring of water with a bank line on each side of the ring
    # and glints running down its middle - "lakes appear to be roadways made in a
    # circle because they still have the centre lines inside".
    # A lake may not drown ground a building already stands on. The test is the one
    # `_water_mark_body` will apply afterwards, not a weaker one: inside the outline,
    # or within the bank band around it. A neighbourhood laid before a lake (the order
    # the vocabulary runs in) otherwise ends up with a house whose own ground the
    # later blueprint turns into a shore - which is the plan contradicting itself,
    # and `no_building_on_ground_it_cannot_stand_on` caught it.
    for b in plan.buildings:
        if _in_poly(b.x, b.y, poly) or _near_path(plan.geom, b.x, b.y, poly,
                                                  ry * 0.95 + 14.0):
            return 0
    lake = Water(kind="lake", path=poly, half=ry * 0.95,
                 flood=rx * 0.28, closed=True, inside=(site.x, site.y))
    plan.water.append(lake)
    _water_mark_body(plan, lake)
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
    return built


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
    rx, ry = rng.uniform(74.0, 104.0), rng.uniform(62.0, 88.0)
    clearing = _ellipse(site.x, site.y, rx, ry, n=9, wob=0.08, rng=rng)
    if add_parcel(plan, clearing, "grass_patchy", "pasture") is None:
        return 0
    # the fire clearing in the middle
    plan.greens.append(Green(x=site.x, y=site.y, radius=rng.uniform(11.0, 16.0),
                             mat="earth_cracked"))
    kind = (ps.kinds or ("cabin",))[0]
    # cabins on a ring, spaced by their own ink width, all facing the fire
    ring = rx + 26.0
    size = max(ink_size(kind, 0.3))
    n = max(3, min(6, int(math.tau * ring // (size + AIR))))
    a0 = rng.uniform(0, math.tau)
    built = 0
    for i in range(n):
        a = a0 + (i / n) * math.tau
        # a cabin that does not fit where the ring says moves inward or around;
        # a campground missing two cabins is still a campground, and one puddle
        # used to cost the whole ring
        for rr in (ring, ring - 22.0, ring + 22.0, ring - 40.0):
            cx, cy = site.x + math.cos(a) * rr, site.y + math.sin(a) * rr
            if place_building(plan, kind, cx, cy, (site.x, site.y),
                              rng.uniform(0.26, 0.34), "campground", air=AIR):
                built += 1
                break
    # gear and a parked block by the track head
    hit = _nearest_road(plan, site.x, site.y)
    if hit is not None and hit[3] < 460.0:
        (ax, ay) = hit[1]
        # the track runs from the road to the clearing's edge on that side
        edge = (site.x + math.copysign(rx + 10.0, ax - site.x), site.y)
        add_road(plan, "track", [(ax, ay), edge], 10.0)
        px, py = edge[0] + math.copysign(18.0, ax - site.x), site.y
        if _inside(plan, px, py, 24.0):
            place_building(plan, "container", px, py, (site.x, site.y),
                           rng.uniform(0.15, 0.2), "campground", air=14.0)
    return built


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


BUILDERS: dict[str, Callable[[SitePlan, _Site, PlaceSpec, random.Random], int]] = {
    "neighborhood": build_neighborhood,
    "highway": build_highway,
    "lake": build_lake,
    "campground": build_campground,
    "farmstead": build_farmstead,
}


def lay_places(plan: SitePlan, names: tuple[str, ...],
               rng: random.Random) -> dict[str, int]:
    """Lay the sector's places. Returns what was built, for the log and the tests.

    Order matters and is deliberate: the things that claim the most ground and
    decide the pattern (a highway's corridor, a neighborhood's lane) go first, and
    the small things that lean against them (a campground by the water) come after,
    because they are sited against what the earlier passes left.
    """
    if not names:
        return {}
    claims: list[_Claim] = []
    out: dict[str, int] = {}
    for name in sorted(names, key=lambda n: (VOCABULARY[n].order, n)):
        ps = VOCABULARY.get(name)
        if ps is None:
            raise KeyError(f"no blueprint for place {name!r}; "
                           f"known: {', '.join(sorted(VOCABULARY))}")
        want = rng.randint(ps.per[0], ps.per[1]) * plan.geom.screens
        made = 0
        for _ in range(want):
            site = _choose(plan, claims, ps, rng)
            if site is None:
                continue
            # Claim AFTER building. Claiming first made a place stand inside its
            # own reservation: the blueprint's lane lay within its own disc, the
            # corridor test read that as someone else's ground, and the
            # neighborhood lost every lane it tried. Claims still happen on
            # failure (marked with what was tried) so the next attempt is not the
            # same anchor over and over.
            made_here = BUILDERS[name](plan, site, ps, rng)
            _claim(claims, plan, site, ps, name)
            made += made_here
        out[name] = made
    return out


__all__ = ["PlaceSpec", "VOCABULARY", "BUILDERS", "lay_places",
           "build_neighborhood", "build_highway", "build_lake",
           "build_campground", "build_farmstead"]
