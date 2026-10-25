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
        name="neighborhood", per=(1, 2), reach=430.0, order=0, against="road",
        against_max=260.0,
        kinds=("house", "house", "house", "cabin")),
    "highway": PlaceSpec(
        # order -1: a highway forbids more ground than anything else in the
        # vocabulary, so it asks first. Laid after a neighborhood it drove through
        # the houses that were already standing there - the corridor test guards
        # NEW buildings, not old ones - and a building ended up 14 px inside the
        # carriageway.
        name="highway", per=(1, 1), reach=240.0, order=-1,
        needs=("flat", "offroad"),
        kinds=("depot", "container", "pylon")),
    "lake": PlaceSpec(
        name="lake", per=(1, 1), reach=330.0, needs=("flat", "offroad"),
        kinds=("shed",)),
    "campground": PlaceSpec(
        name="campground", per=(1, 1), reach=250.0, order=3,
        needs=("flat", "dry"),
        against="water", against_max=330.0, kinds=("cabin", "container")),
    "farmstead": PlaceSpec(
        # against_max 220, not 300: the plan's own rule is that every building is
        # reached by a road (within 260 px), and a farmstead's second range is
        # laid a barn-length further along the yard - at 300 px of slack the barn
        # itself was already out of reach of the lane it served.
        name="farmstead", per=(1, 2), reach=300.0, order=2, against="road",
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
    for j in range(j0, j1 + 1):
        row_p = plan.place[j] if plan.place else None
        for i in range(i0, i1 + 1):
            if (row_p is not None and row_p[i]) or plan.built[j][i]:
                hits += 1
                if hits > 3:
                    return False
    for w in plan.water:
        if _near_path(g, x, y, w.path, r * 0.7):
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
    for _ in range(ps.tries):
        x = rng.uniform(60.0, g.w - 60.0)
        y = rng.uniform(40.0, g.h - 40.0)
        if not _satisfies(plan, x, y, ps):
            continue
        if not _free(plan, claims, x, y, ps.reach * 0.55):
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


def _claim(claims: list[_Claim], plan: SitePlan, site: _Site, ps: PlaceSpec,
           name: str) -> None:
    """Reserve a place's ground so the passes after it keep out."""
    claims.append(_Claim(site.x, site.y, ps.reach, name))
    g = plan.geom
    if plan.place is None:
        plan.place = [[False] * g.cols for _ in range(g.rows)]
    r = ps.reach * 0.62
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
               length: float, rng: random.Random) -> list[Point]:
    """A lane leaving a road at `at`, bending gently away from it."""
    ang = tang + side * math.pi / 2
    pts = [at]
    n = max(3, int(length / 50))
    bend = rng.uniform(-0.5, 0.5)
    for i in range(1, n + 1):
        t = i / n
        a = ang + bend * t
        pts.append((at[0] + math.cos(a) * length * t,
                    at[1] + math.sin(a) * length * t))
    return pts


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
    s = 0.0
    while s <= arc:
        (px, py), tang = _along(path, s / arc)
        for off in (-half, 0.0, half):
            cx = px + math.cos(tang + math.pi / 2) * off
            cy = py + math.sin(tang + math.pi / 2) * off
            if not (12.0 < cx < g.w - 12.0) or not _in_strip(g, cy):
                return False
            if plan.is_wet(cx, cy) or plan.relief_at(cx, cy) > 0.42:
                return False
            if plan.is_place(cx, cy):
                return False
            if plan.is_built(cx, cy):
                hits += 1
                if hits > built_allow:
                    return False
        s += 40.0
    return True


def _house_row(plan: SitePlan, rng: random.Random, lane: Road,
               kinds: tuple[str, ...], scale: tuple[float, float],
               front: float, group: str, lots: str | None) -> int:
    """Houses along a lane, stepped by their own widths.

    The step is `what this house occupies along the lane + AIR`, which is the one
    rule that keeps a row from merging into one roof. It used to be a fixed arc
    fraction, which put a centre every 56-100 px against a 150-220 px house.
    """
    built = 0
    side = 1.0
    # walk the lane by arc, not by vertex: its vertices are ~50 px apart, and a
    # house is wider than that
    pts = lane.path
    arc = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
              for i in range(len(pts) - 1))
    s = 30.0
    while s < arc - 30.0:
        (px, py), tang = _along(pts, s / arc)
        kind = kinds[built % len(kinds)]
        sc = rng.uniform(*scale)
        ang_face = _face(px, py, px + math.cos(tang + math.pi / 2 * side),
                         py + math.sin(tang + math.pi / 2 * side))
        w, h = ink_size(kind, sc, ang_face)
        along = w * abs(math.cos(tang)) + h * abs(math.sin(tang))
        depth = h * abs(math.sin(tang)) + w * abs(math.cos(tang))
        nx_, ny_ = math.cos(tang + math.pi / 2 * side), \
            math.sin(tang + math.pi / 2 * side)
        hx = px + nx_ * (front + depth * 0.5)
        hy = py + ny_ * (front + depth * 0.5)
        # clear of every OTHER road: a lane hanging off a highway must not put a
        # front door on the carriageway. Measured: a neighborhood house stood 14 px
        # inside a 29 px highway, which the corridor test could not see because it
        # only ever looks at the lane being built.
        on_road = any(
            _near_path(plan.geom, hx, hy, other.path,
                       other.width * 0.5 + 30.0)
            for other in plan.roads if other is not lane)
        if on_road:
            s += along + AIR
            side = -side
            continue
        b = place_building(plan, kind, hx, hy, (px, py), sc, group,
                           drive=[(hx, hy), (px, py)], air=AIR)
        if b is not None:
            built += 1
            if lots:
                # the lot is the ground BEHIND the house: a hedge row along its
                # front edge is what makes a lane read as owned parcels rather
                # than houses dropped in grass
                lw = max(w, h) + 46.0
                lot = _clip_poly(plan.geom,
                                 _quad(hx + nx_ * (depth * 0.5 + 26.0),
                                       hy + ny_ * (depth * 0.5 + 26.0),
                                       along + 40.0, lw, tang))
                if len(lot) < 3:
                    # a lot hanging off the end of the strip is not a lot
                    continue
                if add_parcel(plan, lot, lots, "lot", hedge=True) is None:
                    continue
                # and the lot is OWNED ground: without this the next pass plants a
                # tree in the garden or the frontage row stands in the back yard
                _claim_cells(plan, lot)
                # one garden tree, in the lot's far corner
                tx = hx + nx_ * (depth * 0.5 + lw * 0.5) + \
                    math.cos(tang) * (along * 0.5 + 14.0)
                ty = hy + ny_ * (depth * 0.5 + lw * 0.5) + \
                    math.sin(tang) * (along * 0.5 + 14.0)
                if not plan.is_wet(tx, ty):
                    plan.woods.append(Wood(kind="wood",
                                           items=[(tx, ty,
                                                   rng.uniform(0.34, 0.5))]))
        s += along + AIR + rng.uniform(10.0, 46.0)
        side = -side
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
    for _ in range(5):
        (ax, ay), tang = _along(road.path, rng.uniform(0.1, 0.9))
        side = 1.0 if rng.random() < 0.5 else -1.0
        length = rng.uniform(320.0, 560.0)
        lane = _lane_from(plan, (ax, ay), tang, side, length, rng)
        # ±110 covers the carriageway AND the house band behind it: a
        # lane that can be drawn but cannot hold a single roof is not a
        # lane, and picking it produced exactly the empty-cul-de-sac
        # results the first version of this blueprint shipped with.
        if not _corridor_free(plan, lane, 110.0):
            continue
        sp = add_road(plan, "spur", lane, 13.0)
        if sp is None:
            continue
        # the cul-de-sac: a head the houses turn around
        ex, ey = lane[-1]
        plan.greens.append(Green(x=ex, y=ey, radius=26.0, mat="road_asphalt"))
        n = _house_row(plan, rng, sp, ps.kinds or ("house",),
                       (0.5, 0.62), front=rng.uniform(26.0, 40.0),
                       group="neighborhood",
                       lots="grass_lush" if plan.theme != "city"
                       else "concrete_apron")
        if n:
            return n
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
    # half >= the lake's minor radius: the stroke then overlaps itself in the
    # middle and the interior is water, not a ring
    plan.water.append(Water(kind="lake", path=poly, half=ry * 0.95,
                            flood=rx * 0.28))
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
