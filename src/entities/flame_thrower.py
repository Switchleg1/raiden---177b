"""The flamethrower weapon: emits puffs of fire and remembers the ones away."""
from __future__ import annotations

import math

import config as C

from .flame import Flame


class FlameThrower:
    """The timed weapon: it emits puffs and remembers the ones already away.

    Pure model - :meth:`update` takes the nozzle position, ages the field and
    culls what has burned out. Targeting policy and collision are the Game's
    business, and nothing here draws from an RNG, so a seeded replay reproduces
    the same plume frame for frame.
    """

    __slots__ = ("puffs", "t", "_emit", "_burst")

    def __init__(self) -> None:
        self.puffs: list[Flame] = []
        self.t = 0.0
        self._emit = 0.0
        self._burst = 0

    def clear(self) -> None:
        self.puffs = []

    def update(self, dt: float, x: float, y: float, lit: bool = True) -> None:
        """Advance the plume. ``lit`` is the weapon's timer: off, the nozzle
        stops throwing but every puff already away finishes its own flight -
        the model does not unmake fire that is already in the air.
        """
        self.t += dt
        self._emit += dt
        if not lit:
            self._emit = 0.0
        while lit and self._emit >= C.FLAME_INTERVAL:
            self._emit -= C.FLAME_INTERVAL
            self._emit_burst(x, y)
        for p in self.puffs:
            p.update(dt)
        if self.puffs:
            self.puffs = [p for p in self.puffs if p.alive]

    def _emit_burst(self, x: float, y: float) -> None:
        """A fan of puffs from the nozzle, fanned and swayed, never random.

        The fan slides side to side on the thrower's own clock and each puff is
        born with its own sideways drift, so the plume billows and covers the
        width of the craft instead of laying down three tidy columns.
        """
        n = max(1, int(C.FLAME_FAN))
        i = self._burst
        self._burst += 1
        sway = math.sin(math.tau * C.FLAME_SWAY_HZ * self.t) * C.FLAME_SWAY
        for k in range(n):
            off = (k - (n - 1) / 2.0) * C.FLAME_FAN_W + sway
            drift = math.sin(i * 0.7 + k * 1.9) * C.FLAME_BILLOW
            self.puffs.append(Flame(x + off, y - C.FLAME_NOZZLE,
                                    drift, -C.FLAME_SPEED))
        # A plume is a bounded object: life/interval is already the natural
        # ceiling, and this is the hard one the list can never walk past.
        over = len(self.puffs) - C.FLAME_MAX_PUFFS
        if over > 0:
            del self.puffs[:over]

    @property
    def reach(self) -> float:
        """How far ahead of the nozzle the fire gets, in logical units."""
        return C.FLAME_SPEED * C.FLAME_LIFE
