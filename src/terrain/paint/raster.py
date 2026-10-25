"""Rasterising strokes, polygons and discs into masks."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .mask import Mask
from .numpy_import import _numpy
from .surface import _PAD

if TYPE_CHECKING:
    from .plane import Plane

import math
from typing import Any


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
