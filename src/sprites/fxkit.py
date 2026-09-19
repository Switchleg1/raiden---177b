"""Float-accurate FX primitives for bullets, the whip and explosions.

Why this exists: ``pygame.draw`` *writes* alpha instead of compositing it, so
two overlapping translucent circles come out the same opacity as one and a
hand-built bloom is impossible.  It matters most on the smallest sprites in
the game - a 12x16 vulcan bolt is the thing the player looks at most, and hard
1px rectangles read as a coloured stick over bright terrain.

``Tile`` accumulates colour layers in float, premultiplied, with true
"source-over" math at 4x supersample, then resolves once with a box filter.
The result is sub-pixel soft edges and real additive-looking bloom at any cell
size, without a single per-pixel Python loop.

Everything is analytic and seeded, so a sheet baked today equals a sheet
baked tomorrow (test_procedural_deterministic depends on that).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

RGB = tuple[int, int, int]

_EPS = 1e-6


def _smooth(ramp: np.ndarray) -> np.ndarray:
    """Smoothstep a 0..1 ramp so edges have no hard stair-step."""
    r = np.clip(ramp, 0.0, 1.0)
    return r * r * (3.0 - 2.0 * r)


@dataclass
class Tile:
    """One sprite tile accumulated in float RGBA at ``ss``x supersample."""

    w: int
    h: int
    ss: int = 4
    _rgb: Any = field(init=False, repr=False)
    _a: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rgb = np.zeros((self.h * self.ss, self.w * self.ss, 3),
                             np.float32)
        self._a = np.zeros((self.h * self.ss, self.w * self.ss), np.float32)

    # ---------------------------------------------------------------- --
    def _xy(self) -> tuple[np.ndarray, np.ndarray]:
        ss = self.ss
        gy, gx = np.mgrid[0:self.h * ss, 0:self.w * ss]
        return (gx + 0.5) / ss, (gy + 0.5) / ss

    def over(self, colour: RGB, alpha: np.ndarray) -> None:
        """Composite a flat colour through an alpha field (source-over)."""
        self._composite(colour, alpha)

    def _composite(self, colour: RGB, a: np.ndarray) -> None:
        a = np.clip(a, 0.0, 1.0, out=np.asarray(a, np.float32))
        inv = (1.0 - a).astype(np.float32)
        self._rgb *= inv[..., None]
        self._rgb += np.asarray(colour, np.float32) * a[..., None]
        self._a = self._a * inv + a

    def window(self, radius: float, edge: float = 2.0) -> None:
        """Fade everything to nothing at an inscribed circle.

        Radial content (explosions) wants this: it removes the squared tile
        edges you otherwise get when a bloom or shockwave reaches the cell
        boundary, and it is invisible on anything that already fits.
        """
        x, y = self._xy()
        d = np.hypot(x - self.w / 2.0, y - self.h / 2.0)
        m = _smooth((radius - d) / max(edge, _EPS))
        self._rgb *= m[..., None]
        self._a *= m

    # ---- primitives -------------------------------------------------- #
    def disc(self, cx: float, cy: float, r: float, colour: RGB,
             edge: float = 0.55, wobble: tuple[int, float, float] | None = None,
             alpha: float = 1.0) -> None:
        """Filled circle; ``wobble=(lobes, phase, amp)`` ripplies the rim."""
        x, y = self._xy()
        dx, dy = x - cx, y - cy
        d = np.hypot(dx, dy)
        if wobble is not None:
            k, phase, amp = wobble
            d = d / (1.0 + amp * np.sin(k * np.arctan2(dy, dx) + phase))
        self._composite(colour,
                        _smooth((r - d) / max(edge, _EPS)) * alpha)

    def capsule(self, cx: float, cy: float, half_h: float, r: float,
                colour: RGB, edge: float = 0.5, alpha: float = 1.0) -> None:
        """Vertical stadium: the workhorse for bolt and tracer bodies."""
        x, y = self._xy()
        dy = np.maximum(np.abs(y - cy) - half_h, 0.0)
        d = np.hypot(x - cx, dy)
        self._composite(colour, _smooth((r - d) / max(edge, _EPS)) * alpha)

    def box(self, cx: float, cy: float, w: float, h: float, colour: RGB,
            edge: float = 0.45, alpha: float = 1.0) -> None:
        """Axis-aligned rectangle with anti-aliased edges."""
        x, y = self._xy()
        ax = _smooth((w / 2.0 - abs(x - cx)) / edge)
        ay = _smooth((h / 2.0 - abs(y - cy)) / edge)
        self._composite(colour, ax * ay * alpha)

    def rrect(self, cx: float, cy: float, w: float, h: float, radius: float,
              colour: RGB, edge: float = 0.5, alpha: float = 1.0) -> None:
        """Rounded rectangle from a signed-distance field.

        Boxes in this game are hardware (pods, panels, casings), and hardware
        needs corners: an SDF gives clean anti-aliasing on the radius for free,
        which ``box()`` cannot do because it squares off the corner.
        """
        x, y = self._xy()
        r = min(radius, w / 2.0, h / 2.0)
        qx = np.maximum(np.abs(x - cx) - (w / 2.0 - r), 0.0)
        qy = np.maximum(np.abs(y - cy) - (h / 2.0 - r), 0.0)
        inner = np.minimum(np.maximum(np.abs(x - cx) - (w / 2.0 - r),
                                      np.abs(y - cy) - (h / 2.0 - r)), 0.0)
        sd = np.hypot(qx, qy) + inner - r
        self._composite(colour, _smooth(-sd / max(edge, _EPS)) * alpha)

    def cone(self, cx: float, tip_y: float, base_y: float, half_w: float,
             colour: RGB, edge: float = 0.5, bulb: float = 0.0,
             alpha: float = 1.0) -> None:
        """Triangle from a point to a base line, ``bulb`` rounding the base."""
        x, y = self._xy()
        span = base_y - tip_y
        if abs(span) < _EPS:
            return
        t = np.clip((y - tip_y) / span, 0.0, 1.0)
        half = half_w * (bulb + (1.0 - bulb) * t)
        inside = _smooth((half - np.abs(x - cx)) / edge)
        cap = _smooth(t * 8.0) if bulb > 0 else t
        self._composite(colour, inside * cap * alpha)

    def tri(self, p0: tuple[float, float], p1: tuple[float, float],
            p2: tuple[float, float], colour: RGB, edge: float = 0.5,
            alpha: float = 1.0) -> None:
        """Triangle with anti-aliased edges (missile fins, whip barbs)."""
        x, y = self._xy()
        pts = (p0, p1, p2)
        cov = np.ones_like(x)
        for i in range(3):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % 3]
            gx, gy = pts[(i + 2) % 3]
            ex, ey = bx - ax, by - ay
            n = math.hypot(ex, ey) or 1.0
            side = ((gx - ax) * ey - (gy - ay) * ex)
            side = 1.0 if side >= 0 else -1.0
            inside = ((x - ax) * ey - (y - ay) * ex) * side / n
            cov = cov * _smooth(inside / edge)
        self._composite(colour, cov * alpha)

    def annulus(self, cx: float, cy: float, r: float, width: float,
                colour: RGB, edge: float = 0.7, alpha: float = 1.0) -> None:
        """Ring of the given thickness - shockwaves and plasma shells."""
        x, y = self._xy()
        d = np.hypot(x - cx, y - cy)
        self._composite(colour,
                        _smooth((width / 2.0 - abs(d - r)) / edge) * alpha)

    def arc(self, cx: float, cy: float, r: float, width: float,
            a_center: float, half_angle: float, colour: RGB, edge: float = 0.7,
            taper: float = 1.0, alpha: float = 1.0) -> None:
        """Annulus *segment*: a band of the given radius over an angular window.

        ``taper`` shapes the window along its own length: 0 is a flat bracket,
        >0 fades the trailing end (negative angles) so the band reads as an
        orbiting blade moving counter-clockwise instead of a drawn parenthesis.
        Used by the power-up aura; a plain ``annulus`` cannot say "only here".
        """
        x, y = self._xy()
        dx, dy = x - cx, y - cy
        d = np.hypot(dx, dy)
        band = _smooth((width / 2.0 - abs(d - r)) / max(edge, _EPS))
        rel = (np.arctan2(dy, dx) - a_center + math.pi) % math.tau - math.pi
        ha = max(half_angle, _EPS)
        span = _smooth((ha - abs(rel)) / max(ha * 0.45, edge))
        ramp = _smooth(0.5 + 0.5 * rel / ha) ** taper if taper > 0 else 1.0
        self._composite(colour, band * span * ramp * alpha)

    def hole(self, cx: float, cy: float, r: float, edge: float = 2.0) -> None:
        """Punch a soft transparent hole in the middle of everything so far.

        The mirror of :meth:`window`. A marker that rings another sprite (the
        item aura surrounds an icon) must not just be *thin* at the centre — it
        has to leave those pixels alone, or the thing it frames gets milky.
        """
        x, y = self._xy()
        d = np.hypot(x - cx, y - cy)
        m = _smooth((d - r) / max(edge, _EPS))
        self._rgb *= m[..., None]
        self._a *= m

    def bloom(self, cx: float, cy: float, r: float, colour: RGB,
              power: float = 2.2, peak: float = 1.0) -> None:
        """Soft radial wash with a polynomial falloff - the glow halo."""
        x, y = self._xy()
        d = np.hypot(x - cx, y - cy)
        t = np.clip(1.0 - d / max(r, _EPS), 0.0, 1.0)
        self.over(colour, (t ** power) * peak)

    # ---- output ------------------------------------------------------ #
    def surface(self) -> Any:
        """Resolve to a straight-alpha pygame Surface at the cell size."""
        import pygame
        ss, rgb, a = self.ss, self._rgb, self._a
        assert rgb.shape[0] == self.h * ss and rgb.shape[1] == self.w * ss
        small_a = a.reshape(self.h, ss, self.w, ss).mean(axis=(1, 3))
        small_rgb = rgb.reshape(self.h, ss, self.w, ss, 3).mean(axis=(1, 3))
        alpha = np.clip(small_a * 255.0 + 0.5, 0, 255).astype(np.uint8)
        straight = np.where(small_a[..., None] > _EPS,
                            small_rgb / np.maximum(small_a[..., None], _EPS),
                            0.0)
        # _rgb accumulates in 0..255 units, so only alpha needs scaling here.
        cols = np.clip(straight + 0.5, 0, 255).astype(np.uint8)
        rgba = np.dstack([cols, alpha[..., None]])
        surf = pygame.image.fromstring(rgba.tobytes(), (self.w, self.h),
                                       "RGBA")
        surf.set_colorkey(None)
        return surf

    def blit(self, sheet: Any, ox: int, oy: int) -> None:
        sheet.blit(self.surface(), (ox, oy))


def mix(a: RGB, b: RGB, t: float) -> RGB:
    """Linear blend between two colours (``t`` 0 -> a, 1 -> b)."""
    ta = 1.0 - float(t)
    return (int(round(a[0] * ta + b[0] * t)),
            int(round(a[1] * ta + b[1] * t)),
            int(round(a[2] * ta + b[2] * t)))
