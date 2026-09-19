"""Ahead-of-time loading, so the render thread never stops to fetch art.

Two loads used to happen at the worst possible instant: a sector's baked
terrain (three big PNGs, scaled down, per phase zone) when the sector started,
and a boss's sprite sheet the frame it appeared. Both are tens of milliseconds
of work on the main thread, which in a vertical shooter is a visible hitch in
the middle of a fight.

:class:`Prefetch` moves that work onto one daemon thread. The App asks for a
sector (or a sheet) long before it is needed; the worker builds it; whoever
needs it either finds it ready or falls back to loading it the old way. Nothing
here is required for correctness - a prefetch that never completes degrades to
the previous behaviour, it does not break the frame.

Ownership note: a cached sector's maps are **handed over** by
:meth:`sector_track`, not copied. ``Terrain`` carries its own scroll offsets, so
sharing one instance between two live tracks would make two sectors drag the
same parallax state. ``take`` therefore pops, and the App re-requests the next
sector after each handoff so a retry is still warm.
"""
from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

from terrain.track import TerrainTrack, plan_span, sector_key, sector_phases

__all__ = ["Prefetch", "sector_key", "sector_phases"]


class Prefetch:
    """One worker thread, two job kinds: sector terrain and sprite sheets."""

    MAX_SECTORS = 6            # bounded: a long run must not grow without end

    def __init__(self, bank: Any = None, enabled: bool = True,
                 map_factory: Callable[[Any, int], Any] | None = None) -> None:
        self._bank = bank
        self._map_factory = map_factory
        self._enabled = enabled
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._maps: dict[tuple, tuple] = {}
        self._order: list[tuple] = []
        self._wanted: set[tuple] = set()
        self._thread: threading.Thread | None = None
        self.built = 0            # observability (tests, future debug overlay)
        self.misses = 0

    # ------------------------------------------------------------------ queue
    def _start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="raiden-prefetch",
                                        daemon=True)
        self._thread.start()

    def request_sector(self, level: Any, seed: int = 1) -> None:
        """Queue one sector's terrain maps. Idempotent while queued or built."""
        if not self._enabled:
            return
        phases = sector_phases(level)
        key = sector_key(phases, seed)
        with self._lock:
            if key in self._maps or key in self._wanted:
                return
            self._wanted.add(key)
        self._start()
        self._q.put(("sector", key, phases, seed))

    def request_art(self, *names: str) -> None:
        """Queue sprite sheets so the first frame that needs one can blit.

        Sheets are counted in :meth:`pending` like sectors are, so a caller can
        wait for the queue honestly instead of guessing a frame count.
        """
        if not self._enabled or self._bank is None:
            return
        for name in names:
            if not name:
                continue
            key = ("art", name)
            with self._lock:
                if key in self._wanted:
                    continue
                self._wanted.add(key)
            self._start()
            self._q.put(("art", name))

    # ------------------------------------------------------------------- take
    def sector_track(self, level: Any, seed: int = 1) -> TerrainTrack | None:
        """A ready-made track for this sector, or None if it is not built yet.

        Never blocks: the caller is drawing. None means "build it yourself",
        which is exactly what happened before prefetching existed.
        """
        if not self._enabled:
            return None
        phases = sector_phases(level)
        key = sector_key(phases, seed)
        with self._lock:
            maps = self._maps.pop(key, None)
            if maps is not None and key in self._order:
                self._order.remove(key)
            elif key not in self._wanted:
                self.misses += 1
        if maps is None:
            self.request_sector(level, seed)      # warm it for the next attempt
            return None
        return TerrainTrack(phases, seed, maps=maps,
                              plan=plan_span(level))

    def pending(self) -> int:
        with self._lock:
            return len(self._wanted)

    # ------------------------------------------------------------- the worker
    def _run(self) -> None:
        while True:
            job = self._q.get()
            if job is None:
                return
            try:
                if job[0] == "sector":
                    self._build_sector(job[1], job[2], job[3])
                else:
                    self._build_art(job[1])
            except Exception:
                with self._lock:
                    self._wanted.discard(job[1] if job[0] == "sector"
                                         else ("art", job[1]))
                # A prefetch failure is a missed optimisation, never a crash:
                # the consumer falls back to loading the thing synchronously.

    def _build_sector(self, key: tuple, phases: tuple, seed: int) -> None:
        if self._map_factory is not None:
            factory: Callable[[Any, int], Any] = self._map_factory
        else:
            from terrain.terrain_map import Terrain
            factory = Terrain
        maps = tuple(factory(p.theme, seed) for p in phases)
        with self._lock:
            self._maps[key] = maps
            self._order.append(key)
            self._wanted.discard(key)
            while len(self._order) > self.MAX_SECTORS:
                oldest = self._order.pop(0)
                self._maps.pop(oldest, None)
            self.built += 1

    def _build_art(self, name: str) -> None:
        if self._bank is not None:
            self._bank.sheet(name)
            with self._lock:
                self._wanted.discard(("art", name))
                self.built += 1

    def shutdown(self) -> None:
        """Ask the worker to stop. Daemon thread, so a stuck job is harmless."""
        self._q.put(None)
