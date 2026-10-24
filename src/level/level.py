"""One sector, as an object: planned in full, painted while you fly it.

A `Level` is what the game is looking at. It knows the sector's whole length, so
it plans the entire ground once (`siteplan` over a strip, not a screen) and then
paints that plan a slice at a time on worker threads. The level starts as soon as
the first slices exist - the rest of the sector is still being drawn when the
craft takes off, and drawing has to outrun the scroll, not finish first.

The App keeps exactly two of these: the one being flown, and the one being
prepared. That is the whole prefetch story: while the player is halfway through
sector N, sector N+1's ground is already being painted, so a sector change stops
being a load and becomes a pointer swap.
"""
from __future__ import annotations

import threading
from typing import Any

from terrain.common import NEAR_SPEED, SS, TILE2
from terrain.siteplan import CELL, Geom, plan_site

from .strip import STRIP_MARGIN, STRIP_SLICE, TerrainStrip

__all__ = ["Level", "strip_length"]

BOSS_TAIL = 60.0      # seconds of ground kept under a sector after its wave
LOOKAHEAD = 4         # slices painted ahead of the camera
# Painting is not a queue to drain. A worker that paints the whole sector up
# front burns 200 MB and a minute of CPU on ground the player may never reach -
# death, restart and sector change all throw it away. The workers paint a few
# slices ahead of the camera and idle otherwise; the strip is still the whole
# sector, it is just drawn as it is approached.
# The wave table ends and the boss arrives, but the ground has to keep coming:
# a boss fight is flown, not paused, and running out of strip mid-fight would
# stop the world. Generous, because the cost is paint time we were never going
# to use, not a hitch.


def strip_length(spec: Any, tail: float = BOSS_TAIL) -> int:
    """Bake-space length of a sector's ground: everything it can be flown.

    The sector's own wave length plus the boss tail, at the ground layer's
    scroll rate, at the 2x bake scale every painters in ``terrain/`` uses.
    """
    seconds = float(getattr(spec, "wave_seconds", 0.0) or 0.0) + tail
    return int(round(seconds * NEAR_SPEED * 2))       # SS == 2


class Level:
    """A sector: its plan, its painted ground, its place in the scroll."""

    def __init__(self, spec: Any, seed: int = 1,
                 layers: tuple[str, ...] = ("near", "far"),
                 slice_h: int = STRIP_SLICE,
                 margin: int = STRIP_MARGIN,
                 tail: float = BOSS_TAIL) -> None:
        self.spec = spec
        self.seed = int(seed)
        self.theme = str(getattr(spec, "theme", "")).split(".")[-1].lower()
        self.length = strip_length(spec, tail)
        self.slice_h, self.margin = slice_h, margin
        self._layers = tuple(layers)
        for name in self._layers:
            if name not in ("near", "far"):
                raise ValueError(f"unknown strip layer {name!r}")
        self.geom: Any = None
        self.plan: Any = None
        self.strips: dict[str, TerrainStrip] = {}
        self.near_y = 0.0
        self.far_y = 0.0
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    # ------------------------------------------------------------ lifecycle
    def build(self) -> None:
        """Design the whole sector, then open a strip per layer.

        Deliberately not in the constructor: designing a 110 s sector is seconds
        of work, and a Level gets made in the middle of a fight - halfway through
        the sector before it, which is the point of the whole arrangement. So the
        plan is made on the level's own thread, and everything asked before it is
        finished answers "nothing yet" instead of blocking or half-drawing.
        """
        if self.plan is not None:
            return
        self.geom = Geom(h=self.length, cell=CELL, cyclic=False)
        self.plan = plan_site(self.theme, self.seed, self.geom)
        self.strips = {name: TerrainStrip(self.plan, name, self.slice_h,
                                          self.margin)
                       for name in self._layers}

    def start(self) -> None:
        """Begin designing and painting: one thread per layer, the designer on
        the first one. Nothing here runs on the frame thread."""
        if self._threads:
            return
        for i, name in enumerate(self._layers):
            t = threading.Thread(target=self._work, args=(name, i == 0),
                                 name=f"raiden-strip-{name}-{self.seed}",
                                 daemon=True)
            self._threads.append(t)
            t.start()

    def _work(self, name: str, first: bool) -> None:
        if first:
            self.build()
        else:
            while self.plan is None and not self._stop.is_set():
                self._stop.wait(0.05)
        if self.plan is None or self._stop.is_set():
            return
        strip = self.strips[name]
        while not self._stop.is_set():
            if not strip.advance():
                return
            # Stay a few slices ahead of the camera and no further ahead.
            while (not self._stop.is_set()
                   and strip.frontier() >= self._need(strip)):
                self._stop.wait(0.05)

    def _need(self, strip: TerrainStrip) -> int:
        """The slice index the camera is standing on, for this layer."""
        y = self.far_y if strip.layer == "far" else self.near_y
        return int(y / SS) // strip.slice_h + LOOKAHEAD

    def stop(self, timeout: float = 3.0) -> None:
        """Stop painting and wait for the workers to actually stop.

        Joining is the point, not the flag: a worker mid-slice is inside pygame
        building surfaces, and tearing SDL down underneath it is an access
        violation, not an exception.
        """
        self._stop.set()
        for t in self._threads:
            if t.is_alive():
                t.join(timeout)
        self._threads = []

    # ------------------------------------------------------------- progress
    def built(self) -> bool:
        return self.plan is not None

    def progress(self) -> float:
        """0..1 of the way painted, counting the *slowest* layer.

        The ground is only as far along as its laggiest layer; reporting the
        faster one would let a caller believe it is safe to fly somewhere the far
        range has not been drawn yet.
        """
        if not self.strips:
            return 0.0
        return min(s.frontier() / s.count for s in self.strips.values())

    def ready_at(self, y_logical: float) -> bool:
        """Is the ground under a camera at logical `y` painted?"""
        if not self.strips:
            return False
        y = y_logical * 2
        return all(strip.missing_at(y) < 0 for strip in self.strips.values())

    def ensure(self, y_logical: float) -> int:
        """Paint synchronously whatever the camera at `y` can still see.

        The safety net, not the normal path: the first frames of the first
        sector, and any sector that somehow starts behind its painters. Returns
        how many slices it had to draw.
        """
        y = y_logical * 2
        done = 0
        if not self.strips:
            self.build()                    # nothing else can answer this ask
        for strip in self.strips.values():
            while True:
                i = strip.missing_at(y)
                if i < 0 or self._stop.is_set():
                    break
                strip.paint(i)
                done += 1
        return done

    # ---------------------------------------------------------------- scroll
    def update(self, dt: float, scale: float = 1.0) -> None:
        from terrain.common import FAR_SPEED
        from terrain.common import NEAR_SPEED as NEAR

        dt *= scale
        self.near_y += NEAR * dt
        self.far_y += FAR_SPEED * dt
        # The strip has an end. Past it there is nothing to draw, so the ground
        # holds rather than running out from under the craft.
        self.near_y = min(self.near_y, self.length - TILE2)
        self.far_y = min(self.far_y, self.length - TILE2)

    def draw(self, canvas: Any, band: Any) -> int:
        """Draw the field's ground inside `band` (the field rect).

        Returns the number of slices drawn: 0 means this level has nothing to
        show yet, which is the caller's cue to fall back or wait.
        """
        drawn = 0
        # far first: it is the range behind the ground the craft flies over, and
        # the near layer is opaque wherever its material grid was laid
        for name in ("far", "near"):
            strip = self.strips.get(name)
            if strip is None:
                continue
            y = self.far_y if name == "far" else self.near_y
            drawn += strip.draw(canvas, band, y % max(1, self.length - TILE2))
        return drawn
