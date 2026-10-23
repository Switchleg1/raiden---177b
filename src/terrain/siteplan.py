"""The site plan: what a sector's ground *is* before anything is painted.

``compose`` used to ask "put 7 rock clusters at uniform random positions". That
is why a sector reads as scattered props instead of a place: nothing in the map
agrees with anything else. A real landscape is *dependency-ordered*: the ridges
decide where the water goes, the water and the ridges decide where the road
threads, the road decides where the houses stand, the flat dry ground the road
left over is what gets enclosed as fields, and the trees follow the water, the
contour and the field edges.

This module computes that order and nothing else: no pygame, no pixels, no
drawing. It answers, for a (theme, seed):

* where the ridges run and what shape they are (see ``SHAPES``),
* where water drains, and where it is crossed by a bridge,
* the road network, routed along the ground it can actually drive on,
* houses with frontage, setbacks, driveways and yards, a hamlet green where the
  road meets the bridge, farmyards at the edge of the fields,
* field parcels with hedgerows, and woods / treelines / scree fans that sit
  where vegetation and debris would actually sit.

Everything is deterministic from ``(seed, theme)`` - the same seeded-replay
promise the gameplay makes, applied to art. Geometry lives in the bake space of
:mod:`terrain.tilekit` (1600x1120), and every path is **y-periodic by
construction**: the sines that bend them use integer frequencies over the CH
period, so the map wraps at the seam without a cut.

The painter that turns a plan into pixels is :mod:`terrain.features`.
"""
from __future__ import annotations

import math
import random
from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from .tilekit import CH, CW

# Planning grid: 40 px cells, 40 x 28 over the bake space. Coarse enough that a
# relief query is a lookup and the whole plan costs milliseconds, fine enough
# that "is this spot flat, dry and unbuilt" is a real answer.
CELL = 20
COLS = CW // CELL
ROWS = CH // CELL

# One screen is the unit everything is calibrated in: how far a ridge reaches,
# how wide a meander swings, how many fields a theme wants. A plan may cover
# many screens; these stay fixed and the counts scale with them.
SCREEN_W = CW
SCREEN_H = CH


@dataclass(frozen=True)
class Geom:
    """The ground a site plan is designed for: a bake-space strip w x h.

    The default is one screen, and it is a loop in y: the sine paths close on
    themselves so the map wraps with no cut. A streamed sector plans a much
    longer strip, which is NOT a loop - nothing has to line up with the top of
    it, and that is what lets one river, one road and one range run the length
    of a sector instead of one screen repeating twenty-one times.
    """

    w: int = SCREEN_W
    h: int = SCREEN_H
    cell: int = CELL
    cyclic: bool = True

    @property
    def cols(self) -> int:
        return self.w // self.cell

    @property
    def rows(self) -> int:
        return self.h // self.cell

    @property
    def screens(self) -> int:
        """How many screens tall this is. Densities and path sinuosity scale
        with it, so a long strip is designed rather than one map stretched."""
        return max(1, int(round(self.h / SCREEN_H)))

    def col(self, x: float) -> int:
        return max(0, min(self.cols - 1, int(x // self.cell)))

    def row(self, y: float) -> int:
        yy = y % self.h if self.cyclic else y
        return max(0, min(self.rows - 1, int(yy // self.cell)))

    def shifts(self) -> tuple[float, ...]:
        """y offsets a shape must be tested at: the wrap copies for a looping
        map, nothing extra for a strip that does not loop."""
        if not self.cyclic:
            return (0.0,)
        return (0.0, -float(self.h), float(self.h))


#: the one-screen ground every calibration constant in this module assumes
SCREEN = Geom()

Point = tuple[float, float]


# ---------------------------------------------------------------------------
# plan data
# ---------------------------------------------------------------------------

@dataclass
class Ridge:
    """A ridge system seen from above: a spine, a crest profile along it, and
    flanks whose steepness differs (a hogback is steep on one side)."""

    shape: str
    spine: list[Point]
    crest: list[float]            # relative height 0..1 at each spine point
    width: float                  # flank half-width, px
    height: float                 # overall relief this ridge contributes
    asym: float = 0.0             # 0 = symmetric flanks, 1 = one sheer side
    spurs: list[list[Point]] = field(default_factory=list)
    gaps: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class Water:
    kind: str                     # "river" | "wash" | "channel"
    path: list[Point]
    half: float                   # half width, px
    flood: float                  # floodplain half width, px


@dataclass
class Road:
    kind: str                     # "main" | "spur" | "track"
    path: list[Point]
    width: float
    bridges: list[Point] = field(default_factory=list)


@dataclass
class Building:
    kind: str
    x: float
    y: float
    angle: int                    # facing, degrees (0 = faces up-field)
    scale: float
    group: str = ""               # "hamlet" | "farm" | "frontage" | ...
    drive: list[Point] | None = None
    yard: tuple[float, float, float] | None = None   # x, y, radius


@dataclass
class Field:
    poly: list[Point]
    mat: str
    kind: str                     # "crop" | "paddy" | "orchard" | "pasture" | "lot"
    furrows: list[tuple[Point, Point]] = field(default_factory=list)
    hedge: bool = True


@dataclass
class Wood:
    kind: str    # wood | copse | riparian | treeline | orchard | scree |
    #            outcrop
    items: list[tuple[float, float, float]]   # x, y, scale


@dataclass
class Green:
    """A hamlet core: a plaza the houses stand around, and the lanes into it."""

    x: float
    y: float
    radius: float
    mat: str
    lanes: list[list[Point]] = field(default_factory=list)


@dataclass
class SitePlan:
    theme: str
    seed: int
    ridges: list[Ridge]
    water: list[Water]
    roads: list[Road]
    buildings: list[Building]
    fields: list[Field]
    woods: list[Wood]
    greens: list[Green]
    relief: list[list[float]]         # [row][col], 0..1
    wet: list[list[bool]]
    built: list[list[bool]]
    geom: Geom = SCREEN

    # ------------------------------------------------------------------ asks
    def relief_at(self, x: float, y: float) -> float:
        return self.relief[self.geom.row(y)][self.geom.col(x)]

    def is_wet(self, x: float, y: float) -> bool:
        return self.wet[self.geom.row(y)][self.geom.col(x)]

    def is_built(self, x: float, y: float) -> bool:
        return self.built[self.geom.row(y)][self.geom.col(x)]

    def near_water(self, x: float, y: float, dist: float) -> bool:
        return any(_dist_path(self.geom, x, y, w.path) < dist
                   for w in self.water)

    def near_road(self, x: float, y: float, dist: float) -> bool:
        return any(_dist_path(self.geom, x, y, r.path) < dist
                   for r in self.roads)


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------

def _vpath(g: Geom, x0: float, terms: Iterable[tuple[int, float, float]],
           step: int = 40, y_lo: float | None = None,
           y_hi: float | None = None) -> list[Point]:
    """A vertical path x(y).

    On a wrapping map every sine term uses an INTEGER frequency over the screen,
    so x(0) == x(CH) and the map wraps with no cut. A long strip repeats that
    screen-scale wander once per screen instead of bending once over twenty:
    the meander a player can actually see has screen scale, whichever way the
    ground was designed.
    """
    pts: list[Point] = []
    lo = -step if y_lo is None else y_lo
    hi = g.h + step if y_hi is None else y_hi
    cyc = g.screens
    y = lo
    while y <= hi + step:
        f = y / SCREEN_H
        x = x0 + sum(a * SCREEN_H * math.sin(2.0 * math.pi * (k * cyc) * f + p)
                     for k, a, p in terms)
        pts.append((x, y))
        y += step
    return pts


def _hpath(g: Geom, y0: float, terms: Iterable[tuple[int, float, float]],
           step: int = 40) -> list[Point]:
    """A horizontal path y(x). Not wrapped in x (x is the strip's width), and
    the amplitude is kept small so it never crosses the y seam."""
    pts: list[Point] = []
    x = -step
    while x <= g.w + step:
        f = x / SCREEN_W
        y = y0 + sum(a * SCREEN_W * math.sin(2.0 * math.pi * k * f + p)
                     for k, a, p in terms)
        pts.append((x, y))
        x += step
    return pts


def _seg_dist(px: float, py: float, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln2 = dx * dx + dy * dy
    if ln2 <= 1e-9:
        return math.hypot(px - a[0], py - a[1])
    t = max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / ln2))
    return math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy))


def _dist_path(g: Geom, px: float, py: float, path: list[Point]) -> float:
    """Distance to a polyline; on a wrapping map the seam copies are checked."""
    best = float("inf")
    for shift in g.shifts():
        yy = py - shift
        for i in range(len(path) - 1):
            d = _seg_dist(px, yy, path[i], path[i + 1])
            if d < best:
                best = d
                if best < 1e-6:
                    return 0.0
    return best


def _along(path: list[Point], s: float) -> tuple[Point, float]:
    """Point at fraction ``s`` along a polyline, plus the tangent angle."""
    total = sum(math.hypot(path[i + 1][0] - path[i][0],
                           path[i + 1][1] - path[i][1])
                for i in range(len(path) - 1))
    want = max(0.0, min(1.0, s)) * total
    run = 0.0
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        ln = math.hypot(b[0] - a[0], b[1] - a[1])
        if run + ln >= want or i == len(path) - 2:
            t = 0.0 if ln <= 1e-9 else (want - run) / ln
            return ((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])),
                    math.atan2(b[1] - a[1], b[0] - a[0]))
        run += ln
    return path[-1], 0.0


def _crossings(a: list[Point], b: list[Point]) -> list[Point]:
    """Where two polylines cross (used for bridges)."""
    hits: list[Point] = []
    for i in range(len(a) - 1):
        for j in range(len(b) - 1):
            p, q, r, s = a[i], a[i + 1], b[j], b[j + 1]
            d1x, d1y = q[0] - p[0], q[1] - p[1]
            d2x, d2y = s[0] - r[0], s[1] - r[1]
            den = d1x * d2y - d1y * d2x
            if abs(den) < 1e-9:
                continue
            t = ((r[0] - p[0]) * d2y - (r[1] - p[1]) * d2x) / den
            u = ((r[0] - p[0]) * d1y - (r[1] - p[1]) * d1x) / den
            if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
                hits.append((p[0] + t * d1x, p[1] + t * d1y))
    return hits


# ---------------------------------------------------------------------------
# crest shapes: the "various shapes" of a ridge
# ---------------------------------------------------------------------------

def _crest(shape: str, rng: random.Random) -> tuple[list[float], float]:
    """Crest height along the spine, sampled at N points, plus a plateau bias.

    Each shape is a real ridge cross-section, not a random profile:
    """
    n = 40
    h = [0.0] * n
    if shape == "sawback":           # jagged thrust belt: sharp teeth, uneven
        teeth = rng.randint(3, 6)
        for i in range(n):
            t = (i / n) * teeth
            h[i] = 0.45 + 0.55 * abs(t - math.floor(t) - 0.5) * 2.0
        h = [min(1.0, v * rng.uniform(0.75, 1.2)) for v in h]
    elif shape == "domefield":       # domed uplift: broad rounded swells
        bumps = [(rng.uniform(0.1, 0.9), rng.uniform(0.06, 0.18),
                  rng.uniform(0.5, 1.0)) for _ in range(rng.randint(2, 4))]
        for i in range(n):
            u = i / n
            h[i] = max(a * math.exp(-((u - c) / w) ** 2) for c, w, a in bumps)
    elif shape == "mesa":            # table mountain: long flats, cliff edges
        lo = rng.uniform(0.15, 0.35)
        hi = lo + rng.uniform(0.25, 0.45)
        # the cliff is a cosine shoulder over 16% of the run, not a step: a step
        # in the height field shades as a hard-edged black rectangle, which is
        # how the first canyon renders looked like a rendering bug
        for i in range(n):
            u = i / n
            if u < lo or u > hi:
                h[i] = 0.12
            else:
                e = min(u - lo, hi - u, 0.16)
                h[i] = 0.12 + 0.88 * (0.5 - 0.5 * math.cos(math.pi * (e / 0.16)))
    elif shape == "cone":            # stratovolcano: one narrow tall peak
        c, w = rng.uniform(0.35, 0.65), rng.uniform(0.08, 0.14)
        for i in range(n):
            u = i / n
            h[i] = math.exp(-((u - c) / w) ** 2)
    elif shape == "hogback":         # asymmetric dipping strata: steep scarp,
        c = rng.uniform(0.3, 0.7)    #             gentle dip slope
        for i in range(n):
            u = i / n
            h[i] = (1.0 - abs(u - c) / max(1e-6, c if u < c else 1.0 - c))
            h[i] = max(0.05, min(1.0, h[i]))
    elif shape == "massif":          # eroded massif: lumpy core, radiating arms
        bumps = [(rng.uniform(0.15, 0.85), rng.uniform(0.1, 0.22),
                  rng.uniform(0.55, 1.0)) for _ in range(rng.randint(3, 5))]
        for i in range(n):
            u = i / n
            h[i] = 0.35 * max(a * math.exp(-((u - c) / w) ** 2)
                              for c, w, a in bumps) + 0.45
    else:                            # "ridge" - a single gentle arc
        c, w = 0.5, rng.uniform(0.22, 0.35)
        for i in range(n):
            h[i] = math.exp(-((i / n - c) / w) ** 2)
    # one shared smoothing pass: a crest is continuous rock, never a step
    for _ in range(2):
        h = [h[i] if 0 < i < n - 1 else h[i] * 0.9
             for i in range(n)]
        h = [(h[max(0, i - 1)] + 2 * h[i] + h[min(n - 1, i + 1)]) / 4.0
             for i in range(n)]
    return h, (max(h) or 1.0)


SHAPES = ("sawback", "domefield", "mesa", "cone", "hogback", "massif", "ridge")


# ---------------------------------------------------------------------------
# per-theme site character
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SiteSpec:
    """What a theme's ground is made of, in planning terms."""

    ridge_shapes: tuple[str, ...] = ("massif", "ridge")
    ridge_weight: float = 0.7        # chance a candidate ridge is kept
    relief_gain: float = 1.0         # peak height the theme's ground hits
    ridge_count: tuple[int, int] = (1, 2)
    ridge_prop: str = "rock_cluster"
    water_kinds: tuple[str, ...] = ("river",)
    road: str = "main"               # main | ring | none
    build: tuple[str, ...] = ("house",)
    house_gap: float = 78.0          # min centre-to-centre distance, bake px
    hamlet: bool = True
    field_kinds: tuple[str, ...] = ()
    field_count: tuple[int, int] = (0, 0)
    tree_props: tuple[str, ...] = ("tree_clump",)
    woods: tuple[int, int] = (2, 4)
    treeline: bool = True
    scree: bool = True
    hedge: str = "hedge"


_DEFAULT = SiteSpec()

SPEC: dict[str, SiteSpec] = {
    "countryside": SiteSpec(
        ridge_shapes=("massif", "sawback", "domefield"), ridge_weight=0.9,
        # more than one mass: a single ridge somewhere on the map is why the
        # review said "no strong hills or slopes read" - the ground has to have
        # a high side and a low side across the whole strip
        ridge_count=(2, 3), house_gap=95.0, water_kinds=("river",), road="main",
        build=("house", "barn"), field_kinds=("crop", "pasture", "orchard"),
        field_count=(5, 8), tree_props=("tree_clump", "pine_clump"),
        woods=(3, 5)),
    "farmland": SiteSpec(
        ridge_shapes=("domefield", "massif"), ridge_weight=0.7,
        ridge_count=(1, 1), water_kinds=("channel", "river"), road="main",
        build=("barn", "house"), field_kinds=("crop", "paddy", "pasture"),
        field_count=(8, 12), tree_props=("tree_clump", "pine_clump"),
        woods=(2, 4)),
    "forest": SiteSpec(
        ridge_shapes=("massif", "hogback"), ridge_weight=0.8,
        ridge_count=(1, 2),
        water_kinds=("river",), road="main", build=("hut",),
        field_kinds=("pasture",), field_count=(1, 3),
        tree_props=("pine_clump", "tree_clump"), woods=(7, 11),
        treeline=True),
    "canyon": SiteSpec(
        ridge_shapes=("mesa", "hogback", "sawback"), ridge_weight=0.95,
        ridge_count=(2, 3), water_kinds=("wash",), road="main",
        build=(), field_count=(0, 0), tree_props=("dead_tree",),
        # no treeline: a contour-following row of bare trees along every ridge
        # flank shades into "tangled roots" and hides the canyon wall it was
        # supposed to trace
        woods=(1, 3), scree=True, treeline=False),
    "glacier": SiteSpec(
        ridge_shapes=("massif", "domefield", "cone"), ridge_weight=0.9,
        ridge_count=(2, 3), water_kinds=("channel",), road="main",
        build=("hut",), field_count=(0, 0),
        tree_props=("pine_snow",), woods=(3, 6), scree=True),
    "volcanic": SiteSpec(
        ridge_shapes=("cone", "cone", "sawback", "hogback"), ridge_weight=0.95,
        ridge_count=(2, 3), ridge_prop="basalt_spire", water_kinds=(),
        road="main", build=(), field_count=(0, 0),
        tree_props=("dead_tree",), woods=(1, 3), scree=True),
    "wasteland": SiteSpec(
        ridge_shapes=("hogback", "massif"), ridge_count=(1, 2),
        water_kinds=("wash",), road="main", build=("crate_stack",),
        field_count=(0, 0), tree_props=("dead_tree",), woods=(2, 4),
        scree=True),
    "ruins": SiteSpec(
        ridge_shapes=("massif", "hogback"), ridge_weight=0.5,
        ridge_count=(1, 2), water_kinds=("river",), road="main",
        build=("house",), hamlet=True, field_kinds=("pasture",),
        field_count=(2, 4), tree_props=("tree_clump", "dead_tree"),
        woods=(3, 5)),
    "city": SiteSpec(
        ridge_shapes=("domefield",), ridge_count=(1, 1),
        ridge_weight=0.5, relief_gain=0.45, water_kinds=("river",),
        # no scree, no outcrops: boulders in a village read as three huge rocks
        # dropped onto a street, and nothing in a settlement is loose rock
        road="grid", scree=False,
        build=("house",), hamlet=True,
        field_kinds=("lot", "park", "yard"), field_count=(10, 16),
        tree_props=("tree_clump",), woods=(4, 7), treeline=False),
    "airbase": SiteSpec(
        ridge_shapes=("domefield",), ridge_weight=0.3, ridge_count=(0, 1),
        water_kinds=("wash",), road="main", build=("warehouse_long",),
        field_count=(0, 0), tree_props=("tree_clump",), woods=(1, 2)),
    "industrial": SiteSpec(
        ridge_shapes=("massif",), ridge_weight=0.35, ridge_count=(0, 1),
        water_kinds=("channel",), road="main",
        build=("warehouse_long", "storage_tank"), field_count=(0, 0),
        tree_props=("dead_tree",), woods=(1, 2)),
    "swamp": SiteSpec(
        ridge_shapes=("ridge",), ridge_count=(1, 2), ridge_weight=0.4,
        relief_gain=0.35, water_kinds=("channel", "channel", "river"),
        # a swamp still gets ONE route - a causeway on the only dry ground
        # there is, crossing every channel - because without a road there is no
        # settlement either, and the sector reads as an empty green soup
        road="main", build=("hut_stilt",), hamlet=False, field_count=(0, 0),
        tree_props=("cypress_clump", "dead_tree"), woods=(6, 10),
        treeline=False),
    "ocean": SiteSpec(
        ridge_shapes=(), ridge_count=(0, 0), water_kinds=(), road="none",
        build=(), field_count=(0, 0), tree_props=(), woods=(0, 0),
        treeline=False, scree=False),
}


def _theme_index(theme: str) -> int:
    names = sorted(SPEC)
    try:
        return names.index(theme)
    except ValueError:
        return len(names)


def _rng(theme: str, seed: int) -> random.Random:
    """Deterministic per (seed, theme) - no ``hash()``, which salted per run."""
    return random.Random((seed * 1_000_003 + _theme_index(theme) * 7919)
                         & 0x7FFFFFFF)


# ---------------------------------------------------------------------------
# passes, in the order a landscape actually forms
# ---------------------------------------------------------------------------

def _orogeny(g: Geom, spec: SiteSpec,
             rng: random.Random) -> tuple[list[Ridge], list[list[float]]]:
    relief = [[0.0] * g.cols for _ in range(g.rows)]
    ridges: list[Ridge] = []
    lo, hi = spec.ridge_count
    want = rng.randint(lo, hi) if spec.ridge_shapes else 0
    attempts = 0
    while len(ridges) < want and attempts < want * 4 + 3:
        attempts += 1
        shape = rng.choice(spec.ridge_shapes)
        # A ridge runs the long way down the map: the camera scrolls in y, so a
        # ridge parallel to the scroll reads as a range the player keeps
        # travelling along. 30 % of them run across instead, which is what
        # gives a sector a wall of hills ahead.
        across = rng.random() < 0.3
        # A range is one landform, so most further ridges BRANCH off the first
        # instead of standing up as another full-height wall somewhere else.
        # Independent trunks were the canyon's "separate, overlapping shapes -
        # their crests, faces and bases don't connect".
        branch = bool(ridges) and rng.random() < 0.72
        if branch:
            parent = ridges[rng.randrange(len(ridges))]
            (ax, ay), tang = _along(parent.spine, rng.uniform(0.25, 0.95))
            side = 1.0 if rng.random() < 0.5 else -1.0
            ang = tang + side * rng.uniform(0.5, 1.15)
            reach = rng.uniform(0.22, 0.5) * (SCREEN_W if across
                                             else SCREEN_H)
            steps = 16
            spine = []
            for i in range(steps + 1):
                t = i / steps
                wob = math.sin(t * math.pi * rng.uniform(1.0, 2.2)) * 26.0
                spine.append((ax + math.cos(ang) * reach * t + wob,
                              ay + math.sin(ang) * reach * t + wob * 0.5))
            # an arm is thickest where it leaves the trunk and dies outwards,
            # which is also what makes the eye read it as belonging to it
            n = len(spine)
            crest = [max(0.0, 1.0 - (i / (n - 1)) * rng.uniform(0.9, 1.3))
                     for i in range(n)]
            peak = max(crest) or 1.0
            crest = [v / peak for v in crest]
            width = rng.uniform(90.0, 180.0)
            height = rng.uniform(0.5, 0.85) * spec.ridge_weight
            asym = rng.uniform(0.0, 0.5) if shape in ("hogback", "mesa") else 0.0
        else:
            crest, peak = _crest(shape, rng)
            crest = [v / peak for v in crest]      # the shape peaks at 1.0
            width = rng.uniform(120.0, 260.0)
            height = rng.uniform(0.55, 1.0) * spec.ridge_weight
            asym = rng.uniform(0.0, 0.75) if shape in ("hogback", "mesa") else 0.0
            if across:
                y0 = rng.uniform(0.15, 0.85) * g.h
                terms = [(1, rng.uniform(0.01, 0.05), rng.uniform(0, 6.28))]
                if rng.random() < 0.5:
                    terms.append((2, rng.uniform(0.005, 0.02),
                                  rng.uniform(0, 6.28)))
                spine = _hpath(g, y0, terms, step=40)
            else:
                x0 = rng.uniform(0.12, 0.88) * g.w
                terms = [(1, rng.uniform(0.03, 0.12), rng.uniform(0, 6.28))]
                if rng.random() < 0.6:
                    terms.append((2, rng.uniform(0.01, 0.05),
                                  rng.uniform(0, 6.28)))
                if g.cyclic:
                    spine = _vpath(g, x0, terms, step=40)
                else:
                    # A trunk holds one or two screens of a long strip, not the
                    # whole thing: the range the player flies along changes over
                    # a sector, the way the ground does on a real campaign.
                    span = rng.uniform(0.8, 1.9) * SCREEN_H
                    ys = rng.uniform(-0.15 * SCREEN_H,
                                     max(0.0, g.h - span))
                    spine = _vpath(g, x0, terms, step=40,
                                   y_lo=ys, y_hi=ys + span)
            spine = [(max(-80.0, min(g.w + 80.0, x)), y) for x, y in spine]
        spine = [(max(-120.0, min(g.w + 120.0, x)),
                  max(-120.0, min(g.h + 120.0, y))) for x, y in spine]
        ridge = Ridge(shape=shape, spine=spine, crest=crest, width=width,
                      height=height, asym=asym)
        # spurs: shorter arms leaving the spine at angles - a ridge system, not
        # a line. Massifs and cones get the most. A branch arm gets almost none:
        # it IS an arm
        arms = {"massif": (3, 6), "cone": (3, 5), "sawback": (1, 3),
                "domefield": (1, 3), "hogback": (1, 2), "mesa": (0, 1),
                "ridge": (1, 2)}[shape]
        if branch:
            arms = (0, 1)
        for _ in range(rng.randint(*arms)):
            s = rng.uniform(0.12, 0.88)
            (bx, by), tang = _along(spine, s)
            side = 1.0 if rng.random() < 0.5 else -1.0
            ang = tang + side * rng.uniform(0.5, 1.2)
            ln = rng.uniform(0.25, 0.6) * width * 2.0
            pts: list[Point] = []
            steps = 8
            for i in range(steps + 1):
                t = i / steps
                wob = math.sin(t * math.pi * rng.uniform(1.0, 2.0)) * 18.0
                pts.append((bx + math.cos(ang) * ln * t + wob,
                            by + math.sin(ang) * ln * t + wob * 0.4))
            ridge.spurs.append(pts)
            _carve_relief(g, relief, pts, height * rng.uniform(0.45, 0.75),
                          width * rng.uniform(0.35, 0.6), asym, taper=0.55)
        ridges.append(ridge)
        _carve_relief(g, relief, spine, height, width, asym, crest=crest)
    return ridges, relief


def _carve_relief(g: Geom, relief: list[list[float]], path: list[Point],
                  height: float, width: float, asym: float,
                  crest: list[float] | None = None,
                  taper: float = 0.0) -> None:
    """Raise the relief field around a spine. The flanks differ: an asymmetric
    ridge has a scarp on one side and a dip slope on the other.

    ``crest`` is the ridge's shape profile sampled along its length: it is the
    whole reason a mesa, a cone and a sawback look different, so the height
    stamped at a point is ``height * crest`` at that point, not a constant.

    Stamped outward from the path rather than queried cell-by-cell across the
    grid - the same shape, at a fraction of the cost, because a ridge only
    touches the cells it can reach."""
    reach = int(width * 1.2 / CELL) + 1
    n_seg = max(1, len(path) - 1)
    for k in range(len(path) - 1):
        (ax, ay), (bx, by) = path[k], path[k + 1]
        dx, dy = bx - ax, by - ay
        ln = math.hypot(dx, dy)
        if ln <= 1e-9:
            continue
        nx, ny = -dy / ln, dx / ln          # unit normal: the flank direction
        frac = (k + 0.5) / n_seg
        h = height
        if crest:
            idx = min(len(crest) - 1, int(frac * len(crest)))
            h = height * crest[idx]
        if taper:
            h *= 1.0 - taper * frac
        if h <= 0.001:
            continue
        steps = max(1, int(ln / (CELL * 0.5)))
        for m in range(steps + 1):
            t = m / steps
            px, py = ax + dx * t, ay + dy * t
            for shift in g.shifts():
                py_s = py + shift
                if not -CELL <= py_s <= g.h + CELL:
                    continue
                j0 = max(0, g.row(py_s) - reach)
                j1 = min(g.rows - 1, g.row(py_s) + reach)
                i0 = max(0, g.col(px) - reach)
                i1 = min(g.cols - 1, g.col(px) + reach)
                for j in range(j0, j1 + 1):
                    cy = j * CELL + CELL / 2
                    for i in range(i0, i1 + 1):
                        cx = i * CELL + CELL / 2
                        side = (cx - px) * nx + (cy - py_s) * ny
                        w = width if side >= 0 else width * (1.0 - 0.55 * asym)
                        d = math.hypot(cx - px, cy - py_s)
                        if d > w:
                            continue
                        u = 1.0 - d / max(1.0, w)
                        val = h * u * u * (3.0 - 2.0 * u)
                        if val > relief[j][i]:
                            relief[j][i] = min(1.0, val)


def _drainage(g: Geom, spec: SiteSpec, relief: list[list[float]],
              rng: random.Random) -> list[Water]:
    """Water goes where the ground falls away. Candidates are scored on how
    much ridge they would have to cut through, so the river is in the valley it
    belongs to rather than across a mountain."""
    if not spec.water_kinds:
        return []
    kinds = list(spec.water_kinds)
    out: list[Water] = []
    # one body per kind fills a screen; a strip needs drainage along its whole
    # length, or twenty screens of level have one brook in them
    want = 1 if g.cyclic else max(1, round(g.screens * 0.7))
    for kind in kinds:
        for _ in range(want):
            best: Water | None = None
            best_score = float("inf")
            for _ in range(16):
                vertical = rng.random() < (0.4 if kind == "wash" else 0.7)
                amp_a = (0.02, 0.06) if kind == "wash" else (0.04, 0.14)
                amp_b = (0.0, 0.02) if kind == "wash" else (0.01, 0.05)
                if vertical:
                    path = _vpath(
                        g, rng.uniform(0.1, 0.9) * g.w,
                        [(1, rng.uniform(*amp_a), rng.uniform(0, 6.28)),
                         (2, rng.uniform(*amp_b), rng.uniform(0, 6.28))],
                        step=32)
                else:
                    path = _hpath(g, rng.uniform(0.15, 0.85) * g.h,
                                  [(1, rng.uniform(0.02, 0.05),
                                    rng.uniform(0, 6.28))], step=32)
                score = (_path_relief(g, relief, path)
                         + 0.6 * _path_max(g, relief, path))
                # channels spread out, they do not stack
                for prev in out:
                    if _paths_close(g, path, prev.path, 130.0):
                        score += 2.0
                if score < best_score:
                    best_score = score
                    # a channel has to read at playfield scale, where these
                    # numbers are halved: a 12 px half-width is a scratch, not a
                    # watercourse
                    half = {"wash": rng.uniform(30.0, 44.0),
                            "arroyo": rng.uniform(26.0, 40.0),
                            "channel": rng.uniform(22.0, 34.0),
                            "fjord": rng.uniform(40.0, 70.0),
                            }.get(kind, rng.uniform(30.0, 46.0))
                    best = Water(kind=kind, path=path, half=half,
                                 flood=rng.uniform(60.0, 130.0))
            if best is not None:
                out.append(best)
    # carve the valley: a river lowers the ground it runs in, and everything
    # beside it reads as its floodplain
    for w in out:
        # a river cuts; a dry wash only sweeps sand off the surface. Carving a
        # wash as deep as a river leaves a hollow that shades into "a brown
        # stain", which is what the canyon review kept calling an unexplained pit
        depth = 0.35 if w.kind in ("wash", "arroyo") else 0.85
        # bound the cell scan to the corridor the channel can actually reach:
        # on a twenty-screen strip an unbounded scan is 20x the work for cells
        # that are nowhere near the water
        lo_j, hi_j, lo_i, hi_i = _cell_box(g, w.path, w.flood)
        for j in range(lo_j, hi_j + 1):
            cy = j * CELL + CELL / 2
            for i in range(lo_i, hi_i + 1):
                cx = i * CELL + CELL / 2
                d = _dist_path(g, cx, cy, w.path)
                if d < w.flood:
                    t = 1.0 - d / w.flood
                    relief[j][i] = max(0.0, relief[j][i] - depth * t * t)
    return out


def _cell_box(g: Geom, path: list[Point], pad: float) -> tuple[int, int, int, int]:
    """The planning cells a path plus `pad` can touch, as (row0, row1, col0,
    col1) inclusive.

    Clamped by RAW index: the row helper wraps y on a cyclic map (that is what
    makes a shape crossing the seam stitch), and a box computed through it can
    come out inverted - which silently skips the checks the box was there to
    keep cheap.
    """
    xs = [p[0] for p in path]
    ys = [p[1] for p in path]
    r0, r1 = _span(min(ys) - pad, max(ys) + pad, g.rows, g.cell)
    c0, c1 = _span(min(xs) - pad, max(xs) + pad, g.cols, g.cell)
    return r0, r1, c0, c1


def _span(lo: float, hi: float, count: int, cell: int) -> tuple[int, int]:
    return (max(0, int(math.floor(lo / cell))),
            min(count - 1, int(math.floor(hi / cell))))


def _decks(run: list[Point]) -> list[Point]:
    """Decks along a wet run: a short one is a crossing (one deck), a long one
    is a causeway - a road running along a flooded edge needs decks close enough
    that no stretch of it stands over water unsupported."""
    if not run:
        return []
    arc = sum(math.hypot(run[i + 1][0] - run[i][0], run[i + 1][1] - run[i][1])
              for i in range(len(run) - 1))
    n = max(1, int(arc / 110.0) + 1)
    return [run[int((k + 0.5) / n * len(run))] for k in range(n)]


def _bridge_spans(g: Geom, path: list[Point],
                water: list[Water]) -> list[Point]:
    """Where a route needs a deck.

    ``_crossings`` only finds a route that passes clean through a channel. A spur
    that runs *to* the water, or a road that grazes a wide channel without ever
    reaching the far bank, gets nothing from it - and then the carriageway is
    painted through the channel with no bridge, which is the "road fords the
    river" artefact. So: any contiguous run of the route standing inside the
    channel band earns one deck at its middle.
    """
    out: list[Point] = []
    for w in water:
        run: list[Point] = []
        for pt in path:
            if _dist_path(g, pt[0], pt[1], w.path) < w.half + 14.0:
                run.append(pt)
            elif run:
                out.extend(_decks(run))
                run = []
        out.extend(_decks(run))
    return out


def _paths_close(g: Geom, a: list[Point], b: list[Point], dist: float) -> bool:
    for pt in a[::2]:
        if _dist_path(g, pt[0], pt[1], b) < dist:
            return True
    return False


def _path_relief(g: Geom, relief: list[list[float]], path: list[Point]) -> float:
    return sum(relief[g.row(y)][g.col(x)] for x, y in path) / max(1, len(path))


def _path_max(g: Geom, relief: list[list[float]], path: list[Point]) -> float:
    return max(relief[g.row(y)][g.col(x)] for x, y in path)


def _circulation(g: Geom, spec: SiteSpec, relief: list[list[float]],
                 water: list[Water], rng: random.Random) -> list[Road]:
    """Route the road: it follows the low ground, crosses water on a bridge,
    and reaches a col rather than fighting a ridge."""
    if spec.road == "none":
        return []
    if spec.road == "grid":
        return _city_grid(g, water, rng)
    best: Road | None = None
    best_score = float("inf")
    for _ in range(22):
        vertical = rng.random() < 0.72
        if vertical:
            path = _vpath(g, rng.uniform(0.12, 0.88) * g.w,
                          [(1, rng.uniform(0.02, 0.1), rng.uniform(0, 6.28)),
                           (2, rng.uniform(0.0, 0.04), rng.uniform(0, 6.28))],
                          step=32)
        else:
            path = _hpath(g, rng.uniform(0.2, 0.8) * g.h,
                          [(1, rng.uniform(0.02, 0.05), rng.uniform(0, 6.28))],
                          step=32)
        score = (3.0 * _path_relief(g, relief, path)
                 + 2.0 * _path_max(g, relief, path))
        crossings = 0
        for w in water:
            crossings += len(_crossings(path, w.path))
        # a route that actually crosses the water is worth a lot - a bridge is
        # the most legible human-made object in a scrolling map - but only the
        # first crossing earns the big bonus; the rest are just fine
        score -= 5.0 * min(1, crossings) + 1.2 * max(0, crossings - 1)
        for w in water:
            # ...but a road that runs *with* the river is the "channel or track?"
            # ambiguity the reviewers kept reporting, and it is what the old
            # cost function produced: low ground is the valley floor, and the
            # valley floor is where the river already lives. Measure the share
            # of the route that hugs the water and make that expensive.
            hug = sum(1 for (x, y) in path
                      if any(math.hypot(x - wx, y - wy) < w.half + 80.0
                             for (wx, wy) in w.path)) / max(1, len(path))
            score += 13.0 * hug
        if score < best_score:
            best_score = score
            # widths are bake-space: the bake space is stretched 2:1 to the
            # playfield, so a 30 px lane here is a 15 px lane on screen. Anything
            # thinner than that stops reading as a road while scrolling.
            best = Road(kind="main", path=path,
                        width=rng.uniform(15.0, 21.0))
    if best is None:
        return []
    for w in water:
        for hit in _crossings(best.path, w.path):
            best.bridges.append(hit)
    for span in _bridge_spans(g, best.path, water):
        if not any(math.hypot(span[0] - bx, span[1] - by) < w0.half + 40.0
                   for w0 in water for bx, by in best.bridges):
            best.bridges.append(span)
    roads = [best]
    # a spur: it leaves the main road and goes somewhere - the bridge end, a
    # col through the ridge, or out to a farm. A road that goes nowhere is the
    # tell of generated art.
    for _ in range(rng.randint(1, 2)):
        s = rng.uniform(0.15, 0.85) if not best.bridges else _near_hit(best)
        (bx, by), tang = _along(best.path, s)
        ang = tang + (1.0 if rng.random() < 0.5 else -1.0) * rng.uniform(0.5, 1.1)
        ln = rng.uniform(160.0, 340.0)
        pts = [(bx, by)]
        for i in range(1, 7):
            t = i / 6.0
            px = bx + math.cos(ang) * ln * t
            py = by + math.sin(ang) * ln * t
            # a spur that runs off along a bank is the "is that a road or the
            # river?" ambiguity again: it may reach the water, it may not follow
            # it, so the run stops at the near bank
            if any(_dist_path(g, px, py, w.path) < w.half + 26.0
                       for w in water) \
                    and len(pts) > 2:
                break
            pts.append((px, py))
        spur = Road(kind="spur", path=pts, width=rng.uniform(10.0, 13.0))
        for w in water:
            spur.bridges.extend(_crossings(spur.path, w.path))
        spur.bridges.extend(_bridge_spans(g, spur.path, water))
        roads.append(spur)
    return roads


def _near_hit(road: Road) -> float:
    """Fraction along the road closest to its bridge."""
    if not road.bridges:
        return 0.5
    hit = road.bridges[0]
    best, best_s = float("inf"), 0.5
    for i in range(0, 100):
        s = i / 99.0
        (px, py), _ = _along(road.path, s)
        d = math.hypot(px - hit[0], py - hit[1])
        if d < best:
            best, best_s = d, s
    return best_s


def _dist_path_max(path: list[Point], water: list[Water]) -> float:
    return 1.0


def _city_grid(g: Geom, water: list[Water], rng: random.Random) -> list[Road]:
    """City: a street grid, because that is what a city is. Two main streets and
    their cross streets, with a bridge if the grid meets water."""
    roads: list[Road] = []
    # the two main streets have to be far enough apart to enclose a block: two

    # mains 40 px apart make a sliver, and a city is nothing but its blocks
    xs: list[float] = []
    ys: list[float] = []
    for _ in range(40):
        xs = sorted(rng.uniform(0.12, 0.88) * g.w for _ in range(2))
        if xs[1] - xs[0] > 320.0:
            break
    if g.cyclic:
        for _ in range(40):
            ys = sorted(rng.uniform(0.2, 0.8) * g.h for _ in range(2))
            if ys[1] - ys[0] > 280.0:
                break
    else:
        # a city down a long strip is a grid, not two streets: the streets
        # repeat at block spacing over the whole length, so the player keeps
        # flying through the same plan rather than a single giant block
        ys = list(range(int(g.h * 0.12), int(g.h * 0.9), 460))
    for x in xs:
        r = Road("main", _vpath(g, x, [(1, 0.0, 0.0)], step=40), 18.0)
        roads.append(r)
    for y in ys:
        roads.append(Road("main", _hpath(g, float(y), [(1, 0.0, 0.0)],
                                         step=40), 18.0))
    # cross streets fill the block between the mains
    # block spacing is the city's real scale: at 150 px a block is 40 px on the
    # playfield, too small to read as anything, and a city is nothing but blocks.
    # A cross street also has to leave room for the block it borders - one 8 px
    # from a main makes a sliver instead of a yard
    x0, x1 = xs
    for x in range(int(x0) + 240, int(x1) - 180, 240):
        roads.append(Road("track", _vpath(g, float(x), [(1, 0.0, 0.0)],
                                         step=40), 12.0))
    y0, y1 = ys[0], ys[-1]
    step_y = 220 if g.cyclic else 240
    for y in range(int(y0) + step_y, int(y1) - 170, step_y):
        roads.append(Road("track", _hpath(g, float(y), [(1, 0.0, 0.0)],
                                         step=40), 12.0))
    # a street that runs WITH the river for most of its length is the same
    # ambiguity the serpentine routes had; nudge it off the channel instead
    if water:
        for r in roads:
            for _ in range(6):
                wet = sum(1 for x, y in r.path
                          if any(_dist_path(g, x, y, w.path) < w.half + 26.0
                                 for w in water))
                if wet <= max(2, len(r.path) // 8):
                    break
                off = 60.0 * (1.0 if _ % 2 == 0 else -1.0) * (1 + _ // 2)
                if abs(r.path[0][0] - r.path[-1][0]) > g.w * 0.5:
                    r.path = [(x, y + off) for x, y in r.path]
                else:
                    r.path = [(x + off, y) for x, y in r.path]
    for r in roads:
        for w in water:
            r.bridges.extend(_crossings(r.path, w.path))
        r.bridges.extend(_bridge_spans(g, r.path, water))
    return roads


def _settlement(spec: SiteSpec, plan: SitePlan, rng: random.Random) -> None:
    """Houses with frontage: on the road, facing it, set back from it, with a
    drive to it - and a hamlet where the road meets the water."""
    if not spec.build or not plan.roads:
        return
    main = max(plan.roads, key=lambda r: len(r.path))
    # the green: where a bridge lands, or where the spur leaves the main road.
    # That is where a village actually forms.
    if spec.hamlet:
        at = plan.roads[0].bridges[0] if plan.roads[0].bridges else None
        if at is None:
            (_gx, _gy), _ = _along(main.path, rng.uniform(0.3, 0.7))
            at = (_gx, _gy)
        gx, gy = at
        radius = rng.uniform(34.0, 58.0)
        green = Green(x=gx, y=gy, radius=radius,
                      mat="cobble_moss" if plan.theme in ("countryside",
                                                          "ruins",
                                                          "farmland")
                      else "concrete_apron")
        for i in range(rng.randint(4, 6)):
            a = (i / 6.0) * math.tau + rng.uniform(-0.2, 0.2)
            d = radius + rng.uniform(40.0, 66.0)
            hx, hy = gx + math.cos(a) * d, gy + math.sin(a) * d
            if not _buildable(plan, hx, hy, spec.house_gap):
                continue
            plan.buildings.append(Building(
                kind=rng.choice(spec.build), x=hx, y=hy,
                angle=int(math.degrees(math.atan2(gy - hy, gx - hx))) % 360,
                scale=rng.uniform(0.78, 0.95), group="hamlet"))
            green.lanes.append([(hx, hy), (gx + math.cos(a) * radius,
                                           gy + math.sin(a) * radius)])
            _mark_built(plan, hx, hy, 26.0)
        plan.greens.append(green)
    # frontage: the row of houses along the road the player reads as a lane
    # Frontage spacing is a DISTANCE along the road, not a share of it: eight
    # screens of lane must have eight screens of houses, not eight houses
    # smeared over eight screens.
    lane = sum(math.hypot(main.path[i + 1][0] - main.path[i][0],
                          main.path[i + 1][1] - main.path[i][1])
               for i in range(len(main.path) - 1)) or 1.0
    s = 0.04
    gap = rng.uniform(0.05, 0.09) * SCREEN_H / lane
    side = 1.0
    while s < 0.96:
        (bx, by), tang = _along(main.path, s)
        setback = rng.uniform(40.0, 70.0)
        nx = bx + math.cos(tang + math.pi / 2 * side) * setback
        ny = by + math.sin(tang + math.pi / 2 * side) * setback
        side = -side
        s += gap * rng.uniform(0.7, 1.4)
        if not _buildable(plan, nx, ny, spec.house_gap):
            continue
        kind = rng.choice(spec.build)
        plan.buildings.append(Building(
            kind=kind, x=nx, y=ny,
            angle=int(math.degrees(tang - math.pi / 2 * side)) % 360,
            scale=rng.uniform(0.62, 0.86), group="frontage",
            drive=[(nx, ny), (bx, by)],
            yard=(nx + math.cos(tang + math.pi / 2 * side) * 26.0,
                  ny + math.sin(tang + math.pi / 2 * side) * 26.0,
                  rng.uniform(14.0, 22.0))))
        _mark_built(plan, nx, ny, 30.0)
    # farmyards: set back off the road, at the edge of the fields
    for _ in range(rng.randint(1, 2) * plan.geom.screens):
        (bx, by), tang = _along(main.path, rng.uniform(0.1, 0.9))
        fx = bx + math.cos(tang + math.pi / 2) * rng.uniform(70.0, 120.0)
        fy = by + math.sin(tang + math.pi / 2) * rng.uniform(70.0, 120.0)
        if not _buildable(plan, fx, fy, spec.house_gap):
            continue
        for i in range(rng.randint(2, 3)):
            hx = fx + rng.uniform(-40.0, 40.0)
            hy = fy + rng.uniform(-30.0, 30.0)
            if not _buildable(plan, hx, hy, spec.house_gap):
                continue
            plan.buildings.append(Building(
                kind="barn" if i == 0 else rng.choice(spec.build),
                x=hx, y=hy, angle=int(math.degrees(tang)) % 360,
                scale=rng.uniform(0.8, 1.0), group="farm",
                drive=[(hx, hy), (bx, by)]))
            _mark_built(plan, hx, hy, 30.0)


def _near_building(plan: SitePlan, x: float, y: float, dist: float) -> bool:
    """Foliage within arm's reach of a house reads as scrub swallowing the
    village, which is exactly what the old maps did."""
    return any(math.hypot(b.x - x, b.y - y) < dist for b in plan.buildings)


def _buildable(plan: SitePlan, x: float, y: float,
               gap: float = 78.0) -> bool:
    if not 20.0 < x < plan.geom.w - 20.0:
        return False
    if plan.relief_at(x, y) > 0.42 or plan.is_wet(x, y) or plan.is_built(x, y):
        return False
    if plan.near_water(x, y, 40.0):
        return False
    for b in plan.buildings:
        if math.hypot(b.x - x, b.y - y) < gap:
            return False
    return True


def _mark_built(plan: SitePlan, x: float, y: float, r: float) -> None:
    g = plan.geom
    j0, j1 = g.row(y - r), g.row(y + r)
    i0, i1 = g.col(x - r), g.col(x + r)
    for j in range(j0, j1 + 1):
        for i in range(i0, i1 + 1):
            plan.built[j][i] = True


def _fields(spec: SiteSpec, plan: SitePlan, rng: random.Random) -> None:
    """Enclose the flat, dry ground the road left over. Fields are parcels with
    hedgerows, which is what makes ground look owned rather than empty."""
    if not spec.field_kinds:
        return
    if spec.road == "grid":
        _city_blocks(spec, plan, rng)
        return
    g = plan.geom
    lo, hi = spec.field_count
    # one screen's worth of parcels per screen of strip: a sector that is
    # twenty screens long cannot be farmed by eight fields
    want = max(1, int(round(rng.randint(lo, hi) * g.screens)))
    tries = 0
    while len(plan.fields) < want and tries < want * 14:
        tries += 1
        cx, cy = rng.uniform(60, g.w - 60), rng.uniform(40, g.h - 40)
        if plan.relief_at(cx, cy) > 0.34 or plan.is_wet(cx, cy):
            continue
        w = rng.uniform(120.0, 260.0)
        h = rng.uniform(90.0, 200.0)
        kind = rng.choice(spec.field_kinds)
        poly = _parcel(cx, cy, w, h, rng)
        if not _parcel_ok(plan, poly):
            continue
        poly = _clip_poly(plan.geom, poly)
        mat = _field_mat(plan.theme, kind)
        furrows = _furrows(poly, w, h, kind, rng)
        plan.fields.append(Field(poly=poly, mat=mat, kind=kind,
                                 furrows=furrows, hedge=kind != "lot"))
        for px, py in poly:
            _mark_built(plan, px, py, 4.0)
        _mark_parcel(plan, poly)


def _city_blocks(spec: SiteSpec, plan: SitePlan, rng: random.Random) -> None:
    """A grid city is read by its BLOCKS, so the blocks are planned from the
    streets instead of scattered as blobs: every pair of adjacent streets
    encloses one parcel - a yard, a lot, a green, a paddock - and the street
    layout becomes visible as the gaps between them. Random parcels on a grid
    produce the opposite, "one continuous cobbled texture with stripes in it".
    """
    # a street that runs top to bottom fixes an x; one that runs across fixes a y
    xs = sorted({round(sum(px for px, _ in r.path) / len(r.path))
                 for r in plan.roads
                 if len(r.path) > 3
                 and abs(r.path[0][1] - r.path[-1][1]) > CH * 0.5})
    ys = sorted({round(sum(py for _, py in r.path) / len(r.path))
                 for r in plan.roads
                 if len(r.path) > 3
                 and abs(r.path[0][0] - r.path[-1][0]) > CW * 0.5})
    xs = [0.0] + xs + [float(CW)]      # the map edge is a block boundary too
    ys = [0.0] + ys + [float(CH)]
    kinds = ("lot", "yard", "park")
    for x0, x1 in zip(xs, xs[1:], strict=False):
        for y0, y1 in zip(ys, ys[1:], strict=False):
            if x1 - x0 < 150 or y1 - y0 < 130:
                continue
            inset = 34.0
            poly = [(x0 + inset, y0 + inset), (x1 - inset, y0 + inset),
                    (x1 - inset, y1 - inset), (x0 + inset, y1 - inset)]
            if any(plan.is_wet(px, py) for px, py in poly):
                continue
            # the river may cut the block: a parcel standing in water is not a
            # parcel, so test the interior, not only the corners
            if any(plan.is_wet(x0 + inset + i * 40.0, y0 + inset + j * 40.0)
                   for i in range(int((x1 - x0) / 40.0))
                   for j in range(int((y1 - y0) / 40.0))):
                continue
            kind = rng.choice(kinds)
            # no furrows in a city: parallel strips inside a paved block read as
            # planking or decking, not as land use
            plan.fields.append(Field(
                poly=_clip_poly(plan.geom, poly),
                mat=_field_mat(plan.theme, kind), kind=kind,
                furrows=[], hedge=False))


def _clip_poly(g: Geom, poly: list[Point]) -> list[Point]:
    """Keep a parcel inside the ground it was designed for.

    Parcels are laid out against routes, and routes deliberately bleed past the
    ends of a strip so they read as continuing. A parcel bleeding with them puts
    half a field past the end of the sector, where it is painted once per chunk
    window and never seen. A wrapping map is different: its ends are the same
    place, so nothing is clipped there."""
    if g.cyclic:
        return poly
    lo, hi = 0.0, float(g.h)
    return [(x, lo if y < lo else (hi if y > hi else y)) for x, y in poly]


def _parcel(cx: float, cy: float, w: float, h: float,
            rng: random.Random) -> list[Point]:
    """A four-sided parcel with jittered corners and bowed edges - hedgerows
    follow old fences, and old fences are not rectangles."""
    pts: list[Point] = []
    corners = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    for dx, dy in corners:
        pts.append((cx + dx + rng.uniform(-18, 18),
                    cy + dy + rng.uniform(-14, 14)))
    out: list[Point] = []
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        out.append(a)
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        nx, ny = -(b[1] - a[1]), (b[0] - a[0])
        ln = math.hypot(nx, ny) or 1.0
        bow = rng.uniform(-0.08, 0.08)
        out.append((mx + nx / ln * ln * bow, my + ny / ln * ln * bow))
    return out


def _in_poly(x: float, y: float, poly: list[Point]) -> bool:
    inside = False
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        if (a[1] > y) != (b[1] > y):
            t = (y - a[1]) / (b[1] - a[1])
            if x < a[0] + t * (b[0] - a[0]):
                inside = not inside
    return inside


def _parcel_ok(plan: SitePlan, poly: list[Point]) -> bool:
    """A parcel has to sit on ground a plough can reach, and must not swallow
    the road, a house or the water."""
    g = plan.geom
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    if min(xs) < 10 or max(xs) > g.w - 10:
        return False
    jr = _span(min(ys) - 4, max(ys) + 4, g.rows, CELL)
    ic = _span(min(xs) - 4, max(xs) + 4, g.cols, CELL)
    for j in range(jr[0], jr[1] + 1):
        for i in range(ic[0], ic[1] + 1):
            cx, cy = i * CELL + CELL / 2, j * CELL + CELL / 2
            if not _in_poly(cx, cy, poly):
                continue
            if plan.relief[j][i] > 0.34 or plan.wet[j][i] or plan.built[j][i]:
                return False
            if plan.near_road(cx, cy, 26.0):
                return False
    return True


def _mark_parcel(plan: SitePlan, poly: list[Point]) -> None:
    g = plan.geom
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    jr = _span(min(ys) - 4, max(ys) + 4, g.rows, CELL)
    ic = _span(min(xs) - 4, max(xs) + 4, g.cols, CELL)
    for j in range(jr[0], jr[1] + 1):
        for i in range(ic[0], ic[1] + 1):
            if _in_poly(i * CELL + CELL / 2, j * CELL + CELL / 2, poly):
                plan.built[j][i] = True      # parcels claim their ground


def _field_mat(theme: str, kind: str) -> str:
    """A crop field is bare tilled earth. Painting a furrow line on grass is how
    the old maps pretended at farmland, and it is why nothing read as owned
    ground."""
    from .theme_table import FIELD_MAT, FIELD_MAT_CITY
    if theme == "city" and kind in FIELD_MAT_CITY:
        return FIELD_MAT_CITY[kind]
    return FIELD_MAT.get(kind, "grass_patchy")


def _furrows(poly: list[Point], w: float, h: float, kind: str,
             rng: random.Random) -> list[tuple[Point, Point]]:
    """Plough rows along the parcel's long axis, or paddy levees."""
    if kind == "pasture":
        return []
    rows: list[tuple[Point, Point]] = []
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    step = rng.uniform(11.0, 17.0) if kind != "paddy" else 26.0
    along_x = (x1 - x0) >= (y1 - y0)
    n = int(((x1 - x0) if along_x else (y1 - y0)) / step)
    for k in range(max(2, n)):
        t = (k + 0.5) / max(1, n)
        if along_x:
            a: Point = (x0 + t * (x1 - x0), y0 + 4)
            b: Point = (x0 + t * (x1 - x0) + rng.uniform(-3, 3), y1 - 4)
        else:
            a = (x0 + 4, y0 + t * (y1 - y0))
            b = (x1 - 4, y0 + t * (y1 - y0) + rng.uniform(-3, 3))
        rows.append((a, b))
    return rows


def _in_strip(g: Geom, y: float) -> bool:
    """Can a thing sit at this y?

    A one-screen plan loops in y, so anything goes and the painter's seam copies
    stitch it. A strip has an end: a tree placed past it is a tree the player
    never sees, painted again and again by every chunk window that overlaps it.
    """
    return True if g.cyclic else 12.0 < y < g.h - 12.0


def _cover(spec: SiteSpec, plan: SitePlan, rng: random.Random) -> None:
    """Vegetation and debris follow the ground: woods on ground nothing else
    claims, a treeline where the hillside turns, trees along the water, scree at
    the ridge foot and outcrops on its crest. Trees come in clusters with gaps,
    because a uniform scatter of foliage is the single loudest tell of generated
    ground."""
    g = plan.geom
    props = spec.tree_props
    if props:
        lo, hi = spec.woods
        for _ in range(rng.randint(lo, hi) * g.screens):
            cx, cy = rng.uniform(40, g.w - 40), rng.uniform(20, g.h - 20)
            if plan.relief_at(cx, cy) > 0.7 or plan.is_wet(cx, cy) \
                    or plan.is_built(cx, cy) or plan.near_road(cx, cy, 34.0):
                continue
            n = rng.randint(3, 7)              # clustered, never uniform
            items = []
            for _ in range(n):
                a = rng.uniform(0, math.tau)
                r = abs(rng.gauss(0, 46.0))
                x, y = cx + math.cos(a) * r, cy + math.sin(a) * r * 0.8
                if 12 < x < g.w - 12 and _in_strip(g, y) \
                        and plan.relief_at(x, y) < 0.72 \
                        and not plan.is_built(x, y) \
                        and not _near_building(plan, x, y, 60.0):
                    items.append((x, y, rng.uniform(0.45, 1.05)))
            if len(items) >= 3:
                plan.woods.append(Wood(kind="wood", items=items))
        # riparian corridor: trees follow the water, with gaps
        for w in plan.water:
            step = 0.0
            for i in range(len(w.path) - 1):
                a, b = w.path[i], w.path[i + 1]
                ln = math.hypot(b[0] - a[0], b[1] - a[1])
                step += ln
                if step > 62.0:
                    step = 0.0
                    if rng.random() < 0.42:      # the corridor is not a wall
                        side = 1.0 if rng.random() < 0.5 else -1.0
                        ang = math.atan2(b[1] - a[1], b[0] - a[0]) + \
                            side * math.pi / 2
                        # a crown over the channel hides the bank, and "its
                        # banks disappear under foliage" was the single most
                        # repeated note: the corridor has to stay a corridor
                        d = w.half + rng.uniform(42.0, 76.0)
                        x = a[0] + math.cos(ang) * d
                        y = a[1] + math.sin(ang) * d
                        if 12 < x < g.w - 12 and _in_strip(g, y) \
                                and not plan.is_built(x, y) \
                                and not _near_building(plan, x, y, 50.0):
                            plan.woods.append(Wood(
                                kind="riparian",
                                items=[(x, y, rng.uniform(0.5, 0.8))]))
        # treeline where the hillside turns: contour-following, so it reads as
        # the top of the trees rather than a random band of them
        if spec.treeline:
            for ridge in plan.ridges:
                items = []
                for i in range(len(ridge.spine) - 1):
                    (ax, ay), (bx, by) = ridge.spine[i], ridge.spine[i + 1]
                    if rng.random() < 0.55:
                        continue
                    ang = math.atan2(by - ay, bx - ax) + math.pi / 2
                    d = ridge.width * rng.uniform(0.55, 0.8)
                    x = ax + math.cos(ang) * d
                    if 12 < x < g.w - 12:
                        y = ay + math.sin(ang) * d
                        if _in_strip(g, y) and not _near_building(plan, x, y,
                                                                 50.0):
                            items.append((x, y, rng.uniform(0.6, 1.0)))
                if len(items) >= 6:
                    plan.woods.append(Wood(kind="treeline", items=items))
        # orchard rows inside one field
        for f in plan.fields:
            if f.kind == "orchard":
                items = []
                for a, b in f.furrows[::2]:
                    n = 3
                    for k in range(n):
                        t = (k + 0.5) / n
                        ox = a[0] + (b[0] - a[0]) * t
                        oy = a[1] + (b[1] - a[1]) * t
                        if _near_building(plan, ox, oy, 46.0):
                            continue     # an orchard is not a hedge on a house
                        items.append((ox, oy, rng.uniform(0.4, 0.55)))
                if items:
                    plan.woods.append(Wood(kind="orchard", items=items))
    # debris: scree fans at the ridge foot, outcrops on the crest. Both are
    # LINEAR: a line of rock reads as a ridge, a scatter of rock reads as a
    # level-design mistake.
    if spec.scree:
        for ridge in plan.ridges:
            fan: list[tuple[float, float, float]] = []
            crest: list[tuple[float, float, float]] = []
            for i in range(len(ridge.spine) - 1):
                (ax, ay), (bx, by) = ridge.spine[i], ridge.spine[i + 1]
                idx = min(len(ridge.crest) - 1,
                          int(i / max(1, len(ridge.spine) - 1)
                              * len(ridge.crest)))
                hgt = ridge.crest[idx]
                ang = math.atan2(by - ay, bx - ax) + math.pi / 2
                if rng.random() < 0.22 and hgt > 0.25 \
                        and not _near_building(plan, ax, ay, 90.0):
                    d = ridge.width * rng.uniform(0.75, 1.15)
                    fx = ax + math.cos(ang) * d
                    fy = ay + math.sin(ang) * d
                    # a scree fan does not sit in a river, and not next to a
                    # barn either: nothing stands where the slope lets go
                    if not plan.near_water(fx, fy, 70.0) \
                            and not _near_building(plan, fx, fy, 70.0) \
                            and 12.0 < fx < plan.geom.w - 12.0:
                        fan.append((fx, fy, 0.3 + 0.5 * hgt))
                if hgt > 0.68 and not plan.near_water(ax, ay, 60.0):
                    # a rocky crest is CONTINUOUS: outcrops every few spine
                    # points, overlapping, so the eye reads one mass of rock
                    # along the top of the ridge. Scattered at 6% they read as
                    # "individual boulders, not a coherent ridge" - the most
                    # common complaint about the planned maps
                    crest.append((ax, ay, 0.3 + 0.3 * hgt))
                elif rng.random() < 0.05:
                    cx2 = ax
                    cy2 = ay
                    if not plan.near_water(cx2, cy2, 60.0):
                        crest.append((cx2, cy2, 0.35 + 0.45 * hgt))
            if len(fan) >= 3:
                plan.woods.append(Wood(kind="scree", items=fan))
            if len(crest) >= 2:
                plan.woods.append(Wood(kind="outcrop", items=crest))


def _water_mark(plan: SitePlan) -> None:
    g = plan.geom
    for w in plan.water:
        lo_j, hi_j, lo_i, hi_i = _cell_box(g, w.path, w.half + 14.0)
        for j in range(lo_j, hi_j + 1):
            for i in range(lo_i, hi_i + 1):
                cx, cy = i * CELL + CELL / 2, j * CELL + CELL / 2
                if _dist_path(g, cx, cy, w.path) < w.half + 14.0:
                    plan.wet[j][i] = True


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def plan_site(theme: str, seed: int, geom: Geom | None = None) -> SitePlan:
    """Design a sector's ground. Deterministic from ``(seed, theme, geom)``.

    ``geom`` is the ground being designed: one screen by default, a longer strip
    for a streamed sector. Densities and the reach of a meander key off it, so a
    six-screen strip is a designed six screens and not one screen stretched.
    """
    g = geom or SCREEN
    if theme not in SPEC:
        # an unknown theme used to fall back to the default landscape, so a typo
        # in a level table silently painted rolling farmland where a glacier was
        # intended - and the picture looked plausible enough to ship
        raise KeyError(f"no site spec for theme {theme!r}; "
                       f"known: {', '.join(sorted(SPEC))}")
    spec = SPEC[theme]
    rng = _rng(theme, seed)
    if not g.cyclic:
        # more than one of everything a screen gets: a range, a hamlet, a
        # stand of woods per screen, each a local story the next one continues
        spec = replace(
            spec,
            ridge_count=(max(1, round(spec.ridge_count[0] * g.screens * 0.6)),
                         max(1, round(spec.ridge_count[1] * g.screens * 0.6))),
            woods=(max(1, round(spec.woods[0] * g.screens)),
                   max(1, round(spec.woods[1] * g.screens))))
    ridges, relief = _orogeny(g, spec, rng)
    # Normalise the height field. Raw orogeny peaks near 0.6, and the painter's
    # colour ramp, rock coverage and snowline are all calibrated 0..1 - so an
    # un-normalised plan paints a mountain range at two thirds of its own
    # possible contrast, which is what made reviewers write "no convincing
    # elevation" for every single theme.
    peak = max(max(row) for row in relief)
    if peak > 0.05:
        # normalise to the theme's own target, not always to full scale: a
        # canyon range and a village's low terrace are not the same kind of
        # ground, and the painter's rock and snow thresholds key off h
        gain = spec.relief_gain / peak
        relief = [[min(1.0, v * gain) for v in row] for row in relief]
    water = _drainage(g, spec, relief, rng)
    plan = SitePlan(theme=theme, seed=seed, ridges=ridges, water=water,
                    roads=[], buildings=[], fields=[], woods=[], greens=[],
                    relief=relief,
                    wet=[[False] * g.cols for _ in range(g.rows)],
                    built=[[False] * g.cols for _ in range(g.rows)], geom=g)
    _water_mark(plan)
    plan.roads = _circulation(g, spec, plan.relief, water, rng)
    _fields(spec, plan, rng)
    _settlement(spec, plan, rng)
    _cover(spec, plan, rng)
    return plan


__all__ = ["Building", "Field", "Green", "Road", "Ridge", "SitePlan",
           "Geom", "SCREEN", "SCREEN_H", "SCREEN_W", "SiteSpec", "SPEC",
           "Water", "Wood", "CELL", "COLS", "ROWS",
           "SHAPES", "plan_site"]
