"""Do the *composed* pixels contain a line at every slice boundary?

A measurement, not a test. It flies a streamed sector headless, composes the
field exactly as the renderer does, and asks the question a screenshot asked
first: is the row-to-row tone step at a slice boundary bigger than the row-to-row
step anywhere else on the same screen?

Every other probe so far asked a structural question - is the slice present, is
it opaque, does it match its neighbour where they overlap - and every one answered
"yes, clean", while the screen showed a line at every boundary. So this measures
the composed frame instead, at the one place the answer has to show up.

    python scripts/study_composed_lines.py [FRAMES] [--baked] [--dump PNGDIR]
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


def _rows(surface, band):
    """Mean tone per field row, as the screenshot measurement computed it."""
    a = np.asarray(pygame.surfarray.array3d(surface)).astype(np.float32)
    g = a.transpose(1, 0, 2).mean(axis=2)          # (rows, cols)
    return g[band.top:band.bottom, band.left:band.right]


def main(argv: list[str]) -> int:
    frames = next((int(a) for a in argv if a.isdigit()), 600)
    dump = Path(argv[argv.index("--dump") + 1]) if "--dump" in argv else None
    if dump:
        dump.mkdir(parents=True, exist_ok=True)

    app = App(headless=True)
    baked = "--baked" in argv
    if baked:
        app.settings = dataclasses.replace(app.settings, streamed_terrain=False)
    app.init_display()
    app.sm.to(State.TITLE)
    app._start_game()
    lvl = app.level
    band = pygame.Rect(C.FIELD_LEFT, C.FIELD_TOP,
                       C.FIELD_RIGHT - C.FIELD_LEFT,
                       C.FIELD_BOTTOM - C.FIELD_TOP)
    scratch = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H), pygame.SRCALPHA)
    ratios, rows_seen = [], []
    frame = 1.0 / 60.0
    t0 = time.perf_counter()
    for i in range(frames):
        app._update(frame)
        # Throttle EVERY frame. Sleeping only on the sampled ones lets the loop
        # run flat out between samples, and an unthrottled loop holds the GIL so
        # the painting threads never get a slice in - the harness then reports
        # "never launched" about a game that launches fine. Ask the same question
        # of the harness before asking it of the game.
        left = frame - (time.perf_counter() - t0) / (i + 1)
        time.sleep(max(0.0, min(frame, left)))
        if i % 6 or app.sm.state != State.PLAYING or lvl is None:
            continue
        scratch.fill((0, 0, 0, 0))
        lvl.draw(scratch, band)
        g = _rows(scratch, band)
        step = np.abs(np.diff(g, axis=0)).mean(axis=1)
        # Where does each slice boundary land on this frame? Same arithmetic the
        # renderer uses, so "boundary" means what the player sees, not a guess.
        edges = set()
        for name in ("near", "far"):
            strip = lvl.strips.get(name)
            if strip is None:
                continue
            y = lvl.far_y if name == "far" else lvl.near_y
            for k in range(-1, 4):
                top = (y - k * strip.slice_h) / 2.0
                r = int(round(top))
                if 1 <= r < len(step):
                    edges.add(r)
        med = float(np.median(step))
        if med <= 0:
            continue
        at = [step[r] for r in sorted(edges) if r < len(step)]
        if not at:
            continue
        ratios.append((float(np.mean(at)) / med, float(max(at)) / med, med,
                       len(edges)))
        rows_seen.extend(sorted(edges))
        if dump and len(rows_seen) < 40:
            pygame.image.save(scratch, str(dump / f"field_{i:05d}.png"))

    kind = "BAKED" if baked else "STREAMED"
    if not ratios:
        print(f"{kind}: no flown frames composed - nothing to measure")
        return 1
    mean_ratio = float(np.mean([r[0] for r in ratios]))
    worst = max(r[1] for r in ratios)
    print(f"{kind}: {len(ratios)} flown frames composed at full speed")
    print("  row-to-row tone step at a slice boundary / same screen's median step")
    print(f"    mean {mean_ratio:5.2f}x   worst single boundary {worst:5.2f}x")
    print("    (terrain's own median step is what the eye calls 'ground';")
    print("     a boundary reads as a LINE when it sits far above that)")
    app.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
