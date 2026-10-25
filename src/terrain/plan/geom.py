"""The ground being designed: its size, its planning grid."""
from __future__ import annotations

from dataclasses import dataclass

from ..tilekit import CH, CW

# Planning grid: 40 px cells, 40 x 28 over the bake space. Coarse enough that a
# relief query is a lookup and the whole plan costs milliseconds, fine enough
# that "is this spot flat, dry and unbuilt" is a real answer.
CELL = 20


COLS = CW // CELL


ROWS = CH // CELL


# One screen is the unit everything is calibrated in: how far a ridge reaches,
# how wide a meander swings, how many fields a theme wants. A plan may cover
# many screens; these stay fixed and the counts scale with them.
SCREEN_W = CW


SCREEN_H = CH


@dataclass(frozen=True)
class Geom:
    """The ground a site plan is designed for: a bake-space strip w x h.

    The default is one screen, and it is a loop in y: the sine paths close on
    themselves so the map wraps with no cut. A streamed sector plans a much
    longer strip, which is NOT a loop - nothing has to line up with the top of
    it, and that is what lets one river, one road and one range run the length
    of a sector instead of one screen repeating twenty-one times.
    """

    w: int = SCREEN_W
    h: int = SCREEN_H
    cell: int = CELL
    cyclic: bool = True

    @property
    def cols(self) -> int:
        return self.w // self.cell

    @property
    def rows(self) -> int:
        return self.h // self.cell

    @property
    def screens(self) -> int:
        """How many screens tall this is. Densities and path sinuosity scale
        with it, so a long strip is designed rather than one map stretched."""
        return max(1, int(round(self.h / SCREEN_H)))

    def col(self, x: float) -> int:
        return max(0, min(self.cols - 1, int(x // self.cell)))

    def row(self, y: float) -> int:
        yy = y % self.h if self.cyclic else y
        return max(0, min(self.rows - 1, int(yy // self.cell)))

    def shifts(self) -> tuple[float, ...]:
        """y offsets a shape must be tested at: the wrap copies for a looping
        map, nothing extra for a strip that does not loop."""
        if not self.cyclic:
            return (0.0,)
        return (0.0, -float(self.h), float(self.h))


#: the one-screen ground every calibration constant in this module assumes
SCREEN = Geom()


Point = tuple[float, float]
