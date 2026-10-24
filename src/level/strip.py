"""One sector's ground as a strip of painted slices.

The strip is *bake space*: the same 2x coordinates every painter in
``terrain/`` already works in, so nothing in the painting code had to learn a
second scale. A slice is one screen tall bake-wise (1120 px) and is handed back
at logical size, exactly like a baked PNG would have been.

Painting a slice is pure and idempotent: the slice's window of the world plus a
margin, painted out of the plan, and the middle kept. That is what makes the
whole scheme safe to run on a thread while the player is already in the level -
a slice does not care when it is painted, in which order, or by which thread.
"""
from __future__ import annotations

import math
import random
import threading
from typing import Any

from terrain.common import SS, TILE2, W2
from terrain.siteplan import SitePlan

__all__ = ["TerrainStrip", "STRIP_SLICE", "STRIP_MARGIN", "kit_for"]

STRIP_SLICE = TILE2 // 2      # one slice: 560 bake px, two per screen of ground
STRIP_MARGIN = 96             # bake px painted beyond the kept band
# The margin is not decoration. A feature anchored just outside a slice still
# reaches into it - a tree crown, a hedge stroke, a bridge deck - and if the
# slice was painted without that feature, the boundary shows as the feature
# being cut. 96 bake px (48 logical) covers every prop the planner stamps; it is
# measured, not guessed: with a 96 px margin and 560 px slices, two windows over
# the same world rows agree on ~99.9% of them.

_KIT: Any = None
_KIT_LOCK = threading.Lock()


def kit_for() -> Any:
    """One shared TileKit: it loads the material/prop set for the whole game."""
    global _KIT
    with _KIT_LOCK:
        if _KIT is None:
            from terrain.tilekit import TileKit
            _KIT = TileKit()
    return _KIT


class TerrainStrip:
    """A tall strip of designed ground, painted slice by slice, off-thread.

    ``layer`` selects which painter runs: ``"near"`` is the ground the craft
    flies over (``paint_site``), ``"far"`` the softer range behind it
    (``paint_far``). Each layer gets its own strip and its own worker, because
    they scroll at different rates and one slow painter must not hold up the
    other.
    """

    def __init__(self, plan: SitePlan, layer: str = "near",
                 slice_h: int = STRIP_SLICE, margin: int = STRIP_MARGIN,
                 downscale: bool = True) -> None:
        if layer not in ("near", "far"):
            raise ValueError(f"unknown strip layer {layer!r}")
        if slice_h <= 0 or margin < 0:
            raise ValueError("a strip slice needs a positive height")
        self.plan = plan
        self.layer = layer
        self.slice_h = int(slice_h)
        self.margin = int(margin)
        self.downscale = downscale
        self.height = int(plan.geom.h)
        self.count = max(1, math.ceil(self.height / self.slice_h))
        # Painting happens in the worker process unless the caller says otherwise
        # (see `paint`). Set by `Level`, which knows how long the sector is.
        self.via_process = False
        self._surf: list[Any] = [None] * self.count
        self._lock = threading.Lock()
        self._cursor = 0

    # ------------------------------------------------------------- painting
    def window(self, i: int) -> tuple[int, int]:
        """(y0, h) of the bake-space window slice `i` is painted from.

        The window runs `margin` past the kept band at both ends, clamped at the
        ends of the strip - a strip has ends, which is the whole reason it does
        not wrap.
        """
        lo = i * self.slice_h - self.margin
        hi = (i + 1) * self.slice_h + self.margin
        lo = max(0, lo)
        hi = min(self.height, hi)
        return lo, hi - lo

    def paint(self, i: int) -> Any:
        """Paint slice `i` and return its surface. Idempotent, thread-safe.

        With `via_process` set, the work is asked for in the design/paint worker
        - which is the point of the whole arrangement, since a slice is 0.75 s of
        numpy and surface work that the frame thread will not share. A worker
        that cannot do it costs a slower slice, not a hole: the local path is
        always there. The picture is the same either way, which is asserted in
        tests/test_level_paint.py rather than assumed.
        """
        with self._lock:
            if self._surf[i] is not None:
                return self._surf[i]
        surf = None
        if self.via_process:
            from .paintsrv import paint_slice

            surf = paint_slice(self.plan, self.layer, i, self.slice_h,
                               self.margin)
        if surf is None:
            surf = self._paint(i)
        with self._lock:
            # Another worker may have finished the same slice while this one
            # was drawing; keep the first, free the second, hand back a surface
            # either way so the caller never sees a hole.
            if self._surf[i] is None:
                self._surf[i] = surf
            return self._surf[i]

    def _paint(self, i: int) -> Any:
        import pygame

        from terrain.features import Plane, paint_far, paint_site

        kit = kit_for()
        y0, h = self.window(i)
        # A window, not a canvas: the plane knows where it sits in the world, so
        # materials land on the same tile grid and props land on the same ground
        # as they would in any other window. `wrap=0` - a strip does not loop.
        plane = Plane(W2, h, x0=0, y0=y0)
        if self.layer == "near":
            # The ground the craft flies over is opaque, and it is opaque
            # because the material grid is laid down *under* the plan - the same
            # step compose._near_for performs for a baked map. Skip it and half
            # the layer is transparent: the plan's features float over whatever
            # the renderer happened to draw first.
            from random import Random

            from terrain.compose import NEAR_MATS, _grid
            _grid(plane.stamp, kit, list(NEAR_MATS[self.plan.theme]),
                  Random(self.plan.seed * 7717 + i))
            plane.sync()
        # The pass-level stream only picks things the plan did not already pin
        # down; per-feature jitter comes from the plan itself, which is why
        # painting a slice in any order gives the same pixels.
        rng = random.Random(self.plan.seed * 8191 + i * 131 + (7 if self.layer == "far" else 3))
        if self.layer == "far":
            paint_far(plane, kit, self.plan, rng)
        else:
            paint_site(plane, kit, self.plan, rng)
        surf = plane.surface()
        top = y0 - i * self.slice_h          # where the kept band starts
        keep = surf.subsurface((0, max(0, top), W2, min(h, self.slice_h)))
        keep = keep.copy()
        if self.downscale:
            keep = pygame.transform.smoothscale(
                keep, (keep.get_width() // SS, keep.get_height() // SS))
        return keep

    # ------------------------------------------------------------- frontier
    def frontier(self) -> int:
        """How many slices from the top are painted, contiguously.

        Contiguously matters: the renderer draws up to this line and nothing
        beyond it, so a slice that finished early out of order must not open a
        hole in the ground.
        """
        with self._lock:
            n = 0
            while n < self.count and self._surf[n] is not None:
                n += 1
            return n

    def surface(self, i: int) -> Any:
        with self._lock:
            return self._surf[i] if 0 <= i < self.count else None

    def advance(self) -> bool:
        """Paint the next unfinished slice. False when the strip is done.

        The worker's whole inner loop: one slice at a time, so a stop request
        costs at most one slice.
        """
        with self._lock:
            while self._cursor < self.count and self._surf[self._cursor] is not None:
                self._cursor += 1
            if self._cursor >= self.count:
                return False
            i = self._cursor
        self.paint(i)
        return True

    def missing_at(self, y: float) -> int:
        """Index of the first unfinished slice the camera at `y` can see.

        `y` is bake-space, and it is the strip row at the **top** edge of the
        field: what the camera can see is the screen of ground behind that row,
        [y - TILE2, y]. Asking only at and past `y` would call a sector ready
        whose visible ground is not painted yet.
        """
        top = max(0, int(y - TILE2) // self.slice_h)
        with self._lock:
            for i in range(top, min(self.count, top + 4)):
                if self._surf[i] is None:
                    return i
        return -1

    # ----------------------------------------------------------------- draw
    def draw(self, canvas: Any, band: Any, y: float) -> int:
        """Blit the slices the camera at bake offset `y` can see.

        `y` is the strip row standing at the **top edge** of the band, and it
        grows as the craft flies forward through the sector, so the ground
        flows *down* the screen past the craft - the same direction the baked detail layers
        move (`layer.py` blits at `HUD_H + off`). The sign here is not a
        preference: a strip that scrolls the other way disagrees with the baked
        ground the renderer still falls back to inside the same frame.

        Returns the number of slices drawn, so a caller can tell a hole in the
        ground from the whole picture.
        """
        if not self.downscale:
            raise RuntimeError("a strip drawn unscaled would cover the field 4x")
        # rows behind the top edge are the ones in view: [y - view, y]
        lo = int((y - band.height * SS) // self.slice_h) - 1
        hi = int(y // self.slice_h) + 1
        drawn = 0
        for i in range(max(0, lo), min(self.count, hi)):
            surf = self.surface(i)
            if surf is None:
                continue
            # the slice's *far* row is the one nearest the top edge
            top = band.top + (y - (i + 1) * self.slice_h) / SS
            canvas.blit(surf, (band.left, int(round(top))), band)
            drawn += 1
        return drawn
