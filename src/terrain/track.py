"""Per-sector terrain schedule: zones + crossfade."""
from __future__ import annotations

from typing import Any

import config as C

from .common import TILE_H
from .terrain_map import Terrain

# ---------------------------------------------------------------------------
# phase scheduling: a sector dissolves through its terrain zones as the
# player scrolls (Raiden's mid-level environment changes).
# ---------------------------------------------------------------------------

PHASE_PLAN = 46.0          # default span, used when a sector has no wave length


PHASE_FADE = 1.8           # dissolve duration at each zone boundary


def plan_span(level: Any) -> float:
    """How long a sector's zone plan should take.

    A sector defines its own wave length, and the terrain plan is meant to fill
    that wave: on a 75 s sector the zone change should not arrive after 46 s of
    scroll and leave the rest of the sector on one map. Sectors without a wave
    length (an arena, a menu backdrop) fall back to the default plan.
    """
    span = float(getattr(level, "wave_seconds", 0.0) or 0.0)
    return span if span > 0.0 else PHASE_PLAN


class TerrainTrack:
    """One sector's worth of terrain: baked zone segments in phase order.

    Segments are Terrain objects sharing one seed; the active one is drawn
    plain, and each zone boundary dissolves in over PHASE_FADE virtual
    seconds (new map crossfading over the old one)."""

    def __init__(self, phases: tuple, seed: int = 1,
                 maps: tuple | None = None, plan: float = PHASE_PLAN) -> None:
        """Build a sector track, optionally from pre-built zone maps.

        ``maps`` is what the prefetch thread hands over: the expensive part of
        a track is loading and rescaling each zone's baked art, so the App can
        have that done off the render thread and assemble the schedule here in
        microseconds. ``seed`` is still required because it identifies the maps
        (a map built for another seed would not match one handed over later).
        """
        if not phases:
            raise ValueError("TerrainTrack needs at least one phase")
        if maps is not None and len(maps) != len(phases):
            raise ValueError("TerrainTrack got maps for a different schedule")
        if plan <= 0.0:
            raise ValueError("TerrainTrack needs a positive plan span")
        total = sum(float(p.weight) for p in phases) or 1.0
        segs: list = []
        t0 = 0.0
        for i, p in enumerate(phases):
            t1 = t0 + plan * float(p.weight) / total
            segs.append([Terrain(p.theme, seed) if maps is None else maps[i],
                         t0, t1])
            t0 = t1
        self.plan = float(plan)
        self.segs = segs
        self.t = 0.0
        self._scratch: Any = None

    def update(self, dt: float, scale: float) -> None:
        self.t += dt * scale
        for seg in self.segs:                    # cheap: offsets only
            seg[0].update(dt, scale)

    def _idx(self, t: float) -> int:
        for i, (_, _t0, t1) in enumerate(self.segs):
            if t < t1:
                return i
        return len(self.segs) - 1

    def draw(self, canvas: Any, clip: Any = None) -> None:
        import pygame
        band = pygame.Rect(0, C.HUD_H, C.LOGICAL_W, TILE_H)
        if clip is not None:
            band = band.clip(clip)
            if band.width <= 0 or band.height <= 0:
                return
        old = canvas.get_clip()
        canvas.set_clip(band)
        i = self._idx(self.t)
        if i > 0:
            b = self.segs[i][1]
            a = (self.t - b) / PHASE_FADE
            if a < 1.0:
                self.segs[i - 1][0].draw(canvas, clip=band)   # old zone below
                if self._scratch is None:
                    self._scratch = pygame.Surface(
                        (C.LOGICAL_W, C.LOGICAL_H), pygame.SRCALPHA)
                self._scratch.fill((0, 0, 0, 0))
                self.segs[i][0].draw(self._scratch)       # new zone (full field)
                self._scratch.set_alpha(max(2, min(254, int(255 * a))))
                canvas.blit(self._scratch, (0, 0))
                canvas.set_clip(old)
                return
        self.segs[i][0].draw(canvas, clip=band)
        canvas.set_clip(old)
