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
          Random(plan.seed * 7717), origin=(0, y0))
    plane.sync()
    # SEED_MODE=world gives both windows the SAME pass-level stream, which separates
    # "the ground disagrees with itself" from "the paint call disagrees with the
    # paint call": whatever survives the swap is coming from a stream that belongs
    # to the window rather than to the world.
    key = 1 if os.environ.get("SEED_MODE") == "world" else (y0 // STRIP_SLICE)
    rng = random.Random(plan.seed * 8191 + key * 131 + 3)
    paint_site(plane, kit, plan, rng)
    arr = pygame.surfarray.array3d(plane.surface())
    return numpy.asarray(arr).transpose(1, 0, 2)     # (rows, cols, rgb)


def main() -> int:
    kit = TileKit()
    height = STRIP_SLICE * 4
    plan = plan_site("countryside", 1, Geom(h=height, cell=CELL, cyclic=False))

    # THE real seam test, matching how a strip actually paints: every window is the
    # same height (slice + 2 x margin), consecutive windows start one slice apart,
    # and the band where they both cover the same world rows is the 2 x margin
    # overlap. Comparing windows of *different* heights - which an earlier version of
    # this script did - measures the feather's neighbourhood changing shape, which is
    # a real purity bug but not the seam the player crosses, so it flattered or
    # damned the painter for the wrong reason. Bit-for-bit, over the overlap, or the
    # ground has a line in it.
    H = STRIP_SLICE + 2 * STRIP_MARGIN
    worst = 0.0
    for i in (1, 2, 3):
        y_a = i * STRIP_SLICE - STRIP_MARGIN
        y_b = y_a + STRIP_SLICE
        a = paint_window(plan, kit, y_a, H)
        b = paint_window(plan, kit, y_b, H)
        # Rows [S, S+2M) of A are the same world rows as rows [0, 2M) of B.
        s = STRIP_SLICE
        ca = a[s:s + 2 * STRIP_MARGIN]
        cb = b[:2 * STRIP_MARGIN]
        common = min(ca.shape[0], cb.shape[0])
        diff = ca[:common].astype(int) - cb[:common].astype(int)
        bad = numpy.abs(diff).max(axis=2) > 0
        pct = float(bad.mean()) * 100.0
        worst = max(worst, pct)
        per_col = bad.mean(axis=0)
        print(f"boundary {i}: {pct:6.3f}% of the {common}-row overlap disagrees"
              f"  (worst row {bad.mean(axis=1).max() * 100:5.1f}%"
              f" at overlap row {int(bad.mean(axis=1).argmax())}"
              f", worst column {per_col.max() * 100:5.1f}%"
              f" at col {int(per_col.argmax())})")
        if pct:
            print(f"          mean magnitude where different: "
                  f"{numpy.abs(diff[bad]).mean():.1f} of 255"
                  f", max {numpy.abs(diff[bad]).max()}")
    print(f"\nworst overlap disagreement: {worst:.3f}% - "
          f"{'SEAMS ARE REAL' if worst > 0.02 else 'the overlap agrees: no seam'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
