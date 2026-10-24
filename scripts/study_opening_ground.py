"""What is actually missing in the first second of play?

The loading bar goes away, the craft starts, and the ground is not there for about
a second. The gate was widened to one screen of lead and the player reports no
change, so the question is not whether the gate waits - it is *where the camera is*
when it does, and whether the row the gate asks about is the row the renderer draws
from. Printed per frame, because every theory about this has been a frame-timing
theory, and frame timing is only visible one frame at a time.

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

pygame.display.init()
pygame.display.set_mode((64, 64))

import config as C  # noqa: E402
from state import State  # noqa: E402
from terrain.common import TILE2  # noqa: E402


def main(frames: int) -> int:
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
        while time.time() - started < 90 and app.sm.state != State.PLAYING:
            app._update(1.0 / 60.0)
            time.sleep(0.008)
        print(f"launched after {time.time() - started:5.1f}s "
              f"state={app.sm.state}")

        band = pygame.Rect(C.FIELD_LEFT, C.FIELD_TOP,
                           C.FIELD_RIGHT - C.FIELD_LEFT,
                           C.FIELD_BOTTOM - C.FIELD_TOP)
        canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H), pygame.SRCALPHA)
        prev = None
        for f in range(frames):
            app._update(1.0 / 60.0)
            if app.sm.state != State.PLAYING:
                continue
            lvl = app.level
            near = lvl.strips.get("near")
            far = lvl.strips.get("far")
            miss_n = near.missing_at(lvl.near_y)
            miss_f = far.missing_at(lvl.far_y) if far else -99
            canvas.fill((0, 0, 0, 0))
            drawn = lvl.draw(canvas, band)
            arr = pygame.surfarray.pixels_alpha(canvas)[
                band.left:band.right, band.top:band.bottom]
            cov = float((arr > 200).mean())
            row = (f"frame {f:3d} near_y={lvl.near_y:7.1f} "
                   f"missing(near)={miss_n:3d} missing(far)={miss_f:3d} "
                   f"drawn={drawn} coverage={cov * 100:5.1f}%")
            if prev is None or abs(cov - prev) > 0.02 or f < 12 or cov < 0.98:
                print(row)
            prev = cov
        return 0
    finally:
        app.shutdown()


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 90))
