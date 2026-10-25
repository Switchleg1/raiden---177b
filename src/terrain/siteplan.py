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

import logging
import math
import random
from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from .art_table import ART_FRONT, ART_FRONT_DEFAULT, INK, INK_DEFAULT, PROP_OF
from .field_table import LIFTABLE_FIELDS
from .tilekit import CH, CW
from .water_table import WATER_HALF, WATER_RATE

_LOG = logging.getLogger("raiden.siteplan")

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
    kind: str                     # "river" | "wash" | "channel" | "lake"
    path: list[Point]
    half: float                   # half width, px
    flood: float                  # floodplain half width, px
    #: a body you stand IN, not a channel you cross: its outline is a shoreline and
    #: the water is INSIDE it. Without this the painter strokes the outline like a
    #: river - a ring of water, a bank line on each side of the ring, and flow
    #: glints down the middle of it - and a lake reads as a circular roadway with
    #: centre lines, which is exactly what the user reported seeing.
    closed: bool = False
    #: a point known to be inside a closed body (its anchor): what the fill asks
    #: "which side is water" with
    inside: Point | None = None


@dataclass
class Road:
    kind: str                     # "main" | "highway" | "spur" | "track"
    path: list[Point]
    width: float
    bridges: list[Point] = field(default_factory=list)
    #: paved/gravel strip either side of the carriageway. Part of the ROAD, not a
    #: row of parcels: a highway's shoulders were modelled as ~200 narrow Field
    #: polygons, which the painter paid for per slice and which the city-block
    #: rules then read as 18 px-wide "blocks".
    shoulder: float = 0.0


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


# ---------------------------------------------------------------------------
# how big a thing IS: the art's own ink extents
# ---------------------------------------------------------------------------



def prop_art(kind: str) -> str:
    """The prop art a plan kind is drawn with."""
    return PROP_OF.get(kind, kind)


def ink_size(kind: str, scale: float = 1.0, angle: float = 0.0
             ) -> tuple[float, float]:
    """Ink width and height of a prop as it will be PAINTED.

    ``angle`` is the plan's facing, snapped to the four cardinal facings by
    :func:`_face`. Snapping is what keeps a footprint axis-aligned, and an
    axis-aligned footprint is what makes "does this overlap that" an exact test
    instead of a rumour.
    """
    w, h = INK.get(prop_art(kind), INK_DEFAULT)
    if art_turn(kind, angle) % 180:
        w, h = h, w
    return (w * scale, h * scale)


def art_turn(kind: str, angle: float) -> int:
    """How far to turn a prop's art (pygame degrees, counter-clockwise on screen)
    so that its FRONT faces `angle` (the plan's facing, see `_face`).

    The plan measures a facing with y pointing down; pygame turns art counter-
    clockwise on screen. Passing one straight to the other, as the painter used to,
    turned no building's front toward its street: a square house hid it, and a
    long apartment slab or a parked car stood sideways to its kerb. Where the front
    of each picture is lives in `ART_FRONT`.
    """
    front = ART_FRONT.get(prop_art(kind), ART_FRONT_DEFAULT)
    return int(round((front - angle) / 90.0)) * 90 % 360


def _face(x: float, y: float, tx: float, ty: float) -> int:
    """The cardinal facing that points from (x, y) toward a target.

    Arbitrary angles made every building lean its own way - half of why a row of
    houses read as a pile rather than a lane - and a rotated footprint cannot be
    tested for overlap without rotating the test with it.
    """
    return int(round(math.degrees(math.atan2(ty - y, tx - x)) / 90.0) * 90) % 360


def _ink_rect(kind: str, x: float, y: float, scale: float, angle: float,
              pad: float = 0.0) -> tuple[float, float, float, float]:
    """The ground a prop covers, as ``(x0, y0, x1, y1)`` plus `pad` px of air."""
    w, h = ink_size(kind, scale, angle)
    return (x - w / 2.0 - pad, y - h / 2.0 - pad,
            x + w / 2.0 + pad, y + h / 2.0 + pad)


def _y_extent(f: Any) -> tuple[float, float]:
    """The y-range a planned feature occupies, before its reach is added."""
    pts = getattr(f, "path", None)
    if pts is None:
        poly = getattr(f, "poly", None)
        if poly is not None:
            ys = [p[1] for p in poly]
        elif hasattr(f, "items"):
            ys = [p[1] for p in f.items]
        elif hasattr(f, "spine"):
            # a ridge: its points are the spine, and its flanks hang off them.
            # Missing this case put every ridge on a strip at y 0..0, so the
            # slice cull dropped the ridges out of every window but the first -
            # and the spatial index answered "no ridges here" to everything.
            ys = [p[1] for p in f.spine]
            for spur in getattr(f, "spurs", ()):
                ys += [p[1] for p in spur]
        elif hasattr(f, "y"):
            ys = [f.y - getattr(f, "radius", 0.0),
                  f.y + getattr(f, "radius", 0.0)]
        else:                        # pragma: no cover - a new feature kind
            return (0.0, 0.0)
    else:
        ys = [p[1] for p in pts]
    drive = getattr(f, "drive", None)
    if drive:
        ys += [p[1] for p in drive]
    if not ys:
        # An item list emptied by a later pass (a building cleared the growth it
        # stands on) has no extent, and `min()` of nothing is a crash inside the
        # paint worker. A range no window can intersect is the honest answer.
        return (1.0e18, -1.0e18)
    return (min(ys), max(ys))


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
    #: ground a PLACE owns: its lane, its clearing, its highway corridor. Kept
    #: separate from `built` on purpose - `built` means "a footprint stands here",
    #: and a place must be able to build on the ground it reserved. Using one grid
    #: for both made every blueprint block its own buildings: the neighborhood
    #: claimed its disc, then refused every house in it.
    place: list[list[bool]] | None = None
    geom: Geom = SCREEN
    #: how fought-over this ground is, 0..1 (see `terrain.war`)
    scars: float = 0.0
    _bands: dict | None = None
    # (y_lo, y_hi, corridor half-width, path) per road, rebuilt when roads change
    _road_box: list | None = None
    _road_n: int = -1

    # ------------------------------------------------------------- windowing
    # How far a feature of each kind reaches beyond its own y-range. The painter
    # used to walk every feature of the plan for every window - 357 houses and
    # 2700 wood stamps per slice, each rotated and blitted and thrown away. On a
    # thirty-screen strip that is the difference between painting a slice in a
    # second and in half a minute.
    # How far past its own anchor a feature of this kind can paint, in bake px: a
    # window that cannot see a feature's anchor must still paint the part of it that
    # reaches into the kept band, or a house ends up cut in half along a boundary -
    # and no overlap test can see that, because both neighbours dropped it happily.
    # These values were raised once on a hunch (320/90/260/160) and measured: the
    # slice-vs-one-window difference did not move at all (0.04% either way), so the
    # clipped-feature explanation was wrong and the extra reach is only extra work.
    # Lowered numbers are guarded by `scripts/study_slice_seams.py`; if a theme ever
    # grows a sprite that paints past these, that measurement moves first.
    _REACH = {"ridges": 0.0, "water": 0.0, "roads": 0.0, "buildings": 130.0,
              "fields": 30.0, "woods": 150.0, "greens": 70.0}

    def band(self, kind: str, y0: float, y1: float) -> list[int]:
        """Indices of the features of `kind` that can appear in a y-range.

        Indices, not features: the painter's jitter is keyed to the feature's
        index in the plan, and a window that saw a renumbered neighbourhood
        would grow different hedges than the window next door.

        A wrapping (one-screen) plan answers with everything: its features wrap
        across the seam, so culling by y would drop the seam copies and change
        the baked maps.
        """
        attr = {"ridges": "ridges", "water": "water", "roads": "roads",
                "buildings": "buildings", "fields": "fields",
                "woods": "woods", "greens": "greens"}[kind]
        feats = getattr(self, attr)
        if self.geom.cyclic:
            return list(range(len(feats)))
        self._bands = self._bands or {}
        ranges = self._bands.get(kind)
        if ranges is None:
            reach = self._REACH[kind]
            ranges = []
            for i, f in enumerate(feats):
                lo, hi = _y_extent(f)
                if kind == "ridges":
                    reach = f.width * 3.4 + 40.0
                elif kind == "water":
                    reach = max(f.flood, f.half * 2.0) + 60.0
                elif kind == "roads":
                    reach = f.width * 2.0 + 90.0
                elif kind == "buildings":
                    # A building is not its footprint. It stamps a prop sprite
                    # (256 px of art at `scale`, so it overhangs 128*scale either
                    # way) and splats a yard (art scaled by radius/60, so about
                    # 2.1 radii beyond the yard's own edge). The constant 130 was a
                    # guess at the sprite and covered neither, so a neighbour's yard
                    # appeared in the window that happened to include it and not in
                    # the one painting the ground under it - measured as one compact
                    # 100x100 px blob of differently-shaded ground at a slice
                    # boundary, present in a one-window reference and absent from the
                    # slice. Reach is what the feature DRAWS, not what it IS.
                    spread = 128.0 * float(getattr(f, "scale", 1.0)) + 40.0
                    if getattr(f, "yard", None):
                        spread = max(spread, 2.2 * float(f.yard[2]) + 40.0)
                    reach = max(reach, spread)
                elif kind == "woods":
                    # The stand's trees are its own props, up to 256*scale wide,
                    # and its edge is the outermost crown, not the stand's points.
                    reach = max(reach, 128.0 + 40.0)
                elif kind == "greens":
                    # A green draws its lanes too, and they run out to the houses
                    # around it - a window that saw the anchor but not the lane end
                    # (or the reverse) painted half a lane, which is the same
                    # half-a-house artifact at a slice boundary wearing a different
                    # hat. Reach is what the feature DRAWS.
                    lanes = getattr(f, "lanes", None) or []
                    far = max((max(abs(p2[1] - f.y) for p2 in lane)
                               for lane in lanes), default=0.0)
                    reach = max(reach, far + 20.0)
                ranges.append((lo - reach, hi + reach, i))
            self._bands[kind] = ranges
        return [i for lo, hi, i in ranges if hi >= y0 and lo <= y1]

    # ------------------------------------------------------------------ asks
    def relief_at(self, x: float, y: float) -> float:
        return self.relief[self.geom.row(y)][self.geom.col(x)]

    def is_wet(self, x: float, y: float) -> bool:
        return self.wet[self.geom.row(y)][self.geom.col(x)]

    def is_built(self, x: float, y: float) -> bool:
        return self.built[self.geom.row(y)][self.geom.col(x)]

    def in_road_corridor(self, x: float, y: float,
                         margin: float = 30.0) -> bool:
        """Is this point inside a road's cleared corridor?

        Every road is tested - not just the one a building faces - because a
        building set back from its own lane can still be standing on a highway the
        lane runs beside.

        Cheap by bounding box first: roads are indexed once per plan by the y they
        span, and a point outside that span plus the corridor cannot be in it.
        Without that prefilter the check walked every segment of every road for
        every candidate building, and planning a 24-screen strip went from seconds
        to two minutes.
        """
        if self._road_box is None or self._road_n != len(self.roads):
            self._road_n = len(self.roads)
            self._road_box = [(min(p[1] for p in r.path),
                               max(p[1] for p in r.path),
                               r.width * 0.5 + margin, r.path)
                              for r in self.roads]
        for lo, hi, half, path in self._road_box:
            if not (lo - half <= y <= hi + half):
                continue
            if _near_path(self.geom, x, y, path, half):
                return True
        return False

    def is_place(self, x: float, y: float) -> bool:
        """Is this ground owned by a place (a lane, a clearing, a road corridor)?

        Vegetation and parcels stay out of it. Buildings may stand in it - they are
        the place.
        """
        return bool(self.place) and             self.place[self.geom.row(y)][self.geom.col(x)]

    def near_water(self, x: float, y: float, dist: float) -> bool:
        for w in self.water:
            # A CLOSED body is a region, and being inside it is closer to water than
            # any distance test against its outline can say. `_near_path` measures to
            # the shoreline, and a lake's `half` is its MINOR radius: a point deep in
            # the middle of a wide lake is further from the outline than `half`, so
            # every guard of the form `near_water(x, y, 70)` - scree, outcrops,
            # vegetation - read the middle of a lake as dry ground and dropped rocks
            # in it.
            if w.closed and _in_poly(x, y, w.path):
                return True
            if _near_path(self.geom, x, y, w.path, dist):
                return True
        return False

    def near_road(self, x: float, y: float, dist: float) -> bool:
        return any(_near_path(self.geom, x, y, r.path, dist)
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
    # Cycles per SCREEN, on any ground. This used to be `g.screens` for every map,
    # which on a wrapping one-screen map is 1 (correct) and on a strip is the strip's
    # length: a 33-screen sector ran every k=1 meander 33 times per screen, a 34 px
    # wavelength, and every road and river in the game zigzagged like a stitched seam.
    # A wrapping map needs whole cycles over its own height to close; a strip needs
    # nothing but the meander it was asked for.
    cyc = g.screens if g.cyclic else 1
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
    """Distance to a polyline; on a wrapping map the seam copies are checked.

    See :func:`_near_path` for why the sweep is bucketed by y and how it is
    pruned - the same exactness rule applies, with `best` in place of the radius.
    """
    best = float("inf")
    for shift in g.shifts():
        best = min(best, _dist_path_band(g, px, py - shift, path, best))
    return best


def _dist_path_band(g: Geom, px: float, py: float, path: list[Point],
                    limit: float) -> float:
    buckets, lo_b, hi_b = _seg_buckets_range(path)
    qb = int(math.floor(py / _SEG_BAND))
    best = limit
    for side in (-1, 1):
        b = qb
        while (side < 0 and b >= lo_b) or (side > 0 and b <= hi_b):
            gap = _bucket_gap(py, b)
            if gap > best:
                break
            for j in buckets.get(b, ()):
                d = _seg_dist(px, py, path[j], path[j + 1])
                if d < best:
                    best = d
                    if best <= 1e-6:
                        return 0.0
            b += side
    return best


def _near_path(g: Geom, px: float, py: float, path: list[Point],
               dist: float) -> bool:
    """Is any part of `path` within `dist` of the point?

    The question the planner asks constantly - is this parcel off the road, is
    this tree clear of the river, does this building stand in a channel - over a
    path that is a thousand segments long on a multi-screen strip.

    The sweep walks the y buckets outward from the bucket the query falls in and
    stops at each side once that side's bucket gap exceeds the radius. The
    previous version stopped at the first band whose extent did not reach the
    query, which is a different thing: bands are scattered along the path, not a
    partition of y, so a nearer band can sit behind a farther one in the sort
    order. It therefore answered "not near" to points that were ON the line - a
    house whose drive ended on its own lane, a building standing in a channel, a
    tree inside a carriageway - and every check that runs through it inherited
    the same silent "no". `tests/test_places.py` found it: a drive measured 0 px
    from a spur at radius 400 and unreachable at radius 24.
    """
    buckets, lo_b, hi_b = _seg_buckets_range(path)
    for shift in g.shifts():
        yy = py - shift
        q = int(math.floor(yy / _SEG_BAND))
        for side in (-1, 1):
            b = q
            while (side < 0 and b >= lo_b) or (side > 0 and b <= hi_b):
                if _bucket_gap(yy, b) > dist:
                    break
                for j in buckets.get(b, ()):
                    if _seg_dist(px, yy, path[j], path[j + 1]) <= dist:
                        return True
                b += side
    return False


def _bucket_gap(py: float, b: int) -> float:
    """The least vertical distance from `py` to anything in bucket `b`.

    A lower bound, which is what makes pruning exact: no segment inside the
    bucket can be nearer than this.
    """
    lo, hi = b * _SEG_BAND, (b + 1) * _SEG_BAND
    if py < lo:
        return lo - py
    if py > hi:
        return py - hi
    return 0.0


def _seg_buckets_range(path: list[Point]) -> tuple[dict[int, list[int]], int, int]:
    """The path's y buckets, plus the first and last bucket index it occupies."""
    ent = _seg_cache(path)
    return ent[2], ent[3][0], ent[3][1]


_SEG_BAND = 160.0            # bake px of y per segment bucket
_SEG_INDEX: dict[int, tuple] = {}


def _seg_index(path: list[Point]) -> list[tuple[float, float, list[int]]]:
    """The path's segments as (y_lo, y_hi, indices), ordered by y_lo."""
    return _seg_cache(path)[1]


def _seg_buckets(path: list[Point]) -> dict[int, list[int]]:
    """The path's segments keyed by the bucket index of y they touch.

    A segment that spans several buckets is filed in every one of them, which is
    what makes bucket-keyed queries exact: two y-ranges that overlap share a
    bucket.
    """
    return _seg_cache(path)[2]


def _seg_cache(path: list[Point]) -> tuple:
    """(path, bands, buckets, (first_bucket, last_bucket)) for a polyline.

    Cached per path object - the planner asks the same question about the same
    road or channel over and over while it lays fields, houses and trees around
    it. Keyed by identity and re-checked against the cached path, so a recycled
    id can never answer with someone else's geometry.
    """
    key = id(path)
    ent = _SEG_INDEX.get(key)
    if ent is not None and ent[0] is path:
        return ent
    buckets: dict[int, list[int]] = {}
    for i in range(len(path) - 1):
        y0, y1 = path[i][1], path[i + 1][1]
        b0, b1 = int(y0 // _SEG_BAND), int(y1 // _SEG_BAND)
        # min/max, not b0..b1: a segment whose y DECREASES has b0 > b1, and
        # range(b0, b1 + 1) is then empty - so every downward-running segment of
        # every vertical road, river and channel filed itself into no bucket at all
        # and was invisible to the nearness index. That is why a road "does not
        # cross" the river it runs along, why a drive measured 24 px from the lane
        # it was drawn on, and why a building could stand in a channel the plan
        # believed it was clear of.
        for b in range(min(b0, b1), max(b0, b1) + 1):
            buckets.setdefault(b, []).append(i)
    bands: list[tuple[float, float, list[int]]] = []
    for _b, idxs in buckets.items():
        lo = min(min(path[i][1], path[i + 1][1]) for i in idxs)
        hi = max(max(path[i][1], path[i + 1][1]) for i in idxs)
        bands.append((lo, hi, idxs))
    bands.sort()
    keys = sorted(buckets)
    lohi = (keys[0], keys[-1]) if keys else (0, -1)
    if len(_SEG_INDEX) > 400:          # a planning pass pins its paths; bound it
        _SEG_INDEX.clear()
    cum = [0.0]
    for i in range(len(path) - 1):
        cum.append(cum[-1] + math.hypot(path[i + 1][0] - path[i][0],
                                        path[i + 1][1] - path[i][1]))
    ent = (path, bands, buckets, lohi, cum)
    _SEG_INDEX[key] = ent
    return ent


def _along(path: list[Point], s: float) -> tuple[Point, float]:
    """Point at fraction ``s`` along a polyline, plus the tangent angle.

    The cumulative lengths are cached with the path (see :func:`_seg_cache`) and
    looked up by bisection. Recomputing the total and walking from the start on
    every call made the placement pass quadratic: a twenty-four screen strip took
    two minutes to design, against a dozen seconds of budget, because the place
    blueprints ask this question thousands of times per candidate.
    """
    ent = _seg_cache(path)
    cum = ent[4]
    total = cum[-1]
    want = max(0.0, min(1.0, s)) * total
    i = max(0, bisect_right(cum, want) - 1)
    i = min(i, len(path) - 2) if len(path) > 1 else 0
    a, b = path[i], path[i + 1]
    ln = cum[i + 1] - cum[i]
    t = 0.0 if ln <= 1e-9 else (want - cum[i]) / ln
    return ((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])),
            math.atan2(b[1] - a[1], b[0] - a[0]))


def _nearest_on_path(path: list[Point], px: float, py: float
                     ) -> tuple[Point, float, float]:
    """The nearest point on a polyline, its tangent, and the distance.

    Bucketed by y like the rest of the index, so "which road is this place
    leaning against" costs what it should. Sampling the road by arc - which is
    what this replaced - was both slower and less exact.
    """
    ent = _seg_cache(path)
    buckets, (lo_b, hi_b) = ent[2], ent[3]
    q = int(math.floor(py / _SEG_BAND))
    best = (float("inf"), 0)
    for side in (-1, 1):
        b = q
        while (side < 0 and b >= lo_b) or (side > 0 and b <= hi_b):
            if _bucket_gap(py, b) > best[0]:
                break
            for j in buckets.get(b, ()):
                d = _seg_dist(px, py, path[j], path[j + 1])
                if d < best[0]:
                    best = (d, j)
            b += side
    d, i = best
    a, c = path[i], path[i + 1]
    ln2 = (c[0] - a[0]) ** 2 + (c[1] - a[1]) ** 2
    if ln2 <= 1e-9:
        return a, math.atan2(c[1] - a[1], c[0] - a[0]), d
    t = max(0.0, min(1.0, ((px - a[0]) * (c[0] - a[0])
                           + (py - a[1]) * (c[1] - a[1])) / ln2))
    return ((a[0] + t * (c[0] - a[0]), a[1] + t * (c[1] - a[1])),
            math.atan2(c[1] - a[1], c[0] - a[0]), d)


def _crossings(a: list[Point], b: list[Point]) -> list[Point]:
    """Where two polylines cross (used for bridges).

    Only the segments that could touch are tested: each segment of `a` looks at
    the bands of `b` its own y-range reaches, and rejects on bounding box
    before any arithmetic. A road and a river down a twenty-screen strip are a
    thousand and seven hundred points apiece, and the naive double loop paid
    seven hundred thousand pair tests to find two bridges.
    """
    hits: list[Point] = []
    buckets = _seg_buckets(b)
    for i in range(len(a) - 1):
        p, q = a[i], a[i + 1]
        ylo = p[1] if p[1] < q[1] else q[1]
        yhi = q[1] if p[1] < q[1] else p[1]
        ax0 = p[0] if p[0] < q[0] else q[0]
        ax1 = q[0] if p[0] < q[0] else p[0]
        for bi in range(int(ylo // _SEG_BAND), int(yhi // _SEG_BAND) + 1):
            for j in buckets.get(bi, ()):  # a shared band is a possible overlap
                r, s = b[j], b[j + 1]
                if (max(r[0], s[0]) < ax0 or min(r[0], s[0]) > ax1
                        or max(r[1], s[1]) < ylo or min(r[1], s[1]) > yhi):
                    continue
                d1x, d1y = q[0] - p[0], q[1] - p[1]
                d2x, d2y = s[0] - r[0], s[1] - r[1]
                den = d1x * d2y - d1y * d2x
                if abs(den) < 1e-9:
                    continue
                t = ((r[0] - p[0]) * d2y - (r[1] - p[1]) * d2x) / den
                u = ((r[0] - p[0]) * d1y - (r[1] - p[1]) * d1x) / den
                if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
                    hits.append((p[0] + t * d1x, p[1] + t * d1y))
    # a segment that spans two bands is filed in both, so the same crossing can
    # be found twice; decks are paired positionally downstream, and a doubled
    # deck shifts every span after it
    uniq: list[Point] = []
    for h in hits:
        if h not in uniq:
            uniq.append(h)
    return uniq


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
    # NOTE: there is deliberately no house_gap. Spacing between buildings is
    # the size of the buildings (see INK / ink_size), which is the only rule
    # that can hold across kinds as different as a hut and a 255 px warehouse.
    hamlet: bool = True
    field_kinds: tuple[str, ...] = ()
    field_count: tuple[int, int] = (0, 0)
    tree_props: tuple[str, ...] = ("tree_clump",)
    #: which places this theme knows how to build (see terrain.places.VOCABULARY).
    #: This is the theme's SETTLEMENT character: countryside knows neighborhoods
    #: and campgrounds by the water, a city knows neighborhoods and a highway, a
    #: forest knows campgrounds and lakes, a canyon knows neither.
    places: tuple[str, ...] = ()
    woods: tuple[int, int] = (2, 4)
    #: how hard the main river swings: 1 is a lowland river, a city's is a
    #: straightened, embanked channel
    meander: float = 1.0
    #: which kind of mountain range this ground grows (see `mountain_table`);
    #: "" for none
    ranges: str = ""
    treeline: bool = True
    scree: bool = True
    hedge: str = "hedge"


_DEFAULT = SiteSpec()

SPEC: dict[str, SiteSpec] = {
    "countryside": SiteSpec(
        ranges="foothills",
        ridge_shapes=("massif", "sawback", "domefield"), ridge_weight=0.9,
        # more than one mass: a single ridge somewhere on the map is why the
        # review said "no strong hills or slopes read" - the ground has to have
        # a high side and a low side across the whole strip
        ridge_count=(2, 3), water_kinds=("river",), road="main",
        build=("house", "barn"), field_kinds=("crop", "pasture", "orchard"),
        field_count=(5, 8), tree_props=("tree_clump", "pine_clump"),
        woods=(1, 3),
        places=("neighborhood", "woodland", "farmstead", "campground",
                "lake", "plains")),
    "farmland": SiteSpec(
        ridge_shapes=("domefield", "massif"), ridge_weight=0.7,
        ridge_count=(1, 1), water_kinds=("channel", "river"), road="main",
        build=("barn", "house"), field_kinds=("crop", "paddy", "pasture"),
        field_count=(8, 12), tree_props=("tree_clump", "pine_clump"),
        woods=(1, 2),
        places=("neighborhood", "woodland", "farmstead", "lake", "plains")),
    "forest": SiteSpec(
        ranges="alpine",
        ridge_shapes=("massif", "hogback"), ridge_weight=0.8,
        ridge_count=(1, 2),
        water_kinds=("river",), road="main", build=("house",),
        field_kinds=("pasture",), field_count=(1, 3),
        tree_props=("pine_clump", "tree_clump"), woods=(5, 8),
        treeline=True,
        places=("woodland", "campground", "lake", "farmstead")),
    "canyon": SiteSpec(
        ranges="badlands",
        ridge_shapes=("mesa", "hogback", "sawback"), ridge_weight=0.95,
        ridge_count=(2, 3), water_kinds=("wash",), road="main",
        build=(), field_count=(0, 0), tree_props=("dead_tree",),
        # no treeline: a contour-following row of bare trees along every ridge
        # flank shades into "tangled roots" and hides the canyon wall it was
        # supposed to trace
        woods=(1, 3), scree=True, treeline=False,
        places=()),
    "glacier": SiteSpec(
        ranges="alpine",
        ridge_shapes=("massif", "domefield", "cone"), ridge_weight=0.9,
        ridge_count=(2, 3), water_kinds=("channel",), road="main",
        build=("hut",), field_count=(0, 0),
        tree_props=("pine_snow",), woods=(2, 4), scree=True,
        places=("farmstead",)),
    "volcanic": SiteSpec(
        ranges="volcanic",
        ridge_shapes=("cone", "cone", "sawback", "hogback"), ridge_weight=0.95,
        ridge_count=(2, 3), ridge_prop="basalt_spire", water_kinds=(),
        road="main", build=(), field_count=(0, 0),
        tree_props=("dead_tree",), woods=(1, 3), scree=True,
        places=()),
    "wasteland": SiteSpec(
        ranges="badlands",
        ridge_shapes=("hogback", "massif"), ridge_count=(1, 2),
        water_kinds=("wash",), road="main", build=("crate_stack",),
        field_count=(0, 0), tree_props=("dead_tree",), woods=(2, 4),
        scree=True,
        places=()),
    "ruins": SiteSpec(
        ranges="foothills",
        ridge_shapes=("massif", "hogback"), ridge_weight=0.5,
        ridge_count=(1, 2), water_kinds=("river",), road="main",
        build=("house",), hamlet=True, field_kinds=("pasture",),
        field_count=(2, 4), tree_props=("tree_clump", "dead_tree"),
        woods=(1, 3),
        places=("neighborhood", "woodland", "farmstead", "lake")),
    "city": SiteSpec(
        ridge_shapes=("domefield",), ridge_count=(1, 1),
        ridge_weight=0.5, relief_gain=0.45, water_kinds=("river",),
        # no scree, no outcrops: boulders in a village read as three huge rocks
        # dropped onto a street, and nothing in a settlement is loose rock
        road="grid", scree=False,
        # the blocks build the city (see terrain.city): a frontage row or a
        # subdivision has nowhere to go in a grid, and only took a block's ground
        build=(), hamlet=False, meander=0.25,
        field_kinds=("lot", "park", "yard"), field_count=(10, 16),
        tree_props=("tree_clump",), woods=(0, 1), treeline=False,
        places=("highway",)),
    "airbase": SiteSpec(
        ridge_shapes=("domefield",), ridge_weight=0.3, ridge_count=(0, 1),
        water_kinds=("wash",), road="main", build=("warehouse_long",),
        field_count=(0, 0), tree_props=("tree_clump",), woods=(1, 2),
        places=("highway",)),
    "industrial": SiteSpec(
        ridge_shapes=("massif",), ridge_weight=0.35, ridge_count=(0, 1),
        water_kinds=("channel",), road="main",
        build=("warehouse_long", "storage_tank"), field_count=(0, 0),
        tree_props=("dead_tree",), woods=(1, 2),
        places=("highway",)),
    "swamp": SiteSpec(
        ridge_shapes=("ridge",), ridge_count=(1, 2), ridge_weight=0.4,
        relief_gain=0.35,
        water_kinds=("channel", "channel", "river"),
        # a swamp still gets ONE route - a causeway on the only dry ground
        # there is, crossing every channel - because without a road there is no
        # settlement either, and the sector reads as an empty green soup
        road="main", build=("hut_stilt",), hamlet=False, field_count=(0, 0),
        tree_props=("cypress_clump", "dead_tree"), woods=(3, 6),
        treeline=False,
        places=("farmstead",)),
    "ocean": SiteSpec(
        ridge_shapes=(), ridge_count=(0, 0), water_kinds=(), road="none",
        build=(), field_count=(0, 0), tree_props=(), woods=(0, 0),
        treeline=False, scree=False,
        places=()),

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
    if not g.cyclic:
        _ranges(g, spec, relief, rng)
    return ridges, relief


def _ranges(g: Geom, spec: SiteSpec, relief: list[list[float]],
            rng: random.Random) -> None:
    """Mountain ranges: long walls of high ground down one side of the strip.

    The scattered ridges above are hills - a mass here, a spur there. A range is a
    different landform: a crest line that runs for screens with peaks and saddles
    along it, falling steeply to a valley the river and the road share. Flying down
    a valley with a range on one side is one of the things the user asked to see,
    and it is the shape of most real mountain country.

    The crest wanders slowly, its height rises and falls in long waves (peaks and
    passes), and the flank falls off with distance from the crest. Raised into the
    relief with `max`, so it joins the hills already there instead of stacking on
    them. Rivers and roads are routed after this and keep to the low ground.
    """
    from .mountain_table import RANGES
    spec_r = RANGES.get(spec.ranges)
    if spec_r is None:
        return
    per, (w_lo, w_hi), (h_lo, h_hi) = spec_r
    count = int(g.screens / per) + (1 if rng.random() < (g.screens / per) % 1.0 else 0)
    for _ in range(count):
        left = rng.random() < 0.5
        length = rng.uniform(4.0, 9.0) * SCREEN_H
        y0 = rng.uniform(-0.2, 1.0) * g.h
        y1 = y0 + length
        width = rng.uniform(w_lo, w_hi)
        base = rng.uniform(0.04, 0.16) * g.w
        crest = [(rng.uniform(0.0, 6.28), rng.uniform(0.02, 0.05) * g.w,
                  rng.uniform(1.4, 2.6) * SCREEN_H) for _k in range(2)]
        peaks = [(rng.uniform(0.0, 6.28), rng.uniform(0.6, 1.4) * SCREEN_H),
                 (rng.uniform(0.0, 6.28), rng.uniform(0.25, 0.5) * SCREEN_H)]
        top = rng.uniform(h_lo, h_hi)
        j0 = max(0, int(y0 // g.cell))
        j1 = min(g.rows - 1, int(y1 // g.cell))
        for j in range(j0, j1 + 1):
            y = j * g.cell + g.cell / 2
            t = (y - y0) / length
            # the range rises out of the plain at its ends rather than starting as
            # a cliff across the strip
            taper = min(1.0, t * 5.0, (1.0 - t) * 5.0)
            if taper <= 0.0:
                continue
            cx = base + sum(a * math.sin(y / wl + ph) for ph, a, wl in crest)
            if not left:
                cx = g.w - cx
            h = top * taper * (0.72 + 0.18 * math.sin(y / peaks[0][1] + peaks[0][0])
                               + 0.10 * math.sin(y / peaks[1][1] + peaks[1][0]))
            for i in range(g.cols):
                x = i * g.cell + g.cell / 2
                d = abs(x - cx)
                if d >= width:
                    continue
                u = 1.0 - d / width
                v = h * u * u * (3.0 - 2.0 * u)
                if v > relief[j][i]:
                    relief[j][i] = min(1.0, v)


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
    if g.cyclic:
        out = _drainage_screen(g, spec, relief, rng)
    else:
        out = _drainage_strip(g, spec, relief, rng)
    _carve(g, relief, out)
    return out


def _water_half(kind: str, rng: random.Random) -> float:
    """A channel's half-width, bake px. It has to read at playfield scale, where
    these numbers are halved: a 12 px half-width is a scratch, not a watercourse."""
    lo, hi = WATER_HALF.get(kind, WATER_HALF["river"])
    return rng.uniform(lo, hi)


def _drainage_screen(g: Geom, spec: SiteSpec, relief: list[list[float]],
                     rng: random.Random) -> list[Water]:
    """One screen that wraps: a body per kind, the best of sixteen candidates."""
    out: list[Water] = []
    for kind in spec.water_kinds:
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
            for prev in out:
                if _paths_close(g, path, prev.path, 130.0):
                    score += 2.0
            if score < best_score:
                best_score = score
                best = Water(kind=kind, path=path, half=_water_half(kind, rng),
                             flood=rng.uniform(60.0, 130.0))
        if best is not None:
            out.append(best)
    return out


def _drainage_strip(g: Geom, spec: SiteSpec, relief: list[list[float]],
                    rng: random.Random) -> list[Water]:
    """A sector's water as one SYSTEM: a main river down the length of the strip
    and tributaries that run in from one edge and end where they meet it.

    The old rule asked for `round(screens * 0.7)` bodies PER KIND, every one of them
    either a full-length river or a full-width crossing: a four-screen strip got three
    near-identical parallel rivers a screen apart, and a real 33-screen sector asked
    for twenty-three. Water does not do that. It collects: small streams join bigger
    ones, and a valley has one river in it.
    """
    out: list[Water] = []
    kinds = list(spec.water_kinds)
    main_kind = kinds[-1]                 # the theme lists its biggest water last
    rate = WATER_RATE.get(spec.water_kinds, WATER_RATE[()])
    mains = max(1, int(round(g.screens / rate[0])))
    for _ in range(mains):
        best: Water | None = None
        best_score = float("inf")
        for _ in range(16):
            m = spec.meander
            path = _vpath(g, rng.uniform(0.15, 0.85) * g.w,
                          [(1, rng.uniform(0.05, 0.11) * m, rng.uniform(0, 6.28)),
                           (2, rng.uniform(0.015, 0.04) * m, rng.uniform(0, 6.28)),
                           (3, rng.uniform(0.0, 0.015) * m, rng.uniform(0, 6.28))],
                          step=32)
            score = (_path_relief(g, relief, path)
                     + 0.6 * _path_max(g, relief, path))
            for prev in out:
                if _paths_close(g, path, prev.path, 260.0):
                    score += 4.0
            if score < best_score:
                best_score = score
                best = Water(kind=main_kind, path=path,
                             half=_water_half(main_kind, rng),
                             flood=rng.uniform(80.0, 140.0))
        if best is not None:
            out.append(best)
    # tributaries: from one edge of the strip to the main river, and no further
    streams = int(round(g.screens / rate[1]))
    ys = sorted(rng.uniform(0.04, 0.96) * g.h for _ in range(streams))
    for y0 in ys:
        kind = kinds[0]
        path = _hpath(g, y0, [(1, rng.uniform(0.02, 0.05), rng.uniform(0, 6.28)),
                              (2, rng.uniform(0.01, 0.025), rng.uniform(0, 6.28)),
                              (3, rng.uniform(0.0, 0.012), rng.uniform(0, 6.28))],
                      step=32)
        if out:
            main = out[0]
            hits = _crossings(path, main.path)
            if hits:
                hx = hits[0][0]
                # run in from whichever edge is further from the confluence, so
                # the stream has a length worth drawing
                if hx > g.w * 0.5:
                    path = [pt for pt in path if pt[0] <= hx + 8.0]
                else:
                    path = [pt for pt in path if pt[0] >= hx - 8.0]
        if len(path) < 6:
            continue
        # a stream should not drop into the same reach as the last one
        if any(_paths_close(g, path, w.path, 220.0) for w in out[1:]):
            continue
        half = _water_half(kind, rng) * (0.62 if kind == main_kind else 1.0)
        out.append(Water(kind=kind, path=path, half=half,
                         flood=rng.uniform(50.0, 90.0)))
    return out


def _carve(g: Geom, relief: list[list[float]], out: list[Water]) -> None:
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
    that no stretch of it stands over water unsupported.

    The decks are placed at even *arc length* and interpolated between vertices,
    not snapped to the nearest vertex: vertex spacing is around 30 px, and
    snapping lets a gap grow past the span the painter has to cover, which is
    how a causeway ends up with one wet stretch left unsupported.
    """
    if not run:
        return []
    cum = [0.0]
    for i in range(1, len(run)):
        cum.append(cum[-1] + math.hypot(run[i][0] - run[i - 1][0],
                                        run[i][1] - run[i - 1][1]))
    arc = cum[-1]
    n = max(1, int(arc / 90.0) + 1)
    out: list[Point] = []
    seg = 0
    for k in range(n):
        want = arc * (k + 0.5) / n
        while seg + 1 < len(run) and cum[seg + 1] < want:
            seg += 1
        span = cum[seg + 1] - cum[seg] if seg + 1 < len(run) else 0.0
        t = 0.0 if span <= 0.0 else (want - cum[seg]) / span
        out.append((run[seg][0] + t * (run[seg + 1][0] - run[seg][0]),
                    run[seg][1] + t * (run[seg + 1][1] - run[seg][1]))
                   if seg + 1 < len(run) else run[seg])
    return out


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
            if _near_path(g, pt[0], pt[1], w.path, w.half + 14.0):
                run.append(pt)
            elif run:
                out.extend(_decks(run))
                run = []
        out.extend(_decks(run))
    return out


def _add_decks(road: Road, spans: list[Point]) -> None:
    """Append bridge decks, ignoring only ones landing on top of a deck that is
    already there.

    A causeway is a *run* of decks, and they are deliberately close - close
    enough that no stretch of road stands over water unsupported. Suppressing a
    deck because another deck sits a channel-width away is how a causeway ends
    up with a hole in it, so the only thing dropped here is a true duplicate.
    """
    for x, y in spans:
        if any(math.hypot(x - bx, y - by) < 24.0
               for bx, by in road.bridges):
            continue
        road.bridges.append((x, y))


def _paths_close(g: Geom, a: list[Point], b: list[Point], dist: float) -> bool:
    for pt in a[::2]:
        if _near_path(g, pt[0], pt[1], b, dist):
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
        # on a strip the main road IS the through-route, so it runs along it: a
        # horizontal main road on a long strip is a lane across one screen, and the
        # rest of the sector has no road at all
        vertical = (not g.cyclic) or rng.random() < 0.72
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
        # A route that crosses water is worth a lot - a bridge is the most legible
        # human-made object in a scrolling map - and crossing several different
        # channels is fine. Crossing the SAME river again and again is a road that
        # was never planned: rewarding every crossing made the main road weave over
        # a sector's one long river five times in four screens.
        per_body = [len(_crossings(path, w.path)) for w in water]
        bodies = sum(1 for c in per_body if c)
        repeats = sum(max(0, c - 1) for c in per_body)
        score -= 5.0 * min(1, bodies) + 1.2 * max(0, bodies - 1)
        score += 3.0 * repeats
        for w in water:
            # ...but a road that runs *with* the river is the "channel or track?"
            # ambiguity the reviewers kept reporting, and it is what the old
            # cost function produced: low ground is the valley floor, and the
            # valley floor is where the river already lives. Measure the share
            # of the route that hugs the water and make that expensive.
            hug = sum(1 for (x, y) in path
                      if _near_path(g, x, y, w.path, w.half + 80.0)) \
                / max(1, len(path))
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
    decks: list[Point] = []
    for w in water:
        decks.extend(_crossings(best.path, w.path))
    decks.extend(_bridge_spans(g, best.path, water))
    _add_decks(best, decks)
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
            if any(_near_path(g, px, py, w.path, w.half + 26.0)
                       for w in water) \
                    and len(pts) > 2:
                break
            pts.append((px, py))
        spur = Road(kind="spur", path=pts, width=rng.uniform(10.0, 13.0))
        for w in water:
            decks = [pt for w in water for pt in _crossings(spur.path, w.path)]
        _add_decks(spur, decks + _bridge_spans(g, spur.path, water))
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
        # a cross street 20 px from a main street is a doubled line, not a block:
        # keep cross streets a block's depth clear of every main
        if any(abs(y - m) < 110 for m in ys):
            continue
        roads.append(Road("track", _hpath(g, float(y), [(1, 0.0, 0.0)],
                                         step=40), 12.0))
    # a street that runs WITH the river for most of its length is the same
    # ambiguity the serpentine routes had; nudge it off the channel instead
    if water:
        for r in roads:
            for _ in range(6):
                wet = sum(1 for x, y in r.path
                          if any(_near_path(g, x, y, w.path, w.half + 26.0)
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
            decks = [pt for w in water for pt in _crossings(r.path, w.path)]
        _add_decks(r, decks + _bridge_spans(g, r.path, water))
    return roads


def _along_extent(kind: str, scale: float, angle: float, tang: float) -> float:
    """How much ROOM a building takes along a road running at `tang`.

    Footprints are axis-aligned (buildings face the cardinal directions), so a
    building on a north-south road occupies its height along the road and one on an
    east-west road its width. Interpolating between the two by the road's own
    direction is exact enough for choosing a step, and the footprint test catches
    anything this under-estimates.
    """
    w, h = ink_size(kind, scale, angle)
    c = abs(math.cos(tang))
    s = abs(math.sin(tang))
    return w * c + h * s


def _settlement(spec: SiteSpec, plan: SitePlan, rng: random.Random) -> None:
    """Houses with frontage: on the road, facing it, set back from it, with a
    drive to it - and a hamlet where the road meets the water.

    Spacing here is sized from the ART, because that is what was missing. The frontage
    step used to be a fraction of the lane's arc (`0.05-0.09 * SCREEN_H / lane`), which
    on a multi-screen strip puts a centre every 56-100 bake px while a house at the
    scale being stamped is 150-220 px of ink wide: every frontage row overlapped the
    next one by half a house, at a random tilt, which is the report this module exists
    to fix. Now a house is placed where its own footprint fits, and the next one
    starts after that footprint ends.
    """
    if not spec.build or not plan.roads:
        return
    # the theme's own route, not the longest road in the sector: a six-screen
    # highway is longer than the lane a village fronts, and `max(len)` made the
    # village front the traffic
    main = max([r for r in plan.roads if r.kind in ("main", "ring")]
               or plan.roads, key=lambda r: len(r.path))
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
        # Houses around a green are spaced by their own size, not by a fixed count:
        # six houses on a small green were six roofs merged into one roof.
        room = 2.0 * math.pi * (radius + 52.0)
        n = max(0, min(6, int(room // (max(ink_size(spec.build[0], 0.85)) + 26.0))))
        for i in range(n):
            a = (i / float(n)) * math.tau + rng.uniform(-0.14, 0.14)
            d = radius + rng.uniform(46.0, 66.0)
            hx, hy = gx + math.cos(a) * d, gy + math.sin(a) * d
            b = place_building(plan, rng.choice(spec.build), hx, hy, (gx, gy),
                               rng.uniform(0.6, 0.78), "hamlet")
            if b is None:
                continue
            green.lanes.append([(hx, hy), (gx + math.cos(a) * radius,
                                           gy + math.sin(a) * radius)])
        plan.greens.append(green)
    # frontage: the row of houses along the road the player reads as a lane
    lane = sum(math.hypot(main.path[i + 1][0] - main.path[i][0],
                          main.path[i + 1][1] - main.path[i][1])
               for i in range(len(main.path) - 1)) or 1.0
    s = 0.04 * lane
    side = 1.0
    while s < 0.96 * lane:
        (bx, by), tang = _along(main.path, s / lane)
        kind = rng.choice(spec.build)
        scale = rng.uniform(0.58, 0.8)
        # Set the front EDGE back from the carriageway, then stand the centre far
        # enough in for the footprint to clear it: setting the CENTRE 40 px off a
        # 22 px road put half the house on the road.
        nx_, ny_ = math.cos(tang + math.pi / 2 * side), math.sin(tang + math.pi / 2 * side)
        front = rng.uniform(34.0, 64.0) + main.width * 0.5
        w, h = ink_size(kind, scale, _face(bx, by, bx + nx_, by + ny_))
        depth = h if abs(math.sin(tang)) > abs(math.cos(tang)) else w
        nx = bx + nx_ * (front + depth * 0.5)
        ny = by + ny_ * (front + depth * 0.5)
        b = place_building(plan, kind, nx, ny, (bx, by), scale, "frontage",
                           drive=[(nx, ny), (bx, by)],
                           yard=(nx + nx_ * 30.0, ny + ny_ * 30.0,
                                 rng.uniform(14.0, 22.0)))
        # Advance by whatever this house actually occupies, plus a gap - and when
        # the ground refused the house, advance by the house's own width anyway, so
        # a rejected site does not become the same candidate retried forever.
        step = _along_extent(kind, scale, _face(nx, ny, bx, by), tang)
        s += step + rng.uniform(26.0, 90.0) if b is not None else step
        side = -side
    # farmyards: set back off the road, at the edge of the fields. A farm is a
    # COMPOUND: a barn and a house with a yard between them, sized apart so their
    # roofs do not merge. The old code jittered both inside a 80x60 px box guarded
    # only by a centre distance smaller than either roof.
    for _ in range(rng.randint(1, 2) * plan.geom.screens):
        (bx, by), tang = _along(main.path, rng.uniform(0.1, 0.9))
        nx_, ny_ = math.cos(tang + math.pi / 2), math.sin(tang + math.pi / 2)
        off = rng.uniform(90.0, 150.0)
        fx, fy = bx + nx_ * off, by + ny_ * off
        barn = place_building(plan, "barn" if "barn" in spec.build else
                              spec.build[0], fx, fy, (bx, by),
                              rng.uniform(0.62, 0.78), "farm",
                              drive=[(fx, fy), (bx, by)])
        if barn is None:
            continue
        # the second building stands beside the first, clear of its footprint
        bw, bh = ink_size(barn.kind, barn.scale, barn.angle)
        span = max(bw, bh) + 34.0
        for k in range(rng.randint(1, 2)):
            hx = fx + math.cos(tang) * span * (k + 1)
            hy = fy + math.sin(tang) * span * (k + 1)
            place_building(plan, spec.build[0], hx, hy, (bx, by),
                           rng.uniform(0.58, 0.72), "farm",
                           drive=[(hx, hy), (bx, by)])


def _shore_clear(plan: SitePlan, x: float, y: float, scale: float) -> bool:
    """Would this tree's crown hang over standing water?

    The shore band in the wet grid is a *building* margin (26 px): ground you will not
    put a house on. A tree is a different object - the art is a 256 px ink box and the
    crown is roughly 90 px of radius at scale 1 - so a lake ringed by trees planted
    just outside its wet band came out with pale blobs sitting on the water (measured:
    mask 1.0 water pixels reading 46-58 luminance because a crown was painted over
    them; the lake test calls it "dry ground with lines in it").

    Only CLOSED bodies are tested. A tree leaning over a narrow stream is what a
    stream bank looks like, and the riparian pass already keeps its own distance from
    the channel; the defect is foliage floating on a lake.
    """
    # The art's own half-width (a 256 px prop at scale 1), plus the error in the
    # distance test itself: `_near_path` measures to a path's SAMPLE POINTS, not to
    # its edges, and a shoreline sampled every ~48 px reads up to half that further
    # away than it is. Measured: trees 71-88 px from a lake's nearest vertex still
    # lightened water 30-100 px inside the shoreline; keeping them 150*scale clear of
    # it took the body from 14/22 dark samples to 21/22. The honest fix is segment
    # distance in `_near_path` itself, which changes every proximity rule in the plan
    # and is not tonight's change.
    reach = 150.0 * scale
    for w in plan.water:
        if not w.closed:
            continue
        if _in_poly(x, y, w.path) or _near_path(plan.geom, x, y, w.path, reach):
            return False
    return True
def _near_building(plan: SitePlan, x: float, y: float, dist: float) -> bool:
    """Foliage within arm's reach of a house reads as scrub swallowing the
    village, which is exactly what the old maps did."""
    return any(math.hypot(b.x - x, b.y - y) < dist for b in plan.buildings)


def lift_vegetation(plan: SitePlan,
                    rect: tuple[float, float, float, float],
                    margin: float = 18.0) -> None:
    """Clear the growth out of the ground a building is about to stand on.

    Trees claim no cells, so a footprint test cannot see them: a frontage barn was
    laid in ground a woodland had planted first, and the map got a tree crown sitting
    on a roof (`foliage_does_not_swallow_the_village`). The order of the plan makes it
    unavoidable in general - a woodland is a landmark laid before the small roadside
    buildings fill the gaps - and the answer real development uses is a clearing: the
    footprint, plus a margin for the crown that leans over the wall, is cleared.
    """
    x0, y0, x1, y1 = rect[0] - margin, rect[1] - margin, \
        rect[2] + margin, rect[3] + margin
    kept = []
    for wd in plan.woods:
        items = [(x, y, s) for (x, y, s) in wd.items
                 if not (x0 <= x <= x1 and y0 <= y <= y1)]
        if len(items) >= 2 or (items and wd.kind in ("riparian", "treeline")):
            wd.items = items
            kept.append(wd)
    plan.woods = kept


def _rect_free(plan: SitePlan, rect: tuple[float, float, float, float]) -> bool:
    """Is a footprint's ground free: inside the strip, unbuilt, dry, not on a slope,
    not in a channel.

    Checked against the PLANNING CELLS the rect covers, not against the rect's
    centre. A centre-only test is how two houses whose art is 160-220 px wide were
    allowed to stand 60 px apart: each centre sat on free ground while the two
    footprints were on top of one another.
    """
    x0, y0, x1, y1 = rect
    g = plan.geom
    if x0 < 10.0 or x1 > g.w - 10.0:
        return False
    # The footprint's own position, sampled the way the plan's own contract samples
    # it. The cell test below reads planning cells; a house can pass it (every cell
    # it covers under 0.42) and still stand where `relief_at` says 0.46 - which is
    # the number `no_building_on_ground_it_cannot_stand_on` measures, and what a
    # farmstead's barn on a farmland ridge tripped. A building is allowed on ground
    # a lane can climb to, not on a slope it has to sit into.
    if plan.relief_at((x0 + x1) / 2.0, (y0 + y1) / 2.0) > 0.40:
        return False
    # NOT `_in_strip`: that asks "does this y exist once the strip wraps", which is
    # always yes, so a footprint straddling the seam was tested against cells it does
    # not cover. A building whose rect leaves [0, h) has its own ground on one side of
    # the seam and its cell test on the other: a neighborhood house measured up at
    # y = 1233 in a 1120-tall sector, standing in a river it was never checked
    # against. Straddling the seam is not worth the bookkeeping; refuse it.
    if y0 < 0.0 or y1 > g.h:
        return False
    j0, j1 = _span(y0, y1, g.rows, g.cell)
    i0, i1 = _span(x0, x1, g.cols, g.cell)
    # `built` and slope get zero tolerance: another building's ground and a hillside
    # are not things a footprint may clip. WET gets a small share, because the cell
    # grid (64 px) is coarser than a house (170x134 px): a lot next to a river covers
    # one river cell with a corner and was refused for it, which is how three
    # countryside sectors ended up with no buildings at all. What decides whether the
    # house stands in water is the corner-and-centre test below, against the water's
    # own geometry - that stays exact.
    wet_cells = 0
    cells = (j1 - j0 + 1) * (i1 - i0 + 1)
    for j in range(j0, j1 + 1):
        row_rel, row_wet, row_built = plan.relief[j], plan.wet[j], plan.built[j]
        for i in range(i0, i1 + 1):
            if row_built[i] or row_rel[i] > 0.42:
                return False
            if row_wet[i]:
                wet_cells += 1
    if wet_cells > cells * 0.12:
        return False
    # a footprint must not straddle water either: the corners and the middle are
    # enough, because a channel wider than the spacing between those samples would
    # swallow the whole building anyway
    for px, py in ((x0, y0), (x1, y0), (x0, y1), (x1, y1),
                   # the middle is held further off the water than the corners: a
                   # building's centre is where its door and yard are, and the plan
                   # promises no building stands in a channel (measured against the
                   # water's own half-width + 38) - a 26 px corner test let a frontage
                   # house sit 30 px from a channel it was built across
                   ((x0 + x1) / 2.0, (y0 + y1) / 2.0)):
        centre = abs(px - (x0 + x1) / 2.0) < 1.0 and abs(py - (y0 + y1) / 2.0) < 1.0
        if plan.near_water(px, py, 42.0 if centre else 26.0):
            return False
    return True


def _claim_rect(plan: SitePlan, rect: tuple[float, float, float, float]) -> None:
    """Mark the ground a footprint covers as taken.

    This mark is what every later pass reads: fields refuse the cell (`_fields`),
    vegetation refuses it (`_cover`), the next building refuses it. Claiming a 26 px
    dot under a 160 px house is why a hedgerow used to run through a living room and
    a barn stood in the middle of a crop field.
    """
    g = plan.geom
    x0, y0, x1, y1 = rect
    j0, j1 = _span(max(0.0, y0), min(float(g.h), y1), g.rows, g.cell)
    i0, i1 = _span(max(0.0, x0), min(float(g.w), x1), g.cols, g.cell)
    for j in range(j0, j1 + 1):
        for i in range(i0, i1 + 1):
            plan.built[j][i] = True


def place_building(plan: SitePlan, kind: str, x: float, y: float,
                   face_to: Point, scale: float, group: str,
                   drive: list[Point] | None = None,
                   yard: tuple[float, float, float] | None = None,
                   air: float = 16.0, commit: bool = True) -> Building | None:
    """The one way a building enters the plan.

    Size comes from the art, not from a wish: the footprint is the prop's ink box at
    its painted scale, the candidate is rejected if any of that ground is taken, and
    on success the ground it covers is claimed - so nothing later plants a tree, a
    hedge or another house inside it.

    `air` is the gap kept between footprints, in bake px. It is a *painting* margin:
    shadows and the light dot at a house's near edge reach a few px past the ink.
    """
    angle = _face(x, y, face_to[0], face_to[1])
    rect = _ink_rect(kind, x, y, scale, angle, pad=air)
    if not _rect_free(plan, rect):
        return None
    # A road owns its corridor. Checked here, in the one gate every building
    # passes through, because a rule that lives in one blueprint is a rule the
    # others do not know: a frontage house set back from the lane it faces ended
    # up 23 px from the edge of a highway the lane happened to run beside.
    if plan.in_road_corridor(x, y):
        return None
    b = Building(kind=kind, x=x, y=y, angle=angle, scale=scale, group=group,
                 drive=drive, yard=yard)
    if not commit:
        # A probe, not a placement: a blueprint is allowed to ask "would a house
        # stand here" before it commits to the road that house hangs off. Without
        # this the probe built the house for real, the blueprint built it again, and
        # when the road was then refused the sector kept houses with no lane under
        # them - which is what `every_house_is_reached_by_a_road` caught.
        return b
    plan.buildings.append(b)
    lift_parcel_ground(plan, rect)
    lift_vegetation(plan, rect)
    _claim_rect(plan, rect)
    return b


def along_road(road: Road, s: float) -> tuple[Point, float]:
    """A point and tangent part-way along a road, `s` in ARC px from its start."""
    total = sum(math.hypot(road.path[i + 1][0] - road.path[i][0],
                           road.path[i + 1][1] - road.path[i][1])
                for i in range(len(road.path) - 1))
    return _along(road.path, (s / total) if total else 0.0)


def _fields(spec: SiteSpec, plan: SitePlan, rng: random.Random) -> None:
    """Enclose the flat, dry ground the road left over. Fields are parcels with
    hedgerows, which is what makes ground look owned rather than empty."""
    if not spec.field_kinds:
        return
    if spec.road == "grid":
        from .city import build_city
        build_city(plan, rng)
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
        _mark_parcel(plan, poly)      # a parcel claims its own ground


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
            if plan.relief[j][i] > 0.34 or plan.wet[j][i] or plan.built[j][i] \
                    or (plan.place and plan.place[j][i]):
                return False
            if plan.near_road(cx, cy, 26.0):
                return False
    return True


def lift_parcel_ground(plan: SitePlan,
                       rect: tuple[float, float, float, float]) -> None:
    """Take the crop out of the ground a building is about to stand on.

    Field parcels claim their cells (`_mark_parcel`), which is what stops a hedgerow
    running through a living room and a barn standing in a crop. It also meant a
    neighborhood could not be built at all: the flat, drained, road-side ground a
    subdivision wants IS farmland, and one sector refused 161 estate house probes for
    standing in a field. Real development eats fields, so the plan says the same:
    the parcel a footprint covers is removed and its ground released, and the house
    goes there.

    Only the lifted parcel's own cells are cleared - a road or another building that
    claimed ground keeps its claim.
    """
    x0, y0, x1, y1 = rect
    g = plan.geom
    keep = []
    for f in plan.fields:
        fx = [q[0] for q in f.poly]
        fy = [q[1] for q in f.poly]
        # FARMLAND only. Every other parcel was laid by a place for the buildings
        # that stand on it - a camp's clearing, a rest stop's apron, a city block's
        # paving - and lifting those deleted each one the moment its first tent or
        # depot went down.
        if (f.kind not in LIFTABLE_FIELDS
                or max(fx) < x0 or min(fx) > x1 or max(fy) < y0 or min(fy) > y1):
            keep.append(f)
            continue
        jr = _span(max(y0, min(fy)), min(y1, max(fy)), g.rows, CELL)
        ic = _span(max(x0, min(fx)), min(x1, max(fx)), g.cols, CELL)
        for j in range(jr[0], jr[1] + 1):
            for i in range(ic[0], ic[1] + 1):
                px, py = i * CELL + CELL / 2.0, j * CELL + CELL / 2.0
                if plan.built[j][i] and _in_poly(px, py, f.poly):
                    plan.built[j][i] = False
    plan.fields = keep


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
                    or plan.is_built(cx, cy) or plan.is_place(cx, cy) \
                    or plan.near_road(cx, cy, 34.0):
                continue
            n = rng.randint(3, 7)              # clustered, never uniform
            items = []
            for _ in range(n):
                a = rng.uniform(0, math.tau)
                r = abs(rng.gauss(0, 46.0))
                x, y = cx + math.cos(a) * r, cy + math.sin(a) * r * 0.8
                sc = rng.uniform(0.45, 1.05)
                if 12 < x < g.w - 12 and _in_strip(g, y) \
                        and plan.relief_at(x, y) < 0.72 \
                        and not plan.is_built(x, y) \
                        and not plan.is_place(x, y) \
                        and not plan.is_wet(x, y) \
                        and _shore_clear(plan, x, y, sc) \
                        and not _near_building(plan, x, y, 60.0):
                    items.append((x, y, sc))
            if len(items) >= 3:
                plan.woods.append(Wood(kind="wood", items=items))
        # riparian corridor: trees follow the water, with gaps
        for w in plan.water:
            step = 0.0
            for i in range(len(w.path) - 1):
                a, b = w.path[i], w.path[i + 1]
                ln = math.hypot(b[0] - a[0], b[1] - a[1])
                step += ln
                # One tree per ~110 px of bank, at 20%: the corridor used to plant a
                # tree every 62 px at 42%, which is a wall of foliage along every
                # drain in the sector, and the sector read as scrub with roofs in it
                # (measured: 347-529 trees in a 4-screen countryside sector).
                if step > 110.0:
                    step = 0.0
                    if rng.random() < 0.20:      # the corridor is not a wall
                        side = 1.0 if rng.random() < 0.5 else -1.0
                        ang = math.atan2(b[1] - a[1], b[0] - a[0]) + \
                            side * math.pi / 2
                        # a crown over the channel hides the bank, and "its
                        # banks disappear under foliage" was the single most
                        # repeated note: the corridor has to stay a corridor
                        d = w.half + rng.uniform(42.0, 76.0)
                        x = a[0] + math.cos(ang) * d
                        y = a[1] + math.sin(ang) * d
                        sc = rng.uniform(0.5, 0.8)
                        if 12 < x < g.w - 12 and _in_strip(g, y) \
                                and not plan.is_built(x, y) \
                                and not plan.is_place(x, y) \
                                and not plan.is_wet(x, y) \
                                and _shore_clear(plan, x, y, sc) \
                                and not _near_building(plan, x, y, 50.0):
                            plan.woods.append(Wood(
                                kind="riparian", items=[(x, y, sc)]))
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
                    sc = rng.uniform(0.6, 1.0)
                    if 12 < x < g.w - 12:
                        y = ay + math.sin(ang) * d
                        # a treeline follows the hillside, and the hillside goes on
                        # underneath a lake: relief was laid before the water and has
                        # no idea the water exists. Measured, this planted a lattice of
                        # crowns at ~40 px spacing straight across three lakes, which
                        # is what "dry ground with lines through the middle" looked
                        # like after the fill itself was fixed.
                        if (_in_strip(g, y) and not plan.is_wet(x, y)
                                and _shore_clear(plan, x, y, sc)
                                and not _near_building(plan, x, y, 50.0)):
                            items.append((x, y, sc))
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
    for w in plan.water:
        _water_mark_body(plan, w)


def _water_mark_body(plan: SitePlan, w) -> None:
    """Mark the cells this water body makes wet.

    Called as the body is laid, not only during orogeny: a lake a blueprint digs
    arrives after the orogeny pass, and until its cells are marked the rest of the
    planner believes the middle of that lake is dry ground.
    """
    g = plan.geom
    lo_j, hi_j, lo_i, hi_i = _cell_box(g, w.path,
                                       w.half + (26.0 if w.closed else 14.0))
    for j in range(lo_j, hi_j + 1):
        for i in range(lo_i, hi_i + 1):
            cx, cy = i * CELL + CELL / 2, j * CELL + CELL / 2
            # A closed body is wet INSIDE it. Marking wet by distance to the outline
            # alone left a dry core in the middle of every lake: the shoreline is
            # `ry` away from the centre while the stroke reaches 0.95*ry, so the very
            # middle of the water read as buildable ground - and a later pass put
            # something there. That dry core, ringed by the inner bank line and the
            # flow glints of a channel stroke, is what made a lake look like "a
            # roadway made in a circle, with the centre lines still inside it".
            #
            # And the shore band is a BAND. The channel radius (`half + 14`, where
            # `half` is a channel's own half-width) made no sense for a body whose
            # `half` is its minor radius: a lake 446 px across marked everything
            # within ~460 px of its shoreline wet, and measured 37-50% of two
            # countryside sectors became unbuildable shore - no house, lane, field or
            # camp anywhere near water, and 0 buildings in those sectors. A lake's
            # ground is water, its shore is marsh for a short way, and beyond that it
            # is the ground everybody else uses.
            if w.closed:
                if _in_poly(cx, cy, w.path) or _near_path(g, cx, cy, w.path,
                                                          26.0):
                    plan.wet[j][i] = True
            elif _near_path(g, cx, cy, w.path, w.half + 14.0):
                plan.wet[j][i] = True


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def plan_site(theme: str, seed: int, geom: Geom | None = None,
              scars: float = 0.0) -> SitePlan:
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
    # Settlement BEFORE fields, which is the order the module promises: the road
    # decides where the houses stand, and the flat dry ground the road and the
    # houses left over is what gets enclosed as fields. Run the other way round,
    # the parcels took the roadside and the frontage row was pushed into the
    # leftovers - which is part of why the houses looked put down at random.
    # Places first, then the frontage row, then the fields that enclose whatever
    # settled ground is left. Two orderings were wrong before this: fields claimed
    # the ground a blueprint was about to build on (a lane got laid and then lost
    # every house on it), and with settlement first the frontage row took the
    # roadside - which is where a neighborhood hangs its lane from - so the
    # neighborhood was sited onto ground the houses had already claimed and lost
    # every footprint to `built`. A place owns ground; a frontage house fills a
    # gap. That is the order that says so.
    from .places import lay_places
    built = lay_places(plan, spec.places, rng)
    # Reconcile the roads with the water once, AFTER the vocabulary is down: a
    # lane laid before a lake can cross it, and a road standing in water with no
    # deck is the "road fords the river" artifact this project has already been
    # told about twice.
    for r in plan.roads:
        _add_decks(r, _bridge_spans(g, r.path, plan.water))
    if built:
        _LOG.debug("places for %s: %s", theme,
                   ", ".join(f"{k}={v}" for k, v in sorted(built.items())))
    _settlement(spec, plan, rng)
    _fields(spec, plan, rng)
    _cover(spec, plan, rng)
    # the war, last: the same ground, broken (a no-op at scars 0)
    from .war import scar
    scar(plan, scars)
    return plan


__all__ = ["Building", "Field", "Green", "Road", "Ridge", "SitePlan",
           "Geom", "SCREEN", "SCREEN_H", "SCREEN_W", "SiteSpec", "SPEC",
           "Water", "Wood", "CELL", "COLS", "ROWS",
           "SHAPES", "plan_site"]
