"""Boss music: the cues exist, they are faster and denser, and they are routed
as a third pool that rides early in the background render plan."""

import array
import math

import pytest

import music
from audio import BOSS_KEY, LEVEL_KEY, MENU_KEY, AudioManager

FAST_RATE = 8000        # test renders: proof of life, not shipping quality


class Recorder:
    """Counts every voice/drum event _add_bar asks for."""

    rate = 44100

    def __init__(self) -> None:
        self.events = 0

    def __getattr__(self, _name: str):
        def _hit(*_args, **_kwargs):
            self.events += 1
        return _hit


def rms(pcm: bytes) -> float:
    """Root-mean-square of the mono int16 stream, 0.0 silent / ~0.3 loud."""
    vals = array.array("h")
    vals.frombytes(pcm[: len(pcm) // 2 * 2])
    if not vals:
        return 0.0
    return math.sqrt(sum(v * v for v in vals) / len(vals)) / 32768.0


def seconds_of(pcm: bytes, rate: int) -> float:
    # mono int16
    return len(pcm) / 2.0 / rate


# ---------------------------------------------------------------- theme data
def test_boss_pool_exists_and_is_typed_for_fights():
    assert len(music.BOSS_THEMES) >= 4
    for theme in music.BOSS_THEMES:
        assert theme["drive"] is True, "boss cues must use the drive bed"
        assert theme["bpm"] >= 150
        assert theme.get("layout"), "boss cues need the short punchy layout"
        assert theme["scale"] in ("harmonic", "natural", "minor")


def test_boss_cues_are_faster_than_any_level_cue():
    assert min(t["bpm"] for t in music.BOSS_THEMES) > \
        max(t["bpm"] for t in music.THEMES)


def test_boss_names_are_unique():
    names = [t["name"] for t in music.BOSS_THEMES]
    assert len(set(names)) == len(names)
    assert not set(names) & {t["name"] for t in music.THEMES}


# ------------------------------------------------------------------- synth
def test_drive_flag_makes_the_rhythm_bed_denser():
    theme = music.BOSS_THEMES[0]
    spb = 60.0 / theme["bpm"]

    def count(drive: bool) -> int:
        rec = Recorder()
        music._add_bar(rec, "A", 1, theme["root"], theme["prog"],
                       theme["lead"], spb, 0.0, drive=drive)
        return rec.events

    plain, driven = count(False), count(True)
    assert driven > plain * 1.4, (
        f"drive only added {driven - plain} events of {plain}")


def test_boss_intro_bar_is_an_alarm():
    theme = music.BOSS_THEMES[1]
    spb = 60.0 / theme["bpm"]
    groove = music.GROOVES[music.GROOVE_BOSS]

    def count(drive: bool) -> int:
        rec = Recorder()
        music._add_bar(rec, "intro", 0, theme["root"], theme["prog"],
                       theme["lead"], spb, 0.0, groove=groove, drive=drive)
        return rec.events

    plain, alarmed = count(False), count(True)
    assert alarmed > plain, f"alarm roll added nothing to {plain} events"
    # The alarm *is* the roll: a crescendo of snares across the whole bar.
    roll = groove.get("roll") or ()
    assert len(roll) >= 8, "boss groove needs a multi-hit snare roll"
    velocities = [vel for _step, vel in roll]
    assert velocities == sorted(velocities), "the roll must crescendo"
    assert max(velocities) >= 0.9, "the roll must arrive at full strength"


@pytest.mark.parametrize("index", [0, 3])
def test_boss_cue_renders_to_audible_audio(index):
    theme = music.BOSS_THEMES[index]
    pcm = music.render_track(theme, FAST_RATE)
    assert pcm, "boss cue rendered nothing"
    dur = seconds_of(pcm, FAST_RATE)
    # A fight loop, not a 90-second level suite: short enough to loop tensile.
    assert 12.0 < dur < 70.0, f"unexpected boss cue length {dur:.1f}s"
    assert rms(pcm) > 0.02, "boss cue is inaudible"


def test_build_bosses_is_cached_and_complete():
    first = music.build_bosses(FAST_RATE)
    assert len(first) == len(music.BOSS_THEMES)
    assert all(first), "every boss cue must render"
    assert music.build_bosses(FAST_RATE) is first, "cache miss on second call"
    assert music.build_boss(FAST_RATE) == first[0]


# ---------------------------------------------------------------- pool plan
@pytest.fixture()
def mgr(monkeypatch):
    m = AudioManager(__import__("config").Settings())
    m._ntracks = 5
    monkeypatch.setattr("music.MENU_THEMES",
                        tuple({"name": f"m{i}"} for i in range(3)))
    monkeypatch.setattr("music.THEMES",
                        tuple({"name": f"c{i}"} for i in range(5)))
    monkeypatch.setattr("music.LEVEL_CUES",
                        {0: ("c0", "c1"), 1: ("c2",), 2: ("c3", "c4")},
                        raising=False)
    return m


def test_boss_pool_rides_early_in_the_build_plan(mgr):
    plan = mgr._music_build_plan(music)
    pools = [pool for pool, _i, _t in plan]
    assert pools[:3] == [MENU_KEY, LEVEL_KEY, BOSS_KEY], \
        "a boss can appear in the first minute; its cue must render early"
    assert pools.count(BOSS_KEY) == len(music.BOSS_THEMES)
    boss_keys = [k for p, k, _t in plan if p == BOSS_KEY]
    assert sorted(boss_keys) == [f"{BOSS_KEY}{i}"
                                 for i in range(len(music.BOSS_THEMES))]


def test_worker_publishes_boss_keys(mgr, monkeypatch):
    monkeypatch.setattr("music.render_track", lambda theme, rate: b"x")
    mgr._build_music_bytes()
    assert len(mgr._boss_keys) == len(music.BOSS_THEMES)
    assert all(k.startswith(BOSS_KEY) for k in mgr._boss_keys)
    assert len(mgr._menu_keys) == 3 and len(mgr._level_keys) == 5


# ------------------------------------------------------------ play/fallback
def test_play_boss_music_reports_false_until_the_pool_is_live(mgr):
    mgr.available = True
    mgr._music_ch = object()          # stand-in for a real mixer channel
    played: list[str] = []
    mgr._play_music = lambda key, loops=-1: setattr(mgr, "_music_key", key) \
        or played.append(key)

    assert mgr.play_boss_music() is False, "no cue rendered yet"
    assert played == []

    mgr._boss_keys[:] = ["boss0", "boss1"]
    assert mgr.play_boss_music() is True
    assert played and played[0].startswith(BOSS_KEY)


def test_boss_music_does_not_repeat_itself(mgr):
    mgr.available = True
    mgr._music_ch = object()
    mgr._play_music = lambda key, loops=-1: setattr(mgr, "_music_key", key)
    mgr._boss_keys[:] = ["boss0", "boss1"]

    seen = [mgr.play_boss_music() for _ in range(3)]
    assert all(seen)
    assert mgr._last_boss_key in ("boss0", "boss1")
    # With two cues available, four picks cannot all be the same one.
    picks = set()
    for _ in range(12):
        mgr.play_boss_music()
        picks.add(mgr._last_boss_key)
    assert picks == {"boss0", "boss1"}


def test_pool_lists_are_separate(mgr):
    mgr._menu_keys[:] = ["menu0"]
    mgr._level_keys[:] = ["level0"]
    mgr._boss_keys[:] = ["boss0"]
    assert mgr._pool_lists(BOSS_KEY)[0] == ["boss0"]
    assert mgr._pool_lists(LEVEL_KEY)[0] == ["level0"]
    assert mgr._pool_lists(MENU_KEY)[0] == ["menu0"]
