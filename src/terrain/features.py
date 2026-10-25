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

from .cover_table import COVER_PROPS
from .mountain_table import SNOWLINE
from .relief_table import HILL, HILL_LIGHT, HILL_OCTAVES, RELIEF_LOOK
from .siteplan import CH, CW, SitePlan, _in_poly
from .theme_table import ROCK
from .tilekit import TILE, TileKit

_TILE3: dict[str, Any] = {}          # one material tile as uint8 (TILE,TILE,3)

# How far a mask may reach beyond the window it was painted for, in painted pixels.
# It has to be at least a feather's width plus a brush radius, and finite, so that a
# feature's shape stops depending on the window while a pathological piece of geometry
# cannot ask for a canvas-sized surface.
_PAD = 48
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
                 wrap: float = 0.0, scale: int = 1) -> None:
        import pygame
        np = _numpy()
        # where this window sits in plan coordinates. A strip is painted as a
        # run of windows; the world position is what keeps materials, masks and
        # props in the same place in every window that touches them.
        self.x0, self.y0 = int(x0), int(y0)
        # a plan that loops in y paints its seam copies; a strip does not
        self.wrap = float(wrap)
        # Plan (bake) pixels per PAINTED pixel. One is the historic default: the
        # plan is designed in the same units the plane is painted in, which is what
        # a baked one-screen map wants.
        #
        # Two is what a strip on screen wants. The ground is designed at 2x because
        # the baked PNG pipeline was authored that way - "baked PNGs live at 2x for
        # extra detail; runtime loads them once and downscales" - and the strip
        # inherited it, painting a 2x window and filtering it down per slice.
        # Following one material's texel through that: 256 -> 160 (the bake pitch)
        # -> 80 (the per-slice halving) -> 156 on the screen at a 1.95x window.
        # The supersample therefore ends with FEWER pixels than the material
        # already had before it was halved, and what it definitely buys is a filter
        # pass on every slice. Painting at 2 pixels per painted pixel makes the
        # painted plane the size the game blits, so there is nothing left to filter
        # and four times fewer pixels to paint.
        self.scale = max(1, int(scale))
        self.w, self.h = max(1, w // self.scale), max(1, h // self.scale)
        self.rgb = np.zeros((self.w, self.h, 3), dtype=np.float32)
        self.a = np.zeros((self.w, self.h), dtype=np.float32)   # 0..1
        self._layer = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        self._dirty = False
        self._box: tuple[int, int, int, int] | None = None

    def shifts(self) -> tuple[float, ...]:
        """y offsets a shape must be stamped at: the seam copies of a looping
        map, nothing else for a strip."""
        if not self.wrap:
            return (0.0,)
        return (0.0, -self.wrap, self.wrap)

    def local(self, x: float, y: float) -> tuple[int, int]:
        s = self.scale
        return int(round((x - self.x0) / s)), int(round((y - self.y0) / s))

    @property
    def stamp(self) -> Any:
        """The sprite layer: props, decks, strokes. Reading it marks it dirty."""
        self._dirty = True
        return self._layer

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


def _tile3(kit: TileKit, mat: str, pitch: int = 0) -> Any:
    """One material tile as uint8 (x, y, 3), cached. Pitch 0 means the bake pitch.

    A plane painted at 2 plan pixels per painted pixel needs the same tile at half
    the pitch, and scaling it once per (material, pitch) is the ONLY resample the
    material ever goes through - where the supersampled path sent every tile through
    a full-plane filter once per slice.
    """
    import pygame
    np = _numpy()
    pitch = pitch or TILE
    if (mat, pitch) not in _TILE3:
        t = kit.material(mat)
        if t.get_width() != pitch:
            t = pygame.transform.smoothscale(t, (pitch, pitch))
        _TILE3[(mat, pitch)] = np.ascontiguousarray(
            np.asarray(pygame.surfarray.array3d(t)))
    return _TILE3[(mat, pitch)]


def _view(kit: TileKit, mat: str, plane: Plane) -> Any:
    """The material tiling as it lies under this window, uint8 (x, y, 3).

    The tile grid is fixed in WORLD coordinates: two windows of one strip read
    the same material at the same world position, so the tile phase cannot jump
    at a chunk boundary. That is the seam a player would actually see.
    """
    np = _numpy()
    key = (mat, plane.x0, plane.y0, plane.w, plane.h, plane.scale)
    v = _VIEWS.get(key)
    if v is None:
        if len(_VIEWS) > 24:                    # windows come and go; do not
            _VIEWS.clear()                      # grow with the sector
        pitch = max(1, TILE // plane.scale)
        tile = _tile3(kit, mat, pitch)
        reps_x = plane.w // pitch + 2
        reps_y = plane.h // pitch + 2
        big = np.tile(tile, (reps_x, reps_y, 1))
        # The phase is the world position measured in PAINTED pixels, which is what
        # the grid below is counted in. Taking it in plan pixels against a half-size
        # tile is the same unit error that halved every query once, in reverse.
        ox = (plane.x0 // plane.scale) % pitch
        oy = (plane.y0 // plane.scale) % pitch
        v = np.ascontiguousarray(big[ox:ox + plane.w, oy:oy + plane.h, :])
        _VIEWS[key] = v
    return v


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
    """Stamp a sprite, in window coordinates, plus its seam copies.

    A plane painted at less than plan resolution is given the stamp at its own
    resolution, about the same centre. Doing it HERE rather than in each caller is
    what keeps `_prop`, `_splat`, `_shadow_on` and the bridge deck honest: they all
    build their surface in plan pixels and centre it on a plan anchor, and the anchor
    is the thing that must not move. Filtering the stamp alone also costs a fraction
    of the pixels the old whole-plane downscale filtered, and touches none of the
    ground between props - which is the seam this removes.
    """
    surf = _target(canvas)
    if not isinstance(canvas, Plane):                # bare surface (legacy)
        xi, yi = int(round(x)), int(round(y % CH))
        span = CH
    else:
        s = canvas.scale
        if s > 1 and img.get_width() > s and img.get_height() > s:
            cx, cy = x + img.get_width() / 2.0, y + img.get_height() / 2.0
            import pygame
            img = pygame.transform.smoothscale(
                img, (max(1, img.get_width() // s), max(1, img.get_height() // s)))
            x, y = cx - img.get_width() / 2.0, cy - img.get_height() / 2.0
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

    def clip(self, w: int, h: int):
        """This mask's box and array, limited to a `w` x `h` canvas.

        A mask is rasterised over its **own geometry**, not over the window it is
        being painted for. Clipping the box to the plane made a feature's shape
        depend on where the window happened to end, and the pixels that then
        disagreed with a one-window reference were the outer rows of the kept band -
        the rows at a slice boundary, magnitude ~10/255 on a tenth of the band. A
        box may therefore reach past the plane by `_PAD`; everything that writes
        pixels clips here instead.
        """
        x0, y0, x1, y1 = self.box
        cx0, cy0 = max(0, x0), max(0, y0)
        cx1, cy1 = min(w, x1), min(h, y1)
        if cx1 <= cx0 or cy1 <= cy0:
            return (0, 0, 0, 0), None
        return (cx0, cy0, cx1, cy1), self.arr[cx0 - x0: cx1 - x0, cy0 - y0: cy1 - y0]

    def full(self) -> Any:
        """A canvas-sized copy, for the few callers that shade the whole map."""
        np = _numpy()
        out = np.zeros((CW, CH), dtype=np.float32)
        self.paste(out)
        return out

    def paste(self, dst: Any) -> None:
        """Union this mask into a canvas-sized one."""
        np = _numpy()
        box, arr = self.clip(dst.shape[0], dst.shape[1])
        if arr is None:
            return
        x0, y0, x1, y1 = box
        dst[x0:x1, y0:y1] = np.maximum(dst[x0:x1, y0:y1], arr)


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
    m = _feather(m * (1.0 / 255.0), _softness(plane, 2))
    return Mask(m, (x0, y0, x1, y1))


def _width_mask(path: list[tuple[float, float]], radii: list[float],
                plane: Plane, feather: int = 2) -> Mask:
    """A stroke whose half-width is given per vertex (plan px)."""
    import pygame
    np = _numpy()
    painted = _raster(path, max(radii), plane, radii=radii)
    if painted is None:
        return Mask(np.zeros((1, 1), dtype=np.float32), (0, 0, 1, 1))
    (x0, y0, x1, y1), surf = painted
    m = np.asarray(pygame.surfarray.array3d(surf))[:, :, 0].astype(np.float32)
    return Mask(_feather(m * (1.0 / 255.0), _softness(plane, feather)),
                (x0, y0, x1, y1))


def _raster(path: list[tuple[float, float]], r: float, plane: Plane,
            poly: bool = False, radii: list[float] | None = None) -> Any:
    """Rasterize a brushstroke (or a polygon) over just the box it covers.

    Returns ``((x0, y0, x1, y1), surface)`` in PLANE coordinates, or None when
    the geometry misses this window - which is the other half of why painting a
    strip in chunks is cheap: a window skips every feature that is not in it.
    The 4 px margin is the room a feather pass needs."""
    import pygame
    if radii is not None:
        # a varying brush: the box must hold the WIDEST point of it
        r = max(r, max(radii))
    lo_x = min(p[0] for p in path) - r
    hi_x = max(p[0] for p in path) + r
    ys = [p[1] + sh for p in path for sh in plane.shifts()]
    lo_y, hi_y = min(ys) - r, max(ys) + r
    s = plane.scale
    # geometry arrives in plan pixels; the raster works in painted pixels. The 4 px
    # margin is in PAINTED pixels - it is room for a feather pass, which happens
    # here, not in the world.
    #
    # The box is the GEOMETRY's, clamped only to `_PAD` beyond the window - never to
    # the window itself. Clipping it to the plane is what made a feature change shape
    # depending on which slice's window happened to be painting it, and the rows that
    # changed were the outer rows of the kept band: a line at every boundary.
    pad = _PAD
    # The box is the GEOMETRY's, clamped to the canvas plus a feather's allowance -
    # never to the canvas itself. Clipping to the plane is what made a feature change
    # shape depending on which slice's window happened to be painting it, and the rows
    # that changed were the outer rows of the kept band: a line at every boundary. The
    # clamp is what keeps a wrapped road, whose geometry runs the whole map plus its
    # seam copies, from asking for a surface three canvases tall.
    x0 = max(-pad, int((lo_x - plane.x0) / s) - 4)
    y0 = max(-pad, int((lo_y - plane.y0) / s) - 4)
    x1 = min(plane.w + pad, int((hi_x - plane.x0) / s) + 5)
    y1 = min(plane.h + pad, int((hi_y - plane.y0) / s) + 5)
    # Rejected only when the geometry misses the window by more than a feather's
    # width. (Writing `x1 - x0 <= pad` here, as if a small box were a suspicious one,
    # deletes every disc on the map - a tree crown is 20 px, the pad is 48.)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    surf = pygame.Surface((x1 - x0, y1 - y0))
    surf.fill((0, 0, 0))
    for shift in plane.shifts():
        pts = [((x - plane.x0) / s - x0, (y + shift - plane.y0) / s - y0)
               for x, y in path]
        if max(p[1] for p in pts) < -60 \
                or min(p[1] for p in pts) > surf.get_height() + 60:
            continue
        if poly:
            pygame.draw.polygon(surf, (255, 255, 255),
                                [(int(px), int(py)) for px, py in pts])
            continue
        # The brush is as wide as the road, and the road is measured in plan pixels:
        # on a half-resolution plane it covers half as many of them. `k` rather than
        # `s` for the sample index because `s` is the scale, and shadowing it here
        # silently made every disc after the first one a different width.
        brush = max(1.0, r / s)
        for i in range(len(pts) - 1):
            (ax, ay), (bx, by) = pts[i], pts[i + 1]
            ln = math.hypot(bx - ax, by - ay)
            ra = rb = brush
            if radii is not None:
                # interpolated between the plan's own vertices, so the width at a
                # world point is the same whichever window is painting it
                ra, rb = max(1.0, radii[i] / s), max(1.0, radii[i + 1] / s)
            n = max(1, int(ln / max(2.0, min(ra, rb) * 0.35)))
            for k in range(n + 1):
                t = k / n
                pygame.draw.circle(surf, (255, 255, 255),
                                   (int(ax + (bx - ax) * t),
                                    int(ay + (by - ay) * t)),
                                   int(ra + (rb - ra) * t))
    return (x0, y0, x1, y1), surf


def _feather(m: Any, passes: int) -> Any:
    """Soften a mask edge, in the mask's own box."""
    np = _numpy()
    for _ in range(passes):
        m = (m + np.roll(m, 1, 0) + np.roll(m, -1, 0)
             + np.roll(m, 1, 1) + np.roll(m, -1, 1)) / 5.0
    return m


def _softness(plane: Any, passes: int) -> int:
    """How many blur passes a mask edge needs AT THIS PLANE'S RESOLUTION.

    A feather is a softness in the WORLD, not a count of pixels. Asked in painted
    pixels, it doubles the moment the plane halves its resolution: the supersampled
    route blurred twice at 2x and then halved the whole plane, ending about one
    display pixel wide, while painting at 1x with the same two passes ends about two -
    so the change of resolution quietly made the whole ground softer than it was,
    which is an appearance regression wearing the costume of a performance change.
    """
    return max(1, int(round(passes / max(1, getattr(plane, "scale", 1)))))


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
    return Mask(_feather(m * (1.0 / 255.0), _softness(plane, feather)),
                (x0, y0, x1, y1))


def _fill_mask(canvas: Any, kit: TileKit, mat: str, mask: Any,
               strength: float = 1.0) -> None:
    """Fill a material through a mask, keeping the layer's alpha. The curve comes
    from the mask, not from the tile grid - which is exactly where the old
    square-edged road shoulders came from."""
    np = _numpy()
    if np is None or not isinstance(canvas, Plane):   # pragma: no cover
        return
    if isinstance(mask, Mask):
        box, raw = mask.clip(canvas.w, canvas.h)
        if raw is None:
            return
    else:
        box, raw = (0, 0, canvas.w, canvas.h), mask
    m = np.clip(np.asarray(raw, dtype=np.float32) * strength, 0.0, 1.0)
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
    if isinstance(mask, Mask):
        box, raw = mask.clip(canvas.w, canvas.h)
        if raw is None:
            return
    else:
        box, raw = (0, 0, canvas.w, canvas.h), mask
    m = np.clip(np.asarray(raw, dtype=np.float32), 0.0, 1.0)
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
        s = canvas.scale
    else:                                            # bare surface (legacy)
        shifts = (0, -CH, CH) if shift_wraps else (0,)
        ox, oy = 0, 0
        lo, hi = 0, CH
        s = 1
    if len(pts) < 2:
        return                      # nothing to stroke: a degenerate run, not an error
    for shift in shifts:
        seg = [((x - ox) / s, (y + shift - oy) / s) for x, y in pts]
        if max(p[1] for p in seg) < lo - 20 or min(p[1] for p in seg) > hi + 20:
            continue
        pygame.draw.lines(surf, col, False,
                          [(int(x), int(y)) for x, y in seg],
                          max(1, int(width / s)))
        if isinstance(canvas, Plane):
            canvas.touch_box(min(p[0] for p in seg) - width,
                             min(p[1] for p in seg) - width,
                             max(p[0] for p in seg) + width,
                             max(p[1] for p in seg) + width)


def _splat(kit: TileKit, canvas: Any, name: str, x: float, y: float,
           s: float, rng: random.Random) -> None:
    import pygame
    # `rng` is a window's stream and this stamp must not depend on which window
    # asked for it: the same splat, at the same world position, arrives at the same
    # angle in every window that shows it.
    _ = rng
    p = pygame.transform.rotozoom(kit.splats[name],
                                  _at("splat", name, round(x), round(y))
                                  .randint(0, 359), s)
    _blit_wrap(canvas, p, x - p.get_width() / 2, y - p.get_height() / 2)


def _prop(kit: TileKit, canvas: Any, name: str, x: float, y: float,
          s: float, rng: random.Random, rot4: bool = True,
          shadow: float = 0.0) -> None:
    import pygame
    if name not in kit.props:
        return
    # See `_splat`: variant, angle and flip come from the ground this prop stands
    # on, never from the window that happens to be painting it.
    _ = rng
    here = _at("prop", name, round(x), round(y))
    p = kit.props[name]
    ang = here.choice((0, 90, 180, 270)) if rot4 else 0
    p = pygame.transform.rotozoom(p, ang, s)
    if here.random() < 0.5:
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

    def cr(n: int, xs: Any) -> tuple:
        # Catmull-Rom weights for EXPLICIT sample positions. Building the samples
        # from two endpoints (linspace(lo, hi, m)) was the bug: when `hi` had to be
        # clamped to the last grid row - which happens for every window that runs
        # past the end of the plan - the whole interval was re-fitted into the same
        # number of samples, so the relief got stretched across the window instead
        # of reading flat ground beyond the end. Every interior row of that window
        # then sampled a different world row than its neighbour did: 37% of a slice
        # wrong, growing to the end, and invisible between two windows that were
        # both clamped the same way. Clamp the sample, never the interval.
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
    # Grid coordinate of every pixel row and column, from the window's world
    # position: identical to the full-canvas map when the window IS the whole map,
    # and identical to the neighbour wherever two windows overlap. Clamping is per
    # sample, so a window that reaches past the end of the plan reads the last grid
    # row (flat ground, the honest answer) rather than rescaling its own relief.
    rxs = np.clip((plane.y0 + np.arange(h, dtype=np.float64) * plane.scale)
                  * ((rows - 1) / max(1, gh)), 0.0, rows - 1)
    cxs = np.clip((plane.x0 + np.arange(w, dtype=np.float64) * plane.scale)
                  * ((cols - 1) / max(1, gw)), 0.0, cols - 1)
    a0, a1, a2, a3, q0, q1, q2, q3 = cr(rows, rxs)
    tmp = (g[a0] * q0[:, None] + g[a1] * q1[:, None]
           + g[a2] * q2[:, None] + g[a3] * q3[:, None])       # (h, cols)
    b0, b1, b2, b3, r0, r1, r2, r3 = cr(cols, cxs)
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
    # A plane's `h` is PAINTED pixels, and the plan is counted in PLAN pixels, so the
    # window's world range is `h * scale`. Both directions of this have now been
    # wrong once: dividing `h` by SS (an earlier commit, chasing a half-drawn house)
    # halved every query when plane and plan were the same resolution, and NOT
    # multiplying by the plane's scale halves it now that they differ. The rule is
    # neither divide nor multiply by a constant - it is that a query is made in plan
    # units, so a painted extent has to be converted by the plane's own scale.
    reach = h * getattr(canvas, "scale", 1)
    return plan.band(kind, y0, y0 + reach)


def _bytes(v: int) -> bytes:
    """Eight bytes of an integer, order-stable across runs (never `hash()`)."""
    if -(2 ** 63) <= v < 2 ** 63:
        return v.to_bytes(8, "little", signed=True)
    return str(v).encode()


def _at(*key: object) -> random.Random:
    """A stream belonging to one **place**, not to one paint call or one slice.

    The painter must be a pure function of world position, because that is the only
    way a strip painted in overlapping pieces can come out seamless: if the choice
    depends on which window asked, then the same tree is a different tree in each
    piece, and the seam is not a line to hide but a genuine disagreement that no
    margin or blend can fix. Everything a stamp needs - variant, rotation, flip -
    is therefore derived from where it stands, and `rng` arguments are no longer
    consulted for it.

    FNV-1a over the quantised coordinates, so a 1 px difference in the anchor gives
    a different stream (that is the point) while the same anchor gives the same one
    in every window, on every machine, in any interpreter.
    """
    mask = 0xFFFFFFFFFFFFFFFF
    h = 1469598103934665603 & mask
    for v in key:
        parts = (v.encode("utf-8", "ignore") if isinstance(v, str)
                 else _bytes(int(v)))
        for b in parts:
            h = ((h ^ b) * 1099511628211) & mask
    return random.Random(h)


def _frand(plan: SitePlan, index: int, salt: int) -> random.Random:
    """A jitter stream belonging to ONE feature rather than to a paint pass.

    A shared stream makes a chunk's contents depend on which features happened
    to be painted before it - so a strip painted in pieces would grow different
    hedges in the overlap than the piece next door, and the seam would show as
    half a hedgerow. Keyed by plan seed and feature index instead: the same
    jitter, every time, in every window that shows the feature.
    """
    return random.Random(plan.seed * 1_000_003 + index * 4093 + salt)


def _hash01(ix: Any, iy: Any, seed: int) -> Any:
    """A value in 0..1 for each integer lattice point, from its coordinates alone.

    uint32 arithmetic that wraps on purpose: the same lattice point gives the same
    value in every window, every process and every run, which is what lets terrain
    detail be painted in slices that agree at their seams.
    """
    np = _numpy()
    with np.errstate(over="ignore"):
        h = (ix.astype(np.uint32) * np.uint32(374761393)
             + iy.astype(np.uint32) * np.uint32(668265263)
             + np.uint32(seed & 0xFFFFFFFF))
        h = (h ^ (h >> np.uint32(13))) * np.uint32(1274126177)
        h = h ^ (h >> np.uint32(16))
    return h.astype(np.float32) * (1.0 / 4294967296.0)


def _world_noise(xs: Any, ys: Any, cell: float, seed: int) -> Any:
    """Smooth value noise over WORLD coordinates, shape (len(xs), len(ys))."""
    np = _numpy()
    fx = xs / cell
    fy = ys / cell
    ix = np.floor(fx).astype(np.int64)
    iy = np.floor(fy).astype(np.int64)
    tx = (fx - ix).astype(np.float32)
    ty = (fy - iy).astype(np.float32)
    tx = tx * tx * (3.0 - 2.0 * tx)
    ty = ty * ty * (3.0 - 2.0 * ty)
    X0, Y0 = ix[:, None], iy[None, :]
    v00 = _hash01(X0, Y0, seed)
    v10 = _hash01(X0 + 1, Y0, seed)
    v01 = _hash01(X0, Y0 + 1, seed)
    v11 = _hash01(X0 + 1, Y0 + 1, seed)
    a = v00 + (v10 - v00) * tx[:, None]
    b = v01 + (v11 - v01) * tx[:, None]
    return a + (b - a) * ty[None, :]


def _ridged(xs: Any, ys: Any, seed: int) -> Any:
    """Ridged multifractal: sharp crests and the gullies between them - what a
    mountainside looks like from the air, and what a smooth relief blob is not."""
    np = _numpy()
    out = np.zeros((len(xs), len(ys)), dtype=np.float32)
    amp, tot = 1.0, 0.0
    for k, cell in enumerate(HILL_OCTAVES):
        n = _world_noise(xs, ys, cell, seed + 7919 * k)
        r = 1.0 - np.abs(2.0 * n - 1.0)
        out += r * r * amp
        tot += amp
        amp *= 0.5
    return out / tot


class _Window:
    """A plane's sampling frame, widened: `_upsample` reads only these fields."""

    def __init__(self, plane: Any, pad: int) -> None:
        self.w = plane.w + 2 * pad
        self.h = plane.h + 2 * pad
        self.x0 = plane.x0 - pad * plane.scale
        self.y0 = plane.y0 - pad * plane.scale
        self.scale = plane.scale


def _hillshade(canvas: Any, kit: TileKit, plan: SitePlan, field: Any) -> None:
    """Light the WHOLE ground by its slope, with erosion detail on the high ground.

    The relief used to colour a mountain by its height and light it weakly from a
    64 px grid: a smooth blob with no crest, which from the air is a grey stain - the
    "mountains" in every sector read as smears across the fields. Real ground is
    read by its shading: one flank lit, the other in shadow, and on anything steep
    the ridges and gullies erosion cuts into it. This builds a height field at the
    painted resolution - the planned relief, plus ridged detail where the relief is
    high - and multiplies the ground by how much each pixel faces the light.

    Window-safe by construction: the detail is a function of WORLD position, and the
    gradient is taken over the window plus a one-pixel margin, so no pixel's slope
    depends on where the window ends.
    """
    np = _numpy()
    spec = HILL.get(plan.theme)
    if spec is None or not isinstance(canvas, Plane):
        return
    elev, detail, strength = spec
    win = _Window(canvas, 1)
    base = _upsample(field, win, plan.geom.w, plan.geom.h)       # (x, y)
    xs = win.x0 + np.arange(win.w, dtype=np.float64) * win.scale
    ys = win.y0 + np.arange(win.h, dtype=np.float64) * win.scale
    seed = (plan.seed * 2654435761 + sum(map(ord, plan.theme))) & 0xFFFFFFFF
    mount = np.clip((base - 0.22) / 0.45, 0.0, 1.0)
    mount = mount * mount * (3.0 - 2.0 * mount)
    z = base * elev + _ridged(xs, ys, seed) * detail * mount
    step = 2.0 * win.scale
    dzdx = (z[2:, 1:-1] - z[:-2, 1:-1]) / step
    dzdy = (z[1:-1, 2:] - z[1:-1, :-2]) / step
    lx, ly, lz = HILL_LIGHT
    inv = 1.0 / np.sqrt(dzdx * dzdx + dzdy * dzdy + 1.0)
    lam = (-dzdx * lx - dzdy * ly + lz) * inv
    k = np.clip(lam / lz, 0.5, 1.4)                  # 1.0 on flat ground
    k = 1.0 + (k - 1.0) * strength
    canvas.sync()
    line = SNOWLINE.get(plan.theme)
    if line is not None:
        # Snow lies on the heights and slides off the steep faces: above the
        # snowline, less on a cliff, ragged at its lower edge by the same detail
        # that cuts the ridges. Laid before the shading so the snow is lit too.
        h = base[1:-1, 1:-1] + (_ridged(xs[1:-1], ys[1:-1], seed + 31) - 0.5) * 0.12
        steep = np.clip(np.hypot(dzdx, dzdy) * 0.9, 0.0, 1.0)
        snow = np.clip((h - line) / 0.1, 0.0, 1.0) * (1.0 - steep * 0.7)
        src = _view(kit, "snow_field", canvas).astype(np.float32)
        canvas.rgb = canvas.rgb * (1.0 - snow[:, :, None]) + src * snow[:, :, None]
    canvas.rgb *= k[:, :, None]


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
    hs_raw = hs_grid if not far else None
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
    # How much of that a theme wants is the theme's: green country has green hills
    # (a grey ramp over a grassy rise reads as a quarry or a dry riverbed, now that
    # the hillshade carries the form), rugged country has bare rock on its heights.
    look_cover, look_rock, look_rim = RELIEF_LOOK.get(plan.theme, (1.0, 1.0, 1.0))
    cover = np.clip((h - 0.22) / 0.40, 0.0, 1.0) * (0.5 if far else 0.72) \
        * look_cover
    mask = np.clip(cover * rock_m * 3.0, 0.0, 1.0) * look_rock
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
    line = line * np.clip(flank * 1.7, 0.0, 1.0) * look_rim
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
    if hs_raw is not None:
        _hillshade(canvas, kit, plan, hs_raw)
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
    from .theme_table import WATER_BANK, WATER_EDGE_GREEN, WATER_MAT
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
        from .siteplan import _in_poly
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
    from .theme_table import ROAD_MAT
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
        # The plan speaks in plan kinds ("barn", "hut"); the atlas speaks in art
        # names ("barn_red", "hut_stilt"). That alias used to be missing, and the
        # fallback drew a HOUSE for every barn in the game - which is one reason a
        # farm read as a pile of houses.
        from .siteplan import prop_art
        name = prop_art(b.kind)
        if name not in kit.props:
            name = "house_top"
        import pygame
        p = kit.props[name]
        from .siteplan import art_turn
        p = pygame.transform.rotozoom(p, art_turn(b.kind, b.angle), b.scale)
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
    if kind in COVER_PROPS:
        return COVER_PROPS[kind]
    if kind == "pylon_row":
        # a highway's pylons are a ROW of one prop, not vegetation: this is how a
        # place lays something the tree vocabulary cannot express
        return ("mast_lattice",)
    return spec.tree_props or ("tree_clump",)


def paint_scars(canvas: Any, kit: TileKit, plan: SitePlan,
                rng: random.Random) -> None:
    """Craters: over the ground, the roads and the fields, under the buildings
    and the trees - a crater is a hole IN the ground, and a road through a bombed
    field is a broken road."""
    for wdi in _band(canvas, plan, "woods"):
        wd = plan.woods[wdi]
        if wd.kind != "crater":
            continue
        for x, y, s in wd.items:
            _prop(kit, canvas, "crater", x, y, s, rng, rot4=True)


def paint_cover(canvas: Any, kit: TileKit, plan: SitePlan,
                rng: random.Random) -> None:
    for wdi in _band(canvas, plan, "woods"):
        wd = plan.woods[wdi]
        frng = _frand(plan, wdi, 37)
        if wd.kind == "crater":
            continue                  # laid under the buildings by `paint_scars`
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
    SPAN = 280
    # Placed on a lattice in **world** rows and columns, one decision per cell,
    # rather than three positions drawn from a stream belonging to this window -
    # which is what made the far layer disagree with itself across a slice
    # boundary: same patch name, different places, a seam of tone.
    y0 = int(getattr(canvas, "y0", 0))
    # `h` is PAINTED pixels and the lattice is counted in PLAN pixels, so a plane at
    # 2 plan pixels per painted one covers only HALF its world range if this is taken
    # at face value - which put no distant range at all in the lower half of every
    # strip window: slices 4-7 of eight disagreed with a one-window reference on
    # 21%-54% of their pixels, scattered, and looked like "some tiles just wrong".
    # The same unit boundary `_band` documents, arriving from the other side.
    tall = int(getattr(canvas, "h", 0) or canvas.get_height()) \
        * getattr(canvas, "scale", 1)
    y_from = y0 // SPAN * SPAN - SPAN
    y_to = y0 + tall + SPAN
    for name in FAR_PAIR[plan.theme]:
        t = pygame.transform.smoothscale(kit.patch(name), (SPAN, SPAN))
        for wy in range(y_from, y_to, SPAN):
            for wx in range(0, CW, SPAN):
                here = _at("farpatch", plan.seed, name, wx, wy)
                if here.random() >= 0.62:
                    continue
                t.set_alpha(here.randint(22, 40))
                _blit_wrap(canvas, t,
                           wx + here.uniform(-SPAN * 0.4, SPAN * 0.4),
                           wy + here.uniform(-SPAN * 0.4, SPAN * 0.4))
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
    paint_scars(canvas, kit, plan, rng)
    paint_buildings(canvas, kit, plan, rng)
    paint_cover(canvas, kit, plan, rng)


__all__ = ["Plane", "paint_site", "paint_far", "paint_relief", "paint_roads",
           "paint_fields", "paint_water", "paint_buildings", "paint_cover",
           "paint_greens", "paint_scars"]
