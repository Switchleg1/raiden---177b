"""Energy whip: a chain of bead points on a swept, snaking curve."""
from __future__ import annotations

import math

import config as C


class Whip:
    """Energy whip: a chain of bead points on a swept, snaking curve.

    The lash hangs from the craft and sweeps side-to-side around vertical;
    a phase-lagged sine travels down the links so the whole curve undulates
    like a real whip (sum-of-sines approximation of a spline — the beads
    sample the curve exactly like the reference art's energy strand).

    Pure model: :meth:`update` only advances a clock and re-samples
    :attr:`points`; collision is the Game's business.
    """

    __slots__ = ("t", "points")

    def __init__(self) -> None:
        self.t = 0.0
        self.points: list[tuple[float, float]] = []

    def update(self, dt: float, anchor_x: float, anchor_y: float) -> None:
        self.t += dt
        self.points = self._shape(anchor_x, anchor_y)

    def _shape(self, ax: float, ay: float) -> list[tuple[float, float]]:
        # Global sweep: how far the whole lash leans from vertical.
        sweep = math.sin(math.tau * C.WHIP_SWEEP_HZ * self.t)
        step = C.WHIP_LEN / C.WHIP_POINTS
        pts: list[tuple[float, float]] = []
        x, y = ax, ay - 12.0            # attach just above the cockpit
        for i in range(1, C.WHIP_POINTS + 1):
            f = i / C.WHIP_POINTS
            # lean grows toward the tip + travelling snake wave (lagged by
            # distance travelled, so the tip whips after the handle).
            ang = (sweep * math.radians(C.WHIP_MAX_ANGLE) * f
                   + math.sin(math.tau * (C.WHIP_WAVE_HZ * self.t - f * 0.9))
                   * C.WHIP_WAVE_AMP * f)
            x += math.sin(ang) * step
            y -= math.cos(ang) * step
            pts.append((x, y))
        return pts

    @property
    def tip(self) -> tuple[float, float]:
        return self.points[-1] if self.points else (0.0, 0.0)
