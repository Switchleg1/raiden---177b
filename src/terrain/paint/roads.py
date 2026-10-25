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
from .surface import _blit_wrap, _shadow_on, _target


def _wet_span(plan: SitePlan, x: float, y: float) -> float:
    """Half-length, along the road, of the water a bridge has to clear: the
    channel's own half-width at the crossing, from the body actually under it.
    A deck sized from a constant (or from the widest body in the sector) stood on
    the bank as a platform and was wider than the road it carried."""
    best, span = float("inf"), 0.0
    for w in plan.water:
        d = min(math.hypot(px - x, py - y) for px, py in w.path)
        if d < best:
            best, span = d, w.half + 16.0
    return span if best < 260.0 else 0.0


def _wet_mask(canvas: Any, plan: SitePlan) -> Any:
    """The channels' footprint as an array: what a road must not be painted on."""
    np = _numpy()
    wet = np.zeros((canvas.w, canvas.h), dtype=np.float32)
    for w in plan.water:
        _path_mask(w.path, w.half * 2.0, canvas).paste(wet)
    return wet


def _heading_at(path: list, x: float, y: float) -> float:
    """The direction a route is running where it passes (x, y).

    A vertex test ("the first corner within 60 px") silently kept the default of
    0 - straight along the road - for every crossing that fell BETWEEN two
    vertices, so those decks were planks laid along the street, on dry land, a
    field away from the water they were built over.
    """
    best, ang = float("inf"), 0.0
    for i in range(len(path) - 1):
        (ax, ay), (bx, by) = path[i], path[i + 1]
        vx, vy = bx - ax, by - ay
        ln2 = vx * vx + vy * vy
        if ln2 <= 0.0:
            continue
        t = max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / ln2))
        d = math.hypot(ax + t * vx - x, ay + t * vy - y)
        if d < best:
            best, ang = d, math.atan2(vy, vx)
    return ang


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
            wet = _wet_mask(canvas, plan)
            deck = np.zeros((canvas.w, canvas.h), dtype=np.float32)
            for bx, by in r.bridges:
                # a bridge with nothing under it still must not leave a gap in
                # the carriageway, so it keeps a nominal deck
                span = _wet_span(plan, bx, by) or 40.0
                ang = _heading_at(r.path, bx, by)
                dx, dy = math.cos(ang) * span, math.sin(ang) * span
                _path_mask([(bx - dx, by - dy), (bx + dx, by + dy)],
                           r.width * 1.35, canvas).paste(deck)
            surf = _bridge_cut(surf, wet, deck)
            decks = wet
        else:
            decks = None
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
            _bridge(canvas, kit, plan, r, bx, by, frng, decks)


def _bridge(canvas: Any, kit: TileKit, plan: SitePlan, road: Any, x: float,
            y: float, rng: random.Random, wet: Any = None) -> None:
    """A deck across the water with abutments: where the road meets a river,
    the road does not simply continue over it."""
    import pygame
    # The deck runs across the channel it was built over, along the road's own
    # heading AT the crossing, and spans the water and no further: at the old
    # fixed length it lay on the bank as a platform, and at the old angle it lay
    # anywhere.
    ang = _heading_at(road.path, x, y)
    span = max(26.0, _wet_span(plan, x, y))
    ln = span + 8.0
    deck = pygame.Surface((int(ln * 2), int(road.width * 1.5)),
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
    if wet is None:
        _blit_wrap(canvas, d, x - d.get_width() / 2, y - d.get_height() / 2)
        return
    # Only the part of the deck that lies OVER the channel is drawn. Cut out of
    # the carriageway, the gap is exactly as wide as the water; a full rectangle
    # of planks hanging past the bank is what made a bridge read as a hut, and
    # where the road did not run over the crossing it read as a platform in a
    # field - the deck was drawn at the crossing, the carriageway was not.
    from .plane import Plane
    np = _numpy()
    lay = _target(canvas)
    lx, ly = canvas.local(x - d.get_width() / 2.0,
                          y - d.get_height() / 2.0) \
        if isinstance(canvas, Plane) else \
        (int(round(x - d.get_width() / 2.0)), int(round(y - d.get_height() / 2.0)))
    lay.blit(d, (lx, ly))
    cx0, cy0 = max(0, lx), max(0, ly)
    cx1 = min(canvas.w, lx + d.get_width())
    cy1 = min(canvas.h, ly + d.get_height())
    if cx1 <= cx0 or cy1 <= cy0:
        return
    view = pygame.surfarray.pixels_alpha(lay)
    keep = np.clip(wet[cx0:cx1, cy0:cy1] * 255.0, 0.0, 255.0).astype(np.uint8)
    view[cx0:cx1, cy0:cy1] = (view[cx0:cx1, cy0:cy1].astype(np.uint16)
                              * keep // 255).astype(np.uint8)
    del view
    canvas.touch_box(cx0, cy0, cx1, cy1) if isinstance(canvas, Plane) else None


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
