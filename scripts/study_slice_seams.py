"""Where do slice seams come from? Print the rows that disagree, per cause.

Two adjacent slices are painted from windows that overlap by 2 x STRIP_MARGIN, so
the same world rows are painted twice and must come out identical - the painter is
supposed to be a pure function of world coordinates. When they do not match, the
mismatch is a seam: the player sees a line where the ground disagrees with itself.

The docs have been carrying "0.05-2.9% of pixels disagree" for a while, which is a
number without a diagnosis. This says *which rows*, *by how much*, and *on which
pass*, because "some pixels differ" cannot be fixed and "the bottom 3 rows of every
slice differ by this much after the feather pass" can.

Run as a script: the design and paint workers re-run the entry file otherwise.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for path in (os.path.join(ROOT, "src"), ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import numpy  # noqa: E402
import pygame  # noqa: E402

pygame.display.init()
pygame.display.set_mode((64, 64))

import random  # noqa: E402

from level.strip import STRIP_MARGIN, STRIP_SLICE  # noqa: E402
from terrain.common import W2  # noqa: E402
from terrain.features import Plane, paint_site  # noqa: E402
from terrain.siteplan import CELL, Geom, plan_site  # noqa: E402
from terrain.tilekit import TileKit  # noqa: E402


def paint_window(plan, kit, y0: int, h: int) -> numpy.ndarray:
    """Paint one window of the world, exactly as a slice would, and return pixels."""
    plane = Plane(W2, h, x0=0, y0=y0)
    from random import Random

    from terrain.compose import NEAR_MATS, _grid
    _grid(plane.stamp, kit, list(NEAR_MATS[plan.theme]),
          Random(plan.seed * 7717 + (y0 // STRIP_SLICE)))
    plane.sync()
    rng = random.Random(plan.seed * 8191 + (y0 // STRIP_SLICE) * 131 + 3)
    paint_site(plane, kit, plan, rng)
    arr = pygame.surfarray.array3d(plane.surface())
    return numpy.asarray(arr).transpose(1, 0, 2)     # (rows, cols, rgb)


def main() -> int:
    kit = TileKit()
    height = STRIP_SLICE * 4
    plan = plan_site("countryside", 1, Geom(h=height, cell=CELL, cyclic=False))

    # The kept band of slice i and the same rows seen from its neighbour's window:
    # both windows contain these rows, so every pixel must agree bit for bit.
    worst = 0
    for i in (1, 2):
        y_keep = i * STRIP_SLICE
        rows = STRIP_SLICE
        a = paint_window(plan, kit, y_keep - STRIP_MARGIN,
                         rows + 2 * STRIP_MARGIN)
        b = paint_window(plan, kit, y_keep, rows)      # anchored differently
        # align: b row r == world row y_keep + r; a row r == y_keep - MARGIN + r
        shift = STRIP_MARGIN
        common = min(b.shape[0], a.shape[0] - shift)
        ca = a[shift:shift + common]
        cb = b[:common]
        diff = (ca.astype(int) - cb.astype(int))
        bad = (numpy.abs(diff).max(axis=2) > 0)
        per_row = bad.mean(axis=1)
        rows_bad = numpy.nonzero(per_row > 0.001)[0]
        pct = float(bad.mean()) * 100.0
        worst = max(worst, pct)
        print(f"slice {i}: {pct:5.2f}% of pixels disagree over {common} rows")
        if len(rows_bad):
            head = rows_bad[:4]
            tail = rows_bad[-4:]
            print(f"          first bad rows {list(head)} "
                  f"last bad rows {list(tail)} of {common}"
                  f"  (worst row {per_row.max() * 100:.1f}% at "
                  f"{int(per_row.argmax())})")
            print(f"          bad rows are "
                  f"{'at the window edges' if rows_bad.max() > common - 3 * STRIP_MARGIN and rows_bad.min() < STRIP_MARGIN else 'in the middle'}")
            print(f"          mean magnitude where different: "
                  f"{numpy.abs(diff[bad]).mean():.1f} of 255")
    print(f"\nworst disagreement: {worst:.2f}% - seams are "
          f"{'REAL' if worst > 0.5 else 'small but visible in flat ground'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
