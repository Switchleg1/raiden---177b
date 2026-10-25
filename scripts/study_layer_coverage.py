"""Is the far layer's band one slice taller than the near layer's coverage?

The screenshot measurement says: a region exactly one slice tall sits ~8/255 darker
than the ground around it, and the effect repeats at the slice period. Not a hairline
- a BAND. The obvious way to make a band of darker ground is to draw the far layer,
which is mostly transparent over a dark backdrop, where the opaque near layer is
not.

This asks only geometry, so it cannot be fooled by a tone metric: for each field row,
which layers have a band standing on it, using each strip's own window and the same
placement arithmetic `TerrainStrip.draw` uses. Rows covered by `far` but not `near`
are ground the player sees through the distant range rather than across it.

    python scripts/study_layer_coverage.py [FRAMES]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

import config as C  # noqa: E402
from app import App  # noqa: E402
from state import State  # noqa: E402


def _runs(rows):
    """Collapse a set of rows into (start, length) runs, for one-line printing."""
    out, start, prev = [], None, None
    for r in sorted(rows):
        if start is None:
            start = r
        elif r != prev + 1:
            out.append((start, prev - start + 1))
            start = r
        prev = r
    if start is not None:
        out.append((start, prev - start + 1))
    return out


def _covered(lvl, band, name):
    """Field rows a band from this layer stands on, and how many are missing."""
    strip = lvl.strips.get(name)
    if strip is None:
        return set(), 0
    y = lvl.far_y if name == "far" else lvl.near_y
    lo, hi = strip.window_at(y)
    rows, gaps = set(), 0
    for k in range(lo, hi):
        if strip.surface(k) is None:
            gaps += 1
            continue
        dest = band.top + (y - (k + 1) * strip.slice_h) / 2.0
        for r in range(int(dest), int(dest) + strip.slice_h // 2):
            if band.top <= r < band.bottom:
                rows.add(r)
    return rows, gaps


def main(argv):
    frames = next((int(a) for a in argv if a.isdigit()), 600)
    app = App(headless=True)
    app.init_display()
    app.sm.to(State.TITLE)
    app._start_game()
    lvl = app.level
    if lvl is None:
        print("no Level (baked path?) - nothing to measure")
        return 1
    band = pygame.Rect(C.FIELD_LEFT, C.FIELD_TOP,
                       C.FIELD_RIGHT - C.FIELD_LEFT,
                       C.FIELD_BOTTOM - C.FIELD_TOP)
    hits = 0
    frame = 1.0 / 60.0
    t0 = time.perf_counter()
    for i in range(frames):
        app._update(frame)
        left = frame - (time.perf_counter() - t0) / (i + 1)
        time.sleep(max(0.0, min(frame, left)))
        if i % 30 or app.sm.state != State.PLAYING:
            continue
        near, _ = _covered(lvl, band, "near")
        far, _ = _covered(lvl, band, "far")
        far_only = far - near
        uncovered = set(range(band.top, band.bottom)) - near - far
        if far_only or uncovered:
            hits += 1
            if hits <= 6:
                print(f"frame {i:4d} near_y {lvl.near_y:7.0f} "
                      f"far_y {lvl.far_y:7.0f}")
                if far_only:
                    print(f"   rows with ONLY the far layer ({len(far_only)}): "
                          f"runs (row, height) {_runs(far_only)[:4]}")
                if uncovered:
                    print(f"   rows with NO layer at all ({len(uncovered)}): "
                          f"runs {_runs(uncovered)[:4]}")
    print(f"\n{hits} sampled frames where the field is not covered by the opaque "
          f"layer everywhere it is covered at all" if hits else
          "\nevery sampled frame: the far layer never stands alone on a field row")
    app.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
