"""Which slices are wrong, and by how much - per slice, per layer.

"Some tiles are fine, others ok, some are just wrong" is a per-window difference:
the ground at one slice disagrees with the same ground painted by a window that
happened to be placed differently. The suite's slice-vs-reference test covers four
slices of a short plan; this walks a whole sector and prints the distribution, so
"some" becomes a list of slice numbers and a shape to the disagreement.

    python scripts/study_slice_truth.py [SECTOR] [--far]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for k in ("src", "tests"):
    sys.path.insert(0, str(ROOT / k))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np  # noqa: E402
import pygame  # noqa: E402

import config as C  # noqa: E402
from level.design import _plan_here  # noqa: E402
from level.strip import STRIP_MARGIN, STRIP_SLICE, TerrainStrip  # noqa: E402


def main(argv) -> int:
    sector = next((int(a) for a in argv if a.isdigit()), 0)
    far = "--far" in argv
    layer = "far" if far else "near"
    pygame.init()
    pygame.display.set_mode((80, 50))

    spec = C.LEVELS[sector % len(C.LEVELS)]
    theme = str(getattr(spec.theme, "value", spec.theme))
    # The reference: ONE window tall enough to hold every slice compared here. It
    # cannot cull a neighbour out of existence, which is the whole reason a
    # reference is needed and an overlap test is not.
    n = 8
    rows = STRIP_SLICE * n
    plan = _plan_here(theme, sector + 1, rows)
    truth_strip = TerrainStrip(plan, layer, slice_h=rows, margin=STRIP_MARGIN)
    truth = truth_strip.paint(0)
    if truth is None:
        print("no reference")
        return 1
    tv = np.asarray(pygame.surfarray.array3d(truth)).astype(int)
    print(f"{spec.name}  theme {theme}  layer {layer}  reference {truth.get_size()}")

    small = TerrainStrip(plan, layer)
    stride = tv.shape[1] // n
    worst = []
    for i in range(n):
        band = small.paint(i)
        if band is None:
            continue
        kept = np.asarray(pygame.surfarray.array3d(band)).astype(int)
        ref = tv[:, i * stride:(i + 1) * stride]
        if ref.shape != kept.shape:
            print(f"  slice {i}: SHAPE {kept.shape} vs reference {ref.shape}")
            continue
        d = np.abs(ref - kept)
        bad = d.max(axis=2) > 0
        pct = float(bad.mean()) * 100
        mag = float(d[bad].mean()) if bad.any() else 0.0
        # Where inside the band? Edge rows = a boundary line; scattered = content.
        per_row = bad.mean(axis=0)
        where = ("edge" if per_row[:6].mean() + per_row[-6:].mean()
                 > 4 * (per_row[6:-6].mean() + 1e-9) else "scattered") if pct else "-"
        worst.append((pct, i, mag, where))
        print(f"  slice {i}: {pct:7.3f}% of pixels differ, mean {mag:5.1f}/255  {where}")
    if worst:
        worst.sort(reverse=True)
        print(f"worst slice {worst[0][1]}: {worst[0][0]:.3f}% at magnitude "
              f"{worst[0][2]:.1f} ({worst[0][3]})")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
