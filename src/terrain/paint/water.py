"""Rivers and lakes that read as water from the air."""
from __future__ import annotations

import math
import random
from typing import Any

from ..design.geometry import _in_poly
from ..plan.site_plan import SitePlan
from ..tilekit import TileKit
from .ink import _darken_band, _fill_mask
from .raster import _disc_mask, _path_mask, _poly_mask, _raster_mask, _width_mask
from .sampling import _band, _frand


def _river_profile(w: Any) -> tuple[list[float], list[float]]:
    """Half-widths of a channel's water and of its bank, per path vertex.

    A river of one width is a road: constant width with a parallel edge either
    side is exactly what a carriageway looks like from the air, and that - plus a
    kerb line on each bank and white dashes down the middle - is why every river in
    the game read as a highway. Real channels breathe: wider in the pools, narrower
    over the riffles, the bank wider where the water has cut it back.

    Keyed to arc length along the PLAN's path and to the path's own start point, so
    the width at a world point is the same in every window that paints it.
    """
    import zlib
    x0, y0 = w.path[0]
    h = zlib.crc32(f"{round(x0)}:{round(y0)}:{w.kind}".encode())
    p1 = (h % 628) / 100.0
    p2 = (h // 628 % 628) / 100.0
    p3 = (h // 394384 % 628) / 100.0
    rw: list[float] = []
    rb: list[float] = []
    arc = 0.0
    prev = w.path[0]
    for pt in w.path:
        arc += math.hypot(pt[0] - prev[0], pt[1] - prev[1])
        prev = pt
        m = 1.0 + 0.22 * math.sin(arc / 280.0 + p1) + 0.10 * math.sin(arc / 90.0 + p2)
        r = w.half * max(0.62, m)
        rw.append(r)
        rb.append(r + 10.0 + 8.0 * (0.5 + 0.5 * math.sin(arc / 130.0 + p3)))
    return rw, rb


def _offset_path(path: list[tuple[float, float]], offs: list[float]
                 ) -> list[tuple[float, float]]:
    """The path displaced along its own normal by a per-vertex distance."""
    out = []
    n = len(path)
    for i, (x, y) in enumerate(path):
        ax, ay = path[max(0, i - 1)]
        bx, by = path[min(n - 1, i + 1)]
        ln = math.hypot(bx - ax, by - ay) or 1.0
        nx, ny = -(by - ay) / ln, (bx - ax) / ln
        out.append((x + nx * offs[i], y + ny * offs[i]))
    return out


def paint_water(canvas: Any, kit: TileKit, plan: SitePlan,
                rng: random.Random) -> None:
    """Rivers and lakes that read as WATER from the air.

    The order is the order real water is seen in: the riparian edge, the bank, the
    water, then depth (shallows light, the channel dark), then what the current
    leaves - sand on the inside of bends, a sheen on the side facing the light.
    Every pass runs over every body before the next pass starts, so one body's bank
    never lands on its neighbour's water.
    """
    from ..theme_table import WATER_BANK, WATER_EDGE_GREEN, WATER_MAT
    green = plan.theme in WATER_EDGE_GREEN
    bank_mat = WATER_BANK.get(plan.theme, "sand_canyon")
    feats = []
    for wi in _band(canvas, plan, "water"):
        w = plan.water[wi]
        frng = _frand(plan, wi, 17)
        # A CLOSED water body with an `inside` point is a REGION, not a channel: it
        # is filled, banked on the outside only, and has no current. Stroked like a
        # river it was a ring of water with a kerb either side and dashes down its
        # middle - "a circular roadway with the centre lines still inside".
        region = bool(w.closed) and w.inside is not None
        if region:
            # The shore band is a fixed band, not one scaled by the lake's own minor
            # radius: that painted 470 px of gravel around a 600-px lake, and it was
            # the widest soft mask in the plan, which is what put a line at a slice
            # boundary (a raster box and the feather at its edge belong to the window).
            rw = None
            bank_mask = _path_mask(w.path, min(w.half * 2.0 + 22.0, 70.0), canvas)
            edge_mask = _path_mask(w.path, 150.0, canvas) if green else None
            water_mask = _poly_mask(w.path, canvas)
        else:
            rw, rb = _river_profile(w)
            bank_mask = _width_mask(w.path, rb, canvas)
            edge_mask = (_width_mask(w.path, [r + 34.0 for r in rb], canvas, 4)
                         if green else None)
            water_mask = _width_mask(w.path, rw, canvas)
        feats.append((w, frng, region, bank_mask, water_mask, edge_mask, rw))
    # Standing water wins over a channel's furniture: a river flowing THROUGH a lake
    # must not lay its sand bars and sheen on the lake. Pure geometry (a point inside
    # a closed outline), so it cannot depend on which window is painting.
    bodies = [x for x in plan.water if x.closed]

    def in_standing(px: float, py: float) -> bool:
        return any(_in_poly(px, py, b.path) for b in bodies)

    # 1. the riparian edge: the grass by water is rougher and wetter than a field
    for f in feats:
        if f[5] is not None:
            _fill_mask(canvas, kit, "grass_patchy", f[5], 0.45)
    # 2. the bank: earth and sand, not grey gravel - gravel either side of a dark
    #    band is a road's verge
    for f in feats:
        _fill_mask(canvas, kit, bank_mat, f[3], 0.6)
    # 3. the water
    for f in feats:
        _fill_mask(canvas, kit, WATER_MAT.get(plan.theme, "water_river"), f[4], 1.0)
    # 4. depth. A DRY wash is lightened instead: a desert arroyo is pale sand
    #    between darker desert pavement, and darkening one turns it into a scratch.
    for w, _frng, region, _bm, wm, _em, rw in feats:
        if w.kind in ("wash", "arroyo"):
            _darken_band(canvas, wm, 1.12)
            continue
        _darken_band(canvas, wm, 0.84)
        if region:
            cx, cy = w.inside
            core = [(cx + (x - cx) * 0.7, cy + (y - cy) * 0.7) for x, y in w.path]
            _darken_band(canvas, _raster_mask(core, 0.0, 7, canvas, poly=True), 0.8)
        else:
            _darken_band(canvas, _width_mask(w.path, [r * 0.5 for r in rw], canvas,
                                             4), 0.82)
    # 5. what the current leaves
    for w, frng, region, _bm, _wm, _em, rw in feats:
        if region or w.kind in ("wash", "arroyo"):
            continue
        n = len(w.path)
        # point bars: sand deposited on the INSIDE of a bend, half in the water
        for i in range(3, n - 3, 4):
            (ax, ay), (bx, by), (qx, qy) = w.path[i - 3], w.path[i], w.path[i + 3]
            turn = (bx - ax) * (qy - by) - (by - ay) * (qx - bx)
            la = math.hypot(bx - ax, by - ay) * math.hypot(qx - bx, qy - by) or 1.0
            if abs(turn / la) < 0.18:
                continue
            ln = math.hypot(qx - ax, qy - ay) or 1.0
            nx, ny = -(qy - ay) / ln, (qx - ax) / ln
            side = 1.0 if turn > 0 else -1.0
            px, py = bx + nx * side * rw[i] * 0.85, by + ny * side * rw[i] * 0.85
            if in_standing(px, py):
                continue
            _fill_mask(canvas, kit, bank_mat,
                       _disc_mask(px, py, rw[i] * frng.uniform(0.5, 0.8), canvas, 4),
                       0.7)
        # the sheen: a soft lit band on the side facing the light, which is how a
        # river shows its surface from the air - instead of dashes down its middle
        offs = []
        for i in range(n):
            ax, ay = w.path[max(0, i - 1)]
            bx, by = w.path[min(n - 1, i + 1)]
            ln = math.hypot(bx - ax, by - ay) or 1.0
            nx, ny = -(by - ay) / ln, (bx - ax) / ln
            toward = -0.6 * nx - 0.7 * ny          # light from the upper left
            offs.append(rw[i] * 0.42 * (1.0 if toward > 0 else -1.0))
        sheen = _offset_path(w.path, offs)
        keep = [not in_standing(x, y) for x, y in sheen]
        run: list[int] = []
        for i in range(n + 1):
            if i < n and keep[i]:
                run.append(i)
                continue
            if len(run) > 2:
                _darken_band(canvas, _width_mask([sheen[k] for k in run],
                                                 [rw[k] * 0.2 for k in run], canvas,
                                                 4), 1.22)
            run = []
