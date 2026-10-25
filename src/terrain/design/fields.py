"""Fields: the flat dry ground the settlement left over, enclosed."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..plan.field import Field
from ..plan.geom import CELL
from .footprint import _mark_parcel
from .geometry import _clip_poly, _in_poly, _span

if TYPE_CHECKING:
    from ..plan.geom import Point
    from ..plan.site_plan import SitePlan
    from ..plan.site_spec import SiteSpec

import math
import random


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


def _field_mat(theme: str, kind: str) -> str:
    """A crop field is bare tilled earth. Painting a furrow line on grass is how
    the old maps pretended at farmland, and it is why nothing read as owned
    ground."""
    from ..theme_table import FIELD_MAT, FIELD_MAT_CITY
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
