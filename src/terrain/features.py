"""Turning a :mod:`~terrain.siteplan` into pixels.

The plan says what the ground *is*; this paints it, and the two halves agree on
one thing: **a feature is a shape with an edge, not a stamp**. Roads, rivers,
fields and ridge flanks are cut out as masks and filled with the tileset
material through them, which is why their boundaries are curves instead of the
square steps a row of 160 px tile blits leaves behind. Props stay stamps - a
tree is a sprite - but they now sit where the plan put them: in woods that
cluster, along water that meanders, on the contour where the hillside turns, and
in lines along a ridge foot, which is what makes a ridge read as a ridge.

Relief is the one thing that cannot be a sprite. The plan's 40 px relief grid is
upsampled to canvas resolution, smoothed, and shaded from its own slope with the
light coming from the top left, so a ridge has a lit flank and a shadowed one
and a mesa's cliff edge is an actual edge.

Everything here is bake-time only: the game loads the PNGs that
``scripts/bake_terrain.py`` writes from this code.
"""
from __future__ import annotations

import math
import random
from typing import Any

from .siteplan import CH, CW, SitePlan
from .theme_table import ROCK
from .tilekit import TILE, TileKit

_TILED: dict[str, Any] = {}          # material tiled to canvas size, cached
_ARR: dict[str, Any] = {}            # the same, as float32 numpy (W,H,3)
_TILE3: dict[str, Any] = {}          # one material tile as uint8 (TILE,TILE,3)
_VIEWS: dict[tuple, Any] = {}        # material as it lies under one window
_SOFT: list[Any] = []                # one soft shadow blob, built once


# ---------------------------------------------------------------------------
# the plane: pixels as numbers, for the whole pass
# ---------------------------------------------------------------------------

class Plane:
    """A bake-space ground layer held as numpy arrays while it is painted.

    Every feature here is a mask filled with a material, which is arithmetic.
    The canvas used to be a pygame surface, so each of the ~24 fills read 1.8 M
    pixels out of the surface and wrote them back: 5.2 s for one map. The plane
    keeps the pixels as arrays, folds in the sprite layer only when a fill needs
    to see it, and converts to a surface once. It is also what makes a strip
    paintable in windows: a window is a row range of the same arrays.
    """

    def __init__(self, w: int, h: int, x0: int = 0, y0: int = 0,
                 wrap: float = 0.0) -> None:
        import pygame
        np = _numpy()
        self.w, self.h = w, h
        # where this window sits in plan coordinates. A strip is painted as a
        # run of windows; the world position is what keeps materials, masks and
        # props in the same place in every window that touches them.
        self.x0, self.y0 = int(x0), int(y0)
        # a plan that loops in y paints its seam copies; a strip does not
        self.wrap = float(wrap)
        self.rgb = np.zeros((w, h, 3), dtype=np.float32)
        self.a = np.zeros((w, h), dtype=np.float32)     # 0..1
        self._layer = pygame.Surface((w, h), pygame.SRCALPHA)
        self._dirty = False
        self._box: tuple[int, int, int, int] | None = None

    def shifts(self) -> tuple[float, ...]:
        """y offsets a shape must be stamped at: the seam copies of a looping
        map, nothing else for a strip."""
        if not self.wrap:
            return (0.0,)
        return (0.0, -self.wrap, self.wrap)

    def local(self, x: float, y: float) -> tuple[int, int]:
        return int(round(x - self.x0)), int(round(y - self.y0))

    @property
    def stamp(self) -> Any:
        """The sprite layer: props, decks, strokes. Reading it marks it dirty."""
        self._dirty = True
        return self._layer

    def touch(self) -> None:
        self._dirty = True

    def touch_box(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """Register where a stamp or stroke landed, so the fold-in only has to
        read that part of the sprite layer."""
        self._dirty = True
        bx0, by0 = max(0, int(x0)), max(0, int(y0))
        bx1 = min(self.w, int(x1) + 1)
        by1 = min(self.h, int(y1) + 1)
        if bx1 <= bx0 or by1 <= by0:
            return
        if self._box is None:
            self._box = (bx0, by0, bx1, by1)
        else:
            px0, py0, px1, py1 = self._box
            self._box = (min(px0, bx0), min(py0, by0),
                         max(px1, bx1), max(py1, by1))

    def sync(self) -> None:
        """Fold the sprite layer into the arrays - only over the box that was
        stamped since the last fold, which for a prop or a stroke is a small
        fraction of the canvas."""
        if not self._dirty:
            return
        import pygame
        np = _numpy()
        box = self._box or (0, 0, self.w, self.h)
        x0, y0, x1, y1 = box
        view = self._layer.subsurface(pygame.Rect(x0, y0, x1 - x0, y1 - y0))
        s = np.asarray(pygame.surfarray.array3d(view), dtype=np.float32)
        sa = np.asarray(pygame.surfarray.array_alpha(view),
                        dtype=np.float32) * (1.0 / 255.0)
        m = sa[:, :, None]
        rgb = self.rgb[x0:x1, y0:y1]
        rgb[...] = rgb * (1.0 - m) + s * m
        a = self.a[x0:x1, y0:y1]
        a[...] = np.maximum(a, sa)
        self._layer.fill((0, 0, 0, 0), pygame.Rect(x0, y0, x1 - x0, y1 - y0))
        self._dirty = False
        self._box = None

    def surface(self) -> Any:
        """The finished layer as a pygame surface."""
        import pygame
        np = _numpy()
        self.sync()
        rgba = np.dstack([np.clip(self.rgb, 0.0, 255.0).astype(np.uint8),
                          np.clip(self.a * 255.0, 0.0, 255.0).astype(np.uint8)])
        out = pygame.image.fromstring(
            np.ascontiguousarray(rgba.transpose(1, 0, 2)).tobytes(),
            (self.w, self.h), "RGBA")
        if pygame.display.get_init():
            out = out.convert_alpha()
        return out


def _target(canvas: Any) -> Any:
    """The pygame layer to draw sprites on, whether the caller holds a Plane or
    a bare surface (the hand-composed vector painters still pass one)."""
    return canvas.stamp if isinstance(canvas, Plane) else canvas


# ---------------------------------------------------------------------------
# small shared pieces
# ---------------------------------------------------------------------------

def _numpy() -> Any:
    try:
        import numpy as np
        return np
    except ImportError:                                   # pragma: no cover
        return None


def _tiled(kit: TileKit, mat: str) -> Any:
    """A canvas-sized surface of one material, cached by name."""
    import pygame
    key = mat
    if key not in _TILED:
        surf = pygame.Surface((CW, CH))
        tile = kit.material(mat)
        for y in range(0, CH, TILE):
            for x in range(0, CW, TILE):
                surf.blit(tile, (x, y))
        _TILED[key] = surf
    return _TILED[key]


def _tile3(kit: TileKit, mat: str) -> Any:
    """One 160 px material tile as uint8 (x, y, 3), cached."""
    import pygame
    np = _numpy()
    if mat not in _TILE3:
        t = kit.material(mat)
        _TILE3[mat] = np.ascontiguousarray(
            np.asarray(pygame.surfarray.array3d(t)))
    return _TILE3[mat]


def _view(kit: TileKit, mat: str, plane: Plane) -> Any:
    """The material tiling as it lies under this window, uint8 (x, y, 3).

    The tile grid is fixed in WORLD coordinates: two windows of one strip read
    the same material at the same world position, so the tile phase cannot jump
    at a chunk boundary. That is the seam a player would actually see.
    """
    np = _numpy()
    key = (mat, plane.x0, plane.y0, plane.w, plane.h)
    v = _VIEWS.get(key)
    if v is None:
        if len(_VIEWS) > 24:                    # windows come and go; do not
            _VIEWS.clear()                      # grow with the sector
        tile = _tile3(kit, mat)
        reps_x = plane.w // TILE + 2
        reps_y = plane.h // TILE + 2
        big = np.tile(tile, (reps_x, reps_y, 1))
        ox, oy = plane.x0 % TILE, plane.y0 % TILE
        v = np.ascontiguousarray(big[ox:ox + plane.w, oy:oy + plane.h, :])
        _VIEWS[key] = v
    return v


def _mat_array(kit: TileKit, mat: str) -> Any:
    """The canvas-sized material as float32 numpy (W,H,3), cached. Filling a
    mask and shading a relief field both need the same material as numbers, and
    tiling it once per material is why a map bakes in a second, not a minute."""
    import pygame
    np = _numpy()
    if mat not in _ARR:
        _ARR[mat] = np.asarray(pygame.surfarray.array3d(
            _tiled(kit, mat)), dtype=np.float32)
    return _ARR[mat]


def _blur(a: Any, passes: int) -> Any:
    np = _numpy()
    out = a
    for _ in range(passes):
        out = (out + np.roll(out, 1, 0) + np.roll(out, -1, 0)
               + np.roll(out, 1, 1) + np.roll(out, -1, 1)) / 5.0
    return out


def _soft_shadow() -> Any:
    """A radial alpha blob, reused for every prop shadow."""
    import pygame
    if not _SOFT:
        r = 64
        s = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        for i in range(r, 0, -1):
            a = int(120 * (1.0 - i / r) ** 1.6)
            pygame.draw.circle(s, (0, 0, 0, a), (r, r), i)
        _SOFT.append(s)
    return _SOFT[0]


def _shadow_on(canvas: Any, x: float, y: float, rx: float, ry: float,
               alpha: int = 90) -> None:
    import pygame
    s = _soft_shadow()
    w = max(4, int(rx * 2))
    h = max(4, int(ry * 2))
    sh = pygame.transform.smoothscale(s, (w, h))
    sh.set_alpha(alpha)
    _blit_wrap(canvas, sh, x - w / 2, y - h / 2)


def _blit_wrap(canvas: Any, img: Any, x: float, y: float) -> None:
    """Stamp a sprite, in window coordinates, plus its seam copies."""
    surf = _target(canvas)
    if not isinstance(canvas, Plane):                # bare surface (legacy)
        xi, yi = int(round(x)), int(round(y % CH))
        span = CH
    else:
        xi, yi = canvas.local(x, y)
        span = int(canvas.wrap)
    surf.blit(img, (xi, yi))
    canvas.touch_box(xi, yi, xi + img.get_width(), yi + img.get_height()) \
        if isinstance(canvas, Plane) else None
    if span:
        if yi + img.get_height() > span:
            surf.blit(img, (xi, yi - span))
        if yi - img.get_height() < 0:
            surf.blit(img, (xi, yi + span))


class Mask:
    """A float32 mask plus the box of canvas it covers, stored as (x, y).

    Every fill is arithmetic over a mask, and a road, a river, a field or a
    tree crown only covers a corridor or a blob: painting that box instead of
    the whole 1.8 M-pixel canvas is the difference between ~100 ms and ~5 ms a
    fill, and it is what makes a window of a long strip paintable at all.
    """

    __slots__ = ("arr", "box")

    def __init__(self, arr: Any, box: tuple[int, int, int, int]) -> None:
        self.arr = arr
        self.box = box

    def full(self) -> Any:
        """A canvas-sized copy, for the few callers that shade the whole map."""
        np = _numpy()
        out = np.zeros((CW, CH), dtype=np.float32)
        self.paste(out)
        return out

    def paste(self, dst: Any) -> None:
        """Union this mask into a canvas-sized one."""
        np = _numpy()
        x0, y0, x1, y1 = self.box
        dst[x0:x1, y0:y1] = np.maximum(dst[x0:x1, y0:y1], self.arr)


def _path_mask(path: list[tuple[float, float]], width: float,
               plane: Plane) -> Mask:
    """Alpha mask (numpy, H x W) of a path painted with a **round brush**.

    A thick ``pygame.draw.lines`` has no round joins: at any bend it leaves
    square steps, and those steps are exactly the "the ground shows its
    construction grid" artefact the tileset used to produce. Walking the path in
    small steps and stamping a disc gives a real road edge, and lets the width
    vary along the run - a road that widens at a junction and narrows on a
    bridge approach is a road a player believes.

    The raster runs over the geometry's own bounding box, not the whole canvas:
    the mask is zero outside it, and feathering a 90x960 array is worth doing
    when the alternative is feathering 1.8 M pixels two dozen times per map.
    """
    import pygame
    np = _numpy()
    r = max(1.0, width * 0.5)
    painted = _raster(path, r, plane)
    if painted is None:
        # an empty mask still has to describe itself: box and array agree,
        # or a caller that slices by the box reads someone else's pixels
        return Mask(np.zeros((1, 1), dtype=np.float32), (0, 0, 1, 1))
    (x0, y0, x1, y1), surf = painted
    m = np.asarray(pygame.surfarray.array3d(surf))[:, :, 0].astype(np.float32)
    m = _feather(m * (1.0 / 255.0), 2)
    return Mask(m, (x0, y0, x1, y1))


def _raster(path: list[tuple[float, float]], r: float, plane: Plane,
            poly: bool = False) -> Any:
    """Rasterize a brushstroke (or a polygon) over just the box it covers.

    Returns ``((x0, y0, x1, y1), surface)`` in PLANE coordinates, or None when
    the geometry misses this window - which is the other half of why painting a
    strip in chunks is cheap: a window skips every feature that is not in it.
    The 4 px margin is the room a feather pass needs."""
    import pygame
    lo_x = min(p[0] for p in path) - r
    hi_x = max(p[0] for p in path) + r
    ys = [p[1] + sh for p in path for sh in plane.shifts()]
    lo_y, hi_y = min(ys) - r, max(ys) + r
    x0 = max(0, int(lo_x - plane.x0) - 4)
    y0 = max(0, int(lo_y - plane.y0) - 4)
    x1 = min(plane.w, int(hi_x - plane.x0) + 5)
    y1 = min(plane.h, int(hi_y - plane.y0) + 5)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    surf = pygame.Surface((x1 - x0, y1 - y0))
    surf.fill((0, 0, 0))
    for shift in plane.shifts():
        pts = [(x - plane.x0 - x0, y + shift - plane.y0 - y0)
               for x, y in path]
        if max(p[1] for p in pts) < -60 \
                or min(p[1] for p in pts) > surf.get_height() + 60:
            continue
        if poly:
            pygame.draw.polygon(surf, (255, 255, 255),
                                [(int(px), int(py)) for px, py in pts])
            continue
        for i in range(len(pts) - 1):
            (ax, ay), (bx, by) = pts[i], pts[i + 1]
            ln = math.hypot(bx - ax, by - ay)
            n = max(1, int(ln / max(2.0, r * 0.35)))
            for s in range(n + 1):
                t = s / n
                pygame.draw.circle(surf, (255, 255, 255),
                                   (int(ax + (bx - ax) * t),
                                    int(ay + (by - ay) * t)), int(r))
    return (x0, y0, x1, y1), surf


def _feather(m: Any, passes: int) -> Any:
    """Soften a mask edge, in the mask's own box."""
    np = _numpy()
    for _ in range(passes):
        m = (m + np.roll(m, 1, 0) + np.roll(m, -1, 0)
             + np.roll(m, 1, 1) + np.roll(m, -1, 1)) / 5.0
    return m


def _paste(mask: Any, painted: Any, feather: int) -> Any:
    import pygame
    np = _numpy()
    (x0, y0, x1, y1), surf = painted
    m = np.asarray(pygame.surfarray.array3d(surf))[:, :, 0].astype(np.float32)
    m = _feather(m * (1.0 / 255.0), feather)
    mask[x0:x1, y0:y1] = np.maximum(mask[x0:x1, y0:y1], m)
    return mask


def _poly_mask(poly: list[tuple[float, float]], plane: Plane,
               feather: int = 3) -> Mask:
    return _raster_mask(poly, 0.0, feather, plane, poly=True)


def _disc_mask(x: float, y: float, radius: float, plane: Plane,
               feather: int = 4) -> Mask:
    """A soft circular mask - the shape of a tree crown, a green, a yard."""
    return _raster_mask([(x, y)], max(1.0, radius), feather, plane)


def _raster_mask(path: list[tuple[float, float]], r: float, feather: int,
                 plane: Plane, poly: bool = False) -> Mask:
    import pygame
    np = _numpy()
    painted = _raster(path, r, plane, poly=poly)
    if painted is None:
        # an empty mask still has to describe itself: box and array agree,
        # or a caller that slices by the box reads someone else's pixels
        return Mask(np.zeros((1, 1), dtype=np.float32), (0, 0, 1, 1))
    (x0, y0, x1, y1), surf = painted
    m = np.asarray(pygame.surfarray.array3d(surf))[:, :, 0].astype(np.float32)
    return Mask(_feather(m * (1.0 / 255.0), feather), (x0, y0, x1, y1))


def _fill_mask(canvas: Any, kit: TileKit, mat: str, mask: Any,
               strength: float = 1.0) -> None:
    """Fill a material through a mask, keeping the layer's alpha. The curve comes
    from the mask, not from the tile grid - which is exactly where the old
    square-edged road shoulders came from."""
    np = _numpy()
    if np is None or not isinstance(canvas, Plane):   # pragma: no cover
        return
    box = mask.box if isinstance(mask, Mask) else (0, 0, canvas.w, canvas.h)
    if box[2] <= box[0] or box[3] <= box[1]:
        return
    arr = mask.arr if isinstance(mask, Mask) else mask
    m = np.clip(np.asarray(arr, dtype=np.float32) * strength, 0.0, 1.0)
    if m.ndim == 3:
        m = m[:, :, 0]
    canvas.sync()
    x0, y0, x1, y1 = box
    mm = m[:, :, None]
    rgb = canvas.rgb[x0:x1, y0:y1]
    src = _view(kit, mat, canvas)[x0:x1, y0:y1].astype(np.float32)
    rgb[...] = rgb * (1.0 - mm) + src * mm
    a = canvas.a[x0:x1, y0:y1]
    a[...] = np.maximum(a, m)


def _darken_band(canvas: Any, mask: Any, factor: float) -> None:
    """Multiply the pixels under a mask by ``factor``: the same surface, less
    light. Water is read as much by its value as by its hue."""
    np = _numpy()
    if np is None or not isinstance(canvas, Plane):   # pragma: no cover
        return
    box = mask.box if isinstance(mask, Mask) else (0, 0, canvas.w, canvas.h)
    if box[2] <= box[0] or box[3] <= box[1]:
        return
    arr = mask.arr if isinstance(mask, Mask) else mask
    m = np.clip(np.asarray(arr, dtype=np.float32), 0.0, 1.0)
    if m.ndim == 3:
        m = m[:, :, 0]
    canvas.sync()
    x0, y0, x1, y1 = box
    rgb = canvas.rgb[x0:x1, y0:y1]
    rgb[...] = rgb * (1.0 - m[:, :, None] * (1.0 - factor))


def _tint_lines(canvas: Any, pts: list[tuple[float, float]], col: Any,
                width: float, shift_wraps: bool = True) -> None:
    """A stroke on the sprite layer, in window coordinates."""
    import pygame
    surf = _target(canvas)
    if isinstance(canvas, Plane):
        shifts = canvas.shifts() if shift_wraps else (0.0,)
        ox, oy = canvas.x0, canvas.y0
        lo, hi = 0, canvas.h
    else:                                            # bare surface (legacy)
        shifts = (0, -CH, CH) if shift_wraps else (0,)
        ox, oy = 0, 0
        lo, hi = 0, CH
    for shift in shifts:
        seg = [(x - ox, y + shift - oy) for x, y in pts]
        if max(p[1] for p in seg) < lo - 20 or min(p[1] for p in seg) > hi + 20:
            continue
        pygame.draw.lines(surf, col, False,
                          [(int(x), int(y)) for x, y in seg],
                          max(1, int(width)))
        if isinstance(canvas, Plane):
            canvas.touch_box(min(p[0] for p in seg) - width,
                             min(p[1] for p in seg) - width,
                             max(p[0] for p in seg) + width,
                             max(p[1] for p in seg) + width)


def _splat(kit: TileKit, canvas: Any, name: str, x: float, y: float,
           s: float, rng: random.Random) -> None:
    import pygame
    p = pygame.transform.rotozoom(kit.splats[name], rng.randint(0, 359), s)
    _blit_wrap(canvas, p, x - p.get_width() / 2, y - p.get_height() / 2)


def _prop(kit: TileKit, canvas: Any, name: str, x: float, y: float,
          s: float, rng: random.Random, rot4: bool = True,
          shadow: float = 0.0) -> None:
    import pygame
    if name not in kit.props:
        return
    p = kit.props[name]
    ang = rng.choice((0, 90, 180, 270)) if rot4 else 0
    p = pygame.transform.rotozoom(p, ang, s)
    if rng.random() < 0.5:
        p = pygame.transform.flip(p, True, False)
    if shadow > 0:
        _shadow_on(canvas, x + shadow * 0.5, y + shadow * 0.7,
                   p.get_width() * 0.45, p.get_height() * 0.4, 70)
    _blit_wrap(canvas, p, x - p.get_width() / 2, y - p.get_height() / 2)


# ---------------------------------------------------------------------------
# relief: the one thing that has to be painted, not stamped
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def _upsample(grid: Any, plane: Plane, gw: int, gh: int) -> Any:
    """Resample the planning grid over one window with **Catmull-Rom**, in
    pygame's (x, y) order.

    Bilinear was the wrong interpolant: it is only C0, so its derivative jumps
    at every cell boundary, and a slope-shaded field paints those jumps as lit
    and dark stripes - exactly the "blurred vertical bands" and "separate
    raised blobs" the art review kept naming. A cubic kernel is C1, so the
    shading has nothing to draw.

    Sampling is driven by WORLD position, so two windows of a strip meet mid
    curve instead of each resampling its own half.
    """
    np = _numpy()
    g = np.asarray(grid, dtype=np.float32)            # (y, x)
    w, h = plane.w, plane.h

    def cr(n: int, m: int, lo: float = 0.0,
           hi: float | None = None) -> tuple:
        xs = np.linspace(lo, (n - 1) if hi is None else hi, m)
        i1 = np.clip(np.floor(xs), 0, n - 1).astype(np.int32)
        t = (xs - i1).astype(np.float32)
        i0 = np.clip(i1 - 1, 0, n - 1)
        i2 = np.clip(i1 + 1, 0, n - 1)
        i3 = np.clip(i1 + 2, 0, n - 1)
        t2, t3 = t * t, t * t * t
        return (i0, i1, i2, i3,
                -0.5 * t3 + t2 - 0.5 * t,
                1.5 * t3 - 2.5 * t2 + 1.0,
                -1.5 * t3 + 2.0 * t2 + 0.5 * t,
                0.5 * t3 - 0.5 * t2)

    rows, cols = g.shape
    # grid coordinate of the window's first and last pixel row: identical to the
    # full-canvas map when the window IS the whole map. Clamped: a chunk at the
    # end of a strip asks for rows past the last one, and an unclipped index
    # would wrap to the OTHER end of the grid and paint the far side of the map
    # here.
    r_lo = _clamp(plane.y0 / gh * (rows - 1), 0.0, rows - 1)
    r_hi = _clamp((plane.y0 + plane.h - 1) / gh * (rows - 1), 0.0, rows - 1)
    c_lo = _clamp(plane.x0 / gw * (cols - 1), 0.0, cols - 1)
    c_hi = _clamp((plane.x0 + plane.w - 1) / gw * (cols - 1), 0.0, cols - 1)
    a0, a1, a2, a3, q0, q1, q2, q3 = cr(rows, h, r_lo, r_hi)
    tmp = (g[a0] * q0[:, None] + g[a1] * q1[:, None]
           + g[a2] * q2[:, None] + g[a3] * q3[:, None])       # (h, cols)
    b0, b1, b2, b3, r0, r1, r2, r3 = cr(cols, w, c_lo, c_hi)
    out = (tmp[:, b0] * r0[None, :] + tmp[:, b1] * r1[None, :]
           + tmp[:, b2] * r2[None, :] + tmp[:, b3] * r3[None, :])
    return np.ascontiguousarray(np.clip(out, 0.0, 1.2).T)      # (x, y)


def _band(canvas: Any, plan: SitePlan, kind: str) -> list[int]:
    """The plan features of `kind` that this window can show.

    A thirty-screen strip carries tens of thousands of props. Walking all of
    them for every slice - rotating a tree sprite only to blit it off the edge -
    is what made a slice take half a minute to paint, and painting slices is
    what has to stay ahead of the scroll.
    """
    y0 = getattr(canvas, "y0", 0.0)
    h = getattr(canvas, "h", 0) or getattr(canvas, "get_height", lambda: 0)()
    return plan.band(kind, y0, y0 + h)


def _frand(plan: SitePlan, index: int, salt: int) -> random.Random:
    """A jitter stream belonging to ONE feature rather than to a paint pass.

    A shared stream makes a chunk's contents depend on which features happened
    to be painted before it - so a strip painted in pieces would grow different
    hedges in the overlap than the piece next door, and the seam would show as
    half a hedgerow. Keyed by plan seed and feature index instead: the same
    jitter, every time, in every window that shows the feature.
    """
    return random.Random(plan.seed * 1_000_003 + index * 4093 + salt)

def paint_relief(canvas: Any, kit: TileKit, plan: SitePlan,
                 rng: random.Random, far: bool = False) -> bool:
    """Shade the relief field: colour ramps with height, light from the top
    left, a rock material where the ground is steep, snow above the snowline on
    ice themes. Returns False when numpy is missing (the caller then keeps the
    prop-only read of a ridge)."""
    np = _numpy()
    if np is None or not plan.ridges:                 # pragma: no cover
        return False
    import pygame
    pal = ROCK.get(plan.theme)
    if pal is None:
        return False
    low, high, scree_col, mat = pal
    geom = plan.geom
    # Everything that is a property of the LANDFORM - how steep its steepest
    # flank is, how steep the ground usually is, what the field looks like at
    # all - is measured on the planning grid, once, before any window is
    # resampled. Doing it per window would normalise each chunk to its own
    # terrain, and the seams would show up as bands of different contrast.
    field = np.asarray(plan.relief, dtype=np.float32)
    hs_grid = _blur(field, 2 if not far else 4)
    h_grid = 0.24 + 0.76 * field                     # away from the floor: a
    hs_grid = 0.24 + 0.76 * hs_grid                  # hollow that dips a little
    if far:                                          # is shallow ground, not
        h_grid = h_grid * 0.75                       # an unexplained pit
        hs_grid = hs_grid * 0.75
    gy, gx = np.gradient(hs_grid)
    # --- slope lighting, normalised per map ---
    # An unnormalised coefficient is either invisible on a gentle hillside or
    # clipped to near-black on a cliff, and that clipped black is what made the
    # canyon mesas read as rectangular rendering artefacts. Normalise by the
    # map's own 98th-percentile slope, then bound with tanh: the darkest shadow
    # is a dark tone, never a hole.
    gmag = np.hypot(gy, gx)
    # Normalise by the map's BIGGEST slope, not by its typical one. The 98th
    # percentile is dominated by cell-scale wobble, which puts every little
    # bump at full lighting and turns a range into "separate shaded blobs" with
    # dark halos at their feet: the small slopes were being lit as hard as the
    # cliff. With the extreme as the reference, the dominant mass carries the
    # light and a swale stays a swale.
    scale = float(np.percentile(gmag, 99.6)) or 1.0
    # a second, mid reference: how steep the ground usually is on this map. It
    # decides where the surface turns to bare rock - a steep flank is rock at any
    # absolute height, a tall but gentle dome stays soil
    scale_mid = float(np.percentile(gmag, 85)) or 1.0
    slope_n = np.clip(gmag / scale_mid, 0.0, 1.0)
    # one fixed sun for every map, from the top left: the player learns to read
    # "lit flank = the side facing the sun" once and applies it everywhere
    light = math.radians(200.0)
    lx, ly = math.cos(light), math.sin(light)
    gdot = np.clip((lx * gy + ly * gx) / scale, -3.0, 3.0)
    # Height itself barely brightens: a pale wash along the high ground reads as
    # fog or a rendering seam. The MASS is carried by which flank is lit.
    lit_g = 0.70 + h_grid * 0.20 + 0.52 * np.tanh(gdot * 1.05) \
        + 0.16 * np.tanh(np.clip(gx / scale, -3.0, 3.0))
    # the floor matters: a deep shadow at the foot of every rise is a dark ring,
    # and a dark ring around nothing reads as a painted halo, not as ground
    lit_g = np.clip(lit_g, 0.55, 1.6)

    # only now is anything resampled to canvas resolution, and only this
    # window's slice of it
    h = _upsample(h_grid, canvas, geom.w, geom.h)
    lit = _upsample(lit_g, canvas, geom.w, geom.h)
    slope_n = _upsample(slope_n, canvas, geom.w, geom.h)
    lo = np.asarray(low, dtype=np.float32)
    hi = np.asarray(high, dtype=np.float32)
    rgb = (lo[None, None, :] * (1.0 - h[:, :, None])
           + hi[None, None, :] * h[:, :, None])
    rgb *= lit[:, :, None]
    # a steep flank is rock, not soil: the material only shows where the ground
    # is actually steep, so the foot of a green hill stays green
    rock_m = np.clip((h - 0.30) / 0.30, 0.0, 1.0) \
        * (0.4 + 0.6 * slope_n) * (0.85 if not far else 0.5)
    # The ramp has to actually PAINT the hillside: starting at h 0.30 left most
    # of every slope showing base material with a faint tint, which is why
    # reviewers wrote "no convincing elevation" for every theme. Ground above
    # a quarter height is now fully in the relief palette.
    # The ramp PAINTS the high ground, but never replaces the base: full
    # coverage over a broad area is a pale band with dark margins, which is how
    # "blurred fog / unfinished texture strip" got written twice. 0.72 lets the
    # ground's own material keep showing through the mass.
    cover = np.clip((h - 0.22) / 0.40, 0.0, 1.0) * (0.5 if far else 0.72)
    mask = np.clip(cover * rock_m * 3.0, 0.0, 1.0)
    # contour lines: see below
    # contour lines: one heavy RIM at the foot of the mass, one thinner level
    # partway up. More levels than that read as tracks and cables, not
    # topography - the reviewer kept calling them "infrastructure".
    rim = tuple(int(c * 0.5) for c in low)
    line = np.zeros_like(h)
    # Two levels: the foot of the mass (a rim - the edge that says "this is a
    # landform and here is where it starts") and one mid-slope contour, which is
    # what gives a reader the slope DIRECTION. Both sit on the uphill side of the
    # level, so a hollow never gets outlined around nothing.
    for level, weight in ((0.20, 1.0), (0.46, 0.45)):
        band = (h >= level) & (h < level + (0.022 if not far else 0.04))
        line = np.maximum(line, band.astype(np.float32) * weight)
    # Only along a planned mass. A height line anywhere the ground happens to
    # cross a level outlines every swale and reads as "an unexplained pit" or "a
    # painted boundary". Note this replaces an earlier gate on local slope: once
    # the slope scale was normalised properly that gate killed the rim too, and
    # every mass went edgeless - "soft-edged raised strips, no readable crest".
    flank = np.zeros((canvas.w, canvas.h), dtype=np.float32)
    for si in _band(canvas, plan, "ridges"):
        ridge = plan.ridges[si]
        frng = _frand(plan, si, 41)
        _path_mask(ridge.spine, ridge.width * 3.4, canvas).paste(flank)
    line = line * np.clip(flank * 1.7, 0.0, 1.0)
    cover = np.maximum(cover, line * 0.6)
    mask = np.maximum(mask, line * 0.2)
    # fold first: the far painter stamps its distant patches before it asks for
    # relief, and reading the arrays without syncing throws them away
    if isinstance(canvas, Plane):
        canvas.sync()
    base = canvas.rgb if isinstance(canvas, Plane) \
        else np.asarray(pygame.surfarray.array3d(canvas)).astype(np.float32)
    alpha = canvas.a if isinstance(canvas, Plane) \
        else np.asarray(pygame.surfarray.array_alpha(canvas)).astype(np.float32) \
        * (1.0 / 255.0)
    src = _view(kit, mat, canvas).astype(np.float32)
    blended = base * (1.0 - mask[:, :, None]) + src * mask[:, :, None]
    blended = blended * (1.0 - cover[:, :, None]) + rgb * cover[:, :, None]
    blended = blended * (1.0 - line[:, :, None] * 0.62) \
        + np.asarray(rim, dtype=np.float32)[None, None, :] \
        * (line[:, :, None] * 0.62)
    # (a lit crest band along the spine was tried: it painted pale bands across
    # the map and the review's verdict became "competing terrain directions" -
    # a mass has to be carried by its slope shading, not by a stripe)
    out_a = np.maximum(alpha, cover)
    if isinstance(canvas, Plane):
        canvas.sync()
        canvas.rgb = blended
        canvas.a = out_a
    else:                                             # pragma: no cover
        rgba = np.dstack([np.clip(blended, 0, 255).astype(np.uint8),
                          (out_a * 255.0).astype(np.uint8)]) \
            .transpose(1, 0, 2)
        canvas.blit(pygame.image.fromstring(
            np.ascontiguousarray(rgba).tobytes(), (CW, CH), "RGBA"), (0, 0))
    # scree and slumps at the foot: debris where the slope lets go. Small and
    # dark, and in the theme's own rock tone - a bright grey belt across the
    # middle of a green valley is a landslide of decoration, not a landform.
    foot = tuple(int(c * 0.8) for c in low)
    surf = _target(canvas)
    for wi in _band(canvas, plan, "woods"):
        wd = plan.woods[wi]
        if wd.kind != "scree":
            continue
        frng = _frand(plan, wi, 53)
        for x, y, s in wd.items:
            r = int(3 + 7 * s)
            fx, fy = (canvas.local(x, y) if isinstance(canvas, Plane)
                      else (int(x), int(y % CH)))
            pygame.draw.circle(surf, foot, (int(fx), int(fy)), r)
            if isinstance(canvas, Plane):
                canvas.touch_box(fx - r, fy - r, fx + r, fy + r)
            gx, gy = (canvas.local(x + frng.uniform(-r, r) * 1.6,
                                   y + frng.uniform(-r, r))
                      if isinstance(canvas, Plane)
                      else (int(x + frng.uniform(-r, r) * 1.6),
                            int((y + frng.uniform(-r, r)) % CH)))
            pygame.draw.circle(surf, scree_col, (int(gx), int(gy)),
                               max(1, r // 3))
    return True


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------

def paint_fields(canvas: Any, kit: TileKit, plan: SitePlan,
                 rng: random.Random) -> None:
    for fi in _band(canvas, plan, "fields"):
        f = plan.fields[fi]
        frng = _frand(plan, fi, 11)
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


def paint_water(canvas: Any, kit: TileKit, plan: SitePlan,
                rng: random.Random) -> None:
    from .theme_table import ROCK, WATER_MAT
    pal = ROCK.get(plan.theme, ((40, 40, 36), (120, 120, 110),
                                (80, 80, 70), "gravel_rubble"))
    # the tones come from the theme's own rock palette: the near-black shore
    # line that reads as a bank in a green valley is a hole in the ground on
    # tan sand
    bank = tuple(int(c * 0.55) for c in pal[0])
    bank_mat = {"glacier": "ice_sheet", "canyon": "sand_canyon",
                "wasteland": "sand_canyon", "volcanic": "obsidian",
                "swamp": "mud_flat"}.get(plan.theme, "gravel_rubble")
    for wi in _band(canvas, plan, "water"):
        w = plan.water[wi]
        frng = _frand(plan, wi, 17)
        mat = WATER_MAT.get(plan.theme, "water_river")
        # A bank of material first, water on top of it. Water_river is lum 35 on
        # a lum 42 grass base - almost no value separation - and a *stroke*
        # along the shore reads as a drawn outline. A real band of pale gravel,
        # sand or snow around the channel gives the dark/light adjacency the eye
        # uses to find water, without looking drawn.
        _fill_mask(canvas, kit, bank_mat,
                   _path_mask(w.path, w.half * 2.0 + 10.0, canvas),
                   0.55)
        _fill_mask(canvas, kit, mat,
                   _path_mask(w.path, w.half * 2.0, canvas),
                   1.0)
        dry = w.kind in ("wash", "arroyo")
        # a wet channel is darkened - water reads by value. A DRY wash is
        # lightened instead: a desert arroyo is pale bare sand between darker
        # desert pavement, and darkening one turns it into a black scratch
        _darken_band(canvas, _path_mask(w.path, w.half * 2.0, canvas),
                     1.12 if dry else 0.62)
        # floodplain: ground beside a river is not ground away from it - but at
        # under half the width, or it becomes one more pale smear
        # The floodplain is a *hint*: at the old width and alpha it was a band
        # of pale mud three times wider than the river itself, and reviewers read
        # the whole corridor as "ambiguous pale strip - stream or track?". The
        # dark river material is the feature; the mud only softens its edge.
        if w.half >= 34.0:      # only a wide channel earns a floodplain
            _fill_mask(canvas, kit, "mud_flat" if plan.theme != "glacier"
                       else "ice_sheet",
                       _path_mask(w.path,
                                  w.flood * 0.45, canvas),
                       0.10)
        edge = "splat_mud" if plan.theme not in ("glacier", "volcanic") \
            else "splat_snow"
        for i in range(0, len(w.path) - 1, 3):
            if frng.random() < 0.34:
                (ax, ay), (bx, by) = w.path[i], w.path[i + 1]
                side = 1.0 if frng.random() < 0.5 else -1.0
                ang = math.atan2(by - ay, bx - ax) + side * math.pi / 2
                d = w.half + frng.uniform(4.0, 16.0)
                _splat(kit, canvas, edge, ax + math.cos(ang) * d,
                       ay + math.sin(ang) * d, frng.uniform(0.18, 0.34), frng)
        # a bank line on each side: water needs an edge to be read against, or a
        # river is just a dark smear with rocks in it
        for side in (-1.0, 1.0):
            pts = []
            for i in range(len(w.path) - 1):
                (ax, ay), (bx, by) = w.path[i], w.path[i + 1]
                ln = math.hypot(bx - ax, by - ay) or 1.0
                nx, ny = -(by - ay) / ln, (bx - ax) / ln
                d = w.half * side
                pts.append((ax + nx * d, ay + ny * d))
            _tint_lines(canvas, pts, bank, 3.0)
            # no bright inner lip: it reads as a drawn outline - "its thin
            # bright banks look drawn on" - which is the opposite of a bank
        # glints along the flow, so water reads as moving
        for i in range(2, len(w.path) - 2, 3):
            (ax, ay), (bx, by) = w.path[i], w.path[i + 1]
            ln = math.hypot(bx - ax, by - ay)
            if ln > 1:
                nx, ny = -(by - ay) / ln, (bx - ax) / ln
                off = frng.uniform(0.0, w.half * 0.7)
                a = (ax + nx * off, ay + ny * off)
                b = (bx + nx * off, by + ny * off)
                _tint_lines(canvas, [a, b], (255, 255, 255), 1)


def _bridge_cut(surf: Mask, wet: Any, deck: Any) -> Mask:
    """Cut the water out of a road mask and put the bridge decks back."""
    np = _numpy()
    x0, y0, x1, y1 = surf.box
    kept = surf.arr * (1.0 - wet[x0:x1, y0:y1])
    return Mask(np.maximum(kept, deck[x0:x1, y0:y1]), surf.box)


def paint_roads(canvas: Any, kit: TileKit, plan: SitePlan,
                rng: random.Random) -> None:
    from .theme_table import ROAD_MAT
    np = _numpy()
    for ri in _band(canvas, plan, "roads"):
        r = plan.roads[ri]
        frng = _frand(plan, ri, 29)
        mat = ROAD_MAT.get(plan.theme, "road_dirt")
        # shoulders first: dirt/grass soiling under the road edge, then the
        # road itself. Order matters: the road has a crisp edge, the shoulder
        # is what stops it looking pasted on.
        shoulder = "splat_oil" if plan.theme == "industrial" else "splat_dirt"
        # Small and sparse: at the old scale these soiling blobs merged with the
        # road into one wide pale corridor whose identity - road? track? bare
        # ground? - stopped being readable.
        for i in range(0, len(r.path) - 1, 3):
            if frng.random() < 0.3:
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


def paint_buildings(canvas: Plane, kit: TileKit, plan: SitePlan,
                    rng: random.Random) -> None:
    for bi in _band(canvas, plan, "buildings"):
        b = plan.buildings[bi]
        frng = _frand(plan, bi, 47)
        # the approach first: a drive from the door to the road, and a yard
        if b.drive:
            _fill_mask(canvas, kit, "road_dirt",
                   _path_mask(b.drive, 12.0, canvas), 0.8)
        if b.yard:
            yx, yy, yr = b.yard
            _splat(kit, canvas, "splat_dirt", yx, yy, yr / 60.0, frng)
        name = b.kind if b.kind in kit.props else "house_top"
        import pygame
        p = kit.props[name]
        ang = b.angle
        p = pygame.transform.rotozoom(p, ang, b.scale)
        _shadow_on(canvas, b.x + p.get_width() * 0.06,
                   b.y + p.get_height() * 0.09,
                   p.get_width() * 0.42, p.get_height() * 0.34, 60)
        _blit_wrap(canvas, p, b.x - p.get_width() / 2, b.y - p.get_height() / 2)
        # a house's near edge catches the light: this is what makes a sprite
        # read as a built thing sitting on ground rather than pasted on it
        lx, ly = (canvas.local(b.x - p.get_width() * 0.18,
                               b.y - p.get_height() * 0.2)
                  if isinstance(canvas, Plane)
                  else (int(b.x - p.get_width() * 0.18),
                        int((b.y - p.get_height() * 0.2) % CH)))
        pygame.draw.circle(_target(canvas), (255, 255, 255), (int(lx), int(ly)),
                           1)
        if isinstance(canvas, Plane):
            canvas.touch_box(b.x - p.get_width() * 0.18 - 2,
                             b.y - p.get_height() * 0.2 - 2,
                             b.x + p.get_width() * 0.18 + 2,
                             b.y + p.get_height() * 0.2 + 2)


def _cover_props(theme: str, kind: str) -> tuple[str, ...]:
    from .siteplan import _DEFAULT, SPEC
    spec = SPEC.get(theme, _DEFAULT)
    if kind in ("outcrop", "scree"):
        return (spec.ridge_prop,)
    return spec.tree_props or ("tree_clump",)


def paint_cover(canvas: Any, kit: TileKit, plan: SitePlan,
                rng: random.Random) -> None:
    for wdi in _band(canvas, plan, "woods"):
        wd = plan.woods[wdi]
        frng = _frand(plan, wdi, 37)
        if wd.kind in ("scree", "outcrop"):
            # rock DEBRIS is not a landform. Stamping cluster sprites along a
            # crest gave "boulder fences" - a row of individually drawn rocks
            # instead of one mass of rock. The relief painter shades the ridge
            # itself; debris is only speckled into it
            continue
        names = _cover_props(plan.theme, wd.kind)
        for x, y, s in wd.items:
            name = names[frng.randrange(len(names))]
            _prop(kit, canvas, name, x, y, s, rng,
                  rot4=wd.kind not in ("riparian", "orchard"),
                  shadow=6.0 * s)


def paint_far(canvas: Any, kit: TileKit, plan: SitePlan,
              rng: random.Random) -> None:
    """The slow layer: the same ridge language, seen further off and softer,
    so the range the player is flying along keeps going behind it."""
    import pygame

    from .theme_table import FAR_PAIR
    for namei, name in enumerate(FAR_PAIR[plan.theme]):
        frng = _frand(plan, namei, 43)
        t = pygame.transform.smoothscale(kit.patch(name), (280, 280))
        for _ in range(3):
            t.set_alpha(frng.randint(22, 40))
            _blit_wrap(canvas, t, frng.uniform(0, CW), frng.uniform(0, CH))
    paint_relief(canvas, kit, plan, rng, far=True)


def paint_site(canvas: Plane, kit: TileKit, plan: SitePlan,
               rng: random.Random) -> None:
    """The whole near layer, in the order a landscape is built up."""
    # In the order a landscape exists: ground, then the water in its hollows,
    # then whatever was cleared and enclosed on the flat parts. The old order
    # painted the relief ON TOP of fields and channels, washing out both the
    # cultivation and the elevation it was supposed to explain.
    paint_relief(canvas, kit, plan, rng)
    paint_water(canvas, kit, plan, rng)
    paint_fields(canvas, kit, plan, rng)
    paint_roads(canvas, kit, plan, rng)
    paint_greens(canvas, kit, plan, rng)
    paint_buildings(canvas, kit, plan, rng)
    paint_cover(canvas, kit, plan, rng)


__all__ = ["Plane", "paint_site", "paint_far", "paint_relief", "paint_roads",
           "paint_fields", "paint_water", "paint_buildings", "paint_cover",
           "paint_greens"]
