"""Fly a streamed sector headless and report what actually happened.

Not a test - a measurement. The question it answers is the one a screenshot
cannot: while the craft is flying, does the painted ground keep up with the
camera, how much of the field is covered on a normal frame, and are the
sector's planned fights arriving with the ground they were placed on?

    python scripts/playtest_streamed.py [FRAMES] [--sector N] [--baked]
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
    # the shipped default is streaming; --baked puts the old path back so the two
    # can be compared with the same harness and the same numbers
    if "--baked" in argv:
        app.settings = dataclasses.replace(app.settings, streamed_terrain=False)
    C.LEVELS = tuple(                                    # start at the sector
        C.LEVELS[sector:] + C.LEVELS[:sector])
    app.init_display()
    app.sm.to(State.TITLE)
    app._start_game()
    lvl = app.level
    if lvl is None:
        print("ground: BAKED (one screen, repeated) - no Level for this sector")
        return 0 if "--baked" in argv else 1

    band = pygame.Rect(C.FIELD_LEFT, C.FIELD_TOP,
                       C.FIELD_RIGHT - C.FIELD_LEFT,
                       C.FIELD_BOTTOM - C.FIELD_TOP)
    scratch = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H), pygame.SRCALPHA)
    drawn: list[int] = []
    cover: list[float] = []
    waiting: list[float] = []
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
            # coverage inside the field band only - the rest of the canvas is
            # not ground and never will be
            alpha = pygame.surfarray.array_alpha(scratch)[
                band.left:band.right, band.top:band.bottom]
            # only while the craft is actually flying: the seconds before launch
            # are the sector preparing itself. Counting them is what made a
            # healthy number read as 11%: an artefact of *when* this measures.
            # (The "healthy 84%" itself was also an artefact - a cropped blit -
            # and the real figure is 100%; see docs/terrain.md before quoting
            # either number at anyone.) The pre-launch samples are reported here
            # separately rather than mixed into the flown figure.
            value = float((alpha > 200).mean())
            if app.sm.state == State.PLAYING:
                cover.append(value)
                if value < 0.9:
                    holes += 1
            else:
                waiting.append(value)
        left = frame - (time.perf_counter() - t0) / (i + 1)
        time.sleep(max(0.0, min(frame, left)))
    wall = time.perf_counter() - t0

    encs = lvl.encounters
    print(f"ground: STREAMED  sector {C.LEVELS[0].name}  seed {lvl.seed}  "
          f"{frames} frames ({frames / 60:.1f} s of sector) in {wall:.1f} s wall")
    print(f"  ground   : camera at row {lvl.near_y:7.0f} of {lvl.length} bake px"
          f"  ({lvl.progress() * 100:4.1f}%)")
    print(f"  slices   : min {min(drawn)} mean {statistics.mean(drawn):.2f} "
          f"max {max(drawn)}  sampled frames under-covered: {holes}/{len(drawn)}")
    if cover:
        print(f"  coverage : flown frames - mean {statistics.mean(cover) * 100:5.1f}%  "
              f"min {min(cover) * 100:5.1f}%  first 10 samples "
              f"{statistics.mean(cover[:10]) * 100:5.1f}%  "
              f"settled {statistics.mean(cover[-10:]) * 100:5.1f}%")
    print(f"             ({len(waiting)} samples before launch ignored; "
          f"mean ground then {statistics.mean(waiting) * 100:.1f}%)")
    near = lvl.strips["near"]
    # What the camera needs against what exists. Painting once froze at slice 11
    # while the craft was at slice 16 and this line still read "11/66" as if it
    # were merely slow - the gap is the number that matters, so print it.
    need = near.window_at(lvl.near_y)[0]
    short = need - near.frontier() + 1
    gap = (f"  camera at slice {need}" + (
        f"  ** {short} SLICE(S) MISSING AHEAD **" if short > 0 else "  covered"))
    print(f"  frontier : near {near.frontier()}/{near.count} slices, far "
          f"{lvl.strips['far'].frontier()}/{lvl.strips['far'].count}{gap}")
    print(f"  fights   : {len(encs)} planned, "
          f"{app._enc_i} released, {len(app.game.enemies)} on the field, "
          f"clock {'off' if app.game.ground_spawns else 'ON'}")
    app.shutdown()          # stop the painters before the worker pool goes away
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
