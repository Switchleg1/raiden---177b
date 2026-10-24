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
import os
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

    # A/B switch for finding the line that appears at every slice boundary.
    # Baked sectors are clean and streamed ones are not, so the artifact is in the
    # strip path. Two candidates remain: each band being resampled 2x -> 1x on its
    # own, or the paint disagreeing with itself in the last row or two of every band
    # (the slice-vs-reference test reports 0.02% differing - 1-2 rows out of 278,
    # thin enough to pass every ratio test written so far and straight enough to see
    # as a line). With this on, bands are nearest-sampled. Lines gone = the resampler.
    # Lines still there = the paint. Either answer is one specific fix, instead of
    # another round of confident guessing.
    #
    # Read from the environment at import: the processes that paint the bands are
    # children, and a class attribute set in the parent after they started would
    # look like a switch that does nothing.
    NEAREST_BANDS = os.environ.get("RAIDEN_NEAREST_BANDS") == "1"

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
        # The bake rows a camera can see at one time: one field-height of ground,
        # and the definition `window_at` measures a slice range against.
        self.view = int(TILE2)
        self.count = max(1, math.ceil(self.height / self.slice_h))
        # Painting happens in the worker process unless the caller says otherwise
        # (see `paint`). Set by `Level`, which knows how long the sector is.
        self.via_process = False
        self._surf: list[Any] = [None] * self.count
        self._lock = threading.Lock()
        self._cursor = 0
        # Where the camera wants ground next, as a slice index. See `focus`.
        self._hint = 0

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

    def paint(self, i: int, stop: Any = None) -> Any:
        """Paint slice `i` and return its surface. Idempotent, thread-safe.

        With `via_process` set, the work is asked for in the design/paint worker
        - which is the point of the whole arrangement, since a slice is 0.75 s of
        numpy and surface work that the frame thread will not share. A worker
        that cannot do it costs a slower slice, not a hole: the local path is
        always there. The picture is the same either way, which is asserted in
        tests/test_level_paint.py rather than assumed.

        `stop` is the owning Level's event, and it is handed to the child wait
        rather than only checked before it. A paint that is queued but no longer
        wanted is not worth waiting for, and waiting for it is why `Level.stop()`
        timed out with a worker still inside `future.result()`.
        """
        with self._lock:
            if self._surf[i] is not None:
                return self._surf[i]
        surf = None
        if self.via_process:
            from .paintsrv import paint_slice

            surf = paint_slice(self.plan, self.layer, i, self.slice_h,
                               self.margin, stop=stop)
            if stop is not None and stop.is_set():
                return None        # being taken down; nothing to keep

        if surf is None:
            if stop is not None and stop.is_set():
                return None
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
            # Seeded by world position inside `_grid`, so a slice's base materials
            # do not depend on which slice it is: `i` used to be in the seed here,
            # which re-rolled the whole material grid at every boundary.
            _grid(plane.stamp, kit, list(NEAR_MATS[self.plan.theme]),
                  Random(self.plan.seed * 7717), origin=(0, y0))
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
        # Where the kept band starts **inside the window**. `window(i)` runs the
        # plane `margin` past the band at both ends and clamps at the strip's ends,
        # so the band's offset is `i * slice_h - y0` - positive, usually `margin`.
        # The subtraction here used to be the other way round: `-margin`, which
        # `max(0, ...)` turned into 0, so every slice kept its TOP MARGIN and was
        # displaced by exactly that much ground. Slice 0 clamps to y0 = 0, so slice 0
        # was accidentally correct and every boundary after it jumped by a margin -
        # a line across the field with the period of a slice, which is what the
        # "remove every second tile and it lines up" report described. Measured: with
        # the sign wrong, a best-fit shift of exactly one margin removed 99.97% of the
        # difference; slice 0 showed none at all.
        top = i * self.slice_h - y0
        keep = surf.subsurface((0, top, W2, min(h - top, self.slice_h)))
        keep = keep.copy()
        if self.downscale:
            keep = (pygame.transform.scale if TerrainStrip.NEAREST_BANDS
                    else pygame.transform.smoothscale)(
                keep, (keep.get_width() // SS, keep.get_height() // SS))
        return keep

    # ------------------------------------------------------------- frontier
    def frontier(self) -> int:
        """Slices painted contiguously from the top of the strip.

        **Not** a measure of coverage: painting is ordered by what the camera needs
        next (`focus`), so ground behind the craft is deliberately painted last and
        this stays at 0 while the screen is fully covered. Use `missing_at` for
        "is the view covered" and `painted_count` for "how much exists".
        """
        with self._lock:
            n = 0
            while n < self.count and self._surf[n] is not None:
                n += 1
            return n

    def painted_count(self) -> int:
        """How many slices exist, wherever they are in the strip."""
        with self._lock:
            return sum(1 for s in self._surf if s is not None)

    def focus(self, y: float) -> None:
        """Tell the painter where the camera is, in bake rows.

        Painting used to start at slice 0 and walk down, which meant the first
        seconds of a sector's work went on ground behind the craft - never to be
        seen - while the screen itself stayed empty and the launch gate waited. The
        painter now starts at the camera's own window and walks forward, back-
        filling behind when it has nothing else to do. Called from the frame thread
        with a number the camera already knows.
        """
        lo, _ = self.window_at(y)
        self._hint = lo

    def surface(self, i: int) -> Any:
        with self._lock:
            return self._surf[i] if 0 <= i < self.count else None

    def advance(self, stop: Any = None) -> bool:
        """Paint the next slice the camera will need. False when the strip is done.

        The worker's whole inner loop: one slice at a time, so a stop request costs
        at most one slice. Ordered from the current `focus` forward and then wrapped
        around, so the ground about to be flown arrives first and the ground already
        flown over arrives when the painters are idle - which is also what makes a
        respawn free: nothing about the painted set is thrown away, and the cursor
        is the camera's, not a counter that has to be re-wound.
        """
        with self._lock:
            start = min(max(int(self._hint), 0), self.count - 1)
            i = -1
            for k in range(self.count):
                cand = (start + k) % self.count
                if self._surf[cand] is None:
                    i = cand
                    break
            if i < 0:
                return False
            self._cursor = i
        self.paint(i, stop)
        return True

    def window_at(self, y: float) -> tuple[int, int]:
        """The slice range the camera at row `y` draws: **one** definition.

        This used to be computed twice - once to blit, once to ask whether the
        ground was ready - and the two disagreed by a slice. The strip below the
        craft is drawn from the lowest slice of the range, which was the one the
        readiness check never asked about, so a sector could be called ready with a
        bare band across the bottom of the screen: exactly the second of black
        under the ship that survived every other fix. Draw and readiness now read
        from here, so they cannot drift apart again.

        `y` is bake space and is the strip row standing at the **top** edge of the
        field, so what the camera sees is [y - view, y].
        """
        lo = max(0, int((y - self.view) // self.slice_h) - 1)
        hi = min(self.count, int(y // self.slice_h) + 1)
        return lo, max(lo, hi)

    def missing_at(self, y: float) -> int:
        """Index of the first unfinished slice the camera at `y` can see.

        Asking about a narrower range than `draw` uses is how a sector gets called
        ready while part of the screen is still black; see `window_at`.
        """
        lo, hi = self.window_at(y)
        with self._lock:
            for i in range(lo, hi):
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
        lo, hi = self.window_at(y)
        drawn = 0
        for i in range(max(0, lo), min(self.count, hi)):
            surf = self.surface(i)
            if surf is None:
                continue
            # the slice's *far* row is the one nearest the top edge
            top = band.top + (y - (i + 1) * self.slice_h) / SS
            # The clip is a rect *in the slice*, not the band it lands on. An
            # area's left/top are read as offsets into the source surface, so
            # handing it `band` cropped FIELD_TOP rows off the top of every slice
            # and FIELD_LEFT columns off its left - which is a bare gap the height
            # of the HUD at every slice boundary, and looked exactly like the
            # toolbar had been stamped between the tiles.
            canvas.set_clip(band)
            canvas.blit(surf, (band.left, int(round(top))),
                        (0, 0, min(surf.get_width(), band.width),
                         surf.get_height()))
            canvas.set_clip(None)
            drawn += 1
        return drawn
