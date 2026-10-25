"""The design pass, somewhere the frame thread cannot reach it.

`plan_site` is pure Python, and pure Python inside the game's interpreter gets
whatever the frame thread leaves over. That was measured, not guessed: flying a
real sector headless, a design that costs 2.7 s on its own had not finished after
12 s of wall clock, because the frame thread holds the GIL and a CPU-bound
thread never releases it.

So the design is asked for in another process, which has its own GIL and gets its
own core. Two properties make that cheap rather than heroic:

- a site plan is **pure data**. No pygame, no numpy, no surfaces: it pickles, and
  six screens of it is 336 KB - nothing next to the 0.75 s a slice costs to
  paint.
- it pickles **identically**. The planner keys its randomness on arithmetic, never
  on `hash()`, and never iterates a set, so a plan designed in another process is
  byte-for-byte the plan designed here. A replay cannot tell where the ground was
  thought up.
"""
from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any

__all__ = ["plan_sector", "shutdown_pool", "PROCESS_MIN_LENGTH"]

log = logging.getLogger("raiden.level")

# How long a design request waits on its child before noticing that the Level which
# asked for it has moved on.
_POLL = 0.1

log = logging.getLogger("raiden.level")

# Below this many bake px, paying for a process costs more than the design does.
# A one-screen map (the baked path) is 1120 px and stays in-process; a sector is
# tens of thousands and does not.
PROCESS_MIN_LENGTH = 3000

_POOL: Any = None
_LOCK = threading.Lock()
_BROKEN = False


def _plan_here(theme: str, seed: int, length: int, scars: float = 0.0) -> Any:
    """Design in this interpreter. The fallback, and the small-map path."""
    from terrain.design.site import plan_site
    from terrain.plan.geom import CELL, Geom

    return plan_site(theme, seed, Geom(h=int(length), cell=CELL, cyclic=False),
                     scars=float(scars))


def _init_worker() -> None:
    """Make the child a place terrain code can run: no display, no audio.

    The child does not draw - it thinks - but the import machinery of this repo
    assumes a usable SDL somewhere, so the worker is given a dummy driver rather
    than left to find none.
    """
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


def pool() -> Any:
    """The shared design worker, or None if this platform will not give one.

    Shared, not per level: a spawn on Windows is a fresh interpreter, and the
    point is to pay that once and then design every sector - and the next one
    prepared ahead of it - in the same warm process.
    """
    global _POOL, _BROKEN
    if _BROKEN:
        return None
    with _LOCK:
        if _POOL is None:
            try:
                _POOL = ProcessPoolExecutor(max_workers=2,
                                            initializer=_init_worker)
            except (OSError, ImportError, RuntimeError, ValueError) as exc:
                # Not fatal: the game designs on its own thread instead, which is
                # what it did before. Loud, because a silent fallback here is a
                # stall nobody can explain.
                _BROKEN = True
                log.warning("no design process available (%s); designing in-"
                            "process", exc)
                return None
        return _POOL


def plan_sector(theme: str, seed: int, length: int,
                process: bool | None = None, stop: Any = None,
                scars: float = 0.0) -> Any | None:
    """Design a sector's ground, in the other process when it is worth it.

    `process=None` decides by size; True/False says so. A worker that dies or a
    platform that refuses a child both end in the same place - designing here -
    because the ground arriving late is a worse sector than the ground arriving
    from the wrong interpreter.
    """
    want = (int(length) >= PROCESS_MIN_LENGTH) if process is None else bool(process)
    p = pool() if want else None
    if p is None:
        return _plan_here(theme, seed, length, scars)
    try:
        fut = p.submit(_plan_here, str(theme), int(seed), int(length), float(scars))
        if stop is None:
            return fut.result()
        # Polled for the same reason painting is: a Level can be stopped while its
        # sector is still being thought about, and a design nobody will draw is not
        # worth a thread that outlives `Level.stop()`. Returning None tells the
        # caller the sector was taken down mid-design; `Level.build` treats it as
        # "not designed yet", which is exactly what it is.
        while True:
            try:
                return fut.result(timeout=_POLL)
            except FuturesTimeout:
                if stop.is_set():
                    fut.cancel()
                    return None
    except Exception as exc:                      # noqa: BLE001 - any worker fault
        log.warning("design worker failed (%s); designing in-process", exc)
        return _plan_here(theme, seed, length, scars)


def shutdown_pool() -> None:
    """Finish and dismiss the design worker. Called when the app comes down.

    Waiting is the point, as with every other worker here: tearing the runtime
    down underneath a running child is how a clean exit turns into a crash.
    """
    global _POOL
    with _LOCK:
        if _POOL is not None:
            try:
                _POOL.shutdown(wait=True)
            except Exception:                     # noqa: BLE001 - teardown path
                pass
            _POOL = None
