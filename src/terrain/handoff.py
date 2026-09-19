"""Progressive sector handoff: the next sector's ground scrolls in from the top.

Clearing a boss used to mean "load a new level": the old ground vanished and a
new map appeared, with a load hitch in between. Here the incoming sector's maps
are already built (see :mod:`prefetch`), so the sector change is drawn instead:
the new sector's ground is revealed by an edge that sweeps down the field while
both maps keep scrolling at their own parallax rates. The player never leaves
the field, and no sector boundary is ever a black frame.

The reveal edge is drawn as a bright scanline that thins out as it reaches the
bottom of the field - the same visual language as the zone dissolves inside a
sector (:mod:`terrain.track`), just spatial instead of temporal.
"""
from __future__ import annotations

from typing import Any

import config as C

from .common import TILE_H

HANDOFF_SECONDS = 2.4      # full sweep of the field at 1x scroll


class SectorHandoff:
    """Draw two sector tracks as one: incoming above the edge, outgoing below."""

    def __init__(self, old: Any, new: Any,
                 dur: float = HANDOFF_SECONDS) -> None:
        if new is None:
            raise ValueError("SectorHandoff needs the incoming track")
        if dur <= 0.0:
            raise ValueError("SectorHandoff needs a positive duration")
        self.old = old
        self.new = new
        self.dur = float(dur)
        self.t = 0.0

    @property
    def progress(self) -> float:
        return min(1.0, self.t / self.dur)

    @property
    def done(self) -> bool:
        return self.t >= self.dur

    @property
    def edge(self) -> int:
        """Y of the reveal edge in logical pixels (field top -> field bottom)."""
        return int(C.HUD_H + TILE_H * self.progress)

    def update(self, dt: float, scale: float = 1.0) -> None:
        self.t = min(self.dur, self.t + max(0.0, dt) * max(0.0, scale))
        # Both sectors scroll: a frozen outgoing map would read as a snapshot.
        self.new.update(dt, scale)
        if self.old is not None:
            self.old.update(dt, scale)

    def draw(self, canvas: Any) -> None:
        import pygame

        top = C.HUD_H
        bottom = C.HUD_H + TILE_H
        edge = self.edge
        if self.old is None:
            self.new.draw(canvas)
            return
        edge = max(top, min(bottom, edge))
        self.new.draw(canvas, clip=pygame.Rect(0, top, C.LOGICAL_W, edge - top))
        self.old.draw(canvas, clip=pygame.Rect(0, edge, C.LOGICAL_W,
                                               bottom - edge))
        if self.progress < 1.0:
            self._reveal_line(canvas, edge, pygame)

    def _reveal_line(self, canvas: Any, edge: int, pygame: Any) -> None:
        """The boundary itself: a bright line with a dim trailing echo."""
        fade = 1.0 - self.progress
        bright = int(120 + 135 * fade)
        pygame.draw.line(canvas, (bright, min(255, bright + 40), 255),
                         (0, edge), (C.LOGICAL_W, edge), 2)
        if edge + 3 < C.HUD_H + TILE_H:
            pygame.draw.line(canvas, (40, 60, 90), (0, edge + 3),
                             (C.LOGICAL_W, edge + 3), 1)
