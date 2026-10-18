"""Energy whip: a rope that lives in the world, dragged by the craft.

The lash is *not* a curve resampled from the ship every frame. Only its handle
bead is pinned to the craft; every bead past that keeps its own world position
and is moved by its own momentum, a forward drive along the rope, a bend
relaxation, and a no-stretch constraint against the bead before it.
"""
from __future__ import annotations

import math

import config as C

# Golden angle in radians: spreads the per-bead wander phase so no two beads
# wander in step, without needing an RNG (the lash must stay reproducible).
_PHI = 2.399963229728653


class Whip:
    """A beaded energy lash modelled as an inextensible chain of free beads.

    Four things move it, and only the first is tied to the player:

    * **Handle.** Bead 0 is pinned to the attach point one ``seg`` away, at the
      steered ``aim`` angle. The aim is slew-rate limited (``WHIP_AIM_RATE``),
      so the wrist can never snap the whole lash around in one frame.
    * **Momentum.** Every other bead keeps its velocity (damped by
      ``WHIP_DRAG``). Move the craft and the beads *stay where they were*; the
      constraint then pulls each one only as far as the bead ahead of it
      requires. That is why strafing bends the lash and retracts the tip
      instead of dragging a rigid picture along with the ship.
    * **Forward drive.** ``WHIP_DRIVE`` feeds every bead forward along the
      smoothed rope direction, so the lash keeps travelling up-field in time and
      re-extends after a bend rather than dangling where it was left. Part of it
      (``WHIP_AIM_PULL``) points where the *handle* points instead of along the
      local rope: that is the lash's own forward momentum, it keeps the rope
      thrown up-field instead of streaming out sideways behind the craft, and a
      direction every bead shares cannot buckle the chain the way a local push
      does.
    * **Bend relaxation + wander.** ``WHIP_STRAIGHT`` pulls beads toward the
      straight line through their neighbours (weaker toward the tip), which is
      what propagates the handle's turn down the lash and keeps a still craft's
      lash fairly straight. ``WHIP_JITTER`` adds deterministic per-bead wander,
      tapered toward the tip, so "straight" never means "frozen".

    Pure model: :meth:`update` advances the rope; targeting policy and
    collision are the Game's business.
    """

    __slots__ = ("t", "points", "aim", "anchor", "_prev")

    def __init__(self) -> None:
        self.t = 0.0
        self.points: list[tuple[float, float]] = []
        self.aim = 0.0            # radians from straight up, +right, -left
        self.anchor = (0.0, 0.0)  # handle attach point (world space)
        self._prev: list[tuple[float, float]] = []

    # ------------------------------------------------------------------ aim
    def _wanted(self, ax: float, ay: float,
                target: tuple[float, float] | None) -> float:
        """Angle the handle would like to point at, in radians from vertical."""
        max_a = math.radians(C.WHIP_MAX_ANGLE)
        if target is None:
            # Nothing to chase: sweep, so the lash never freezes into a statue.
            # The sweep is far smaller than the aim cap on purpose. The handle
            # is the only bead pinned to the craft, and swinging it through a
            # right angle in half a second folds 300 units of rope back onto
            # the hull instead of cracking the tip across the field.
            return (math.sin(math.tau * C.WHIP_SWEEP_HZ * self.t)
                    * math.radians(C.WHIP_SWEEP_ANGLE))
        dx = target[0] - ax
        dy = target[1] - ay
        if dy >= 0.0:
            # Below or level with the craft. The lash is anchored above the
            # cockpit and thrown upward; pointing the handle back through the
            # hull would only fold the rope through the ship's own picture.
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

    # ------------------------------------------------------------- integrate
    def update(self, dt: float, anchor_x: float, anchor_y: float,
               target: tuple[float, float] | None = None) -> None:
        self.t += dt
        self.anchor = (anchor_x, anchor_y - C.WHIP_ATTACH)
        self.aim = self._steer(dt, self.anchor[0], self.anchor[1], target)
        if len(self.points) != C.WHIP_POINTS:
            self._seed()
            return
        self._flow(dt)
        self._pin_handle()
        self._hold()

    def _seed(self) -> None:
        """Start the lash out straight ahead of the handle."""
        seg = C.WHIP_LEN / C.WHIP_POINTS
        ax, ay = self.anchor
        sx, sy = self._dir()
        self.points = [(ax + sx * seg * i, ay + sy * seg * i)
                       for i in range(1, C.WHIP_POINTS + 1)]
        self._prev = list(self.points)

    def _dir(self, angle: float | None = None) -> tuple[float, float]:
        """Unit vector the handle points along (world space, y grows down)."""
        a = self.aim if angle is None else angle
        return math.sin(a), -math.cos(a)

    def _flow(self, dt: float) -> None:
        """Advance every free bead: momentum + drive + wander + straightening."""
        pts, prev, n = self.points, self._prev, C.WHIP_POINTS
        seg = C.WHIP_LEN / n
        keep = max(0.0, 1.0 - C.WHIP_DRAG * dt)
        straight = min(1.0, C.WHIP_STRAIGHT * dt)

        # Segment directions, handle -> tip; bead i is preceded by bead i-1
        # (or the handle, for i == 0).
        dirs: list[tuple[float, float]] = []
        last = self.anchor
        for i in range(n):
            dx, dy = pts[i][0] - last[0], pts[i][1] - last[1]
            d = math.hypot(dx, dy) or 1.0
            dirs.append((dx / d, dy / d))
            last = pts[i]

        # The shared aim direction: part of every bead's drive points where the
        # handle points instead of along the local rope. That is the lash's own
        # forward momentum - it keeps the rope thrown up-field instead of
        # streaming out sideways behind the craft, and because every bead shares
        # the direction it cannot buckle the chain the way a local push does.
        hx, hy = self._dir()
        pull = C.WHIP_AIM_PULL

        # Bead 0 is the handle: it is re-pinned to the aim right after this,
        # so it just rides along with itself here.
        moved: list[tuple[float, float]] = [pts[0]]
        for i in range(1, n):
            f = (i + 1) / n
            # Forward along the *smoothed* rope: a wide window of segment
            # directions, because driving along one link is a fire hose - every
            # bump gets pushed outward and the lash curls into a loop.
            ux = uy = 0.0
            for j in range(max(0, i - C.WHIP_SMOOTH), i + 1):
                ux += dirs[j][0]
                uy += dirs[j][1]
            d = math.hypot(ux, uy) or 1.0
            ux, uy = ux / d, uy / d
            ux, uy = ux * (1.0 - pull) + hx * pull, uy * (1.0 - pull) + hy * pull

            vx = (pts[i][0] - prev[i][0]) * keep
            vy = (pts[i][1] - prev[i][1]) * keep

            # Bend relaxation: toward the straight line joining the neighbours.
            # The tip has no next bead, so its "straight" target is simply the
            # link ahead of it carried forward.
            if i + 1 < n:
                mx = 0.5 * (pts[i - 1][0] + pts[i + 1][0])
                my = 0.5 * (pts[i - 1][1] + pts[i + 1][1])
            else:
                mx, my = pts[i - 1][0] + ux * seg, pts[i - 1][1] + uy * seg
            w = straight * (1.0 - C.WHIP_STRAIGHT_TIP * f)

            # Wander: three incommensurate sines per bead, so the lash breathes
            # without a clock that repeats and without an RNG.
            wob = self._wander(i) * C.WHIP_JITTER * f ** C.WHIP_JITTER_TAPER * dt

            moved.append((pts[i][0] + vx + ux * C.WHIP_DRIVE * dt
                          + (mx - pts[i][0]) * w - uy * wob,
                          pts[i][1] + vy + uy * C.WHIP_DRIVE * dt
                          + (my - pts[i][1]) * w + ux * wob))
        self._prev = list(pts)
        self.points = moved

    def _wander(self, i: int) -> float:
        """Deterministic wander in roughly [-1, 1] for one bead."""
        ph = i * _PHI
        t = self.t
        h = C.WHIP_JITTER_HZ
        return (math.sin(math.tau * h * t + ph) * 0.62
                + math.sin(math.tau * h * 0.43 * t + ph * 1.7) * 0.27
                + math.sin(math.tau * h * 2.11 * t + ph * 0.6) * 0.11)

    # ------------------------------------------------------------- constraint
    def _pin_handle(self) -> None:
        """Bead 0 hangs off the attach point at the steered angle."""
        seg = C.WHIP_LEN / C.WHIP_POINTS
        sx, sy = self._dir()
        self.points[0] = (self.anchor[0] + sx * seg, self.anchor[1] + sy * seg)

    def _hold(self) -> None:
        """Inextensible: walk handle -> tip, pull each bead back to its link.

        Only the follower moves, and only the stretch is removed. A bead is
        never dragged past the bead ahead of it, which is what lets the body of
        the lash stay put while the craft moves: the tip pays for the ship's
        motion by coming back in, not by following it.
        """
        seg = C.WHIP_LEN / C.WHIP_POINTS
        last = self.anchor
        fixed: list[tuple[float, float]] = []
        for x, y in self.points:
            dx, dy = x - last[0], y - last[1]
            d = math.hypot(dx, dy)
            if d > seg:
                k = (d - seg) / d
                x, y = x - dx * k, y - dy * k
            fixed.append((x, y))
            last = (x, y)
        self.points = fixed

    @property
    def seg(self) -> float:
        """Link length; the lash is inextensible, so this is fixed."""
        return C.WHIP_LEN / C.WHIP_POINTS

    @property
    def arc(self) -> float:
        """Measured length of the rope, for tests and debugging."""
        last = self.anchor
        total = 0.0
        for x, y in self.points:
            total += math.hypot(x - last[0], y - last[1])
            last = (x, y)
        return total

    @property
    def reach(self) -> float:
        """Distance from the handle to the tip: bends, so this is <= arc."""
        tx, ty = self.tip
        return math.hypot(tx - self.anchor[0], ty - self.anchor[1])

    @property
    def tip(self) -> tuple[float, float]:
        return self.points[-1] if self.points else (0.0, 0.0)
