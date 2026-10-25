"""Canvas access: materials under a window, shadows, blits."""
from __future__ import annotations

from typing import Any

from ..tilekit import CH, TILE, TileKit
from .numpy_import import _numpy
from .plane import Plane

_TILE3: dict[str, Any] = {}          # one material tile as uint8 (TILE,TILE,3)


# How far a mask may reach beyond the window it was painted for, in painted pixels.
# It has to be at least a feather's width plus a brush radius, and finite, so that a
# feature's shape stops depending on the window while a pathological piece of geometry
# cannot ask for a canvas-sized surface.
_PAD = 48


_VIEWS: dict[tuple, Any] = {}        # material as it lies under one window


_SOFT: list[Any] = []                # one soft shadow blob, built once


def _target(canvas: Any) -> Any:
    """The pygame layer to draw sprites on, whether the caller holds a Plane or
    a bare surface (the hand-composed vector painters still pass one)."""
    return canvas.stamp if isinstance(canvas, Plane) else canvas


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


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)
