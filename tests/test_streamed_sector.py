"""Flying a streamed sector: the App, the renderer and a Level in one loop.

``tests/test_level.py`` proves a Level and its strip in isolation. This file asks
the question that file cannot: when the *game* enters a sector with streaming on,
does a Level get made, does ground appear under the craft, and does the next
sector start being prepared while this one is flown?

The sector here is deliberately tiny (a six-second wave and a four-second boss
tail): designing a whole sector costs seconds, and the thing under test is the
wiring, not the length.
"""
from __future__ import annotations

import dataclasses
import os
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

import config as C
from app import App
from level import Level
from state import State
from terrain.common import TILE2


@pytest.fixture()
def tiny_sectors(monkeypatch):
    """Two small sectors in the table, so nothing here waits on a real one."""
    small = []
    for spec in C.LEVELS[:2]:
        small.append(dataclasses.replace(spec, wave_seconds=6.0,
                                         boss_tail_seconds=4.0, phases=()))
    table = tuple(small) + tuple(C.LEVELS[2:])
    monkeypatch.setattr(C, "LEVELS", table)
    return table


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "TEST_DATA_DIR", str(tmp_path), raising=False)
    a = App(headless=True)
    a.init_display()
    a.settings = dataclasses.replace(a.settings, streamed_terrain=True)
    a.sm.to(State.TITLE)
    try:
        yield a
    finally:
        a.shutdown()


def _enter(app: App) -> None:
    """Title first: the machine will not go boot -> ready."""
    if app.sm.state != State.TITLE:
        app.sm.to(State.TITLE)
    app._enter_ready()


def _wait_for(fn, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(0.05)
    return False


def test_entering_a_sector_makes_a_level(app, tiny_sectors):
    assert app.level is None
    app._start_game()
    assert isinstance(app.level, Level), "the sector did not get a Level"
    assert app.level.seed == 1
    # the renderer is showing the same object the model is flying
    assert app.renderer._level is app.level


def test_ground_appears_under_the_craft(app, tiny_sectors):
    """The gap an earlier commit left open: a Level existed, but nothing had
    ever been drawn from it inside the app."""
    app._start_game()
    lvl = app.level
    assert _wait_for(lambda: lvl.built()), "the sector was never designed"
    assert _wait_for(lambda: lvl.ready_at(0.0)), "no ground reached the camera"
    assert lvl.near_y == pytest.approx(TILE2)
    band = pygame.Rect(0, 0, C.LOGICAL_W, C.LOGICAL_H)
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H), pygame.SRCALPHA)
    before = pygame.surfarray.array3d(canvas)
    drawn = lvl.draw(canvas, band)
    assert drawn > 0, "the Level drew nothing into the field"
    after = pygame.surfarray.array3d(canvas)
    assert (after != before).any(), "the slices it drew put no pixels down"
    # and the ground is opaque where the material grid was laid: a translucent
    # near layer is the tell of a missing base step
    alpha = pygame.surfarray.array_alpha(lvl.strips["near"].surface(0))
    assert (alpha > 250).mean() > 0.99


def test_the_next_sector_starts_being_prepared_mid_wave(app, tiny_sectors):
    """Your halfway trigger: by the time the wave is half flown, the next
    sector's ground should already be on its way."""
    app._start_game()
    assert app.next_level is None
    # past the checkpoint the loop watches: half the wave flown
    spec = app.game._spec()
    app.game._wave_timer = 0.6 * spec.wave_seconds
    assert app.game.wave_progress() >= 0.5
    app._watch_load_ahead()               # the checkpoint the loop watches
    assert isinstance(app.next_level, Level)
    assert app.next_level.seed == 2
    assert app.next_level.spec is C.LEVELS[1]
    # swapping in is a pointer swap, not a rebuild
    prepared = app.next_level
    app._use_level(1)
    assert app.level is prepared
    assert app.next_level is None


def test_the_app_does_not_start_levels_when_streaming_is_off(app, tiny_sectors):
    app.settings = dataclasses.replace(app.settings, streamed_terrain=False)
    app._start_game()
    app._warm_level_ahead(0)
    assert app.level is None and app.next_level is None
    assert app.renderer._level is None


def test_the_fights_arrive_with_the_ground(app, tiny_sectors):
    """The seam between the level and the model: the level plans its fights on
    the land, and the app hands them over as that land reaches the field. The
    model's spawn clock stops when they start arriving - two systems deciding
    when things appear is twice the density."""
    app._start_game()
    lvl = app.level
    assert _wait_for(lambda: lvl.encounters, timeout=120.0), \
        "the sector designed ground but never planned its fights"
    planned = len(lvl.encounters)
    assert app.game.ground_spawns is False
    for _ in range(240):                # four seconds of the app's own update
        app._update(1.0 / 60.0)
    assert app._enc_i > 0, "no encounter was released over four seconds of ground"
    assert app.game.ground_spawns is True, "the model is still spawning on its clock"
    assert app._enc_i <= planned


def test_a_sector_without_a_level_keeps_the_old_director(app, tiny_sectors):
    """The fallback has to be complete: with streaming off there is no Level, no
    encounters and no release path, and the sector plays exactly as a baked
    sector always did."""
    app.settings = dataclasses.replace(app.settings, streamed_terrain=False)
    app._start_game()
    for _ in range(180):
        app._update(1.0 / 60.0)
    assert app.level is None
    assert app.game.ground_spawns is False
    assert len(app.game.enemies) > 0, "the timer director stopped fielding things"


def test_a_streamed_sector_survives_a_frame_loop(app, tiny_sectors):
    """The part only a loop can show: the level keeps up while the world moves."""
    app._start_game()
    app.sm.to(C.State.PLAYING) if hasattr(C, "State") else None
    lvl = app.level
    assert _wait_for(lambda: lvl.ready_at(0.0), timeout=120.0)
    top = lvl.strips["near"].frontier()
    for _ in range(60):                   # a second of scrolling
        lvl.update(1.0 / 60.0)
    assert lvl.near_y > 0.0, "the ground never scrolled"
    assert _wait_for(lambda: lvl.ready_at(lvl.near_y / 2.0), timeout=60.0), \
        "the painters fell behind the camera"
    assert lvl.strips["near"].frontier() >= top
