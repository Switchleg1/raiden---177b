"""Roads, bridges and greens."""
from __future__ import annotations

import math
import random
from typing import Any

from ..plan.site_plan import SitePlan
from ..tilekit import TileKit
from .ink import _fill_mask, _prop, _splat, _tint_lines
from .mask import Mask
from .numpy_import import _numpy
from .raster import _disc_mask, _path_mask
from .road_table import SOILED_KINDS, SOILING
from .sampling import _band, _frand
from .surface import _blit_wrap, _shadow_on


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
                _splat(kit, canvas, shoulder, ax + math.cos(ang) * d,
                       ay + math.sin(ang) * d, frng.uniform(0.16, 0.3), frng)
        surf = _path_mask(r.path, r.width * 1.7, canvas)
        # A road that crosses a river does so on a bridge: the carriageway must
        # not smear into the channel, or the two become one corridor again. Cut
        # the water out of the road mask, then put the deck back at each
        # crossing so the bridge still spans its gap.
        if plan.water and r.bridges:
            wet = np.zeros((canvas.w, canvas.h), dtype=np.float32)
            for w in plan.water:
                _path_mask(w.path, w.half * 2.0, canvas).paste(wet)
            deck = np.zeros((canvas.w, canvas.h), dtype=np.float32)
            for bx, by in r.bridges:
                _path_mask([(bx - 40.0, by), (bx + 40.0, by)],
                           r.width * 2.6, canvas).paste(deck)
            surf = _bridge_cut(surf, wet, deck)
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
    for ri in _band(canvas, plan, "roads"):
        r = plan.roads[ri]
        frng = _frand(plan, ri, 29)
        for (bx, by) in r.bridges:
            _bridge(canvas, kit, r, bx, by, frng)


def _bridge(canvas: Any, kit: TileKit, road: Any, x: float, y: float,
            rng: random.Random) -> None:
    """A deck across the water with abutments: where the road meets a river,
    the road does not simply continue over it."""
    import pygame
    ln = road.width * 3.0
    ang = 0.0
    for i in range(len(road.path) - 1):
        ax, ay = road.path[i]
        if math.hypot(ax - x, ay - y) < 60.0:
            bx2, by2 = road.path[i + 1]
            ang = math.atan2(by2 - ay, bx2 - ax)
            break
    deck = pygame.Surface((int(ln * 2), int(road.width * 2.6)),
                          pygame.SRCALPHA)
    deck.fill((0, 0, 0, 0))
    pygame.draw.rect(deck, (96, 74, 48),
                     (0, 0, deck.get_width(), deck.get_height()))
    for px in range(0, deck.get_width(), 7):          # planks
        pygame.draw.line(deck, (70, 54, 36), (px, 0), (px, deck.get_height()))
    pygame.draw.rect(deck, (58, 44, 30),
                     (0, 0, deck.get_width(), deck.get_height()), 2)
    d = pygame.transform.rotozoom(deck, math.degrees(ang), 1.0)
    _shadow_on(canvas, x + 4, y + 5, d.get_width() * 0.5, d.get_height() * 0.5,
               80)
    _blit_wrap(canvas, d, x - d.get_width() / 2, y - d.get_height() / 2)


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
