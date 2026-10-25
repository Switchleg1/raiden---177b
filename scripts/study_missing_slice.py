"""Is a whole SLICE of the near layer missing? (diagnostic)

The screenshots show a horizontal band, exactly one slice tall (557 device px at
1.95 px per logical px = 285 logical px, and a slice is 278), across which the
ground is about 8/255 DARKER than the ground above and below it, with hard tone
steps at both edges. A band that tall and that straight is not terrain: it is one
slice being drawn differently from its neighbours - and the obvious way for a near
slice to read darker is for it not to be there, so the dark far layer shows through.

Every coverage check so far measured the ALPHA OF THE COMPOSED CANVAS, which is
fully opaque wherever EITHER layer has pixels. That is why "100% opaque, 0 bare
rows" was a true statement about a field with a hole in it. This asks about the
near layer alone, slice by slice.

Run as a script: the design and paint workers re-run the entry file otherwise.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for path in (os.path.join(ROOT, "src"), ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import pygame  # noqa: E402

from state import State  # noqa: E402  (after sys.path: src is the package root)

pygame.display.init()
pygame.display.set_mode((64, 64))


def main(seconds: float) -> int:
    from app import App

    app = App(headless=True)
    import dataclasses
    try:
        app.settings = dataclasses.replace(app.settings, streamed_terrain=True)
        app.init_display()
        if app.sm.state is not State.TITLE:
            app.sm.to(State.TITLE)
        app._start_game()
        started = time.time()
        while time.time() - started < 120 and app.sm.state.name != "PLAYING":
            app._update(1.0 / 60.0)
            time.sleep(0.008)
        # Fly a while so painting is mid-strip, the state the player sees.
        for _ in range(int(seconds * 60)):
            app._update(1.0 / 60.0)
            time.sleep(0.004)

        lvl = app.level
        print(f"state={app.sm.state.name} near_y={lvl.near_y:.0f} "
              f"strips={sorted(lvl.strips)}")
        for name in ("near", "far"):
            strip = lvl.strips[name]
            print(f"\n{name}: slices {strip.count}, slice_h {strip.slice_h}, "
                  f"margin {strip.margin}")
            holes = 0
            for i in range(strip.count):
                surf = strip.surface(i)
                if surf is None:
                    continue
                a = pygame.surfarray.array_alpha(surf)
                opaque = float((a > 250).mean())
                if opaque < 0.999:
                    holes += 1
                    print(f"   slice {i:>3}: only {opaque * 100:5.1f}% opaque  "
                          f"min alpha {int(a.min())}  <- HOLE")
            if not holes:
                print("   every painted slice is fully opaque")
        return 0
    finally:
        app.shutdown()


if __name__ == "__main__":
    raise SystemExit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 3.0))
