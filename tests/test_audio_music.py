"""Music pipeline regressions (no mixer needed; rendering is stubbed).

Bug being locked down: the worker used to publish the whole menu playlist
(19 tracks, ~13 s) before touching level tracks, so starting the game right
after launch left the level pool empty for ~45 s — the retry loop had
nothing to play and gameplay ran silent until returning to the menu.
"""
import pytest

import config as C
from audio import AudioManager


@pytest.fixture()
def mgr(monkeypatch):
    m = AudioManager(C.Settings())
    m._ntracks = 5
    monkeypatch.setattr("music.MENU_THEMES",
                        tuple({"n": i} for i in range(3)))
    monkeypatch.setattr("music.THEMES",
                        tuple({"n": 100 + i} for i in range(5)))
    return m


def test_plan_leads_with_one_track_from_each_pool(mgr):
    import music
    plan = mgr._music_build_plan(music)
    assert [p for p, _, _ in plan[:2]] == ["menu", "level"]
    # both pools must be fully covered afterwards
    pools = [p for p, _, _ in plan]
    assert pools.count("menu") == len(music.MENU_THEMES)
    assert pools.count("level") == mgr._ntracks


def test_plan_covers_every_track(mgr):
    import music
    plan = mgr._music_build_plan(music)
    idents = {ident for p, ident, _ in plan if p == "level"}
    assert len(idents) == mgr._ntracks          # no dupes/losses
    menus = [ident for p, ident, _ in plan if p == "menu"]
    assert sorted(menus) == list(range(len(music.MENU_THEMES)))


def test_worker_publishes_each_track_incrementally(mgr, monkeypatch):
    # snapshot pools during each render call to observe incremental publish
    snapshots = []

    def watch_render(theme, rate):
        snapshots.append((len(mgr._menu_keys), len(mgr._level_keys)))
        return b"x"

    monkeypatch.setattr("music.render_track", watch_render)
    mgr._build_music_bytes()
    assert (len(mgr._menu_keys), len(mgr._level_keys)) == (3, 5)
    # snapshots fire during render, i.e. before that track's own publish:
    # step1 menu-0 renders (nothing published yet), step2 level-0 renders
    # (menu pool already live), step3 renders with both pools live.
    assert snapshots[:3] == [(0, 0), (1, 0), (1, 1)]


def test_one_broken_track_does_not_kill_the_playlist(mgr, monkeypatch):
    calls = {"n": 0}

    def flaky(theme, rate):
        calls["n"] += 1
        if calls["n"] == 2:          # the first level track
            raise RuntimeError("synth boom")
        return b"x"

    monkeypatch.setattr("music.render_track", flaky)
    mgr._build_music_bytes()
    assert len(mgr._menu_keys) == 3
    assert len(mgr._level_keys) == 4          # only the flaky one is missing
