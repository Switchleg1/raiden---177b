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

PHASE_PLAN = 46.0          # virtual seconds of scroll the plan spans


PHASE_FADE = 1.8           # dissolve duration at each zone boundary


class TerrainTrack:
    """One sector's worth of terrain: baked zone segments in phase order.

    Segments are Terrain objects sharing one seed; the active one is drawn
    plain, and each zone boundary dissolves in over PHASE_FADE virtual
    seconds (new map crossfading over the old one)."""

    def __init__(self, phases: tuple, seed: int = 1) -> None:
        if not phases:
            raise ValueError("TerrainTrack needs at least one phase")
        total = sum(float(p.weight) for p in phases) or 1.0
        segs: list = []
        t0 = 0.0
        for p in phases:
            t1 = t0 + PHASE_PLAN * float(p.weight) / total
            segs.append([Terrain(p.theme, seed), t0, t1])
            t0 = t1
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

    def draw(self, canvas: Any) -> None:
        import pygame
        old = canvas.get_clip()
        canvas.set_clip(pygame.Rect(0, C.HUD_H, C.LOGICAL_W, TILE_H))
        i = self._idx(self.t)
        if i > 0:
            b = self.segs[i][1]
            a = (self.t - b) / PHASE_FADE
            if a < 1.0:
                self.segs[i - 1][0].draw(canvas)          # old zone below
                if self._scratch is None:
                    self._scratch = pygame.Surface(
                        (C.LOGICAL_W, C.LOGICAL_H), pygame.SRCALPHA)
                self._scratch.fill((0, 0, 0, 0))
                self.segs[i][0].draw(self._scratch)       # new zone
                self._scratch.set_alpha(max(2, min(254, int(255 * a))))
                canvas.blit(self._scratch, (0, 0))
                canvas.set_clip(old)
                return
        self.segs[i][0].draw(canvas)
        canvas.set_clip(old)
