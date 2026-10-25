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
from app.app import READY_HOLD_CEIL, READY_HOLD_MAX, READY_TIME
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

        def painted_count(self) -> int:
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


class _WaitingGround:
    """A sector whose ground arrives on someone else's schedule."""

    seed = 1
    near_y = 1120.0        # the sector's opening row, as `Level` reports it

    class _Strip:
        count = 40
        slice_h = 560

        def __init__(self, level) -> None:
            self.level = level

        def frontier(self) -> int:
            return self.level.painted

        def painted_count(self) -> int:
            return self.level.painted

        def window_at(self, y):
            return 0, self.count

        def surface(self, i):
            return object() if i < self.level.painted else None

    def __init__(self, painted: int = 0, ready: bool = False) -> None:
        self.painted = painted
        self.ready = ready
        self.elapsed = 0.0
        self.built_flag = True
        self.strips = {"near": self._Strip(self)}

    def built(self) -> bool:
        return self.built_flag

    def ready_at(self, y: float) -> bool:
        return self.ready

    def ready_ahead(self, y: float, lead: float) -> bool:
        # the fake has no geometry; `ready` answers for the whole lead
        return self.ready

    def design_elapsed(self) -> float:
        return self.elapsed

    def page_slices(self, lead: float = 0.0):
        total = self.strips["near"].count * 2
        have = min(total, self.painted * 2)
        return total - have, total

    def ensure_page(self, lead: float = 0.0) -> bool:
        # The fake cannot paint: `ready` says whether the page is there, and this
        # reports it without inventing slices.
        return self.ready

    def design_estimate(self) -> float:
        return 10.0

    def stop(self, timeout: float | None = None) -> None:
        pass


def test_skipping_ready_cannot_launch_onto_missing_ground(app):
    """The hold existed and the player still got a black field - because pressing
    fire to skip the countdown called `_launch_craft` directly, and the gate was
    only on the timer path. So the gate moved to where both paths meet, and the
    message says what is happening while it waits.
    """
    import dataclasses

    app.settings = dataclasses.replace(app.settings, streamed_terrain=True)
    app.level = _WaitingGround(painted=0, ready=False)
    app.sm.to(State.READY)
    app._ready_timer = 0.0
    app._ready_wait = 0.0
    # New ground is pending - which is exactly when a wait is owed. A respawn of
    # ground already flown disarms it, and says so elsewhere.
    app._ground_wait = True

    app._on_confirm()                      # the skip
    assert app.sm.state == State.READY, "the skip walked past the ground check"
    assert app._msg == "LOADING", f"the wait was never named: {app._msg!r}"
    # Two phases, and the mid-point is where the handover happens: the design is
    # over, the painting has begun, and nothing has been painted yet - so half,
    # not zero. A bar that reads nought while half the work is done is a bar that
    # tells the player nothing about how much is left.
    assert app._load_status() == (0.5, "Painting the ground")

    # The first half belongs to the design and creeps while it runs, against the
    # last measured design of this sector on this machine - and it never claims to
    # be finished, because there is nothing inside that call to count.
    app.level.built_flag = False
    app.level.elapsed = 5.0                       # of an estimate of 10.0
    frac, label = app._load_status()
    assert label == "Designing the sector"
    # the whole first half is 0 -> 0.5, so halfway through the estimate is 0.25
    assert 0.20 < frac < 0.30, f"design at half its estimate read as {frac:.2f}"
    app.level.elapsed = 1.0
    assert app._load_fraction() < frac, "the first half did not track the design"
    app.level.built_flag = True

    # The second half is counted: slices that exist over slices the camera draws.
    mid = app._load_fraction()
    app.level.painted = 1
    assert app._load_fraction() > mid, "the bar did not move when ground arrived"
    app.level.painted = app.level.strips["near"].count
    assert app._load_fraction() == 1.0
    assert app._load_status()[1] == "Painting the ground"
    app.level.ready = True
    app._on_confirm()
    assert app.sm.state == State.PLAYING, "a refused launch never recovered"


def test_the_hold_gives_up_on_ground_that_arrived_and_then_stopped(app):
    """Dead painters must cost a late start, never a hung game.

    Two ceilings, and the difference between them is movement: while the frontier
    grows, the wait is worth having; once it stops growing - or the hard ceiling
    passes - the craft goes onto whatever ground exists, because a player stuck in
    READY forever is worse than one watching ground arrive.
    """
    import dataclasses

    app.settings = dataclasses.replace(app.settings, streamed_terrain=True)
    app.level = _WaitingGround(painted=1, ready=False)
    app._ready_seen = 0
    app._ready_wait = 0.0
    app._ground_wait = True
    assert app._ground_ready_to_launch() is False     # grace period: wait

    # the first sight of ground counts as progress, so a stall only becomes a
    # stall once progress has been seen and then failed to repeat
    app._ready_wait = 5.0
    app._ready_seen = 0
    assert app._ground_ready_to_launch() is False
    assert app._ground_ready_to_launch() is True, \
        "a stall held the player in READY forever"

    app.level = _WaitingGround(painted=2, ready=False)
    app._ready_seen = 1            # ...and now it has
    assert app._ground_ready_to_launch() is False, \
        "progress was mistaken for a stall"
    app._ready_wait = READY_HOLD_CEIL
    assert app._ground_ready_to_launch() is True, "the hard ceiling never let go"


def test_readiness_asks_about_every_slice_the_camera_draws():
    """The second of black *under the ship* was two functions disagreeing.

    `TerrainStrip.draw` blits the slice range [lo, hi); `missing_at` - what the
    launch gate asks - computed its own range and started one slice lower, so the
    strip across the bottom of the screen was drawn from a slice nothing had asked
    about. A sector could be, and was, called ready with that band empty.

    Both now read `window_at`, and this pins the whole window down: hide each slice
    of the range in turn and readiness has to name it. Any slice it fails to
    mention is a band of black somebody has just made legal again.
    """
    import pygame

    import config as C
    from level.strip import TerrainStrip
    from terrain.common import TILE2
    from terrain.design.site import plan_site
    from terrain.plan.geom import CELL, Geom

    plan = plan_site("countryside", 3, Geom(h=TILE2 * 2, cell=CELL, cyclic=False))
    st = TerrainStrip(plan, "near")
    for i in range(st.count):
        st.paint(i)
    assert all(st.surface(i) is not None for i in range(st.count))

    pygame.Rect(C.FIELD_LEFT, C.FIELD_TOP,
                       C.FIELD_RIGHT - C.FIELD_LEFT,
                       C.FIELD_BOTTOM - C.FIELD_TOP)
    for y in (float(st.view), 1.4 * st.view, 2.0 * st.view):
        lo, hi = st.window_at(y)
        assert lo < hi, f"the camera at {y} was given an empty slice window"
        for j in range(lo, hi):
            saved = st._surf[j]
            st._surf[j] = None
            try:
                got = st.missing_at(y)
                assert got == j, (
                    f"camera at row {y}: slice {j} is drawn but readiness said "
                    f"{got} - a bare band at the bottom of the screen")
            finally:
                st._surf[j] = saved
        assert st.missing_at(y) == -1


def _painters_alive(lvl) -> bool:
    return any(t.is_alive() for t in getattr(lvl, "_threads", ()))


def test_the_view_letting_go_of_the_ground_does_not_kill_it(app):
    """A view does not own a sector's ground, and used to kill it anyway.

    `Renderer.clear_terrain()` stopped the Level it was showing - and that call is
    how a respawn clears baked maps - so dying stopped the design and every painter
    of the sector being flown, threw away the slices already painted as far as the
    view was concerned, and left the game waiting seconds for a restarted crew to
    catch up with a camera that had not moved. Measured at 6.1 s of respawn wait.

    Ownership, stated once: App makes a Level, replaces it, and stops it - in
    `_start_game`, on a sector change, and in `shutdown`. The renderer detaches.
    """

    app._start_game()
    lvl = app.level
    assert lvl is not None, "starting a run did not start a streamed sector"
    assert _painters_alive(lvl), "the sector's painters were never running"

    app.renderer.clear_terrain()
    assert app.level is lvl, "App's ground vanished with the view's copy of it"
    assert app.renderer._level is None
    assert _painters_alive(lvl), "clearing baked ground stopped a flown sector"

    lvl.stop()
    assert not _painters_alive(lvl), "the owner's stop does not stop either"


def test_a_respawn_keeps_the_ground_and_every_painter_on_it(app, tiny_sectors):
    """Die mid-sector and the world you were flying over stays: same Level object,
    same camera row, painters still working, and the view takes the ground back
    rather than watching it being rebuilt."""
    app._start_game()
    lvl = app.level
    row = lvl.near_y
    app.renderer.clear_terrain()          # what the respawn path does first

    app._enter_ready()                     # ...then the sector is re-entered

    assert app.level is lvl, "a respawn built new ground under a still craft"
    assert lvl.near_y == row, "the camera was moved by dying"
    assert app.renderer._level is lvl, "the view never took the ground back"
    assert _painters_alive(lvl), "the respawn killed the painters of sector 1"


def test_the_painter_works_from_the_camera_outward():
    """Painting starts where the camera is, not at row 0 of the map.

    It used to start at slice 0 and walk down, so a sector's first seconds went on
    ground behind the craft - never to be seen - while the screen stayed empty.
    That is the opening ramp, and it is what made a respawn cost seconds even after
    the ground stopped being destroyed on death.

    Which slice a worker picks is a decision, so the decision is what is tested:
    painting itself is stubbed, because 36 slices of real terrain is a slow way to
    read an index.
    """
    from level.strip import TerrainStrip
    from terrain.design.site import plan_site
    from terrain.plan.geom import CELL, Geom

    plan = plan_site("countryside", 11, Geom(h=CELL * 300, cell=CELL,
                                             cyclic=False))
    st = TerrainStrip(plan, "near")
    chosen: list[int] = []

    def fake_paint(i: int, stop: object = None):
        # stands in for a painted slice: records the choice and fills the slot, so
        # the next call moves on to the next slice like the real thing would
        chosen.append(i)
        st._surf[i] = object()
        return st._surf[i]

    st.paint = fake_paint                                  # type: ignore[assignment]

    y = 6.5 * st.slice_h + st.view
    st.focus(y)
    lo, hi = st.window_at(y)
    assert hi > lo and lo >= 2, "this test needs a camera well down the strip"

    assert st.advance() is True
    assert chosen == [lo], (
        f"camera at slices {lo}..{hi}: the painter chose {chosen[0]} - ground "
        "behind the craft is being drawn before ground ahead of it")

    # Forward from the camera, then wrapped around to back-fill what was flown
    # over, and every slice of the strip is reached exactly once.
    for _ in range(st.count - 1):
        st.advance()
    assert sorted(chosen) == list(range(st.count)), (
        "the painter does not visit every slice, or visits one twice")
    ahead = list(range(lo, st.count))
    assert chosen[:len(ahead)] == ahead, (
        "painting did not run forward from the camera to the end of the strip "
        "before wrapping to back-fill")
    assert chosen[len(ahead):] == list(range(0, lo)), (
        "the back-fill is not in order behind the camera either")


def test_nothing_is_lost_between_death_and_respawn(app, tiny_sectors):
    """A death may cost a life, a transition and a moment of tension. It may not
    cost one painted slice, nor the painters' idea of where the camera is.

    The painted set is compared directly rather than by count: totals would pass
    while one strip lost a slice and another invented one.
    """
    import time

    app._start_game()
    lvl = app.level
    deadline = time.time() + 30.0
    while time.time() < deadline and not lvl.built():
        time.sleep(0.05)
    assert lvl.built(), "the fixture's sector never got designed"
    lvl.near_y += 4 * 560          # fly a bit, so there is something to lose
    near = lvl.strips["near"]
    lvl.update(0.0)                # the painters are told where the camera is
    before = {i for i in range(near.count) if near.surface(i) is not None}
    row, hint = lvl.near_y, near._hint

    app._enter_ready()              # the respawn path, end to end

    after = {i for i in range(near.count) if near.surface(i) is not None}
    assert before <= after, (
        f"a respawn discarded {len(before - after)} painted slice(s): "
        f"{sorted(before - after)[:4]}")
    assert lvl.near_y == row, "the camera moved because the craft died"
    assert near._hint == hint, (
        "the painter forgot where the camera was and will paint the wrong ground")


def test_dying_is_a_pause_not_a_level_reload(app, tiny_sectors, monkeypatch):
    """Dying is allowed to cost a life. It is not allowed to touch the ground.

    The sector being flown was already under the craft, so re-entering it used to
    clear the terrain, detach the ground from the view, and then wait for ground
    that already existed - six seconds of nothing, and before that, actually
    stopping the painters. Pausing has never done any of this, and death is the
    same situation with worse consequences.

    So the sector's ground is identified, and re-entering the sector it names does
    nothing at all to it: no clear, no re-attach, no wait. The launch gate is
    disarmed for the same reason, and re-armed only when new ground is attached -
    which the second test checks, because a fix that never waits again has simply
    removed the fix.
    """
    app._start_game()
    lvl = app.level
    app.renderer.clear_terrain()          # the state a respawn used to start from
    app.renderer.set_level(lvl)
    cleared: list[str] = []
    monkeypatch.setattr(app.renderer, "clear_terrain",
                        lambda: cleared.append("cleared"))

    app._enter_ready()                     # the death path

    assert cleared == [], "dying told the view to forget the ground it is on"
    assert app.renderer._level is lvl, "the ground was detached and re-attached"
    assert app._ground_wait is False, "the craft is waiting for ground it flew on"
    assert app._ground_ready_to_launch() is True
    app._launch_craft()
    assert app.sm.state == State.PLAYING


def test_a_new_sector_does_arm_the_wait_again(app, tiny_sectors):
    """The wait still exists where ground really is new."""
    import config as C
    from level import Level

    app._start_game()
    # New ground *was* attached for sector 1, so the first launch does wait for it -
    # then the launch clears the armed flag, and it is that disarmed state the
    # sector change below is measured against.
    assert app._ground_wait is True, "sector 1's ground was never armed to be waited for"
    assert _launch(app), "the first sector's wait never opened"
    assert app._ground_wait is False, "launching did not discharge the wait"
    nxt = Level(C.LEVELS[1], seed=2)
    nxt.start()
    app.next_level = nxt
    app.game.advance_level()
    app.sm.reset(State.READY)      # the sector change arrives via a transition
    app._enter_ready(seamless=True)
    assert app.level is nxt
    assert app._ground_wait is True, (
        "new ground was attached and the launch was not told to wait for it")
    nxt.stop()


def test_the_launch_wants_ground_the_craft_has_not_reached_yet(app,
                                                               tiny_sectors):
    """The black second after the loading bar goes away.

    The gate used to ask only about what was on screen at the instant of launch.
    The craft starts moving the same frame, and the ground it moves into was never
    promised - so the sector opened covered and then immediately showed the field's
    backdrop, which is worse timing than waiting: it looks like the loading lied.

    One screen of lead is the ask, and it costs a fraction of a second of READY
    rather than a second of the player's first view.
    """
    import time

    from terrain.common import TILE2

    app._start_game()
    lvl = app.level
    deadline = time.time() + 30.0
    while time.time() < deadline and not lvl.built():
        time.sleep(0.05)
    assert lvl.built(), "the sector was never designed"
    deadline = time.time() + 10.0
    while time.time() < deadline and not lvl.strips:
        time.sleep(0.05)
    assert lvl.strips, "the strips were never built"
    near = lvl.strips["near"]
    for strip in lvl.strips.values():
        for i in range(strip.count):
            strip._surf[i] = None

    # The camera's own window complete, and nothing beyond it: covered at launch,
    # black a heartbeat later. That is exactly the state that used to pass.
    lo, hi = near.window_at(lvl.near_y)
    for strip in lvl.strips.values():
        for i in range(lo, min(hi, strip.count)):
            strip._surf[i] = object()
    assert lvl.ready_at(lvl.near_y / 2.0), "the window itself should read covered"
    assert not lvl.ready_ahead(lvl.near_y, TILE2), (
        "a covered screen with nothing ahead must not be launchable")
    assert app._opening_painted() is False, (
        "the gate opened on ground the craft had not reached yet - the black "
        "second the player sees next")

    for strip in lvl.strips.values():
        for i in range(strip.count):
            strip._surf[i] = object()
    assert lvl.ready_ahead(lvl.near_y, TILE2)
    assert app._opening_painted() is True


def test_the_launch_paints_the_page_it_promised(app, tiny_sectors):
    """The ground must be there when play starts, not "on its way".

    Every previous version of this gate was a question - *is* the ground ready? -
    and each time the sector opened with the field's backdrop showing for a second,
    because a question cannot put ground down. So the launch asks for the page and
    paints it: one slice per READY frame, which keeps the loading screen alive and
    the bar moving, and means the pause is spent making the ground rather than
    watching for it.

    The page includes a screen of lead, and the bar counts exactly that range, so
    bar and gate measure one thing rather than two that happen to agree.
    """
    import time

    app._start_game()
    lvl = app.level
    deadline = time.time() + 30.0
    while time.time() < deadline and not (lvl.built() and lvl.strips):
        time.sleep(0.05)
    assert lvl.strips, "the sector never got its strips"

    for strip in lvl.strips.values():
        for i in range(strip.count):
            strip._surf[i] = None           # nothing exists; the launch must make it

    lead = 1112.0                            # one screen, as the gate uses it
    missing, total = lvl.page_slices(lead)
    assert missing > 0, "this test needs an unpainted page"
    # The page is wider than the visible window: ground the craft flies *into*.
    window = lvl.strips["near"].count
    assert total > 2, f"the page should include lead, not just the window ({total})"
    assert window >= 0

    progressed = []
    for _ in range(400):
        if lvl.ensure_page(lead):
            break
        progressed.append(lvl.page_slices(lead)[0])
    assert progressed, "the launch painted nothing at all"
    assert progressed[0] >= progressed[-1], "painting the page made it less painted"
    assert progressed[-1] == 0, f"the page never completed: {progressed[-1]} missing"
    assert app._opening_painted() is True
