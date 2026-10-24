"""Fly a streamed sector headless and report what actually happened.

Not a test - a measurement. The question it answers is the one a screenshot
cannot: while the craft is flying, does the painted ground keep up with the
camera, how much of the field is covered on a normal frame, and are the
sector's planned fights arriving with the ground they were placed on?

    python scripts/playtest_streamed.py [FRAMES] [--sector N]
"""
from __future__ import annotations

import dataclasses
import os
import statistics
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


def main(argv: list[str]) -> int:
    frames = next((int(a) for a in argv if a.isdigit()), 900)
    sector = _opt(argv, "--sector", 0)

    app = App(headless=True)
    app.settings = dataclasses.replace(app.settings, streamed_terrain=True)
    C.LEVELS = tuple(                                    # start at the sector
        C.LEVELS[sector:] + C.LEVELS[:sector])
    app.init_display()
    app.sm.to(State.TITLE)
    app._start_game()
    lvl = app.level
    if lvl is None:
        print("no Level: streaming is not wired into the sector start")
        return 1

    band = pygame.Rect(C.FIELD_LEFT, C.FIELD_TOP,
                       C.FIELD_RIGHT - C.FIELD_LEFT,
                       C.FIELD_BOTTOM - C.FIELD_TOP)
    scratch = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H), pygame.SRCALPHA)
    drawn: list[int] = []
    holes = 0
    # Throttle like the real loop (`clock.tick(FPS)`) and sample lightly. An
    # unthrottled loop holds the GIL solid and the painting threads never get a
    # slice in: the first version of this harness reported an empty sector for
    # exactly that reason, and it was the harness that was wrong.
    frame = 1.0 / 60.0
    every = 10
    t0 = time.perf_counter()
    for i in range(frames):
        app._update(frame)
        if i % every == 0:
            scratch.fill((0, 0, 0, 0))
            drawn.append(lvl.draw(scratch, band))
            alpha = pygame.surfarray.array_alpha(scratch)
            if (alpha > 200).mean() < 0.9:
                holes += 1
        left = frame - (time.perf_counter() - t0) / (i + 1)
        time.sleep(max(0.0, min(frame, left)))
    wall = time.perf_counter() - t0

    encs = lvl.encounters
    print(f"sector {C.LEVELS[0].name}  seed {lvl.seed}  "
          f"{frames} frames ({frames / 60:.1f} s of sector) in {wall:.1f} s wall")
    print(f"  ground   : camera at row {lvl.near_y:7.0f} of {lvl.length} bake px"
          f"  ({lvl.progress() * 100:4.1f}%)")
    print(f"  slices   : min {min(drawn)} mean {statistics.mean(drawn):.2f} "
          f"max {max(drawn)}  sampled frames under-covered: {holes}/{len(drawn)}")
    print(f"  frontier : near {lvl.strips['near'].frontier()}/"
          f"{lvl.strips['near'].count} slices, far "
          f"{lvl.strips['far'].frontier()}/{lvl.strips['far'].count}")
    print(f"  fights   : {len(encs)} planned, "
          f"{app._enc_i} released, {len(app.game.enemies)} on the field, "
          f"clock {'off' if app.game.ground_spawns else 'ON'}")
    if encs:
        kinds = {}
        for e in encs:
            kinds[str(e.kind)] = kinds.get(str(e.kind), 0) + 1
        print(f"           {kinds}")
    return 0


def _opt(argv: list[str], name: str, default: int) -> int:
    if name in argv:
        return int(argv[argv.index(name) + 1])
    return default


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
