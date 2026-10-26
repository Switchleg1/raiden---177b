"""Roads, bridges and greens."""
from __future__ import annotations

import math
import random
from typing import Any

from ..design.geometry import _in_poly, _near_path
from ..plan.site_plan import SitePlan
from ..tilekit import TileKit
from .ink import _darken_band, _fill_mask, _prop, _splat, _tint_lines
from .mask import Mask
from .numpy_import import _numpy
from .raster import _disc_mask, _path_mask
from .road_table import BRIDGE, BRIDGE_DECK, SOILED_KINDS, SOILING
from .sampling import _band, _frand


def _seg_dist(x: float, y: float, path: list) -> float:
    """Distance from (x, y) to a polyline."""
    best = float("inf")
    for i in range(len(path) - 1):
        (ax, ay), (bx, by) = path[i], path[i + 1]
        vx, vy = bx - ax, by - ay
        ln2 = vx * vx + vy * vy
        t = 0.0 if ln2 <= 0.0 else max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / ln2))
        best = min(best, math.hypot(ax + t * vx - x, ay + t * vy - y))
    return best


def _densify(path: list, step: float) -> list:
    """The same route with a point every `step` px."""
    out = [path[0]]
    for (ax, ay), (bx, by) in zip(path, path[1:], strict=False):
        n = max(1, int(math.hypot(bx - ax, by - ay) / step))
        out.extend((ax + (bx - ax) * k / n, ay + (by - ay) * k / n)
                   for k in range(1, n + 1))
    return out


def _deck_run(plan: SitePlan, road: Any, x: float, y: float):
    """The stretch of THIS road that is over the water at a crossing, as
    (points, first wet index, last wet index): the bridge is the road itself
    where it is over water, so it follows the road's own line and curve.

    A deck drawn as a rectangle and rotated to "the road's heading" landed
    across the road rather than along it whenever the heading was not 0 or 90
    degrees (pygame rotates counter-clockwise, the plan's y runs down), and a
    rectangle cannot follow a road that bends on the bridge anyway.
    """
    pts = _densify(road.path, 4.0)
    i0 = min(range(len(pts)),
             key=lambda k: math.hypot(pts[k][0] - x, pts[k][1] - y))
    # the nearest body the road is actually OVER here, not the nearest body: a
    # deck by one bank of a river can be closer to a tributary beside it, and
    # asking that one found no water under the road and drew no bridge
    for body in sorted(plan.water, key=lambda w: _seg_dist(x, y, w.path)):
        def wet(k: int, body=body) -> bool:
            # a lake is a region: its `half` is the minor radius, and a deck more
            # than that from the shore - the middle of a causeway - is still on it
            if body.closed:
                return _in_poly(pts[k][0], pts[k][1], body.path)
            return _seg_dist(pts[k][0], pts[k][1], body.path) < body.half + 2.0

        near = [k for k in range(max(0, i0 - 20), min(len(pts), i0 + 21))
                if wet(k)]
        if near:
            i = min(near, key=lambda k: abs(k - i0))
            break
    else:
        return None
    # the WHOLE wet stretch, uncapped: the run must be the same whichever of a
    # causeway's deck points a window starts from, or two windows draw two
    # different decks and the seam between them shows
    lo = hi = i
    while lo > 0 and wet(lo - 1):
        lo -= 1
    while hi < len(pts) - 1 and wet(hi + 1):
        hi += 1
    land = BRIDGE["landing"] // 4
    a, b = max(0, lo - land), min(len(pts), hi + land + 1)
    return pts[a:b], lo - a, hi - a


def _in_window(canvas: Any, y: float, reach: float) -> bool:
    """Could something at plan row `y`, drawing `reach` px around it, touch this
    window? A looping one-screen map is always yes."""
    from .plane import Plane
    if not isinstance(canvas, Plane) or canvas.wrap:
        return True
    top = canvas.y0
    return top - reach <= y <= top + canvas.h * canvas.scale + reach


def _offset(pts: list, d: float) -> list:
    """A polyline displaced sideways by `d` (positive = the road's left)."""
    out = []
    for k, (x, y) in enumerate(pts):
        (ax, ay) = pts[max(0, k - 1)]
        (bx, by) = pts[min(len(pts) - 1, k + 1)]
        ln = math.hypot(bx - ax, by - ay) or 1.0
        out.append((x - (by - ay) / ln * d, y + (bx - ax) / ln * d))
    return out


def _wet_mask(canvas: Any, plan: SitePlan) -> Any:
    """The channels' footprint as an array: what a road must not be painted on."""
    np = _numpy()
    wet = np.zeros((canvas.w, canvas.h), dtype=np.float32)
    for w in plan.water:
        _path_mask(w.path, w.half * 2.0, canvas).paste(wet)
    return wet


def _bridge_cut(surf: Mask, wet: Any, deck: Any) -> Mask:
    """Cut the water out of a road mask and put the bridge decks back."""
    np = _numpy()
    box, arr = surf.clip(wet.shape[0], wet.shape[1])
    if arr is None:
        return surf
    x0, y0, x1, y1 = box
    kept = arr * (1.0 - wet[x0:x1, y0:y1])
    return Mask(np.maximum(kept, deck[x0:x1, y0:y1]), box)


def paint_roads(canvas: Any, kit: TileKit, plan: SitePlan,
                rng: random.Random) -> None:
    from ..theme_table import ROAD_MAT
    np = _numpy()
    wet = None            # the channels under this window, built once if needed
    for ri in _band(canvas, plan, "roads"):
        r = plan.roads[ri]
        frng = _frand(plan, ri, 29)
        mat = ROAD_MAT.get(plan.theme, "road_dirt")
        # shoulders first: dirt/grass soiling under the road edge, then the
        # road itself. Order matters: the road has a crisp edge, the shoulder
        # is what stops it looking pasted on.
        if r.shoulder > 0.0:
            # a wider band of gravel under the carriageway: the shoulder is what
            # stops a high-speed road looking like a stripe laid on grass
            _fill_mask(canvas, kit, "gravel_rubble",
                       _path_mask(r.path, r.width * 0.5 + r.shoulder, canvas),
                       0.85)
        shoulder = SOILING.get(plan.theme, "splat_dirt")
        if r.kind not in SOILED_KINDS:
            shoulder = None
        # Small and sparse: at the old scale these soiling blobs merged with the
        # road into one wide pale corridor whose identity - road? track? bare
        # ground? - stopped being readable.
        for i in range(0, len(r.path) - 1, 3):
            if shoulder is not None and frng.random() < 0.3:
                (ax, ay), (bx, by) = r.path[i], r.path[i + 1]
                side = 1.0 if frng.random() < 0.5 else -1.0
                ang = math.atan2(by - ay, bx - ax) + side * math.pi / 2
                d = r.width + frng.uniform(10.0, 22.0)
                sx, sy = ax + math.cos(ang) * d, ay + math.sin(ang) * d
                sc = frng.uniform(0.16, 0.3)
                # verge dirt, not a raft: a splat thrown off a bridge lay on the river
                if not any((w.closed and _in_poly(sx, sy, w.path))
                           or _near_path(plan.geom, sx, sy, w.path, w.half + 20.0)
                           for w in plan.water):
                    _splat(kit, canvas, shoulder, sx, sy, sc, frng)
        surf = _path_mask(r.path, r.width * 1.7, canvas)
        # A road that crosses a river does so on a bridge: the carriageway must
        # not smear into the channel, or the two become one corridor again. Cut
        # the water out of the road mask, then put the deck back at each
        # crossing so the bridge still spans its gap.
        runs = []
        # EVERY road stops at the water, bridged or not: a road that grazes a bank
        # has its kerb in the channel band and no bridge, and painting it through
        # the edge of the river is the "road fords the river" look. (This used to
        # happen only for roads with bridges, so the planner recorded decks on
        # grazes - bridges on dry land - to get the cut.)
        if plan.water:
            if wet is None:
                wet = _wet_mask(canvas, plan)
            deck = np.zeros((canvas.w, canvas.h), dtype=np.float32)
            seen = set()
            for bx, by in r.bridges:
                # only the crossings this window can show: every deck run is a walk
                # over the whole route, and a road down the strip has decks a
                # screen away from any one window
                if not _in_window(canvas, by, r.width + 120.0):
                    continue
                run = _deck_run(plan, r, bx, by)
                if run is None or (run[0][run[1]], run[0][run[2]]) in seen:
                    continue
                seen.add((run[0][run[1]], run[0][run[2]]))
                runs.append(run)
                _path_mask(run[0], r.width * 1.7 + 2.0 * BRIDGE["kerb"],
                           canvas).paste(deck)
            surf = _bridge_cut(surf, wet, deck)
            # the shadow goes on the water first, then the deck over it: what is
            # left of the shadow is the strip of water the deck shades
            for pts, _, _ in runs:
                sx, sy = BRIDGE["shadow"]
                shade = _path_mask([(x + sx, y + sy) for x, y in pts],
                                   r.width * 1.7 + 2.0 * BRIDGE["kerb"], canvas)
                box, arr = shade.clip(canvas.w, canvas.h)
                if arr is not None:
                    # on the water only: a shadow carried onto the bank is a
                    # smudge at each end of the bridge
                    x0, y0, x1, y1 = box
                    _darken_band(canvas, Mask(arr * wet[x0:x1, y0:y1], box),
                                 BRIDGE["shadow_dark"])
        _fill_mask(canvas, kit, mat, surf, 1.0)
        # a lit edge on both sides: a road that is only a darker band disappears
        # into dirt and shadow while it scrolls. The edges are what make it read
        # as a formed surface with a thickness.
        # A shoulder of the SAME material, wider and softer - but only a few px
        # wider: at the old width and alpha the soft band plus the carriageway
        # made a pale corridor the length of the map, and the review's verdict
        # was "a broad pale strip: dry channel, dirt clearing, or enormous road".
        _fill_mask(canvas, kit, mat,
                   _path_mask(r.path, r.width * 1.7 + 8.0, canvas),
                   0.22)
        # the deck: over the carriageway and its soft shoulder, a surface of
        # its own
        if runs:
            for pts, _, _ in runs:
                _fill_mask(canvas, kit, BRIDGE_DECK.get(mat, mat),
                           _path_mask(pts, r.width * 1.7 + 2.0 * BRIDGE["kerb"],
                                      canvas), 1.0)
        if mat == "road_asphalt" and r.kind == "main":
            step = 0.0
            for i in range(len(r.path) - 1):
                (ax, ay), (bx, by) = r.path[i], r.path[i + 1]
                ln = math.hypot(bx - ax, by - ay)
                step += ln
                if step > 46.0:
                    step = 0.0
                    mx, my = (ax + bx) / 2, (ay + by) / 2
                    _tint_lines(canvas, [(ax, ay), (mx, my)],
                                (190, 180, 120), 1)
        else:                                   # dirt: two wheel ruts
            for side in (-1.0, 1.0):
                pts = []
                for i in range(len(r.path) - 1):
                    (ax, ay), (bx, by) = r.path[i], r.path[i + 1]
                    ln = math.hypot(bx - ax, by - ay) or 1.0
                    nx, ny = -(by - ay) / ln, (bx - ax) / ln
                    d = r.width * 0.45 * side
                    pts.append((ax + nx * d, ay + ny * d))
                # the last point too: an edge is drawn along the whole route, and
                # a route of two points (a place's short track) has one segment -
                # appending only segment starts gave a ONE point polyline and
                # pygame.draw.lines raised inside the paint workers
                ex, ey = r.path[-1]
                ln = math.hypot(ex - r.path[-2][0], ey - r.path[-2][1]) or 1.0
                nx = -(ey - r.path[-2][1]) / ln
                ny = (ex - r.path[-2][0]) / ln
                pts.append((ex + nx * r.width * 0.45 * side,
                            ey + ny * r.width * 0.45 * side))
                _tint_lines(canvas, pts, (0, 0, 0), 1)
        for run in runs:
            _bridge(canvas, r, *run)


def _bridge(canvas: Any, road: Any, pts: list, lo: int, hi: int) -> None:
    """Parapets along both edges of the deck, running onto each bank, with a
    post where each one ends.

    Everything here is drawn from the road's own line, so a bridge cannot be at
    a different angle from the road it carries. (Abutments drawn as bars across
    the road at each bank read as a gate, or as the rungs of a ladder.)
    """
    half = road.width * 0.85 + BRIDGE["kerb"]
    land = BRIDGE["landing"] // 4
    span = pts[max(0, lo - land): hi + land + 1]
    if len(span) < 2:
        return
    for side in (-1.0, 1.0):
        _tint_lines(canvas, _offset(span, side * (half + 1.0)),
                    BRIDGE["rail_shade"], 2)
        rail = _offset(span, side * (half - 1.0))
        _tint_lines(canvas, rail, BRIDGE["rail"], 2)
        for end, inward in ((0, 1), (len(rail) - 1, -1)):
            nxt = rail[end + inward] if 0 <= end + inward < len(rail) else rail[end]
            _tint_lines(canvas, [rail[end], nxt], BRIDGE["post"], 4)


def paint_greens(canvas: Any, kit: TileKit, plan: SitePlan,
                 rng: random.Random) -> None:
    for gi in _band(canvas, plan, "greens"):
        g = plan.greens[gi]
        frng = _frand(plan, gi, 31)
        _fill_mask(canvas, kit, g.mat,
                   _disc_mask(g.x, g.y, g.radius, canvas), 0.95)
        for lane in g.lanes:
            _fill_mask(canvas, kit, "road_dirt",
                       _path_mask(lane, 11.0, canvas), 0.9)
        # a green has a stand of trees and often a stack of crates or a trough
        for _ in range(frng.randint(1, 3)):
            a = frng.uniform(0, math.tau)
            _prop(kit, canvas, "tree_clump", g.x + math.cos(a) * g.radius * 0.6,
                  g.y + math.sin(a) * g.radius * 0.6, frng.uniform(0.3, 0.45),
                  frng, shadow=4.0)
