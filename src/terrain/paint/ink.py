"""Laying material, tint, splats and props through masks."""
from __future__ import annotations

import random
from typing import Any

from ..tilekit import CH, TileKit
from .mask import Mask
from .numpy_import import _numpy
from .plane import Plane
from .sampling import _at
from .surface import _blit_wrap, _shadow_on, _target, _view


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
