"""Painting a strip slice in another interpreter.

The design pass moved to a process and the plan arrived on time; the ground still
did not, because *painting* is the expensive part and it was still on threads
inside the game's interpreter. A slice is 0.75 s of numpy and pygame surface
work, and the camera wants one every 1.7 s: that is half a core, which the frame
thread is not willing to give up.

So the child does the painting too. It can: `terrain.features` paints into pygame
surfaces, and a child with a dummy video driver has working surfaces - nothing
about the painter needs a window. What crosses the boundary is the finished
slice: about 0.9 MB of RGBA at logical scale (the child downscales, as it does
in-process), tens of milliseconds to pickle, and the parent wraps it in a surface
with `pygame.image.fromstring`.

The property the whole arrangement rests on, and the reason the child's plan is
cached rather than sent per slice: the same slice, painted here or there, must be
the same picture. Test that first, before trusting a stream of it.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from .design import pool

__all__ = ["paint_slice", "shutdown_pool"]

log = logging.getLogger("raiden.level")

_CACHE: dict[tuple, Any] = {}
_CACHE_LOCK = threading.Lock()
_MAX_PLANS = 3


def _display() -> None:
    """A dummy display in this process, once: convert()/scale need one."""
    import pygame

    if pygame.display.get_surface() is None:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((8, 8))


def _plan_for(theme: str, seed: int, length: int,
              slice_h: int, margin: int) -> Any:
    """The plan, designed once per child process and kept.

    Sending a sector's plan with every slice would be a few hundred kilobytes of
    copying per slice for something the child can hold. Keeping it is also what
    makes painting start promptly for the slices prepared ahead of the camera:
    the plan is already there.
    """
    key = (theme, int(seed), int(length))
    with _CACHE_LOCK:
        plan = _CACHE.get(key)
        if plan is not None:
            return plan
        # Design *inside* the lock: two workers asked for slices of the same
        # sector at once would otherwise each spend seconds thinking up the same
        # ground, and each hold a copy of it.
        from terrain.siteplan import CELL, Geom, plan_site

        plan = plan_site(theme, int(seed), Geom(h=int(length), cell=CELL,
                                                cyclic=False))
        if len(_CACHE) >= _MAX_PLANS:
            _CACHE.clear()
        _CACHE[key] = plan
    return plan


def _paint_here(theme: str, seed: int, length: int, layer: str, index: int,
                slice_h: int, margin: int) -> tuple:
    """Paint slice `index` in this process; hand back (w, h, rgba bytes)."""
    _display()
    import pygame

    from .strip import TerrainStrip

    plan = _plan_for(theme, seed, length, slice_h, margin)
    strip = TerrainStrip(plan, layer, slice_h, margin)
    surf = strip.paint(index)
    return (surf.get_width(), surf.get_height(),
            pygame.image.tostring(surf, "RGBA"))


def paint_slice(plan: Any, layer: str, index: int, slice_h: int,
                margin: int) -> Any | None:
    """Paint one slice in the worker and return a surface, or None on failure.

    None means "the child could not do it" - and the caller paints it here, which
    is slower but never wrong. The plan is *not* sent: it is looked up in the
    child's cache by (theme, seed, length), and designed there if the child has
    not seen it, so a sector's ground is thought up once per process rather than
    once per slice.
    """
    p = pool()
    if p is None:
        return None
    args = (str(plan.theme), int(plan.seed), int(plan.geom.h), str(layer),
            int(index), int(slice_h), int(margin))
    try:
        w, h, raw = p.submit(_paint_here, *args).result()
    except Exception as exc:                      # noqa: BLE001 - worker fault
        log.warning("paint worker failed for slice %d (%s); painting in-"
                    "process", index, exc)
        return None
    import pygame

    surf = pygame.image.fromstring(raw, (w, h), "RGBA")
    try:
        surf = surf.convert_alpha()
    except pygame.error:           # no display yet here: the raw form still works
        pass
    return surf


def shutdown_pool() -> None:
    """The shared worker serves design and painting; it is dismissed once."""
    from .design import shutdown_pool as _shutdown

    _shutdown()
