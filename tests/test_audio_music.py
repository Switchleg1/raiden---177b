"""Music pipeline regressions (no mixer needed; rendering is stubbed).

Bug being locked down: the worker used to publish the whole menu playlist
(19 tracks, ~13 s) before touching level tracks, so starting the game right
after launch left the level pool empty for ~45 s — the retry loop had nothing
to play and gameplay ran silent until returning to the menu.

Second bug of the same family: a sector's cue used to be picked from one shared
pool, so the sector you were flying over had no bearing on what played. Cues are
now grouped per sector (`music_content.LEVEL_CUES`), which makes *which cue is
ready for which sector* the thing the pipeline has to get right.
"""
import pytest

import config as C
from audio import AudioManager


@pytest.fixture()
def mgr(monkeypatch):
    """A manager with small synthetic tables (no mixer, no rendering)."""
    m = AudioManager(C.Settings())
    monkeypatch.setattr("music.MENU_THEMES",
                        tuple({"name": f"m{i}"} for i in range(3)))
    monkeypatch.setattr("music.THEMES",
                        tuple({"name": f"c{i}"} for i in range(5)))
    monkeypatch.setattr("music.LEVEL_CUES",
                        {0: ("c0", "c1", "c2"), 1: ("c2", "c3"), 2: ("c4",)},
                        raising=False)
    return m


def _level_names(plan) -> list[str]:
    return [key[len("level"):] for pool, key, _ in plan if pool == "level"]


# ------------------------------------------------------------------ planning
def test_plan_leads_with_one_track_from_each_pool(mgr):
    import music
    plan = mgr._music_build_plan(music)
    assert [p for p, _, _ in plan[:3]] == ["menu", "level", "boss"]
    pools = [p for p, _, _ in plan]
    assert pools.count("menu") == len(music.MENU_THEMES)
    assert pools.count("boss") == len(music.BOSS_THEMES)


def test_plan_covers_every_cue_exactly_once(mgr):
    import music
    names = _level_names(mgr._music_build_plan(music))
    assert len(names) == len(set(names)), "a cue renders twice"
    assert set(names) == {t["name"] for t in music.THEMES}


def test_plan_gives_every_sector_its_own_cue_early(mgr):
    """Round-robin, not sector-by-sector.

    Sector 9 must not wait behind sector 1's whole pool: the first step for
    every sector comes before any sector gets a second cue.
    """
    import music
    pools = music.LEVEL_CUES
    names = _level_names(mgr._music_build_plan(music))[:len(pools)]
    assert set(names) == {pools[i][0] for i in pools}


def test_plan_survives_a_cue_name_that_does_not_resolve(mgr, monkeypatch):
    """A typo in the table costs one cue, never the soundtrack."""
    import music
    monkeypatch.setattr("music.LEVEL_CUES",
                        {0: ("c0", "no such cue", "c1")}, raising=False)
    names = _level_names(mgr._music_build_plan(music))
    assert "no such cue" not in names
    assert set(names) >= {"c0", "c1"}


# ---------------------------------------------------------------- publishing
def test_worker_publishes_each_track_incrementally(mgr, monkeypatch):
    snapshots = []

    def watch_render(theme, rate):
        snapshots.append((len(mgr._menu_keys), len(mgr._level_keys)))
        return b"x"

    monkeypatch.setattr("music.render_track", watch_render)
    mgr._build_music_bytes()
    assert (len(mgr._menu_keys), len(mgr._level_keys)) == (3, 5)
    # snapshots fire during render, i.e. before that track's own publish:
    # step1 renders a menu cue (nothing published), step2 renders a level cue
    # (menu pool already live), step3 renders with both pools live.
    assert snapshots[:3] == [(0, 0), (1, 0), (1, 1)]


def test_level_buffers_are_keyed_by_cue_name(mgr, monkeypatch):
    """Keys carry names, because a sector's pool is looked up by name."""
    monkeypatch.setattr("music.render_track", lambda theme, rate: b"x")
    mgr._build_music_bytes()
    assert "levelc0" in mgr._level_keys
    assert "levelm0" not in mgr._level_keys


def test_one_broken_track_does_not_kill_the_playlist(mgr, monkeypatch):
    calls = {"n": 0}

    def flaky(theme, rate):
        calls["n"] += 1
        if calls["n"] == 2:          # the first level cue
            raise RuntimeError("synth boom")
        return b"x"

    monkeypatch.setattr("music.render_track", flaky)
    mgr._build_music_bytes()
    assert len(mgr._menu_keys) == 3
    assert len(mgr._level_keys) == 4          # only the flaky one is missing


# ------------------------------------------------------------- sector choice
def test_a_level_pool_may_draw_a_cue_written_for_the_menu(mgr, monkeypatch):
    """Cross-table pools are a feature: the planner must render the cue under
    its own sector, not skip it because it was authored for the attract loop."""
    import music
    monkeypatch.setattr("music.LEVEL_CUES", {0: ("c0", "m1")})
    assert "m1" in _level_names(mgr._music_build_plan(music)), "cue dropped"
    monkeypatch.setattr("music.render_track", lambda theme, rate: b"x")
    mgr._music_stop = False
    mgr._build_music_bytes()
    assert "levelm1" in mgr._level_keys


@pytest.fixture()
def live(mgr, monkeypatch):
    """A manager that behaves like a running mixer, recording what it played."""
    played: list[str] = []

    def fake_play(key, loops=0):
        played.append(key)
        mgr._music_key = key

    monkeypatch.setattr(mgr, "_play_music", fake_play)
    mgr.available = True
    mgr._music_ch = object()
    return mgr, played


def test_play_level_music_only_picks_this_sector_s_cues(live):
    mgr, played = live
    mgr._level_keys = ["levelc0", "levelc1", "levelc4"]
    for _ in range(12):
        mgr.play_level_music(0)                # sector 0 owns c0, c1, c2
    assert set(played) == {"levelc0", "levelc1"}


def test_play_level_music_never_repeats_itself(live):
    mgr, played = live
    mgr._level_keys = ["levelc0", "levelc1", "levelc2"]
    for _ in range(8):
        mgr.play_level_music(0)
        mgr._music_key = None                  # next cue, not still this one
    pairs = list(zip(played, played[1:], strict=False))
    assert pairs and all(a != b for a, b in pairs), "same cue back to back"


def test_play_level_music_waits_for_its_sector_then_falls_back(live):
    """Nothing for this sector yet: any ready cue beats silence."""
    mgr, played = live
    mgr._level_keys = ["levelc4"]              # c4 belongs to sector 2
    mgr.play_level_music(1)                    # sector 1 wants c2/c3
    assert played == ["levelc4"]


def test_play_level_music_is_silent_when_nothing_is_ready(live):
    mgr, played = live
    mgr._level_keys = []
    mgr.play_level_music(0)
    assert played == []
