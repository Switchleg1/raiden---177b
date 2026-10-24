"""Find horizontal seams in screenshots, without eyes.

A seam is a row where the picture disagrees with the row above it much more than
the ground does anywhere else, or a row where the average tone steps and then
holds. Both are measurable, and measuring beats asking a vision model that has
been on the wrong side of the same argument I keep having with myself.

Reports the y of every candidate, the spacing between them, and the spacing in
terms of the game's own periods - 278 logical rows is one strip slice, 1112 is a
screen - because the spacing IS the diagnosis: 278 means slice boundaries, 1112
means the renderer's scroll arithmetic, no structure means the terrain itself.
"""
from __future__ import annotations

import sys

import numpy as np
from PIL import Image

SLICE_LOGICAL = 278          # one strip slice, in logical pixels
SCREEN_LOGICAL = 600 - 116 - 8  # the field's logical height
LOGICAL_W = 800


def analyse(path: str) -> None:
    img = Image.open(path).convert("RGB")
    a = np.asarray(img).astype(np.int16)
    h, w = a.shape[:2]
    sx = w / LOGICAL_W                     # screenshot scale vs logical px
    print(f"\n=== {path}  {w}x{h}  ({sx:.2f}px per logical px) ===")

    # Rows only inside the playfield: the HUD strip at the top and the black
    # frame are their own business, and their edges would headline this report.
    top = int(round(0.10 * h))
    bot = int(round(0.95 * h))
    left = int(round(0.015 * w))
    right = int(round(0.985 * w))
    g = a[top:bot, left:right, :].mean(axis=2)          # (rows, cols) luminance

    # 1. hard horizontal discontinuities: mean |row[y] - row[y-1]| over columns
    step = np.abs(np.diff(g, axis=0)).mean(axis=1)
    med, mad = float(np.median(step)), float(np.median(np.abs(step - np.median(step))))
    spikes = np.nonzero(step > med + 12 * (mad + 1e-6))[0]
    print(f"row-to-row step: median {med:.1f}, {len(spikes)} spike rows "
          f"(>{med + 12 * (mad + 1e-6):.1f})")
    if len(spikes):
        ys = spikes + top + 1
        gaps = np.diff(ys)
        print("   spike y: ", list(map(int, ys[:16])))
        if len(gaps):
            print(f"   spacing: median {int(np.median(gaps))} px "
                  f"= {np.median(gaps) / sx / SLICE_LOGICAL:.2f} slices "
                  f"(counts of each: "
                  f"{sorted({int(v): int((gaps == v).sum()) for v in gaps}.items(), key=lambda kv: -kv[1])[:4]})")

    # 2. tone steps: the mean tone jumps and then HOLDS. A lighting seam does
    #    this; terrain does not, because terrain keeps changing.
    tone = g.mean(axis=1)
    d = np.diff(tone)
    hold = np.nonzero(np.abs(d) > max(3.0, np.abs(d).std()))[0]
    holds = []
    for y in hold:
        before = float(tone[max(0, y - 12):y + 1].mean())
        after = float(tone[y + 1:y + 13].mean())
        if abs(after - before) > 3.0:
            holds.append((int(y + top + 1), round(float(after - before), 1)))
    print(f"tone steps that hold: {len(holds)} -> {holds[:10]}")

    # 3. repeated rows: the same row twice means a boundary was stitched by
    #    copying, which is what a duplicated slice edge looks like.
    same = np.nonzero(np.abs(np.diff(g, axis=0)).mean(axis=1) < 0.12)[0]
    print(f"near-duplicate adjacent rows: {len(same)} "
          f"-> {list(map(int, (same + top + 1)[:12]))}")

    # 4. bare/black rows inside the field (missing ground)
    dark = np.nonzero(g.mean(axis=1) < 12.0)[0]
    print(f"very dark rows inside the field: {len(dark)} "
          f"-> {list(map(int, (dark + top + 1)[:12]))}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        analyse(p)
