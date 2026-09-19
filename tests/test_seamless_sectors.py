"""Seamless sector transitions: prefetch, handoff, and the model's load hooks.

A sector change used to be a load: the ground vanished, a new map was built on
the render thread, and the frame dropped. Now the incoming sector is built ahead
of time (:mod:`prefetch`) and the change is *drawn* (:class:`SectorHandoff`).
These tests cover the three pieces and the level-length budget they serve.
"""

import os
import random
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

import config as C
import terrain
from app import App
from game import SIG_LIFE_LOST, Game
from prefetch import Prefetch, sector_key, sector_phases
from state import State
from terrain.handoff import HANDOFF_SECONDS, SectorHandoff


class FakeMap:
    """Stand-in for a built Terrain map: records scrolling, draws nothing."""

    def __init__(self, theme, seed) -> None:
        self.theme = theme
        self.seed = seed
        self.ups = 0

    def update(self, _dt, _scale) -> None:
        self.ups += 1

    def draw(self, _canvas, clip=None) -> None:
        self.clip = clip


class FakeTrack:
    def __init__(self, name):
        self.name = name
        self.ups = 0
        self.draws = 0

    def update(self, _dt, _scale) -> None:
        self.ups += 1

    def draw(self, _canvas) -> None:
        self.draws += 1


def _wait_idle(pf: Prefetch, timeout: float = 20.0) -> None:
    end = time.monotonic() + timeout
    while pf.pending() and time.monotonic() < end:
        time.sleep(0.005)
    assert pf.pending() == 0, "prefetch worker stalled"


# ------------------------------------------------------- track construction
def test_track_accepts_prebuilt_maps():
    phases = C.LEVELS[0].phases
    maps = (FakeMap("countryside", 1), FakeMap("farmland", 1))
    track = terrain.TerrainTrack(phases, 1, maps=maps)
    assert track.segs[0][0] is maps[0]
    assert track.segs[1][0] is maps[1]


def test_track_rejects_maps_for_another_schedule():
    phases = C.LEVELS[0].phases
    with pytest.raises(ValueError):
        terrain.TerrainTrack(phases, 1, maps=(FakeMap("countryside", 1),))


def test_track_plan_span_sets_the_zone_boundary():
    phases = C.LEVELS[0].phases            # 0.55 / 0.45
    track = terrain.TerrainTrack(phases, 1, plan=100.0)
    assert track.segs[0][2] == pytest.approx(55.0)
    assert track.segs[1][1] == pytest.approx(55.0)


def test_track_plan_defaults_to_the_shared_plan():
    track = terrain.TerrainTrack(C.LEVELS[0].phases, 1)
    assert track.plan == terrain.PHASE_PLAN


def test_track_rejects_a_non_positive_plan():
    with pytest.raises(ValueError):
        terrain.TerrainTrack(C.LEVELS[0].phases, 1, plan=0.0)


def test_plan_span_follows_the_sector_wave_length():
    """Long sectors must stretch the zone plan, or the environment stops
    changing halfway through the level."""
    for level in C.LEVELS:
        assert terrain.plan_span(level) == level.wave_seconds
    assert terrain.plan_span(object()) == terrain.PHASE_PLAN


# ------------------------------------------------------------------ prefetch
def test_prefetch_hands_over_a_ready_track():
    built = []
    pf = Prefetch(enabled=True,
                  map_factory=lambda t, s: built.append((t, s)) or FakeMap(t, s))
    level = C.LEVELS[2]
    pf.request_sector(level, 3)
    assert pf.pending() == 1
    _wait_idle(pf)
    track = pf.sector_track(level, 3)
    assert track is not None
    assert built == [(p.theme, 3) for p in level.phases]
    assert len(track.segs) == len(level.phases)


def test_prefetch_take_is_ownership_not_a_copy():
    """Maps carry scroll state, so handing one to a track must remove it from
    the cache: two live tracks must never drag the same parallax offsets."""
    pf = Prefetch(map_factory=FakeMap)
    level = C.LEVELS[1]
    pf.request_sector(level, 2)
    _wait_idle(pf)
    first = pf.sector_track(level, 2)
    assert first is not None
    assert pf.sector_track(level, 2) is None, "maps were handed out twice"
    assert pf.pending() == 1, "the take should re-queue the sector for a retry"


def test_prefetch_is_idempotent_while_queued():
    pf = Prefetch(map_factory=FakeMap)
    level, seed = C.LEVELS[0], 1
    pf.request_sector(level, seed)
    pf.request_sector(level, seed)
    pf.request_sector(level, seed)
    assert pf.pending() == 1


def test_prefetch_disabled_is_inert():
    pf = Prefetch(enabled=False, map_factory=FakeMap)
    pf.request_sector(C.LEVELS[0], 1)
    assert pf.pending() == 0
    assert pf.sector_track(C.LEVELS[0], 1) is None
    assert pf.pending() == 0


def test_prefetch_survives_a_broken_map():
    """A bad sector must not kill the worker: the consumer then loads the sector
    the slow way, and later sectors still get prefetched."""
    def flaky(theme, seed):
        if seed == 666:
            raise RuntimeError("unreadable art")
        return FakeMap(theme, seed)

    pf = Prefetch(map_factory=flaky)
    pf.request_sector(C.LEVELS[0], 666)
    _wait_idle(pf)
    assert pf.sector_track(C.LEVELS[0], 666) is None
    pf.request_sector(C.LEVELS[1], 1)
    _wait_idle(pf)
    assert pf.sector_track(C.LEVELS[1], 1) is not None


def test_prefetch_cache_is_bounded():
    pf = Prefetch(map_factory=FakeMap)
    for i, level in enumerate(C.LEVELS):
        pf.request_sector(level, i + 1)
    _wait_idle(pf)
    assert len(pf._maps) <= pf.MAX_SECTORS


def test_prefetch_warms_sprite_sheets():
    seen = []

    class FakeBank:
        def sheet(self, name):
            seen.append(name)

    pf = Prefetch(bank=FakeBank(), map_factory=FakeMap)
    pf.request_art("e_boss5", "e_boss6", "")
    _wait_idle(pf)
    assert sorted(seen) == ["e_boss5", "e_boss6"]


def test_sector_key_separates_zones_and_seeds():
    level = C.LEVELS[3]
    phases = sector_phases(level)
    assert sector_key(phases, 4) == sector_key(phases, 4)
    assert sector_key(phases, 4) != sector_key(phases, 5)
    assert sector_key(phases, 4) != sector_key(sector_phases(C.LEVELS[5]), 4)


def test_sector_phases_fall_back_like_the_renderer_does():
    class ThemeOnly:
        theme = C.StageTheme.OCEAN

    phases = sector_phases(ThemeOnly())
    assert len(phases) == 1 and phases[0].theme is C.StageTheme.OCEAN


# ------------------------------------------------------------------ handoff
def test_handoff_sweeps_from_field_top_to_bottom():
    hand = SectorHandoff(FakeTrack("old"), FakeTrack("new"), dur=2.0)
    assert hand.edge == C.HUD_H
    hand.update(1.0, 1.0)
    assert hand.edge == C.HUD_H + terrain.TILE_H // 2
    hand.update(1.0, 1.0)
    assert hand.done
    assert hand.edge == C.HUD_H + terrain.TILE_H


def test_handoff_scrolls_both_sectors():
    old, new = FakeTrack("old"), FakeTrack("new")
    hand = SectorHandoff(old, new, dur=4.0)
    for _ in range(10):
        hand.update(0.1, 1.0)
    assert old.ups == 10 and new.ups == 10


def test_handoff_freezes_with_the_game_not_with_itself():
    hand = SectorHandoff(FakeTrack("old"), FakeTrack("new"), dur=1.0)
    for _ in range(20):
        hand.update(0.1, 0.0)           # paused
    assert hand.progress == 0.0


def test_handoff_requires_an_incoming_track():
    with pytest.raises(ValueError):
        SectorHandoff(FakeTrack("old"), None)
    with pytest.raises(ValueError):
        SectorHandoff(FakeTrack("old"), FakeTrack("new"), dur=0.0)


def test_handoff_clips_each_sector_to_its_side_of_the_edge():
    old, new = FakeMap("city", 1), FakeMap("ocean", 2)
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    hand = SectorHandoff(old, new, dur=4.0)
    hand.update(1.0, 1.0)                        # edge at mid field
    hand.draw(canvas)
    assert new.clip is not None and old.clip is not None
    assert new.clip.bottom > old.clip.top - 1
    assert new.clip.top == C.HUD_H
    assert old.clip.bottom == C.HUD_H + terrain.TILE_H
    assert old.clip.top == hand.edge


def test_handoff_draws_over_the_incoming_sector_only_when_alone():
    new = FakeMap("ocean", 2)
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    SectorHandoff(None, new).draw(canvas)        # must not raise
    assert new.clip is None                      # whole field, nothing to hide


def test_handoff_default_duration_covers_the_banner():
    """The sweep has to outlast the SECTOR CLEAR banner, or the player watches a
    finished handoff instead of the transition."""
    assert HANDOFF_SECONDS >= 1.2


# --------------------------------------------------------- renderer wiring
def _renderer():
    import ui
    return ui.Renderer(pygame.Surface((C.LOGICAL_W, C.LOGICAL_H)), C.Settings())


def test_handoff_needs_something_to_hand_off_from():
    rend = _renderer()
    assert rend.handoff_terrain(C.LEVELS[1], 2) is False
    rend.set_terrain(C.LEVELS[0], 1)
    assert rend.handoff_terrain(C.LEVELS[1], 2) is True
    assert rend.terrain_handoff_active()


def test_renderer_promotes_the_incoming_sector_when_the_sweep_ends():
    rend = _renderer()
    rend.set_terrain(C.LEVELS[0], 1)
    outgoing = rend._terrain
    rend.handoff_terrain(C.LEVELS[1], 2, dur=1.0)
    assert rend._terrain is None                  # handoff owns both meanwhile
    for _ in range(30):
        rend.update_background(0.1, 1.0)
        if not rend.terrain_handoff_active():
            break
    assert not rend.terrain_handoff_active()
    assert rend._terrain is not outgoing
    rend.draw_field(_dummy_game())                # must not raise
    rend.clear_terrain()
    assert rend._terrain is None


def test_renderer_uses_a_prefetched_track_instead_of_building_one():
    rend = _renderer()
    pf = Prefetch(map_factory=FakeMap)
    rend.set_prefetch(pf)
    pf.request_sector(C.LEVELS[4], 5)
    _wait_idle(pf)
    rend.set_terrain(C.LEVELS[4], 5)
    maps = [seg[0] for seg in rend._terrain.segs]
    assert all(isinstance(m, FakeMap) for m in maps), "prefetch was ignored"
    assert rend._terrain.plan == C.LEVELS[4].wave_seconds


def test_renderer_handoff_consumes_the_prefetched_maps():
    rend = _renderer()
    pf = Prefetch(map_factory=FakeMap)
    rend.set_prefetch(pf)
    rend.set_terrain(C.LEVELS[0], 1)
    pf.request_sector(C.LEVELS[1], 2)
    _wait_idle(pf)
    assert rend.handoff_terrain(C.LEVELS[1], 2) is True
    key = sector_key(sector_phases(C.LEVELS[1]), 2)
    assert key not in pf._maps, "a live track and the cache share one map set"


def _dummy_game():
    """A game with a served craft, enough for the renderer to draw a frame."""
    return Game(rng=random.Random(1))


# --------------------------------------------------------- model load hooks
def _boss_on_screen(seed: int = 7) -> Game:
    """A game whose boss has just been put on screen.

    The wave is advanced by moving the model's own clock rather than by
    simulating a minute of a ship that nobody is flying: the boss fight is what
    is being observed, not whether a stationary craft survives its own sector.
    """
    g = Game(rng=random.Random(seed))
    g.new_game()
    g._wave_timer = C.LEVELS[g.level_index].wave_seconds
    g.update(C.SIM_DT)
    assert g.boss_alive()
    return g


def test_boss_sheet_is_addressable_by_sector():
    g = Game(rng=random.Random(1))
    g.new_game()
    assert g.boss_sheet() == C.LEVELS[0].boss
    assert g.boss_sheet(4) == C.LEVELS[4].boss
    assert g.boss_sheet(999) == C.LEVELS[C.FINAL_LEVEL_INDEX].boss


def test_wave_progress_runs_zero_to_one():
    g = Game(rng=random.Random(2))
    g.new_game()
    assert g.wave_progress() == 0.0
    prev = 0.0
    for _ in range(60):
        g.update(C.SIM_DT)
        cur = g.wave_progress()
        assert cur >= prev, "wave progress went backwards"
        prev = cur
    assert 0.0 < prev < 1.0
    g._wave_timer = C.LEVELS[0].wave_seconds
    g.update(C.SIM_DT)
    assert g.boss_alive() and g.wave_progress() == 1.0


def test_boss_hp_fraction_tracks_the_fight():
    g = _boss_on_screen()
    boss = next(e for e in g.enemies if e.alive and e.kind is C.EnemyKind.BOSS)
    assert g.boss_hp_fraction() == pytest.approx(1.0)
    boss.hp = boss.max_hp // 2
    assert 0.49 <= g.boss_hp_fraction() <= 0.51
    boss.hp = 0
    boss.alive = False
    assert g.boss_hp_fraction() is None


# ------------------------------------------------------------ level budget
def test_sectors_are_half_again_as_long_as_they_were():
    """Every sector's wave is 1.5x the original 34..50 s ladder."""
    original = [34.0, 36.0, 38.0, 40.0, 42.0, 44.0, 46.0, 48.0, 50.0]
    got = [lv.wave_seconds for lv in C.LEVELS]
    assert got == [pytest.approx(w * 1.5) for w in original]
    assert sum(got) == pytest.approx(sum(original) * 1.5)


def test_wave_length_still_escalates_sector_by_sector():
    waves = [lv.wave_seconds for lv in C.LEVELS]
    assert waves == sorted(waves)
    assert len(set(waves)) == len(waves)


# ----------------------------------------------------- the App wires it up
@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "TEST_DATA_DIR", str(tmp_path), raising=False)
    a = App()
    a.init_display()
    a.sm.to(State.TITLE)
    yield a
    a.shutdown()


def test_app_builds_a_prefetcher_with_the_renderer_bank(app):
    assert app.prefetch is not None
    assert app.renderer._prefetch is app.prefetch


def test_app_queues_the_next_sector_as_soon_as_this_one_starts(app):
    app._start_game()
    assert app.prefetch.pending() >= 1, "nothing was queued at sector start"
    _wait_idle(app.prefetch)
    assert app.prefetch.built >= 1
    assert app.renderer.handoff_terrain(C.LEVELS[1], 2) is True
    maps = [seg[0] for seg in app.renderer._handoff.new.segs]
    assert all(isinstance(m, terrain.Terrain) for m in maps)


def test_seamless_ready_reveals_the_next_sector(app):
    app._start_game()
    original = app.renderer._terrain
    app._enter_ready(seamless=True)
    assert app.renderer.terrain_handoff_active()
    assert app.renderer._terrain is None
    assert app.renderer._handoff.old is original


def test_seamless_ready_falls_back_when_there_is_no_ground_yet(app):
    app.game.new_game()
    app.renderer.clear_terrain()
    app._enter_ready(seamless=True)
    assert not app.renderer.terrain_handoff_active()
    assert app.renderer._terrain is not None


def test_sector_change_after_the_banner_is_seamless(app):
    app._start_game()
    app.sm.to(State.PLAYING)              # a sector ends from live play
    app._begin_transition("SECTOR CLEAR", "", 0.01, "next_level")
    app._update(0.02)                     # banner expires -> advance
    assert app.game.level_index == 1
    assert app.renderer.terrain_handoff_active()


def test_midwave_and_half_boss_checkpoints_queue_work(app):
    app._start_game()
    app._warmed_wave_sector = -1
    app._warmed_next_sector = -1
    g = app.game
    g._wave_timer = C.LEVELS[0].wave_seconds * 0.5
    app._watch_load_ahead()
    assert app._warmed_wave_sector == 0
    g._wave_timer = 0.0
    g._boss_spawned = True
    boss = next((e for e in g.enemies
                 if e.alive and e.kind is C.EnemyKind.BOSS), None)
    if boss is None:
        g._spawn_boss([])
        boss = next(e for e in g.enemies if e.kind is C.EnemyKind.BOSS)
    boss.hp = boss.max_hp // 2
    app._watch_load_ahead()
    assert app._warmed_next_sector == 0


def test_longer_waves_mean_a_boss_arrives_later():
    g = Game(rng=random.Random(4))
    g.new_game()
    spec = C.LEVELS[0]
    g._wave_timer = spec.wave_seconds / 1.5 - 0.01   # where the boss used to land
    g.update(C.SIM_DT)
    assert not g.boss_alive(), "boss arrived at the old, shorter wave length"
    g._wave_timer = spec.wave_seconds
    g.update(C.SIM_DT)
    assert g.boss_alive()


# ------------------------------------------------- respawn keeps its scenery
# Dying re-serves the craft inside the sector it already flew over. Re-loading
# that sector's ground there scrolled it back to the opening zone, so the tiles
# visibly changed under a ship the camera never moved.

def test_ensure_terrain_keeps_the_ground_of_the_same_sector():
    rend = _renderer()
    rend.set_terrain(C.LEVELS[0], 1)
    track = rend._terrain
    track.update(3.0, 1.0)
    assert rend.ensure_terrain(C.LEVELS[0], 1) is True
    assert rend._terrain is track, "the sector was rebuilt under the player"
    assert rend._terrain.t == pytest.approx(3.0)


def test_ensure_terrain_installs_what_is_not_on_screen():
    rend = _renderer()
    assert rend.ensure_terrain(C.LEVELS[0], 1) is False   # nothing loaded yet
    first = rend._terrain
    assert rend.ensure_terrain(C.LEVELS[0], 1) is True
    assert rend.ensure_terrain(C.LEVELS[1], 2) is False   # a different sector
    assert rend._terrain is not first


def test_ensure_terrain_leaves_an_incoming_sweep_alone():
    rend = _renderer()
    rend.set_terrain(C.LEVELS[0], 1)
    rend.handoff_terrain(C.LEVELS[1], 2)
    assert rend.ensure_terrain(C.LEVELS[1], 2) is True
    assert rend.terrain_handoff_active(), "a respawn cancelled the reveal"


def test_dying_does_not_change_the_ground(app):
    app._start_game()
    app.game.lives = 99                 # one death, not a game over
    app.sm.to(State.PLAYING)
    track = app.renderer._terrain
    for _ in range(30):
        app._update(1.0 / 120.0)
    scrolled = track.t
    assert scrolled > 0.0, "the world never scrolled to begin with"

    app._on_signal({"type": SIG_LIFE_LOST})
    for _ in range(180):                # SHIP DOWN banner, then READY
        app._update(1.0 / 120.0)

    assert app.renderer._terrain is track
    assert app.renderer._terrain.t > scrolled, "the ground wound back"


def test_a_new_run_gets_its_own_ground(app):
    app._start_game()
    first = app.renderer._terrain
    first.update(20.0, 1.0)
    app._start_game()                   # a restart is a new world, not a resume
    assert app.renderer._terrain is not first
    assert app.renderer._terrain.t == pytest.approx(0.0)
