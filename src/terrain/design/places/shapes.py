"""Outlines a place is drawn with: quads, ellipses, shores."""
from __future__ import annotations

import math
import random

from ...plan.geom import Point


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
