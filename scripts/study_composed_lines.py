"""Do the composed pixels contain a line at every slice boundary?

A measurement, not a test. It flies a streamed sector headless, composes the field
the way the renderer does, upscales it the way `_present` does, and asks the
question a screenshot asked first: is the row-to-row tone step at a slice boundary
bigger than the row-to-row step anywhere else on the same screen?

Every other probe so far asked a structural question - is the slice present, is it
opaque, does it match its neighbour where they overlap - and every one answered
"yes, clean", while the screen showed a line at every boundary. So this measures
the composed frame instead, at the one place the answer has to show up, and it
measures the picture the player is actually shown: opaque canvas, then the
non-integer window upscale on top.

    python scripts/study_composed_lines.py [FRAMES] [--baked] [--window WX,WY]
                                          [--inject]   # positive control
"""
from __future__ import annotations

import dataclasses
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np  # noqa: E402
import pygame  # noqa: E402

import config as C  # noqa: E402
from app import App  # noqa: E402
from state import State  # noqa: E402

# A window like the one in the screenshots that started this: 1562 x 1116 for an
# 800 x 600 canvas is 1.9525 device px per logical px - not an integer, so the
# whole field is resampled on the way to the screen.
DEFAULT_WINDOW = (1562, 1116)


def _field_rows(surface, rect):
    """Mean tone per row inside the field, as a screenshot is measured."""
    a = np.asarray(pygame.surfarray.array3d(surface)).astype(np.float32)
    g = a.transpose(1, 0, 2).mean(axis=2)               # (rows, cols)
    return g[rect.top:rect.bottom, rect.left:rect.right]


def main(argv: list[str]) -> int:
    frames = next((int(a) for a in argv if a.isdigit()), 600)
    window = DEFAULT_WINDOW
    if "--window" in argv:
        window = tuple(int(v) for v in argv[argv.index("--window") + 1].split(","))

    app = App(headless=True)
    baked = "--baked" in argv
    if baked:
        app.settings = dataclasses.replace(app.settings, streamed_terrain=False)
    app.init_display()
    app.sm.to(State.TITLE)
    app._start_game()
    lvl = app.level
    if lvl is None:
        print("this sector has no Level (baked path?) - nothing to measure")
        return 1

    band = pygame.Rect(C.FIELD_LEFT, C.FIELD_TOP,
                       C.FIELD_RIGHT - C.FIELD_LEFT,
                       C.FIELD_BOTTOM - C.FIELD_TOP)
    # Opaque, like the app's canvas. The far layer is low-alpha, so what it blends
    # with is part of what the player sees, and the first version of this probe
    # measured a transparent scratch surface - a picture the game never shows.
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    k = window[0] / C.LOGICAL_W
    dev_band = pygame.Rect(int(band.left * k), int(band.top * k),
                           int(band.width * k), int(band.height * k))

    inject = "--inject" in argv
    ratios = []
    frame = 1.0 / 60.0
    t0 = time.perf_counter()
    for i in range(frames):
        app._update(frame)
        # Throttle EVERY frame. Sleeping only on sampled frames lets the loop run
        # flat out in between, the GIL never frees, and the painting threads starve
        # - a harness that reports "never launched" about a healthy game.
        left = frame - (time.perf_counter() - t0) / (i + 1)
        time.sleep(max(0.0, min(frame, left)))
        if i % 6 or app.sm.state != State.PLAYING:
            continue

        canvas.fill(app.renderer.palette.field_bg)
        lvl.draw(canvas, band)
        if inject:
            # A POSITIVE CONTROL, stamped where the renderer puts a boundary. The
            # probe's whole value is its "clean" answer, and a negative from an
            # instrument that has never produced a positive is not evidence - it is
            # an unknown instrument. `--inject` draws the very artifact the player
            # reports and the probe must report ~10x for the clean runs to mean
            # anything.
            for name in ("near", "far"):
                strip = lvl.strips.get(name)
                if strip is None:
                    continue
                yy = lvl.far_y if name == "far" else lvl.near_y
                for j in range(-1, 6):
                    dest = band.top + (yy - j * strip.slice_h) / 2.0
                    if band.top <= dest < band.bottom - 1:
                        pygame.draw.line(canvas, (0, 0, 0), (band.left, int(dest)),
                                         (band.right - 1, int(dest)))
        big = (pygame.transform.smoothscale(canvas, window)
               if k != round(k) else canvas)
        step = np.abs(np.diff(_field_rows(big, dev_band), axis=0)).mean(axis=1)

        # Where each slice boundary lands on this frame, in the pixels measured:
        # the same arithmetic `TerrainStrip.draw` uses, so a "boundary" is what the
        # player sees rather than what a model of the code assumes.
        edges = set()
        for name in ("near", "far"):
            strip = lvl.strips.get(name)
            if strip is None:
                continue
            y = lvl.far_y if name == "far" else lvl.near_y
            # Exactly `TerrainStrip.draw`'s placement, band.top included: the
            # first version subtracted band.top here as well as inside the crop,
            # so it measured rows ~86 device px away from every boundary and
            # reported a spotless result about the wrong rows. A probe that
            # misses its own target by a third of a slice is worse than none.
            for j in range(-1, 6):
                dest = band.top + (y - j * strip.slice_h) / 2.0
                r = int(round(dest * k)) - dev_band.top + 1
                if 2 <= r < len(step):
                    edges.add(r)
        med = float(np.median(step))
        if med <= 0 or not edges:
            continue
        at = [step[r] for r in edges]
        ratios.append((float(np.mean(at)) / med, float(max(at)) / med, med,
                       float(np.percentile(step, 99)) / med))

    kind = "BAKED" if baked else "STREAMED"
    if not ratios:
        print(f"{kind}: no flown frames composed - nothing to measure")
        return 1
    print(f"{kind}: {len(ratios)} flown frames, window {window[0]}x{window[1]} "
          f"({k:.4f} device px per logical px)")
    print("  row-to-row tone step AT A SLICE BOUNDARY, as a multiple of the same")
    print("  screen's median step (terrain's own step is what the eye calls ground)")
    print(f"    mean at boundaries {np.mean([r[0] for r in ratios]):5.2f}x   "
          f"worst boundary on a frame {max(r[1] for r in ratios):5.2f}x")
    print(f"    for scale: the 99th percentile ANYWHERE on screen averages "
          f"{np.mean([r[3] for r in ratios]):5.2f}x - a boundary near that is "
          "ordinary terrain,")
    print("    a boundary far above it is a LINE, and the screenshots showed 5-10x")
    app.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
