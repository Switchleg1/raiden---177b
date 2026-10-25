"""Landforms: ridges, crests and mountain ranges."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..plan.geom import CELL, SCREEN_H, SCREEN_W
from ..plan.ridge import Ridge
from .crest_table import CRESTS, RIDGE_ARMS
from .geometry import _along, _hpath, _vpath

if TYPE_CHECKING:
    from ..plan.geom import Geom, Point
    from ..plan.site_spec import SiteSpec

import math
import random


def _crest(shape: str, rng: random.Random) -> tuple[list[float], float]:
    """Crest height along the spine, sampled at N points, plus a plateau bias.

    Each shape is a real ridge cross-section, not a random profile:
    """
    n = 40
    h = CRESTS.get(shape, CRESTS["ridge"])(n, rng)
    # one shared smoothing pass: a crest is continuous rock, never a step
    for _ in range(2):
        h = [h[i] if 0 < i < n - 1 else h[i] * 0.9
             for i in range(n)]
        h = [(h[max(0, i - 1)] + 2 * h[i] + h[min(n - 1, i + 1)]) / 4.0
             for i in range(n)]
    return h, (max(h) or 1.0)


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
        arms = RIDGE_ARMS[shape]
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


def _path_relief(g: Geom, relief: list[list[float]], path: list[Point]) -> float:
    return sum(relief[g.row(y)][g.col(x)] for x, y in path) / max(1, len(path))


def _path_max(g: Geom, relief: list[list[float]], path: list[Point]) -> float:
    return max(relief[g.row(y)][g.col(x)] for x, y in path)
