"""Per-sector terrain schedule: zones + scroll-pinned zone handover."""
from __future__ import annotations

import math
from typing import Any

import config as C

from .common import NEAR_SPEED, TILE_H
from .terrain_map import Terrain

# ---------------------------------------------------------------------------
# phase scheduling: a sector hands over to its next zone as the player scrolls
# (Raiden's mid-level environment changes).
# ---------------------------------------------------------------------------

PHASE_PLAN = 46.0          # default span, used when a sector has no wave length


# A zone boundary is a PLACE in the level, not an effect laid over it. The old
# handover alpha-dissolved the whole field from one zone's map into the other's
# for 1.8 virtual seconds, which is what read as "a fade shift in the middle of
# the level": the ground itself went translucent. Instead the incoming zone's
# ground is revealed by an edge sweeping down the field at exactly the ground
# layer's own scroll rate, so the boundary travels over the field like any other
# piece of ground and the tiles simply change along a line.
PHASE_SWEEP = TILE_H / NEAR_SPEED     # one field-height of ground travel


# A straight cut is its own tell: "the perfectly straight edge slices through
# scenery, with no shoreline, cliff face or bank explaining the change". The
# boundary is therefore wavy, and the wave is a function of WORLD position, so
# the shape belongs to the ground and scrolls with it instead of sliding down a
# static line.
SEAM_STEP = 24              # px of width per boundary segment
SEAM_WAVE = 20.0            # px amplitude of the big sweep
SEAM_FOLDS = 190.0          # px wavelength of the big sweep
SEAM_RIPPLE = 7.0           # px amplitude of the small folds

# Edge dressing. A bare boundary is a line where one picture stops and another
# starts; the review said it "slices through buildings and trees rather than
# forming a believable shore". A scarp has a lit crest and casts a shadow at its
# foot, so the boundary gets exactly those - in colours sampled from the ground
# it is standing on, so it cannot read as paint. Props along the line were tried
# in the terrain pass and read as boulder fences, so there are none here.
SEAM_LIP = 2                # px of lit crest
SEAM_SHADOW = 16            # px of cast shadow at the foot
SEAM_SHADOW_GAIN = 0.42     # how dark the foot gets, at the line


def seam_y(x: float, edge: float) -> float:
    """y of the zone boundary at column `x`, given the scroll-pinned `edge`.

    Two wavelengths: a broad swing so the boundary reads as a landform edge, and
    a tighter fold so no straight run survives a glance. Both are keyed to the
    world, not the frame."""
    tau = math.tau
    return (edge
            + SEAM_WAVE * math.sin(x * tau / SEAM_FOLDS
                                  + 0.8 * math.sin(edge * tau / 700.0))
            + SEAM_RIPPLE * math.sin(x * tau / 63.0 + edge * tau / 430.0))


def plan_span(level: Any) -> float:
    """How long a sector's zone plan should take.

    A sector defines its own wave length, and the terrain plan is meant to fill
    that wave: on a 75 s sector the zone change should not arrive after 46 s of
    scroll and leave the rest of the sector on one map. Sectors without a wave
    length (an arena, a menu backdrop) fall back to the default plan.
    """
    span = float(getattr(level, "wave_seconds", 0.0) or 0.0)
    return span if span > 0.0 else PHASE_PLAN


def sector_phases(level: Any) -> tuple:
    """The level's phase schedule, including the implicit single-zone fallback.

    A level may simply *be* a theme instead of scheduling zones. Everyone who
    needs to know which ground a sector draws - the renderer, the prefetch
    worker, the "is this the same ground?" test - asks here, so a prefetch can
    never build maps that will not be the ones drawn.
    """
    phases = tuple(getattr(level, "phases", ()) or ())
    if not phases:
        phases = (C.ThemePhase(getattr(level, "theme", level), 1.0),)
    return phases


def sector_key(phases: tuple, seed: int) -> tuple:
    """Identity of a sector's ground: its zones and their map seed.

    Two sectors with the same zones and seed *are* the same ground, which is the
    point: it is what lets a retry keep the terrain it was already flying over
    instead of snapping back to the opening zone, and what makes a repeated
    sector already paid for.
    """
    return tuple(
        (str(p.theme), round(float(p.weight), 4)) for p in phases
    ) + (int(seed),)


class TerrainTrack:
    """One sector's worth of terrain: baked zone segments in phase order.

    Segments are Terrain objects sharing one seed; the active one is drawn
    plain, and each zone boundary hands over spatially over PHASE_SWEEP virtual
    seconds: the incoming zone holds the field above a seam that travels down
    with the scroll, the outgoing zone everything below it, both still
    scrolling. No pixel is ever blended - a blended ground is a fade."""

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

    def _seam(self, canvas: Any, incoming: Any, outgoing: Any,
              band: Any, edge: float) -> bool:
        """Incoming zone above a continuous boundary, outgoing zone below.

        Only the band the boundary can actually reach is masked; the rest of the
        field is two plain draws. That keeps a full-screen per-pixel operation
        out of the frame: the mask is a strip about 60 px tall.

        Drawing the outgoing zone first and painting the incoming zone over it
        through the mask means the two never gap and no pixel is ever averaged
        between them - which is the whole point: a blended ground is a fade.
        """
        import pygame
        try:
            import numpy as np
        except ImportError:
            return False
        top, bottom = band.top, band.bottom
        span = SEAM_WAVE + SEAM_RIPPLE + 2.0
        win_top = max(top, int(edge - span))
        win_bot = min(bottom, int(edge + span))
        if win_bot <= win_top:
            incoming.draw(canvas, clip=band)
            return True
        above = pygame.Rect(band.left, top, band.width, win_top - top)
        if above.height > 0:
            incoming.draw(canvas, clip=above)
        below = pygame.Rect(band.left, win_bot, band.width, bottom - win_bot)
        if below.height > 0:
            outgoing.draw(canvas, clip=below)
        window = pygame.Rect(band.left, win_top, band.width,
                             win_bot - win_top)
        outgoing.draw(canvas, clip=window)

        if (self._scratch is None
                or self._scratch.get_size() != canvas.get_size()):
            self._scratch = pygame.Surface(canvas.get_size(), pygame.SRCALPHA)
        incoming.draw(self._scratch, clip=window)
        # pygame's surfarray is (x, y); the boundary curve is the same function
        # as seam_y(), evaluated across the band in one shot
        xs = np.arange(band.left, band.left + band.width, dtype=np.float64)
        lim = (edge + SEAM_WAVE
               * np.sin(xs * math.tau / SEAM_FOLDS
                        + 0.8 * math.sin(edge * math.tau / 700.0))
               + SEAM_RIPPLE * np.sin(xs * math.tau / 63.0
                                      + edge * math.tau / 430.0))
        yy = np.arange(window.top, window.bottom, dtype=np.float64)[None, :]
        keep = (yy < lim[:, None]).astype(np.uint8) * np.uint8(255)
        alpha = pygame.surfarray.pixels_alpha(self._scratch)
        alpha[:, window.top:window.bottom] = keep
        del alpha
        # pygame places the AREA's top-left at dest, so both must name the same
        # rows or the strip lands somewhere else entirely
        rows = pygame.Rect(0, window.top, canvas.get_width(), window.height)
        canvas.blit(self._scratch, (0, window.top), rows)
        self._dress(canvas, band, lim)
        return True

    def _dress(self, canvas: Any, band: Any, lim: Any) -> None:
        """Light the crest and shade the foot of the boundary in place.

        `lim` is the boundary y per column. The colours come from the pixels
        already on the canvas, which is why this works for any pair of zones."""
        import numpy as np
        import pygame
        top, bottom = band.top, band.bottom - 1
        xs = np.arange(band.left, band.left + band.width)
        line = np.clip(np.floor(lim).astype(np.int64), top + SEAM_LIP + 1,
                       bottom - SEAM_SHADOW - 1)
        px = pygame.surfarray.pixels3d(canvas)
        try:
            # the foot: a shadow that starts hard at the line and dies out, the
            # way ground falling away under a scarp actually reads
            depth = np.arange(1, SEAM_SHADOW + 1, dtype=np.float64)
            ys = np.clip(line[:, None] + depth[None, :],
                          top, bottom).astype(np.int64)
            band_px = px[xs[:, None], ys]
            shape = (1.0 - depth / SEAM_SHADOW) ** 1.5
            dark = band_px * (1.0 - SEAM_SHADOW_GAIN * shape)[None, :, None]
            px[xs[:, None], ys] = np.clip(dark, 0, 255).astype(np.uint8)
            # the crest: two px a touch brighter, so the edge has a top face
            riser = np.arange(SEAM_LIP, dtype=np.int64)
            yl = np.clip(line[:, None] - riser[None, :], top, bottom)
            lip = px[xs[:, None], yl]
            px[xs[:, None], yl] = np.clip(lip * 1.16, 0, 255).astype(np.uint8)
        finally:
            del px

    def draw(self, canvas: Any, clip: Any = None) -> None:
        import pygame
        top = C.HUD_H
        band = pygame.Rect(0, top, C.LOGICAL_W, TILE_H)
        if clip is not None:
            band = band.clip(clip)
            if band.width <= 0 or band.height <= 0:
                return
        i = self._idx(self.t)
        if i > 0:
            begin = self.segs[i][1]
            a = (self.t - begin) / PHASE_SWEEP
            if a < 1.0:
                edge = top + int(TILE_H * a)
                if self._seam(canvas, self.segs[i][0], self.segs[i - 1][0],
                              band, edge):
                    return
                # no numpy: the same split with a stepped boundary - a seam is
                # a seam, and it still never fades
                outgoing = self.segs[i - 1][0]
                incoming = self.segs[i][0]
                outgoing.draw(canvas, clip=band)
                x = band.left
                while x < band.right:
                    w = min(SEAM_STEP, band.right - x)
                    y1 = max(band.top, min(band.bottom,
                                           int(seam_y(x + w * 0.5, edge))))
                    if y1 > band.top:
                        incoming.draw(canvas, clip=pygame.Rect(x, band.top,
                                                               w,
                                                               y1 - band.top))
                    x += w
                return
        self.segs[i][0].draw(canvas, clip=band)
