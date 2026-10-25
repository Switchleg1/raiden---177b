"""What does the flamethrower cost per frame, and where does it go?

Flies sector 1 headless with the real loop (update + render), grants a
flamethrower pod at a chosen second, and reports frame-time percentiles in three
windows: before the pickup, while lit, and after it expires. A cProfile of the
lit window names the functions the time is in.

    python scripts/study_flame_cost.py [--at SECONDS] [--profile]

The craft is not flown, so it can be shot down, and a death ends the flame by
design (powers die with the craft): a "lit" window shorter than FLAME_TIME is
that, not a timer bug.

Measured on the fix (sector 1, first pickup): before the fix 13.4 / 38.9 / 13.9
ms median for before / lit / after, p95 lit 152 ms; after it 1.4 / 1.8 / 1.5 ms,
p95 lit 2.1 ms. The cause is written up in `audio.AudioManager._rendered`.
"""
from __future__ import annotations

import cProfile
import os
import pstats
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import config as C  # noqa: E402
from app import App  # noqa: E402
from game.items import Item  # noqa: E402
from state import State  # noqa: E402


def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0.0


def main(argv: list[str]) -> int:
    at = 8.0
    if "--at" in argv:
        at = float(argv[argv.index("--at") + 1])
    app = App(headless=True)
    app.init_display()
    app.sm.to(State.TITLE)
    app._start_game()
    dt = 1.0 / 60.0
    # wait for launch
    for _ in range(60 * 30):
        app._update(dt)
        app._render()
        if app.sm.state == State.PLAYING:
            break
    times: dict[str, list[float]] = {"before": [], "lit": [], "after": []}
    prof = cProfile.Profile() if "--profile" in argv else None
    granted = False
    t_play = 0.0
    while t_play < at + C.FLAME_TIME + 6.0:
        if not granted and t_play >= at:
            g = app.game
            g._apply_item(Item(C.ItemKind.FLAME, g.player.x, g.player.y), [])
            granted = True
            if prof:
                prof.enable()
        phase = ("before" if not granted else
                 "lit" if app.game.flame_timer > 0.0 else "after")
        if phase == "after" and prof and prof is not None:
            prof.disable()
        t0 = time.perf_counter()
        app._update(dt)
        app._render()
        times[phase].append((time.perf_counter() - t0) * 1000.0)
        t_play += dt
        app.game.lives = max(app.game.lives, 3)    # a death would end the window
    for k, v in times.items():
        if v:
            print(f"{k:7s} n={len(v):4d}  median {statistics.median(v):6.2f} ms  "
                  f"p95 {_pct(v, 0.95):6.2f}  max {max(v):7.2f}  "
                  f"puffs~{len(app.game.flame.puffs)}")
    if prof:
        pstats.Stats(prof).sort_stats("cumulative").print_stats(28)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
