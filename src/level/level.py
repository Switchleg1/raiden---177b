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
import time
from typing import Any

from terrain.common import NEAR_SPEED, TILE2
from terrain.siteplan import CELL, Geom

from .design import PROCESS_MIN_LENGTH, plan_sector
from .encounters import plan_encounters
from .strip import STRIP_MARGIN, STRIP_SLICE, TerrainStrip

__all__ = ["Level", "strip_length"]

# Last measured design time, per (theme, seed, length). The loading bar's first half
# has nothing countable inside it - one call designs the whole sector - so it creeps
# against this, which is at least a measurement of the same job on this machine.
_DESIGN_SECONDS: dict[tuple[str, int, int], float] = {}
_DESIGN_DEFAULT = 8.0

# Workers whose `stop()` ran out of budget. They are joined by the next stop rather
# than dropped, because "timed out" is not the same as "finished" and a live worker
# walking into SDL teardown is a crash, not an exception.
_STRAGGLERS: list[threading.Thread] = []

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


def strip_length(spec: Any, tail: float | None = None) -> int:
    """Bake-space length of a sector's ground: everything it can be flown.

    The sector's own wave length plus the boss tail, at the ground layer's
    scroll rate, at the 2x bake scale every painters in ``terrain/`` uses.
    """
    if tail is None:
        tail = float(getattr(spec, "boss_tail_seconds", BOSS_TAIL))
    seconds = float(getattr(spec, "wave_seconds", 0.0) or 0.0) + tail
    return int(round(seconds * NEAR_SPEED * 2))       # SS == 2


class Level:
    """A sector: its plan, its painted ground, its place in the scroll."""

    def __init__(self, spec: Any, seed: int = 1,
                 layers: tuple[str, ...] = ("near", "far"),
                 slice_h: int = STRIP_SLICE,
                 margin: int = STRIP_MARGIN,
                 tail: float | None = None,
                 process_design: bool | None = None,
                 process_paint: bool | None = None) -> None:
        self.spec = spec
        self.seed = int(seed)
        self.theme = str(getattr(spec, "theme", "")).split(".")[-1].lower()
        self.length = strip_length(spec, tail)
        self.tail_seconds = float(tail if tail is not None else float(
            getattr(spec, "boss_tail_seconds", BOSS_TAIL)))
        self.slice_h, self.margin = slice_h, margin
        self._layers = tuple(layers)
        for name in self._layers:
            if name not in ("near", "far"):
                raise ValueError(f"unknown strip layer {name!r}")
        self.geom: Any = None
        self.plan: Any = None
        # None says "decide by size": a one-screen map is designed here, a
        # sector is designed in another process so the frame thread cannot stall
        # it. True/False says so.
        self.process_design = process_design
        # Same judgement for the painting: a sector is painted in the worker
        # process, a one-screen map is painted here.
        self.process_paint = process_paint
        self.encounters: list[Any] = []
        self.strips: dict[str, TerrainStrip] = {}
        # The camera's row: the strip row standing at the top edge of the field.
        # It starts one screen into the strip so the opening band is full of
        # ground at once (rows 0..one screen fill the field), and it grows as the
        # craft flies forward.
        self.near_y = float(TILE2)
        self.far_y = float(TILE2)
        self._threads: list[threading.Thread] = []
        self._design_t0: float | None = None
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
        t0 = time.monotonic()
        self._design_t0 = t0
        self.plan = plan_sector(self.theme, self.seed, self.length,
                                process=self.process_design, stop=self._stop)
        if self.plan is not None:
            # Remembered, not assumed: the loading bar's first half is an estimate,
            # and the only honest estimate is the last time this same job took. Each
            # finished design replaces the guess, so the bar learns the machine it
            # is running on instead of a number someone typed.
            _DESIGN_SECONDS[self._estimate_key()] = time.monotonic() - t0
        if self.plan is None:
            # Taken down mid-design. `plan` stays None, so `built()` is false and
            # every reader falls back the way it already does for a sector that has
            # not been designed yet - which, from the game's point of view, it now
            # is not.
            return
        # The sector's fights are chosen from the ground, so they are planned on
        # the same thread, straight after the ground they stand on exists. Cheap
        # next to the design pass, and it must not run on the frame thread: a
        # Level is made in the middle of a fight.
        self.encounters = list(plan_encounters(self.plan, self.spec,
                                               tail=self.tail_seconds))
        self.strips = {name: TerrainStrip(self.plan, name, self.slice_h,
                                          self.margin)
                       for name in self._layers}
        use = ((self.length >= PROCESS_MIN_LENGTH) if self.process_paint is None
               else bool(self.process_paint))
        for strip in self.strips.values():
            strip.via_process = use

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
            if not strip.advance(self._stop):
                return
            # Stay a few slices ahead of the camera and no further ahead. Asked as
            # "is the ground the camera will need there yet", not as a count from
            # the top of the strip: painting is ordered from the camera outward, so
            # a contiguous-from-zero count sits at nought while the screen is fully
            # covered, and a throttle reading it would paint the whole sector before
            # the craft had moved.
            #
            # The camera's row is read *inside* the wait, every poll. Reading it
            # once, as this did, parks the worker for the rest of the sector: the
            # slices that were ahead when the wait began are the very slices it is
            # waiting for, so the condition can never become false, and ground stops
            # arriving about a quarter of the way into the sector while the craft
            # flies on past the last painted slice.
            while not self._stop.is_set():
                row = self.far_y if strip.layer == "far" else self.near_y
                if strip.missing_at(row + LOOKAHEAD * strip.slice_h) >= 0:
                    break
                strip.focus(row)          # keep the painter aimed where it is now
                self._stop.wait(0.05)

    def stop(self, timeout: float = 3.0) -> None:
        """Stop painting and wait for the workers to actually stop.

        Joining is the point, not the flag: a worker mid-slice is inside pygame
        building surfaces, and tearing SDL down underneath it is an access
        violation, not an exception.

        `timeout` is a **total** budget, shared by every thread - it used to be per
        thread, which meant a Level with two painters and a designer could take the
        sum of them and the caller had no idea. A worker that outlives the budget is
        not dropped: it is kept in `_STRAGGLERS` and joined by the next `stop()`, so
        a Level can no longer lose a worker into SDL teardown by timing out on it.
        """
        self._stop.set()
        global _STRAGGLERS
        # Anything a previous stop ran out of patience for is given a chance first:
        # it has already had the longest grace period by now.
        still = [t for t in _STRAGGLERS if t.join(0.0) is None and t.is_alive()]
        _STRAGGLERS = still
        deadline = time.monotonic() + max(0.0, float(timeout))
        for t in self._threads:
            if not t.is_alive():
                continue
            left = deadline - time.monotonic()
            if left <= 0.0:
                _STRAGGLERS.append(t)
                continue
            t.join(left)
            if t.is_alive():
                _STRAGGLERS.append(t)
        self._threads = []

    # ------------------------------------------------------------- progress
    def built(self) -> bool:
        return self.plan is not None

    def _estimate_key(self) -> tuple[str, int, int]:
        return (str(self.theme), int(self.seed), int(self.length))

    def design_elapsed(self) -> float:
        """How long this sector's design has been running; 0 once it is done."""
        if self.plan is not None or self._design_t0 is None:
            return 0.0
        return time.monotonic() - self._design_t0

    def design_estimate(self) -> float:
        """Seconds this design is expected to take, from the last time it ran.

        A sector's design is one call with nothing countable inside it, so the
        loading bar cannot measure it the way it measures slices. The honest
        substitute is the previous measurement of the same job on this machine,
        which every completed design replaces - and the bar never claims the first
        half is finished, it only creeps towards it.
        """
        return _DESIGN_SECONDS.get(self._estimate_key(), _DESIGN_DEFAULT)

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

    def ready_ahead(self, y_bake: float, lead: float) -> bool:
        """Is the ground painted for a camera at `y_bake` **and** `lead` rows more?

        This is what a launch should ask. Asking only about what is on screen at
        the instant of launch is how play begins with black underneath it: the
        craft starts moving immediately, and the ground it moves into is the ground
        nobody promised. One screen of lead is a few seconds of flight, which is
        roughly how long the painters need to stay in front anyway - so the wait is
        paid from READY, where it is invisible, instead of from the first second of
        play, where it is the first thing the player sees.
        """
        if not self.strips:
            return False
        return all(strip.missing_at(y_bake + lead) < 0
                   and strip.missing_at(y_bake) < 0
                   for strip in self.strips.values())

    def page_slices(self, lead: float = 0.0) -> tuple[int, int]:
        """(missing, total) slices the page at the camera needs, lead included.

        "The page" is everything the field will show *and* what the craft flies
        into in the first moments of play - the same lead the launch gate insists
        on, counted over the same range, so the loading bar and the gate are
        measuring one thing rather than two that happen to agree.
        """
        if not self.strips:
            return 1, 1
        missing = total = 0
        for strip in self.strips.values():
            y = self.far_y if strip.layer == "far" else self.near_y
            lo, _hi = strip.window_at(y)
            hi = min(strip.count, int((y + lead) // strip.slice_h) + 1)
            hi = max(hi, lo + 1)
            for i in range(lo, hi):
                total += 1
                if strip.surface(i) is None:
                    missing += 1
        return missing, max(1, total)

    def ensure_page(self, lead: float = 0.0) -> bool:
        """Paint **one** missing slice of the page. True when the page is done.

        One slice per call, from the frame thread, on purpose. The alternative -
        paint the whole page in one go before launching - stalls the loading screen
        for seconds and the bar sits frozen doing its job badly. Called once per
        READY frame, this paints the page in the time the pause takes, keeps the bar
        moving per slice, and guarantees the claim the whole arrangement is judged
        on: when play starts, the ground is already there.

        This is the launch path, not a fallback. Asking whether the painters have
        got there yet and hoping is what showed a field backdrop for a second after
        the bar went away.
        """
        if not self.strips:
            self.build()
            return False
        for strip in self.strips.values():
            y = self.far_y if strip.layer == "far" else self.near_y
            lo, _hi = strip.window_at(y)
            hi = min(strip.count, int((y + lead) // strip.slice_h) + 1)
            for i in range(lo, max(hi, lo + 1)):
                if strip.surface(i) is None:
                    strip.paint(i, self._stop)
                    return False
        return True

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
                strip.paint(i, self._stop)
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
        self.near_y = min(self.near_y, float(self.length))
        self.far_y = min(self.far_y, float(self.length))
        # Tell the painters where the camera got to. Cheap integer arithmetic on the
        # frame thread, and it is what keeps painting ahead of the scroll instead of
        # behind it: a strip paints from its `focus` forward, so the ground about to
        # be flown is always next and the ground already flown is back-filled when
        # the painters have nothing else to do.
        for name, strip in self.strips.items():
            strip.focus(self.far_y if name == "far" else self.near_y)

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
