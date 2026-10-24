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
from app.app import READY_HOLD_MAX, READY_TIME
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


def _advance(app: App, seconds: float) -> None:
    """Fly the app's own loop for a while (its clock is driven by _update)."""
    for _ in range(int(seconds * 60)):
        app._update(1.0 / 60.0)


def _launch(app: App, limit: float = READY_TIME + READY_HOLD_MAX + 2.0) -> bool:
    """Frames until the craft is away, or the hold's own cap says enough."""
    deadline = time.time() + limit
    while time.time() < deadline:
        app._update(1.0 / 60.0)
        if app.sm.state == State.PLAYING:
            return True
    return app.sm.state == State.PLAYING


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
    assert _launch(app), "the sector never started"
    _advance(app, 4.0)                  # four seconds of flown sector
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


def test_a_respawn_keeps_the_ground_the_craft_flew_over(app, tiny_sectors):
    """Dying does not move the craft to another sector. Re-entering the sector
    used to build a fresh Level, which put the strip back at row 0 under a craft
    standing halfway down it and threw away every slice its painters had
    finished - the streamed equivalent of the guard `ensure_terrain` already is
    for the baked path."""
    app._start_game()
    lvl = app.level
    assert _wait_for(lambda: lvl.ready_at(0.0), timeout=120.0)
    for _ in range(30):                 # some ground under the wings first
        lvl.update(1.0 / 60.0)
    before = lvl.strips["near"].frontier()
    near_y = lvl.near_y
    app._enter_ready()                  # the respawn path re-enters the sector
    assert app.level is lvl, "the respawn replaced the sector's ground"
    assert app.level.near_y == pytest.approx(near_y), "the camera was moved"
    assert app.level.strips["near"].frontier() >= before


def test_a_cold_sector_waits_for_its_ground_before_launching(app, tiny_sectors):
    """READY is a pause the player is already sitting through; ground appearing
    from nothing under a flying craft is not. So the launch waits for the opening
    band - and waits only up to a cap, because a sector whose painters died still
    has to start."""
    app._start_game()
    lvl = app.level
    for _ in range(int(READY_TIME * 60) + 1):
        app._update(1.0 / 60.0)
    if not lvl.ready_at(lvl.near_y / 2.0):
        assert app.sm.state == State.READY, \
            "launched onto ground that was not there yet"
    assert _launch(app), "the hold never let go"
    assert app.level is lvl


def test_a_baked_sector_is_never_held_by_a_streamed_guards(app, tiny_sectors):
    """The hold belongs to streaming. A baked sector has no Level, so asking
    whether its opening is painted has to answer yes immediately."""
    app.settings = dataclasses.replace(app.settings, streamed_terrain=False)
    app._start_game()
    assert app._opening_painted() is True
    for _ in range(int(READY_TIME * 60) + 2):
        app._update(1.0 / 60.0)
    assert app.sm.state == State.PLAYING


def test_the_first_sector_starts_preparing_when_the_run_starts(app,
                                                               tiny_sectors,
                                                               monkeypatch):
    """Sector 1 is the one with no lead-in: no earlier sector was painting it
    while the player flew. So the run starts it, and 'starts' means the design
    and the first slices are already underway by the time READY is shown - the
    title and READY seconds were idle, and this spends them on work that has to
    happen before the craft takes off either way."""
    seen = {}
    real = app._enter_ready

    def spy(seamless: bool = False):
        lvl = app.next_level
        seen["warmed"] = lvl is not None
        seen["started"] = bool(getattr(lvl, "_threads", ()))
        seen["seed"] = getattr(lvl, "seed", None)
        return real(seamless)

    monkeypatch.setattr(app, "_enter_ready", spy)
    app._start_game()
    assert seen["warmed"], "the run entered READY before its sector began"
    assert seen["started"], "the sector was made but nothing was painting it"
    assert seen["seed"] == 1
    assert app.level is not None and app.level.seed == 1
    assert app.next_level is None, "the prepared sector was not taken over"


def test_the_hud_panel_is_opaque_and_stops_at_the_field(app):
    """Score, lives and bombs are read at a glance while dodging; ground moving
    behind them - which streamed slices allow, since the far range is not cut to
    the field's top edge - turns the readout into a texture.

    The panel is its own call rather than a line inside `draw_hud`: it can be
    tested with no glyphs in the way, and it names the pixels the HUD owns. The
    row at FIELD_TOP belongs to the field, so asserting it is *not* the panel
    colour is what stops a one-row-off fill from eating the top of the ground.
    """
    canvas = app.renderer.canvas
    want = app.renderer.palette.hud_bg
    assert want != app.renderer.palette.field_bg, "needs the two to differ"
    app.renderer.draw_hud_panel()
    for x in range(0, C.LOGICAL_W, 37):
        for y in range(0, C.FIELD_TOP, 7):
            got = tuple(canvas.get_at((x, y))[:3])
            assert got == want, f"the HUD strip at ({x}, {y}) is {got}, not {want}"
    below = tuple(canvas.get_at((C.LOGICAL_W // 2, C.FIELD_TOP))[:3])
    assert below != want, "the panel spilled into the field's first row"


def test_the_readouts_are_drawn_on_the_panel(app):
    """The fill comes first and the readouts land on top of it - that order is the
    whole feature, and it is observable: a panel that hid them would leave the
    strip a single flat colour."""
    canvas = app.renderer.canvas
    want = app.renderer.palette.hud_bg
    app.game.score = 12345
    app.renderer.draw_hud(app.game, 0.0)
    differing = sum(1 for x in range(0, C.LOGICAL_W, 7)
                    for y in range(0, C.FIELD_TOP, 3)
                    if tuple(canvas.get_at((x, y))[:3]) != want)
    assert differing > 20, "the readouts are not drawn on top of the panel"


def test_a_sector_change_never_touches_the_baked_tiles(app, tiny_sectors,
                                                       monkeypatch):
    """The handover process, removed rather than worked around.

    A streamed sector's ground already exists by the time the pointer moves, so
    there is nothing to load, nothing to reveal over the old ground, and nothing
    to snap to afterwards. Baking the next sector is skipped too, so the tiles
    that used to appear mid-handoff are never produced at all. Asserted by
    forbidding the calls, because "it also looked right" is how a fallback that
    still fires gets mistaken for a fix.
    """
    import config as C
    from level import Level

    app._start_game()
    lvl = Level(C.LEVELS[1], seed=2)
    lvl.start()
    app.next_level = lvl

    calls = []
    monkeypatch.setattr(app.renderer, "handoff_terrain",
                        lambda *a, **k: calls.append("handoff") or False)
    monkeypatch.setattr(app.renderer, "ensure_terrain",
                        lambda *a, **k: calls.append("ensure"))

    app.game.advance_level()
    app._enter_ready(seamless=True)

    assert calls == [], f"the baked path was used for the change: {calls}"
    assert app.level is lvl, "the prepared sector's ground was not flown"
    assert getattr(app.renderer, "_terrain", 0) is None, \
        "baked ground is still installed under the streamed sector"
    assert app.renderer.terrain_handoff_active() is False
    lvl.stop()


def test_the_title_screen_starts_sector_ones_ground(app, tiny_sectors,
                                                    monkeypatch):
    """Sector 1 has no lead-in, and its ground takes longer to invent than a READY
    countdown, so the title screen is asked to start it: those seconds were doing
    nothing, and the window already exists for any painter that falls back to this
    interpreter.

    Three things are checked, because each can regress alone: the title path asks
    (a future "that warm is redundant" edit would put the empty-field launch
    back); asking while streaming really does begin the work, threads and all;
    asking twice does not invent the same world twice; and asking while *not*
    streaming declines, so the baked path pays nothing for the arrangement.
    """
    import dataclasses

    calls = []
    monkeypatch.setattr(app, "_warm_current_level", lambda i: calls.append(i))
    app.init_display()
    assert calls == [0], "the title path never asked for sector 1's ground"

    monkeypatch.undo()
    assert app.streaming() is True
    app.next_level = None
    app._warm_current_level(0)
    lvl = app.next_level
    assert lvl is not None and lvl.seed == 1, "the warm designed nothing"
    assert lvl._threads or lvl.built(), "the warm designed but never started"

    app._warm_current_level(0)
    assert app.next_level is lvl, "the sector was designed twice"

    app.settings = dataclasses.replace(app.settings, streamed_terrain=False)
    app.next_level = None
    app._warm_current_level(0)
    assert app.next_level is None, "the baked path warmed a Level it will not fly"


def test_the_launch_hold_continues_while_ground_arrives_and_stops_when_it_doesnt(
        app, monkeypatch):
    """Progress, not a constant, is what decides the wait.

    A fixed hold was the bug's other half: whatever number was chosen, a sector
    that needed longer launched into an empty field at exactly that many seconds.
    So the hold continues while the painted frontier grows - and stops when it
    stops growing, because ground that has died must not be able to sit the player
    in READY forever.
    """
    class Fake:
        seed = 1

        def __init__(self) -> None:
            self.n = 0
            self.strips = {"near": self}

        def frontier(self) -> int:
            return self.n

        def stop(self, timeout: float | None = None) -> None:
            pass

    fake = Fake()
    app.level = fake
    monkeypatch.setattr(app, "_opening_painted", lambda: False)
    app._ready_seen = 0
    assert app._ground_improving() is False, "nothing arrived yet"
    fake.n = 3
    assert app._ground_improving() is True, "ground arrived and was ignored"
    assert app._ground_improving() is False, "the same ground is not progress"
    fake.n = 4
    assert app._ground_improving() is True
