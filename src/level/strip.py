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
from terrain.plan.site_plan import SitePlan

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
                 slice_h: int = STRIP_SLICE, margin: int = STRIP_MARGIN) -> None:
        if layer not in ("near", "far"):
            raise ValueError(f"unknown strip layer {layer!r}")
        if slice_h <= 0 or margin < 0:
            raise ValueError("a strip slice needs a positive height")
        self.plan = plan
        self.layer = layer
        self.slice_h = int(slice_h)
        self.margin = int(margin)
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
        """Paint slice `i` and return the band `draw` blits.

        The band comes back TURNED OVER - its first row carries the strip's farthest
        world row - for the reason spelled out at the return below.
        """
        import pygame

        from terrain.paint.plane import Plane
        from terrain.paint.site import paint_far, paint_site

        kit = kit_for()
        y0, h = self.window(i)
        # One painted pixel per pixel shown. `Plane.scale` counts PLAN pixels per
        # painted pixel, so that means scale = SS: the plane comes out the size of the
        # band the renderer blits, and NOTHING sits between painting and blitting - no
        # scaler, no filter, nothing per slice to filter differently at an edge. It is
        # also three quarters fewer pixels to paint.
        #
        # The route this replaces painted at plan resolution and `smoothscale`d every
        # slice down, because the baked PNG pipeline was authored at 2x ("baked PNGs
        # live at 2x for extra detail; runtime loads them once and downscales"). Measured
        # through one material's texel, that route ran 256 -> 160 -> 80 -> 156 device px
        # at a 1.95x window: it ended with FEWER pixels than the material had before it
        # was halved, and what it bought was a resample of the whole plane per slice.
        # Materials still take the same two bilinear steps (256 -> 160 at load in
        # `TileKit`, 160 -> 80 for the tile pitch) - once per material, not once per
        # slice of ground.
        scale = SS
        plane = Plane(W2, h, x0=0, y0=y0, scale=scale)
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
                  Random(self.plan.seed * 7717), origin=(0, y0), scale=scale)
            plane.sync()
        # The pass-level stream only picks things the plan did not already pin
        # down; per-feature jitter comes from the plan itself, which is why
        # painting a slice in any order gives the same pixels.
        # The slice index used to be in this seed. Measured: taking it out changes
        # nothing (the disagreement between a slice and a one-window reference is
        # bit-identical either way), because every per-feature jitter already comes
        # from the plan. It is out anyway because a paint seeded by *which window*
        # is asking is the exact thing this codebase keeps having to relearn.
        rng = random.Random(self.plan.seed * 8191 + (7 if self.layer == "far" else 3))
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
        top = (i * self.slice_h - y0) // scale
        rows = min(h - (top * scale), self.slice_h) // scale
        keep = surf.subsurface((0, top, surf.get_width(), rows)).copy()
        # Turn the band over. `draw` places a slice so that its LAST world row - the
        # "far" row, furthest along the strip - sits at the top edge, because that is
        # what makes the ground continuous: the world row a display row stands for is
        # then `(y - row) / SS` no matter which slice the row came from. The plane
        # hands its rows over in ASCENDING world order, so returning `keep` as it came
        # out mirror-imaged every band inside its own footprint and left the neighbours
        # pointing the other way: measured across a composed frame, the world row shown
        # stepped correctly by SS within a band and then JUMPED BY 1110 world rows - two
        # whole slices - at every single boundary.
        #
        # That is the bug the screenshots have been describing since the start: a
        # half-house at each boundary, "some tiles are fine and others are just wrong",
        # "remove every second tile and it lines up" (every other band landed where its
        # own arithmetic expected). It survived because it is invisible to every test
        # that asks whether the ground is COVERED or whether slices AGREE: every row is
        # painted, and every slice paints the same way. `tests/test_level_paint.py::
        # test_slice_boundaries_show_no_jump_in_the_world_row` is the test that can see
        # it - colour every band row with the world row it carries and read the screen
        # back - and it fails on the un-flipped band with exactly the 1110-row jump.
        return pygame.transform.flip(keep, False, True)

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
        lo, hi = self.window_at(y)
        drawn = 0
        for i in range(max(0, lo), min(self.count, hi)):
            surf = self.surface(i)
            if surf is None:
                continue
            # What this blit actually needs is not "was `downscale` on" but "is a
            # band exactly one slice of DISPLAY rows": the placement below divides
            # slice_h by SS, and the bands tile only if that is their height. Painting
            # at the size shown satisfies it as well as painting at 2x and filtering
            # did, and this says so directly instead of assuming the old route.
            want = self.slice_h // SS
            if surf.get_height() != want or surf.get_width() > band.width * SS:
                raise RuntimeError(
                    f"slice {i} is {surf.get_size()} and would not tile the field: "
                    f"a band must be {want} display rows tall")
            # Where this slice goes. Its display row 0 stands for world row
            # `i * slice_h`, and a world row belongs at `band.top + (y - world) / SS`,
            # so:
            #
            #     top_i = band.top + (y - i * slice_h) / SS
            #
            # This used to read `(y - (i + 1) * slice_h) / SS`, which is the position
            # of the NEXT slice's first row: every band was drawn one whole slice too
            # high. It is invisible to a tiling check (consecutive bands still differ
            # by exactly a band height, so nothing gaps or overlaps) and invisible to a
            # coverage check (every row is still painted by somebody) - which is how it
            # survived while the ground was being drawn 278 display rows away from
            # where its own geometry says it is. `test_each_display_row_shows_the_
            # slice_that_owns_it` is what sees it: colour every slice, then ask row by
            # row whether the slice standing there is the one that owns that world row.
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
