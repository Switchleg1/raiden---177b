"""Where does the ground go when the craft dies?

Reads like a load: the sector's ground is rebuilt after a respawn even though
everything painted for it is still valid. Two suspects, and this tells them apart
by identity rather than by eye -

* `App._watch_level_ahead` has `if self.game.level_index >= self.game.level_index:`,
  which is always true, resets the "warmed" markers every frame and returns early;
  and stops the next sector's prepared Level when its seed no longer matches.
* `App._use_level` keeps the sector being flown only if `self.level.seed` matches,
  so anything that nulls `self.level` in the death path turns a respawn into a new
  design and a paint frontier back at slice zero.

Run as a script (the paint/design workers re-run the entry file otherwise).
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

from app import App  # noqa: E402
from state import State  # noqa: E402


def _fly(app: App, frames: int) -> None:
    for _ in range(frames):
        app._update(1.0 / 60.0)
        time.sleep(0.004)


def _state(app: App) -> str:
    lvl = app.level
    if lvl is None:
        return "no Level"
    near = (lvl.strips or {}).get("near")
    return (f"seed={lvl.seed} near_y={lvl.near_y:.0f} "
            f"frontier={near.frontier() if near else '-'} "
            f"strips={len(lvl.strips or {})}")


def main() -> int:
    app = App(headless=True)
    import dataclasses

    try:
        app.settings = dataclasses.replace(
            app.settings, streamed_terrain=True)
        app.init_display()
        if app.sm.state is not State.TITLE:
            app.sm.to(State.TITLE)
        app._start_game()

        started = time.time()
        while time.time() - started < 90 and app.sm.state != State.PLAYING:
            app._update(1.0 / 60.0)
            time.sleep(0.01)
        print(f"reached PLAYING after {time.time() - started:5.1f}s "
              f"(msg={app._msg!r})")
        _fly(app, 120)

        lvl = app.level
        nxt = app.next_level
        before = _state(app)
        print(f"before death : sector={app.game.level_index} {before}")
        print(f"               next_level={'yes' if nxt else 'no'} "
              f"warmed=({app._warmed_wave_sector},{app._warmed_next_sector})")

        app.game.lives = 3
        app.game.lives = 2
        app._begin_transition("SHIP DOWN", "2 lives left", 1.2, "ready")
        print(f"death        : state={app.sm.state} "
              f"transition={app._transition_timer:.2f} "
              f"watchdog keeps flying ground")
        _fly(app, 30)
        print(f"               during transition: {_state(app)}")

        done = time.time()
        while time.time() - done < 90 and app.sm.state != State.PLAYING:
            app._update(1.0 / 60.0)
            time.sleep(0.01)
        print(f"respawn      : after {time.time() - done:5.1f}s "
              f"state={app.sm.state} (msg={app._msg!r})")
        after = _state(app)
        print(f"               sector={app.game.level_index} {after}")
        print()
        print(f"LEVEL OBJECT KEPT : {app.level is lvl}")
        print(f"next_level KEPT   : {app.next_level is nxt} "
              f"({'yes' if app.next_level else 'none at all'})")
        same = before == after
        print(f"GROUND UNCHANGED  : {same}  (frontier reset means it was rebuilt)")
        return 0
    finally:
        app.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
