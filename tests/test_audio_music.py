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
from audio import MIXER_RATE, MUSIC_CHANNEL, AudioManager


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


class FakeSound:
    """Stands in for ``pygame.mixer.Sound``: the tests care who builds it, not
    what SDL does with it."""

    def __init__(self, buf: bytes) -> None:
        self.buf = buf


@pytest.fixture()
def no_converter(mgr, monkeypatch):
    """Pin the worker to the retry path: conversion unavailable, so it publishes
    PCM for the game thread.

    Pinning matters. Whether ``Sound`` works depends on whether some other test
    module already opened the mixer, and a test whose subject is *which thread
    converts* must not inherit that from the ambient test order.
    """
    def refuse(buf):
        raise RuntimeError("no mixer here")

    monkeypatch.setattr(mgr, "_make_sound", refuse)
    return mgr


@pytest.fixture()
def converter(mgr, monkeypatch):
    """Conversion works: the worker should be publishing Sounds, not bytes."""
    built: list[FakeSound] = []

    def fake_make_sound(buf):
        snd = FakeSound(buf)
        built.append(snd)
        return snd

    monkeypatch.setattr(mgr, "_make_sound", fake_make_sound)
    mgr.built = built                       # type: ignore[attr-defined]
    return mgr


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
def test_worker_publishes_each_track_incrementally(no_converter, monkeypatch):
    snapshots = []

    def watch_render(theme, rate):
        snapshots.append((len(no_converter._menu_keys),
                          len(no_converter._level_keys)))
        return b"x"

    monkeypatch.setattr("music.render_track", watch_render)
    no_converter._build_music_bytes()
    assert (len(no_converter._menu_keys),
            len(no_converter._level_keys)) == (3, 5)
    # snapshots fire during render, i.e. before that track's own publish:
    # step1 renders a menu cue (nothing published), step2 renders a level cue
    # (menu pool already live), step3 renders with both pools live.
    assert snapshots[:3] == [(0, 0), (1, 0), (1, 1)]


def test_level_buffers_are_keyed_by_cue_name(no_converter, monkeypatch):
    """Keys carry names, because a sector's pool is looked up by name."""
    monkeypatch.setattr("music.render_track", lambda theme, rate: b"x")
    no_converter._build_music_bytes()
    assert "levelc0" in no_converter._level_keys
    assert "levelm0" not in no_converter._level_keys


def test_the_worker_hands_over_sounds_not_bytes(converter, monkeypatch):
    """The whole point of the worker: by the time a cue is eligible to play, the
    mixer object for it already exists and no PCM is kept alongside it."""
    monkeypatch.setattr("music.render_track", lambda theme, rate: b"x" * 8)
    converter._build_music_bytes()
    assert converter._menu_keys and converter._level_keys
    assert converter._track_bytes == {}, "a converted cue kept its PCM too"
    assert all(isinstance(converter._music_sounds[k], FakeSound)
               for k in converter._menu_keys + converter._level_keys)
    assert len(converter.built) == len(converter._music_sounds)


def test_the_frame_thread_does_not_convert_a_ready_cue(converter, monkeypatch):
    """A track change must not build anything. If it does, the judder is back:
    a WAV wrap plus a decode on the thread that is drawing the frame."""
    monkeypatch.setattr("music.render_track", lambda theme, rate: b"x")
    converter._build_music_bytes()
    key = converter._level_keys[0]
    built_before = len(converter.built)

    def no_more(buf):
        raise AssertionError("the game thread converted a track")

    monkeypatch.setattr(converter, "_make_sound", no_more)
    assert converter._ensure_music_sound(key) is converter._music_sounds[key]
    assert len(converter.built) == built_before


def test_pcm_left_by_a_failed_conversion_is_still_playable(mgr, monkeypatch):
    """The retry path, kept on purpose: a cue the worker could not convert is
    published as PCM and converted on demand rather than lost."""
    monkeypatch.setattr("music.render_track", lambda theme, rate: b"x")
    monkeypatch.setattr(mgr, "_make_sound",
                        lambda buf: FakeSound(buf + b"!"))
    mgr._music_stop = True
    mgr._build_music_bytes()                 # stops immediately: nothing built
    mgr._music_stop = False
    mgr._track_bytes["levelc7"] = b"abc"
    snd = mgr._ensure_music_sound("levelc7")
    assert isinstance(snd, FakeSound) and snd.buf == b"abc!"
    assert "levelc7" not in mgr._track_bytes, "retry buffer outlived the retry"
    assert mgr._music_sounds["levelc7"] is snd


def test_one_broken_track_does_not_kill_the_playlist(no_converter, monkeypatch):
    calls = {"n": 0}

    def flaky(theme, rate):
        calls["n"] += 1
        if calls["n"] == 2:          # the first level cue
            raise RuntimeError("synth boom")
        return b"x"


    monkeypatch.setattr("music.render_track", flaky)
    no_converter._build_music_bytes()
    assert len(no_converter._menu_keys) == 3
    assert len(no_converter._level_keys) == 4     # only the flaky one is missing


# ------------------------------------------------------------- sector choice
def test_a_level_pool_may_draw_a_cue_written_for_the_menu(no_converter,
                                                           monkeypatch):
    """Cross-table pools are a feature: the planner must render the cue under
    its own sector, not skip it because it was authored for the attract loop.
    """
    import music
    monkeypatch.setattr("music.LEVEL_CUES", {0: ("c0", "m1")})
    assert "m1" in _level_names(
        no_converter._music_build_plan(music)), "cue dropped"
    monkeypatch.setattr("music.render_track", lambda theme, rate: b"x")
    no_converter._music_stop = False
    no_converter._build_music_bytes()
    assert "levelm1" in no_converter._level_keys


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


# ------------------------------------------------------------------ the mixer
# Two knobs that are easy to confuse: the frame *format* the mixer opens, and how
# many *voices* it mixes. MUSIC_CHANNEL is voice 11, which exists only because
# init() calls set_num_channels - an earlier version passed MIXER_CHANNELS to the
# format argument instead, which pygame read as a channel count.

def test_the_mixer_has_a_voice_for_the_music():
    import pygame
    if pygame.mixer.get_init() is not None:
        pytest.skip("mixer already open in another test's configuration")
    mgr = AudioManager(C.Settings())
    if not mgr.init():
        mgr.dispose()
        pytest.skip("no audio device available")
    try:
        assert pygame.mixer.get_num_channels() >= MUSIC_CHANNEL + 1, \
            "the music channel was never allocated, so music cannot play"
    finally:
        mgr._music_stop = True
        mgr.dispose()


def test_the_pcm_describes_itself_the_way_it_was_made():
    """Sources are mono 16-bit at the mix rate, and say so in their own header.

    This is the part that is ours to control: what the device finally opens is up
    to the device (Windows shared mode answers 8 channels whatever you ask for),
    and that is precisely why converting a cue into a Sound happens on the worker
    thread and not between two frames.
    """
    import struct

    from audio import wav_bytes
    head = wav_bytes(b"\x00\x01" * 100, MIXER_RATE)
    assert head[:4] == b"RIFF" and head[8:12] == b"WAVE"
    (_fmt, channels, sample_rate, byte_rate,
     _align, bits) = struct.unpack("<HHIIHH", head[20:36])
    assert _fmt == 1, "PCM format tag missing"
    assert channels == 1, "mono PCM announcing something else"
    assert bits == 16
    assert sample_rate == MIXER_RATE
    assert byte_rate == MIXER_RATE * 2          # one 16-bit frame per sample
