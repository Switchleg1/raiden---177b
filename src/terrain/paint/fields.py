"""Fields, lots, meadows and burns."""
from __future__ import annotations

import math
import random
from typing import Any

from ..design.geometry import _in_poly
from ..plan.site_plan import SitePlan
from ..tilekit import TileKit
from .ink import _darken_band, _fill_mask, _prop, _splat, _tint_lines
from .raster import _poly_mask, _raster_mask
from .sampling import _band, _frand


def paint_fields(canvas: Any, kit: TileKit, plan: SitePlan,
                 rng: random.Random) -> None:
    for fi in _band(canvas, plan, "fields"):
        f = plan.fields[fi]
        frng = _frand(plan, fi, 11)
        if f.kind == "meadow":
            mask = _raster_mask(f.poly, 0.0, 22, canvas, poly=True)
            _fill_mask(canvas, kit, f.mat, mask, 0.55)
            continue
        if f.kind == "scorch":
            # burned ground: a soft-edged blackening over whatever was there, with
            # the ash heavier in patches - not a parcel with a kerb round it
            mask = _raster_mask(f.poly, 0.0, 22, canvas, poly=True)
            _fill_mask(canvas, kit, f.mat, mask, 0.8)
            _darken_band(canvas, mask, 0.72)
            xs = [q[0] for q in f.poly]
            ys = [q[1] for q in f.poly]
            for _k in range(int((max(xs) - min(xs)) * (max(ys) - min(ys)) / 26000)):
                sx = frng.uniform(min(xs), max(xs))
                sy = frng.uniform(min(ys), max(ys))
                if _in_poly(sx, sy, f.poly):
                    _splat(kit, canvas, "splat_scorch", sx, sy,
                           frng.uniform(0.3, 0.7), frng)
            continue
        mask = _poly_mask(f.poly, canvas)
        _fill_mask(canvas, kit, f.mat, mask, 0.92)
        if f.kind in ("crop", "paddy", "lot", "orchard"):
            # tilled and built parcels are brighter than the waste around them:
            # the material alone leaves them at the same value as the field next
            # door, and the reviewer's verdict was "striped enclosures, purpose
            # unknown"
            _darken_band(canvas, mask, 1.22)
        # the boundary first: a hedgerow or fence reads as a LINE on the ground,
        # and a field without one is just a patch of different colour
        if f.hedge:
            edge = list(f.poly) + [f.poly[0]]
            _tint_lines(canvas, edge, (12, 16, 12), 2.2)
        if f.furrows and f.kind == "parking":
            # stall lines: thin, pale, and the reason a gravel rectangle with cars
            # on it reads as a car park
            for a, b in f.furrows:
                _tint_lines(canvas, [a, b], (196, 192, 178), 1.4)
        if f.furrows and f.kind in ("crop", "paddy"):
            # plough: a dark rut with a lit ridge beside it. On tilled earth the
            # rows are the whole reason the parcel reads as farmed.
            for a, b in f.furrows:
                ln = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
                nx, ny = -(b[1] - a[1]) / ln, (b[0] - a[0]) / ln
                _tint_lines(canvas, [a, b], (18, 14, 10), 2.0)
                off = [(a[0] + nx * 3.0, a[1] + ny * 3.0),
                       (b[0] + nx * 3.0, b[1] + ny * 3.0)]
                _tint_lines(canvas, off, (86, 66, 44), 1.2)
        if f.hedge:
            pts = list(f.poly) + [f.poly[0]]
            # (the stroke above is the hedgerow; city parcels get neither it nor
            # the hedge props, and read as plots with a kerb instead of as
            # fenced planking)
            for i in range(len(pts) - 1):
                (ax, ay), (bx, by) = pts[i], pts[i + 1]
                ln = math.hypot(bx - ax, by - ay)
                n = max(1, int(ln / 26.0))
                for s in range(n):
                    t = (s + 0.5) / n
                    x, y = ax + (bx - ax) * t, ay + (by - ay) * t
                    if frng.random() < 0.82:      # hedges have gaps and gates
                        _prop(kit, canvas, "tree_clump", x, y,
                              frng.uniform(0.22, 0.34), frng, shadow=3.0)
