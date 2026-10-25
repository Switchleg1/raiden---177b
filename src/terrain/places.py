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
    _near_building,
    _near_path,
    _nearest_on_path,
    _shore_clear,
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
    #: how much strip ONE instance wants, in screens. Counted this way because the
    #: old "per screen" reading made a 4-screen sector ask for 4-8 woodlands and 4-8
    #: lakes: measured, 6-9 closed water bodies and 1300 trees in one sector, i.e. a
    #: map that is water and forest with nowhere for a lane. A woodland is a landmark
    #: every two or three screens, not a texture on every screen.
    per: tuple[float, float] = (2.0, 3.0)
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
    #: kinds of place this one keeps away from, and by how far beyond their own
    #: ground (bake px). A lake does not belong in a subdivision: the estate is
    #: houses facing streets, and still water inside it read as a park pond at
    #: best and as a flooded estate at worst.
    shun: tuple[tuple[str, float], ...] = ()
    #: if non-zero, a road must be within this many px: a place sited against
    #: something else (a camp against water) is still reached by a road, and
    #: siting it without asking put camps 600 px from any track, which the builder
    #: then refused - every camp in a sector, every time
    road_max: float = 0.0
    #: how far "offroad" is, px from a carriageway: at least the place's own
    #: footprint, or its clearing is laid across the road and refused
    offroad: float = 70.0
    #: who lays first. A neighborhood needs the roadside more than a campground
    #: needs a clearing, so it asks first; sorted (order, name) keeps that
    #: deterministic instead of dependent on dict or theme-tuple order.
    order: int = 1


#: The vocabulary. A theme picks a subset in `SPEC.places`; the blueprints live here.
VOCABULARY: dict[str, PlaceSpec] = {
    "neighborhood": PlaceSpec(
        name="neighborhood", per=(2.0, 3.0), reach=430.0, keep=210.0, order=0,
        against="road",
        against_max=260.0,
        kinds=("house_suburb", "house_suburb_tan", "house_suburb_brown",
               "house_suburb_slate")),
    "highway": PlaceSpec(
        # order -1: a highway forbids more ground than anything else in the
        # vocabulary, so it asks first. Laid after a neighborhood it drove through
        # the houses that were already standing there - the corridor test guards
        # NEW buildings, not old ones - and a building ended up 14 px inside the
        # carriageway.
        # one every twelve-plus screens: a highway is a through-route, and at one
        # per screen three of them criss-crossed a four-screen city and took most of
        # its blocks
        name="highway", per=(12.0, 16.0), reach=240.0, keep=150.0, order=-1,
        needs=("flat", "offroad"),
        kinds=("depot", "container", "pylon")),
    "lake": PlaceSpec(
        name="lake", per=(2.5, 4.0), reach=330.0, keep=210.0,
        needs=("flat", "offroad"),
        kinds=("shed",), shun=(("neighborhood", 520.0), ("downtown", 600.0))),
    "woodland": PlaceSpec(
        # reach 760 and keep 340: a forest has an EDGE, and the edge is what makes
        # it a forest rather than a density setting applied to the whole map
        name="woodland", per=(2.5, 4.0), reach=760.0, keep=340.0, order=2,
        needs=("offroad",), kinds=("deer_stand",),
        shun=(("neighborhood", 700.0), ("downtown", 800.0))),
    "campground": PlaceSpec(
        name="campground", per=(3.0, 4.5), reach=250.0, keep=140.0, order=3,
        needs=("flat", "dry", "offroad"), road_max=ROAD_MAX - 60.0,
        offroad=150.0,
        against="water", against_max=330.0,
        kinds=("tent_orange", "tent_green", "tent_green")),
    "plains": PlaceSpec(
        # laid after the settlements and the woods: open country is what is LEFT
        # open, and claiming it first would push every estate off the flat ground
        name="plains", per=(3.0, 4.5), reach=520.0, keep=380.0, order=4,
        needs=("flat", "dry", "offroad"), offroad=120.0),
    "farmstead": PlaceSpec(
        # against_max 220, not 300: the plan's own rule is that every building is
        # reached by a road (within 260 px), and a farmstead's second range is
        # laid a barn-length further along the yard - at 300 px of slack the barn
        # itself was already out of reach of the lane it served.
        name="farmstead", per=(2.0, 3.0), reach=300.0, keep=150.0, order=2,
        against="road",
        against_max=210.0, kinds=("barn", "house")),
}


@dataclass
class _Claim:
    """A place's claimed ground: an anchor disc it owns outright.

    `keep` is the ground the place OCCUPIES. The old record also carried `reach`, the
    place's radius of influence, and siting tested against that - which for a
    woodland (reach 760 in a 1600 px-wide sector) meant nothing else could be sited
    anywhere near a forest. Influence is a preference about spacing; occupancy is the
    thing another place would contradict, so this carries occupancy."""

    x: float
    y: float
    keep: float = 0.0
    name: str = ""


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


# ---------------------------------------------------------------------------
# helpers the blueprints share
# ---------------------------------------------------------------------------

def _segs_cross(ax: float, ay: float, bx: float, by: float,
                cx: float, cy: float, dx: float, dy: float) -> bool:
    """Do the segments AB and CD cross? An orientation test on both pairs.

    The point tests elsewhere in this module ask whether a road's SAMPLES fall in
    water, which is not the same question as whether the road does: a carriageway
    sails across a lake's outline between two of its own sample points (routed roads
    sample every 30-40 px), so a causeway bisecting a lake slipped past a test that
    only looked at points."""
    def side(px: float, py: float, qx: float, qy: float,
             rx: float, ry: float) -> float:
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)

    return (side(ax, ay, bx, by, cx, cy) * side(ax, ay, bx, by, dx, dy) < 0
            and side(cx, cy, dx, dy, ax, ay) * side(cx, cy, dx, dy, bx, by) < 0)


def _poly_area(poly: list[Point]) -> float:
    """Shoelace area of a polygon, in bake px^2."""
    s = 0.0
    for i in range(len(poly) - 1):
        ax, ay = poly[i]
        bx, by = poly[i + 1]
        s += ax * by - bx * ay
    return abs(s) * 0.5


def add_water(plan: SitePlan, w) -> bool:
    """Put a water body on the ground, and mark the ground it makes wet NOW.

    The orogeny pass rasterised `wet` before any blueprint existed, so water laid
    later was invisible to every later check until this existed: a blueprint lake
    did not make its own shore wet, a lane could be grown through it, a house could
    stand in it, and the fields pass ploughed its middle. A body that would stand in
    another place's reservation or drown a building is refused here, once, rather
    than contradicted downstream.
    """
    if len(w.path) < 3:
        return False
    if w.inside is not None and plan.is_place(w.inside[0], w.inside[1]):
        return False
    for b in plan.buildings:
        if (w.closed and _in_poly(b.x, b.y, w.path)) or _near_path(
                plan.geom, b.x, b.y, w.path, w.half + 14.0):
            return False
    if w.closed:
        # Standing water keeps clear of standing water. Two lakes laid over each
        # other paint as two overlapping circles - a figure of eight with a seam
        # through it - and nothing about real ground makes that shape.
        for o in plan.water:
            if not o.closed:
                continue
            if any(_in_poly(x, y, o.path) for x, y in w.path[::2]) or any(
                    _in_poly(x, y, w.path) for x, y in o.path[::2]):
                return False
            if _near_path(plan.geom, w.inside[0] if w.inside else w.path[0][0],
                          w.inside[1] if w.inside else w.path[0][1], o.path,
                          w.half + 60.0):
                return False
    # A road may CROSS water - that is what a bridge is - but it may not run along
    # it. A big blueprint lake laid beside an existing carriageway puts the road and
    # the water side by side for hundreds of pixels, which is the "road runs with the
    # river" contradiction the plan already forbids for orogeny-laid water. Counting
    # the samples that sit in the corridor tells the two apart: a crossing is one or
    # two, a chase along the shore is many.
    for r in plan.roads:
        along = 0
        for (px, py) in r.path[::2]:
            if _near_path(plan.geom, px, py, w.path, w.half + 34.0):
                along += 1
        if along >= 4:
            return False
    # ...and no road in it at all. A short chord is a bridge over the head of an
    # inlet, which is a real thing roads do over RIVERS - but across a standing body
    # it reads as the causeway bisecting a lake, which is the "roadway across the
    # water" the user objected to. Point tests miss it: a road can sail across the
    # outline between two of its own samples. The segments have to be tested.
    if w.closed:
        for r in plan.roads:
            if any(_in_poly(sx, sy, w.path) for (sx, sy) in r.path):
                return False
            cut = 0
            for (ax, ay), (bx, by) in zip(r.path, r.path[1:],
                                       strict=False):
                for i in range(len(w.path) - 1):
                    if _segs_cross(ax, ay, bx, by,
                                   w.path[i][0], w.path[i][1],
                                   w.path[i + 1][0], w.path[i + 1][1]):
                        cut += 1
                        break
            if cut:
                return False
    # A sector is not all water. Big lakes are the point - a forest lake should be a
    # landmark, not a puddle - but three of them in one sector measured 60% of the
    # ground as wet, and a map that is mostly lake has nowhere for a lane, a field or
    # a house. One body gets an eighth of the sector, all of them together get a
    # fifth.
    if w.closed:
        area = plan.geom.w * plan.geom.h
        mine = _poly_area(w.path)
        if mine > area * 0.12:
            return False
        laid = sum(_poly_area(x.path) for x in plan.water if x.closed)
        if laid + mine > area * 0.20:
            return False
    plan.water.append(w)
    _water_mark_body(plan, w)
    return True


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


def _mark_corridor(plan: SitePlan, path: list[Point], half: float) -> list[tuple[int, int]]:
    """Claim the cells a carriageway covers, and hand back the ones that were newly
    claimed so a caller can put them back.

    This exists so a street can be ASKED the right question. `_build_street` counted
    how many houses fit before the road was laid, then laid the road, which claimed
    its own corridor and made those houses overlap it: a probe that found six fits
    committed one or two, and the sector ended with lanes and a house or two on each
    instead of a street. The probe has to see the street.
    """
    g = plan.geom
    set_cells: list[tuple[int, int]] = []
    for (px, py) in path:
        j0, j1 = _span(py - half, py + half, g.rows, g.cell)
        i0, i1 = _span(px - half, px + half, g.cols, g.cell)
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                cx, cy = i * g.cell + g.cell / 2, j * g.cell + g.cell / 2
                if _near_path(g, cx, cy, path, half) and not plan.built[j][i]:
                    plan.built[j][i] = True
                    set_cells.append((j, i))
    return set_cells


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
    # A blueprint's road consults the water it is drawn next to. `build_campground`'s
    # entry track and `build_lake`'s shed track are placed by offset arithmetic AFTER
    # the water exists, and a track drawn into a lake paints a causeway across it -
    # the "road down the middle of the water" again, through a gate the water rules
    # never saw. A crossing is a short run of wet samples (the bridge pass puts decks
    # on it afterwards); a run through the body is long.
    run = worst = 0
    for (px, py) in path:
        if plan.is_wet(px, py):
            run += 1
            worst = max(worst, run)
        else:
            run = 0
    if worst > 3:
        return None
    # a lane that crosses a channel needs a deck, exactly like the routed roads:
    # this was the "road fords the river" artifact, and a blueprint that adds a
    # road without asking the water about it puts it straight back
    from .siteplan import _add_decks, _bridge_spans
    _add_decks(r, _bridge_spans(plan.geom, path, plan.water))
    plan.roads.append(r)
    # The carriageway is ground something else already needs. The lot behind one
    # house reached across the street next door and sat on it
    # (`fields_do_not_swallow_the_road`: "lot parcel covers the road"), because a
    # road reserved nothing. Marked in `built`, not in `place`: a building may not
    # stand on a road, but a lane must still be able to CROSS another lane - the
    # `place` grid would forbid the T-junctions that make a neighborhood a network
    # instead of a set of dead ends.
    half = width * 0.5 + 6.0
    _mark_corridor(plan, path, half)
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


def _shore(x: float, y: float, rx: float, ry: float, rng: random.Random,
           n: int = 44) -> list[Point]:
    """A natural shoreline: an ellipse whose radius wanders in a few long
    harmonics - bays and points - plus a little short-scale ragging.

    `_ellipse` with ten vertices and per-vertex wobble is a decagon with dents in
    it, and that is what every lake looked like from the air: straight sides and
    corners. A real shore is smooth at the scale you see it and irregular at the
    scale of the whole lake.
    """
    harm = [(2, rng.uniform(0.05, 0.11), rng.uniform(0, math.tau)),
            (3, rng.uniform(0.03, 0.08), rng.uniform(0, math.tau)),
            (5, rng.uniform(0.01, 0.04), rng.uniform(0, math.tau)),
            (9, rng.uniform(0.005, 0.015), rng.uniform(0, math.tau))]
    pts = []
    for i in range(n):
        a = (i / n) * math.tau
        k = 1.0 + sum(amp * math.sin(f * a + ph) for f, amp, ph in harm)
        pts.append((x + math.cos(a) * rx * k, y + math.sin(a) * ry * k))
    pts.append(pts[0])
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
            # the house stands where the lane plus its setback puts it, and that can
            # fall off the end of the ground even when the lane point itself is inside
            hx = px + nx_ * (front + depth * 0.5)
            hy = py + ny_ * (front + depth * 0.5)
            if not (14.0 < hx < plan.geom.w - 14.0) or not (0.0 <= hy < plan.geom.h):
                s += along + AIR
                continue
            out.append({
                "kind": kind, "scale": sc, "angle": ang_face,
                "x": px + nx_ * (front + depth * 0.5),
                "y": py + ny_ * (front + depth * 0.5),
                "px": px, "py": py,
                "w": w, "h": h, "along": along, "depth": depth,
                "nx": nx_, "ny": ny_, "tang": tang, "side": side,
            })
            s += along + AIR + rng.uniform(6.0, 26.0)
    return out


def _near_other_road(plan: SitePlan, x: float, y: float, lane: list[Point]) -> bool:
    """Is this house on (or at the edge of) a road other than its own lane?

    A lane hanging off a highway must not put a front door on the carriageway:
    a neighborhood house once stood 14 px inside a 29 px highway, which a corridor
    test that only ever looked at the lane being built could not see. Asked at
    PROBE time as well as at build time, so what a street is scored on is what
    gets built on it.
    """
    return any(_near_path(plan.geom, x, y, other.path, other.width * 0.5 + 30.0)
               for other in plan.roads if other.path is not lane)


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
        if _near_other_road(plan, hx, hy, lane):
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
                    and not plan.is_wet(tx, ty)
                    and _shore_clear(plan, tx, ty, 0.5)):
                plan.woods.append(Wood(kind="wood",
                                       items=[(tx, ty, rng.uniform(0.34, 0.5))]))
    return built

# ---------------------------------------------------------------------------
# the blueprints
# ---------------------------------------------------------------------------


def _build_street(plan: SitePlan, rng: random.Random, lane: list[Point],
                  kinds: tuple[str, ...], scale: tuple[float, float],
                  front: float, group: str, lots: str | None,
                  road_kind: str, head: bool, fits_min: int = 2,
                  both_sides: bool = True) -> int:
    """One street: pave it if it holds a street, and put houses on both sides.

    `front` (the setback) and `scale` are chosen ONCE for the whole neighborhood,
    not per house. That is what makes a row read as built by one builder rather than
    as a scatter that happens to be nearby: the reference neighbourhoods in the
    screenshots are organised because the frontage line is consistent along a
    street, and every house in a row is roughly the same size.
    """
    cands = _row_candidates(plan, rng, lane, kinds, scale, front)
    # Ask with the street in place. `add_road` claims the carriageway's cells, and a
    # house may not stand on a road - so counting fits before the road existed counted
    # houses the road would later evict. Measured on one estate: six candidates probed
    # as fitting, one or two committed, and the sector shipped lanes with a house or
    # two on them instead of rows.
    CORRIDOR = 13.0 * 0.5 + 6.0
    marked = _mark_corridor(plan, lane, CORRIDOR)
    fits = [c for c in cands
            if not _near_other_road(plan, c["x"], c["y"], lane)
            and place_building(plan, c["kind"], c["x"], c["y"],
                               (c["px"], c["py"]), c["scale"], group,
                               drive=[(c["x"], c["y"]), (c["px"], c["py"])],
                               air=AIR, commit=False) is not None]
    for (j, i) in marked:
        plan.built[j][i] = False        # `add_road` below re-claims them for real
    if len(fits) < fits_min:
        return 0
    # A street has houses on BOTH sides. Three or more on one side and none on the
    # other is a frontage strip along a river or a road the estate happened to
    # brush - the opposite of "houses facing each other across a street". A loop is
    # exempt (its houses face the middle of it, which is why a loop is built).
    if both_sides and len(fits) >= 3 and len({c["side"] for c in fits}) < 2:
        return 0
    sp = add_road(plan, road_kind, lane, 13.0)
    if sp is None:
        return 0
    if head:
        # a cul-de-sac ends in a head the houses turn around: an asphalt disc with
        # a grass island in it, which is also where the neighborhood's trees go
        ex, ey = lane[-1]
        plan.greens.append(Green(x=ex, y=ey, radius=24.0, mat="road_asphalt"))
        plan.greens.append(Green(x=ex, y=ey, radius=9.0, mat="grass_lush"))
    n = _row_place(plan, rng, sp, lane, fits, group, lots)
    if n == 0:
        # The probe asks about each house alone, so two candidates can each fit and
        # not fit together; a street can end up paved with nobody on it. A street to
        # nowhere is the tell of generated ground: take it back out.
        plan.roads.remove(sp)
        if head:
            del plan.greens[-2:]
    return n


def _ring_fit(plan: SitePlan, at: Point, radius: float, rng: random.Random,
              sweep: float = math.tau) -> list[Point]:
    """A loop road: a ring of ground around a centre, kept only where the ground
    allows, and only as one continuous arc.

    The loop is the shape a real subdivision makes - traffic comes back to where it
    started instead of dead-ending into a field - and it is also what makes a
    neighborhood read as designed from the air. A ring that survives in fragments
    would be slop, so the longest unbroken stretch is kept and the rest is dropped.
    """
    g = plan.geom
    cx = at[0] + math.cos(rng.uniform(0, math.tau)) * radius * 0.55
    cy = at[1] + math.sin(rng.uniform(0, math.tau)) * radius * 0.55
    n = 26
    wob = rng.uniform(0.86, 1.14)
    phase = rng.uniform(0, math.tau)
    run: list[Point] = []
    best: list[Point] = []
    for i in range(n + 1):
        a = phase + sweep * i / n
        r = radius * wob * (1.0 + 0.08 * math.sin(3 * a + phase))
        x, y = cx + math.cos(a) * r, cy + math.sin(a) * r * 0.85
        ok = (16.0 < x < g.w - 16.0 and _in_strip(g, y)
              and not plan.is_place(x, y) and not plan.is_wet(x, y)
              and plan.relief_at(x, y) <= 0.55)
        if ok:
            run.append((x, y))
        else:
            if len(run) > len(best):
                best = run
            run = []
    if len(run) > len(best):
        best = run
    return best if len(best) >= 12 else []


def _estate_trees(plan: SitePlan, streets: list[list[Point]], rng: random.Random,
                  budget: int) -> int:
    """A HANDFUL of trees, on the streets, not a wood between the houses.

    The complaint was that the neighborhoods were slop in a field of trees: every
    lot had its own garden tree, every lane was hedged in, and the whole sector
    read as scrub with roofs in it. A real subdivision has street trees and a few
    in the parkland, and the density that belongs in the trees is put in the
    woodland instead, where it is the point.
    """
    made = 0
    spots: list[Point] = []
    for lane in streets:
        # the head of a cul-de-sac, and the middle of a street's outer side
        ex, ey = lane[-1]
        spots.append((ex, ey))
        mid = lane[len(lane) // 2]
        spots.append(mid)
    for (sx, sy) in spots:
        if made >= budget:
            break
        for _ in range(6):
            a = rng.uniform(0, math.tau)
            d = rng.uniform(26.0, 44.0)
            x, y = sx + math.cos(a) * d, sy + math.sin(a) * d
            if not (14.0 < x < plan.geom.w - 14.0) or not _in_strip(plan.geom, y):
                continue
            sc = rng.uniform(0.42, 0.62)
            if plan.is_built(x, y) or plan.is_wet(x, y):
                continue
            if not _shore_clear(plan, x, y, sc):
                continue
            if _near_path(plan.geom, x, y, [p for lane in streets for p in lane],
                          16.0):
                continue
            plan.woods.append(Wood(kind="yard", items=[(x, y, sc)]))
            made += 1
            break
    return made


def build_neighborhood(plan: SitePlan, site: _Site, ps: PlaceSpec,
                       rng: random.Random) -> int:
    """A subdivision: a collector off the road, a loop, culs-de-sac, and houses
    facing the street they stand on.

    The old version was one dead-end lane with houses alternating down it, which is
    a lane with houses, not a neighborhood. A real one (the photographs the user
    supplied) has a HIERARCHY - a collector entering from the main road, a loop that
    brings traffic back, culs-de-sac off both - a consistent setback along each
    street, houses on both sides facing it, a green or pond somewhere in the middle,
    and few trees between the houses because the trees belong in the woodland.
    """
    hit = _nearest_road(plan, site.x, site.y)
    if hit is None:
        return 0
    road, (ax0, ay0), tang0, dist = hit
    group = "neighborhood"
    lots = "grass_lush" if plan.theme != "city" else "concrete_apron"
    # One builder, one estate: a subdivision is a handful of house types in one or
    # two roof colours, not one of every house in the catalogue. Two colours drawn
    # from the vocabulary, alternated down each street.
    pool = list(ps.kinds or ("house",))
    rng.shuffle(pool)
    kinds = tuple(pool[:2]) if len(pool) > 1 else tuple(pool)

    def score_street(lane: list[Point], kinds: tuple[str, ...],
                     scale: tuple[float, float], front: float) -> int:
        """How many houses this lane would hold, without committing to anything.

        The estate used to take the first anchor that cleared a bar. The anchors are
        drawn at random along a road that is already there, so the first one that
        works is usually ground that merely works: a collector that fits two houses
        where one 300 px along the same road fits six. Score the ground, build on the
        best of it."""
        if len(lane) < 4:
            return 0
        marked = _mark_corridor(plan, lane, 13.0 * 0.5 + 6.0)
        try:
            n = 0
            for c in _row_candidates(plan, rng, lane, kinds, scale, front):
                if place_building(plan, c["kind"], c["x"], c["y"],
                                  (c["px"], c["py"]), c["scale"], "score",
                                  air=AIR, commit=False) is not None:
                    n += 1
            return n
        finally:
            for (j, i) in marked:
                plan.built[j][i] = False

    for _ in range(7):
        best: tuple[int, list[Point], float] = (0, [], 0.0)
        for _scan in range(9):
            (ax, ay), tang = _along(road.path, rng.uniform(0.1, 0.9))
            side = 1.0 if rng.random() < 0.5 else -1.0
            front = rng.uniform(24.0, 34.0)
            # a collector is the long street of the estate: 420-700 px held two
            # houses per side at the art's frontage, which is a lane, not the
            # "bunch of houses facing a street" being asked for
            lane = _lane_grow(plan, (ax, ay), tang + side * math.pi / 2,
                              rng.uniform(560.0, 980.0), rng,
                              wind=rng.uniform(0.0, 40.0))
            sc = score_street(lane, kinds,
                              (rng.uniform(0.40, 0.46), rng.uniform(0.49, 0.55)),
                              front)
            if sc > best[0]:
                best = (sc, lane, front)
        _, collector, front = best
        if not collector:
            continue
        # One scale band for the whole estate, and a smaller house than the plan used
        # to place. At scale 0.55 a house is ~120 px across and a 300 px lane holds
        # two of them, so every "street" the estate tried produced one house and was
        # thrown away - measured: 30 street attempts, zero houses, on two seeds. At
        # 0.40-0.50 the row is ~95 px of house and a real street length holds a real
        # row, which is also what the reference photographs show: many similar small
        # houses, not a few big ones.
        scale = (rng.uniform(0.40, 0.46), rng.uniform(0.49, 0.55))
        jx, jy = collector[-1]
        # The loop and the culs-de-sac are grown when they are BUILT, not all up
        # front. Growing them first meant they were routed through ground the
        # collector's houses had already taken: the lots were claimed after the
        # streets were chosen, and a cul-de-sac laid across a neighbour's garden is
        # exactly the slop the user is asking the designer to stop making
        # (`fields_do_not_swallow_the_road` caught a lot parcel sitting on a road).

        def grow_spine(from_streets: list[list[Point]]) -> list[Point]:
            base = from_streets[rng.randrange(len(from_streets))]
            (bx, by), btang = _along(base, rng.uniform(0.3, 0.9))
            for sgn in (1.0, -1.0):
                cul = _lane_grow(plan, (bx, by), btang + sgn * math.pi / 2,
                                 rng.uniform(300.0, 520.0), rng,
                                 wind=rng.uniform(0.0, 30.0))
                if len(cul) >= 5:
                    return cul
            return []

        # Pave the collector first, so its frontage is claimed ground before any
        # other street is routed.
        total = 0
        built: list[list[Point]] = []
        # "spur", not "main": in this plan `main` is the sector's through-route (the
        # road that carries the encounters and the widest carriageway). A
        # subdivision's collector hangs off it, and a house's drive has to reach a
        # lane of the estate it belongs to.
        n = _build_street(plan, rng, collector, kinds, scale, front, group, lots,
                          "spur", head=False, fits_min=3)
        if n < 2:
            continue
        total += n
        built.append(collector)
        loop = _ring_fit(plan, (jx, jy), rng.uniform(380.0, 620.0), rng)
        if len(loop) >= 12:
            loop = [(jx, jy)] + loop
            m = _build_street(plan, rng, loop, kinds, scale, front, group, lots,
                              "spur", head=False, fits_min=3, both_sides=False)
            if m:
                total += m
                built.append(loop)
        for _cul in range(3):
            cul = grow_spine(built)
            if not cul:
                continue
            m = _build_street(plan, rng, cul, kinds, scale, front, group, lots,
                              "spur", head=True)
            if m:
                total += m
                built.append(cul)
        # Five houses is an estate; eight was a gate that mostly rejected the good
        # ground because a loop plus culs-de-sac needs room, and the sectors that
        # could not fit it came out with no neighborhood at all.
        if total >= 4:
            # No pond. Still water inside the loop was a feature of the first estate
            # design, and the user's word on it is the rule: lakes don't belong in a
            # neighbourhood. The middle of a loop is back gardens.
            _estate_trees(plan, built, rng, budget=rng.randint(4, 7))
            return total
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
    # On a strip, always along it: a highway across a strip is a few hundred px of
    # road that starts and ends at the map edge, which is a bridge to nowhere.
    vert = (not g.cyclic) or rng.random() < 0.75
    y0 = max(40.0, site.y - rng.uniform(0.6, 1.3) * g.h * 0.5)
    y1 = min(g.h - 40.0, site.y + rng.uniform(0.6, 1.3) * g.h * 0.5)
    if not g.cyclic:
        # a through-route runs through: from one end of the sector to the other
        y0, y1 = -40.0, g.h + 40.0
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
    # From here the highway EXISTS, so every return counts it. Returning the rest
    # stop's building count instead (0 when the stop did not fit) told `lay_places`
    # nothing had been built, and it laid another highway: four of them criss-
    # crossed one four-screen city.
    if pad is None:
        return 1
    px, py, tang = pad[3], pad[4], pad[2]
    apron = _quad(pad[0], pad[1], 210.0, 150.0, tang)
    if add_parcel(plan, apron, "concrete_apron", "lot") is None:
        return 1
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
    return 1 + built


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


def build_woodland(plan: SitePlan, site: _Site, ps: PlaceSpec,
                   rng: random.Random) -> int:
    """A forest with a lake in it: ground where the trees ARE the point.

    Two things this replaces. The first is the sector-wide scatter: vegetation used
    to be sprinkled over every unclaimed cell, which is what "there tends to be too
    many trees in general" measures - a 4-screen sector was holding 350-530 trees,
    most of them thinnings between houses and along every drain. Forest is not a
    density setting, it is a PLACE with an edge: inside it the ground is mostly
    trees, outside it the ground is fields, lanes and houses with a few trees.
    The second is the lake, which had no reason to be big: a forest lake is a mere
    or a lake, and the water and the trees arrive together because that is how the
    ground works - water collects where the land dips, and the trees keep it in.
    """
    made = 0
    # the water first: the trees are laid around it, not through it
    cls = rng.choices(("mere", "lake"), weights=(4, 6))[0]
    rx = {"mere": rng.uniform(260.0, 430.0),
          "lake": rng.uniform(500.0, 780.0)}[cls]
    ry = rx * rng.uniform(0.58, 0.9)
    for _ in range(6):
        # the forest asks for a big lake and takes what the sector can spare: the
        # water budget in `add_water` refuses a body that would drown too much of the
        # ground, and a woodland around a mere is still a woodland
        poly = _shore(site.x, site.y, rx, ry, rng)
        body = Water(kind="lake", path=poly, half=ry * 0.95, flood=rx * 0.2,
                     closed=True, inside=(site.x, site.y))
        if add_water(plan, body):
            made += 1
            break
        rx *= 0.72
        ry *= 0.72
    if not made:
        return 0
    # the woods: dense, clustered, with glades - and stopped by the shore
    g = plan.geom
    reach = rx * 2.1
    trees = 0
    tries = 0
    while trees < rng.randint(120, 240) and tries < 900:
        tries += 1
        a = rng.uniform(0, math.tau)
        d = rng.uniform(ry * 1.15, reach)
        cx = site.x + math.cos(a) * d
        cy = site.y + math.sin(a) * d * 0.8
        if not (16.0 < cx < g.w - 16.0) or not _in_strip(g, cy):
            continue
        # a glade: gaps are what make a wood read as a wood rather than as texture
        if rng.random() < 0.16:
            continue
        items = []
        for _ in range(rng.randint(5, 11)):
            ba = rng.uniform(0, math.tau)
            br = abs(rng.gauss(0, 52.0))
            x, y = cx + math.cos(ba) * br, cy + math.sin(ba) * br * 0.85
            sc = rng.uniform(0.55, 1.15)
            if not (14.0 < x < g.w - 14.0) or not _in_strip(g, y):
                continue
            if plan.is_wet(x, y) or plan.is_built(x, y) or plan.is_place(x, y):
                continue
            if not _shore_clear(plan, x, y, sc):
                continue
            if plan.relief_at(x, y) > 0.72:
                continue
            if _near_building(plan, x, y, 70.0) or plan.near_road(x, y, 30.0):
                continue
            items.append((x, y, sc))
        if len(items) >= 4:
            plan.woods.append(Wood(kind="wood", items=items))
            trees += len(items)
    # The forest's OWN ground is the shore band, not the whole reach. Reserving the
    # reach claimed a disc wider than the map in a big-lake forest (rx 780 -> a
    # 3200 px ring in a 1600 px-wide sector), and every other blueprint - camp,
    # farmstead, neighborhood - found the sector already taken and built nothing at
    # all. The trees spread to the reach; the reservation is where the water and its
    # shore are, which is the part another pass would actually contradict.
    shore = _ellipse(site.x, site.y, rx * 1.22, ry * 1.22, n=14, wob=0.1, rng=rng)
    _claim_cells(plan, shore)
    return made + trees


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


BUILDERS: dict[str, Callable[[SitePlan, _Site, PlaceSpec, random.Random], int]] = {
    "neighborhood": build_neighborhood,
    "highway": build_highway,
    "lake": build_lake,
    "woodland": build_woodland,
    "campground": build_campground,
    "farmstead": build_farmstead,
    "plains": build_plains,
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
        want = max(1, int(round(plan.geom.screens
                                    / rng.uniform(ps.per[0], ps.per[1]))))
        made = 0
        tries = 0
        while made < want and tries < want * 4:
            # `want` is how many of these the sector SHOULD have, so it is the number
            # of successes, not the number of looks. A neighborhood asked once or
            # twice per sector, and when both anchors happened to fall on ground the
            # footprint rules refuse, the sector shipped with no settlement at all -
            # which is what the sector-level neighborhood test kept catching.
            tries += 1
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
            # a PLACE was made if its builder put anything down. Adding the builder's
            # count of buildings here let one twenty-house estate stand in for the
            # two estates the sector asked for.
            made += 1 if made_here > 0 else 0
        out[name] = made
    return out


__all__ = ["PlaceSpec", "VOCABULARY", "BUILDERS", "lay_places",
           "build_neighborhood", "build_highway", "build_lake",
           "build_campground", "build_farmstead", "build_woodland"]
