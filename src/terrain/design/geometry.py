"""Paths, distances, polygons and the planning grid's spans."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..plan.geom import SCREEN_H, SCREEN_W

if TYPE_CHECKING:
    from ..plan.geom import Geom, Point

import math
from bisect import bisect_right
from collections.abc import Iterable


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


def _paths_close(g: Geom, a: list[Point], b: list[Point], dist: float) -> bool:
    for pt in a[::2]:
        if _near_path(g, pt[0], pt[1], b, dist):
            return True
    return False


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


def _in_poly(x: float, y: float, poly: list[Point]) -> bool:
    inside = False
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        if (a[1] > y) != (b[1] > y):
            t = (y - a[1]) / (b[1] - a[1])
            if x < a[0] + t * (b[0] - a[0]):
                inside = not inside
    return inside


def _in_strip(g: Geom, y: float) -> bool:
    """Can a thing sit at this y?

    A one-screen plan loops in y, so anything goes and the painter's seam copies
    stitch it. A strip has an end: a tree placed past it is a tree the player
    never sees, painted again and again by every chunk window that overlaps it.
    """
    return True if g.cyclic else 12.0 < y < g.h - 12.0
