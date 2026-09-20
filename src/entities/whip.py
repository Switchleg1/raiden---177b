"""Energy whip: a chain of bead points on a curled, enemy-seeking curve."""
from __future__ import annotations

import math

import config as C


class Whip:
    """Energy whip: a chain of bead points on a curled, enemy-seeking curve.

    The lash hangs from above the cockpit and is thrown upward. Two things
    shape it: an **aim**, which is where the whole lash leans, and a travelling
    snake wave on top of that.

    The aim is steered, never snapped. When the Game hands over a hostile the
    lash slews onto it at ``WHIP_AIM_RATE`` radians a second, so the whip *turns
    toward* the target the way a real lash does and a player can still dodge
    it: instant aim would be a homing missile with a picture of a rope on it.
    With nothing in reach it falls back to the classic side-to-side sweep.

    The lean is applied as ``f ** WHIP_CURL_POWER`` along the length, so the
    handle stays where the craft points and the outer third hooks over. Linear
    lean gives a straight rod tilting; power above one gives a curl, which is
    what a whip is. The wave tapers the same way (``WHIP_WAVE_TAPER``) so the
    crackle lives at the tip instead of shaking the handle.

    Pure model: :meth:`update` advances a clock, steers and re-samples
    :attr:`points`; targeting policy and collision are the Game's business.
    """

    __slots__ = ("t", "points", "aim")

    def __init__(self) -> None:
        self.t = 0.0
        self.points: list[tuple[float, float]] = []
        self.aim = 0.0            # radians from straight up, +right, -left

    def update(self, dt: float, anchor_x: float, anchor_y: float,
               target: tuple[float, float] | None = None) -> None:
        self.t += dt
        self.aim = self._steer(dt, anchor_x, anchor_y, target)
        self.points = self._shape(anchor_x, anchor_y)

    # ------------------------------------------------------------------ aim
    def _wanted(self, ax: float, ay: float,
                target: tuple[float, float] | None) -> float:
        """Angle the lash would like to lean at, in radians from vertical."""
        max_a = math.radians(C.WHIP_MAX_ANGLE)
        if target is None:
            # Nothing to chase: sweep, so the lash never freezes into a statue.
            return math.sin(math.tau * C.WHIP_SWEEP_HZ * self.t) * max_a
        dx = target[0] - ax
        dy = target[1] - ay
        if dy >= 0.0:
            # Below or level with the craft. The lash is anchored above the
            # cockpit and thrown upward; aiming it back through the hull would
            # cut the ship's own picture and hit nothing.
            return self.aim
        return max(-max_a, min(max_a, math.atan2(dx, -dy)))

    def _steer(self, dt: float, ax: float, ay: float,
               target: tuple[float, float] | None) -> float:
        """Move the aim toward the wanted angle, capped at WHIP_AIM_RATE."""
        want = self._wanted(ax, ay, target)
        room = C.WHIP_AIM_RATE * dt
        delta = want - self.aim
        if delta > room:
            delta = room
        elif delta < -room:
            delta = -room
        return self.aim + delta

    # ---------------------------------------------------------------- shape
    def _shape(self, ax: float, ay: float) -> list[tuple[float, float]]:
        step = C.WHIP_LEN / C.WHIP_POINTS
        amp = C.WHIP_WAVE_AMP
        pts: list[tuple[float, float]] = []
        x, y = ax, ay - 12.0            # attach just above the cockpit
        for i in range(1, C.WHIP_POINTS + 1):
            f = i / C.WHIP_POINTS
            ang = (self.aim * f ** C.WHIP_CURL_POWER
                   + math.sin(math.tau * (C.WHIP_WAVE_HZ * self.t - f * 0.9))
                   * amp * f ** C.WHIP_WAVE_TAPER)
            x += math.sin(ang) * step
            y -= math.cos(ang) * step
            pts.append((x, y))
        return pts

    @property
    def tip(self) -> tuple[float, float]:
        return self.points[-1] if self.points else (0.0, 0.0)
