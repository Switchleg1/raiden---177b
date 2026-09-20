"""Drum layer tests: kit synthesis, groove playback, mixing and the tables.

These cover the procedural rompler (``drum_kit``) and its wiring into the music
engine (``music._drum_bar`` / ``music._rhythm``): the thing being changed was
"drums sound cheap", so the assertions are about *signal* properties (envelope,
brightness ordering, no crackle) and about the tables staying playable.
"""

import array
import math

import pytest

import drum_kit
import music
from music_content import (
    GROOVE_BOSS,
    GROOVE_BY_TEMPO,
    GROOVES,
    KIT_BOSS,
    KIT_BY_TEMPO,
    KITS,
    SCALES,
)

RATE = 22050
VOICES = ("kick", "snare", "hat", "open", "crash", "ride", "rim", "clap")
# Every voice is normalised into the same band so one groove velocity means the
# same loudness whatever it hits (see drum_kit._normalise / the manual scales).
PEAK_LO, PEAK_HI = 0.80, 0.95


# ---------------------------------------------------------------- helpers
def _peak(samples) -> float:
    return max(abs(s) for s in samples)


def _zcr(samples) -> float:
    """Zero-crossings per sample: a cheap stand-in for brightness."""
    flips = sum(1 for i in range(1, len(samples))
                if (samples[i] < 0.0) != (samples[i - 1] < 0.0))
    return flips / max(1, len(samples))


def _rms(samples) -> float:
    return math.sqrt(sum(s * s for s in samples) / max(1, len(samples)))


class HitLog:
    """Stand-in for _Mix that records drum(voice, s0, vel, freq) calls."""

    rate = RATE

    def __init__(self) -> None:
        self.hits: list[tuple[str, int, float]] = []
        self.freqs: dict[str, list[float]] = {}

    def drum(self, voice, s0, vel, freq=None):
        self.hits.append((voice, s0, vel))
        if freq is not None:
            self.freqs.setdefault(voice, []).append(freq)

    def voices(self):
        return [v for v, _s0, _vel in self.hits]

    def voices_with_freq(self, voice):
        return self.freqs.get(voice, [])


# ------------------------------------------------------------- kit render
@pytest.mark.parametrize("kit", sorted(KITS))
def test_every_kit_renders_every_voice_cleanly(kit):
    samples = drum_kit.kit_samples(kit, KITS[kit], RATE)
    for voice in VOICES:
        data = samples[voice]
        assert len(data) > 8, f"{kit}/{voice} rendered nothing"
        peak = _peak(data)
        assert PEAK_LO <= peak <= PEAK_HI, f"{kit}/{voice} peak {peak:.2f}"
        assert all(math.isfinite(s) for s in data), f"{kit}/{voice} NaN"
    for data in samples["tom"]:
        assert PEAK_LO <= _peak(data) <= PEAK_HI
        assert all(math.isfinite(s) for s in data)


@pytest.mark.parametrize("kit", sorted(KITS))
def test_kits_are_deterministic(kit):
    """Same params, different cache slot -> bit-identical samples. The kit name
    is part of the cache identity, so the ghost name must be unique per kit."""
    params = KITS[kit]
    a = drum_kit.kit_samples(kit, params, RATE)
    b = drum_kit.kit_samples(f"ghost-{kit}", params, RATE)
    assert a["kick"] == b["kick"]
    assert a["crash"] == b["crash"]
    assert a["tom"] == b["tom"]


def test_tom_pitches_are_tuned_and_separate():
    samples = drum_kit.kit_samples("crisp", KITS["crisp"], RATE)
    assert len(samples["tom"]) == len(drum_kit.TOM_FREQS)
    for freq, data in zip(drum_kit.TOM_FREQS, samples["tom"], strict=False):
        period = max(2, int(RATE / freq))
        assert _rms(data[:period]) > 0.02, f"tom {freq}Hz barely sounds"
    # the table must actually span a pitch range, not eight copies of one drum
    assert _zcr(samples["tom"][0]) < _zcr(samples["tom"][-1])


def test_voice_brightness_is_ordered():
    """A drum kit is only convincing if the voices occupy different bands."""
    samples = drum_kit.kit_samples("crisp", KITS["crisp"], RATE)
    kick = _zcr(samples["kick"])
    snare = _zcr(samples["snare"])
    hat = _zcr(samples["hat"])
    assert kick < snare < hat, f"brightness ordering wrong: {kick} {snare} {hat}"
    # hats are noise: they must be *far* brighter than the tonal kick body
    assert hat > kick * 4, "hi-hat has no sizzle"


def test_envelopes_start_loud_and_end_quiet():
    samples = drum_kit.kit_samples("crisp", KITS["crisp"], RATE)
    for voice in ("kick", "snare", "hat", "clap"):
        data = samples[voice]
        head = _rms(data[: max(2, len(data) // 8)])
        tail = _rms(data[-max(2, len(data) // 8):])
        assert head > tail, f"{voice} does not decay"


def test_kick_pumps_and_hat_is_short():
    """Kick must be the long low voice, hat the short bright one - per sample."""
    samples = drum_kit.kit_samples("crisp", KITS["crisp"], RATE)
    assert len(samples["kick"]) > len(samples["hat"]) * 3
    assert len(samples["crash"]) > len(samples["ride"])


def test_kit_presets_actually_differ():
    """The kits are data: two presets must not render the same kick."""
    a = drum_kit.kit_samples("soft", KITS["soft"], RATE)
    b = drum_kit.kit_samples("metal", KITS["metal"], RATE)
    assert a["kick"][:256] != b["kick"][:256]
    assert len(a["kick"]) != len(b["kick"])


# ---------------------------------------------------------------- playback
def test_play_adds_energy_at_the_right_place():
    samples = drum_kit.kit_samples("crisp", KITS["crisp"], RATE)
    buf = [0.0] * RATE
    before = _rms(buf)
    drum_kit.play(buf, RATE, RATE // 4, "kick", 1.0, samples=samples)
    assert before == 0.0
    head = _rms(buf[:RATE // 8])
    assert head == 0.0, "energy leaked before the hit"
    window = buf[RATE // 4:RATE // 4 + 2000]
    assert _rms(window) > 0.05, "kick inaudible at its own start"
    assert _peak(buf) <= 1.0


def test_velocity_scales_the_hit():
    samples = drum_kit.kit_samples("crisp", KITS["crisp"], RATE)
    full = [0.0] * 8000
    soft = [0.0] * 8000
    drum_kit.play(full, RATE, 100, "snare", 1.0, samples=samples)
    drum_kit.play(soft, RATE, 100, "snare", 0.4, samples=samples)
    assert _rms(soft) < _rms(full) * 0.7
    assert _rms(soft) > 0.0, "a quiet hit must still sound"


def test_play_clamps_at_the_buffer_end():
    samples = drum_kit.kit_samples("heavy", KITS["heavy"], RATE)
    buf = [0.0] * 500
    drum_kit.play(buf, RATE, 490, "crash", 1.0, samples=samples)   # tail runs off
    assert any(buf), "clamped hit rendered nothing"
    assert len(buf) == 500


def test_play_past_the_end_is_a_no_op():
    samples = drum_kit.kit_samples("crisp", KITS["crisp"], RATE)
    buf = [0.0] * 256
    drum_kit.play(buf, RATE, 9999, "kick", 1.0, samples=samples)
    assert not any(buf)


def test_unknown_voice_is_ignored_not_fatal():
    """A groove typo must silence one hit, not the soundtrack thread."""
    samples = drum_kit.kit_samples("crisp", KITS["crisp"], RATE)
    buf = [0.0] * 4096
    drum_kit.play(buf, RATE, 10, "trianglez", 1.0, samples=samples)
    assert not any(buf)


def test_tom_frequency_selects_the_padded_drum():
    samples = drum_kit.kit_samples("crisp", KITS["crisp"], RATE)
    low = [0.0] * 6000
    high = [0.0] * 6000
    drum_kit.play(low, RATE, 0, "tom", 1.0, samples=samples,
                  freq=drum_kit.TOM_FREQS[0])
    drum_kit.play(high, RATE, 0, "tom", 1.0, samples=samples,
                  freq=drum_kit.TOM_FREQS[-1])
    assert _zcr(high) > _zcr(low), "tom pitch selection is backwards"


# ------------------------------------------------------------------ grooves
def test_groove_table_is_playable_data():
    for name, groove in GROOVES.items():
        assert 0.0 <= float(groove.get("swing", 0.0)) <= 0.25, name
        for voice in ("kick", "snare", "ghost", "hat", "open", "ride", "rim",
                      "clap", "tom"):
            for step, vel in groove.get(voice, ()):
                assert 0 <= step <= 15, f"{name}.{voice} step {step} off grid"
                assert 0.0 < vel <= 1.0, f"{name}.{voice} velocity {vel}"
        for variant in groove.get("fill", ()):
            for step, voice, vel in variant:
                assert 0 <= step <= 15, f"{name}.fill step {step}"
                assert 0.0 < vel <= 1.0, f"{name}.fill velocity {vel}"
                assert voice in ("kick", "snare", "ghost", "tom", "crash",
                                 "rim", "clap", "hat"), \
                    f"{name}.fill uses unknown voice {voice}"


def test_every_groove_plays_kick_and_snare():
    for name, groove in GROOVES.items():
        log = HitLog()
        music._drum_bar(log, groove, "A", 0, lambda beat: int(beat * 1000),
                        drive=False)
        assert "kick" in log.voices(), f"{name} has no kick"
        assert "snare" in log.voices(), f"{name} has no snare"


def _backbeats(log: HitLog) -> int:
    """Loud snares only: ghost notes are snares too, at low velocity."""
    return sum(1 for voice, _s0, vel in log.hits if voice == "snare"
               and vel >= 0.7)


def test_fill_replaces_the_snare_backbeat():
    groove = GROOVES["break"]
    plain = HitLog()
    filled = HitLog()
    at = lambda beat: int(beat * 1000)      # noqa: E731 - test-local shim
    music._drum_bar(plain, groove, "A", 0, at, drive=False)
    music._drum_bar(filled, groove, "A", 7, at, drive=False)
    assert _backbeats(plain) == 2
    assert sum(1 for v, _s, vel in plain.hits
               if v == "snare" and vel < 0.7) == 4, "ghost notes missing"
    assert len([h for h in filled.hits if h[0] == "tom"]) >= 2, \
        "fill did not play toms"
    assert len(filled.hits) > len(plain.hits), "fill should be busier"


def test_fills_rotate_between_sections():
    groove = GROOVES["break"]
    at = lambda beat: int(beat * 1000)      # noqa: E731
    a = HitLog()
    b = HitLog()
    music._drum_bar(a, groove, "A", 7, at, drive=False)
    music._drum_bar(b, groove, "B", 7, at, drive=False)
    assert [h for h in a.hits if h[0] == "tom"] != \
        [h for h in b.hits if h[0] == "tom"], "fill did not rotate"


def test_toms_descend_in_pitch_within_a_bar():
    groove = GROOVES["halftime"]
    log = HitLog()
    music._drum_bar(log, groove, "A", 7, lambda beat: int(beat * 1000),
                    drive=False)
    pitches = log.voices_with_freq("tom")
    assert len(pitches) >= 2
    assert pitches == sorted(pitches, reverse=True), f"toms climbed: {pitches}"


def test_swing_pushes_odd_steps_late():
    """Even steps stay on the grid, odd steps land late - that is swing."""
    groove = {"hat": ((0, 0.8), (1, 0.4), (2, 0.8), (3, 0.4)), "swing": 0.25}
    log = HitLog()
    music._drum_bar(log, groove, "A", 0, lambda beat: int(beat * 4000),
                    drive=False)
    hats = [s0 for voice, s0, _vel in log.hits if voice == "hat"]
    assert hats[0] == 0, "swing must not drag the downbeat"
    assert hats[2] == 2000, "swing must not drag 8th notes"
    assert hats[1] == 1250 and hats[3] == 3250, f"odd steps not swung: {hats}"


def test_boss_bars_open_on_a_crash():
    groove = GROOVES[GROOVE_BOSS]
    log = HitLog()
    music._drum_bar(log, groove, "A", 0, lambda beat: int(beat * 1000),
                    drive=True)
    assert "crash" in log.voices()
    quiet = HitLog()
    music._drum_bar(quiet, groove, "A", 3, lambda beat: int(beat * 1000),
                    drive=True)
    assert "crash" not in quiet.voices(), "crash on every bar is not an accent"


def test_boss_intro_rolls_across_the_bar():
    groove = GROOVES[GROOVE_BOSS]
    log = HitLog()
    music._drum_bar(log, groove, "intro", 0, lambda beat: int(beat * 1000),
                    drive=True)
    snares = [s0 for voice, s0, _vel in log.hits if voice == "snare"]
    assert len(snares) >= 12, "boss intro is not a roll"
    assert len(set(snares)) == len(snares), "roll hits land on each other"


# ------------------------------------------------------- theme -> rhythm map
@pytest.mark.parametrize("name", sorted(KITS))
def test_named_kits_exist_in_the_kit_module(name):
    assert KITS[name], f"kit {name} is empty"
    samples = drum_kit.kit_samples(name, KITS[name], RATE)
    assert samples["kick"]


def test_selection_tables_point_at_real_entries():
    for _limit, name in GROOVE_BY_TEMPO:
        assert name in GROOVES, name
    for _limit, name in KIT_BY_TEMPO:
        assert name in KITS, name
    assert GROOVE_BOSS in GROOVES
    assert KIT_BOSS in KITS


def test_every_theme_resolves_a_groove_and_kit():
    for theme in music.THEMES + music.BOSS_THEMES:
        groove, samples = music._rhythm(theme, RATE)
        assert groove in GROOVES.values(), theme["name"]
        assert samples is not None, theme["name"]
        assert samples["kick"], theme["name"]
    for theme in music.MENU_THEMES:
        assert music._rhythm(theme, RATE) == (None, None), \
            f"menu theme {theme['name']} must be drumless"


def test_theme_overrides_win_over_tempo_selection():
    theme = dict(music.THEMES[-1])
    theme["groove"] = "march"
    theme["kit"] = "heavy"
    groove, samples = music._rhythm(theme, RATE)
    assert groove is GROOVES["march"]
    assert samples["kick"] == drum_kit.kit_samples("heavy", KITS["heavy"],
                                                   RATE)["kick"]


def test_bad_theme_names_fall_back_instead_of_raising():
    theme = dict(music.THEMES[0])
    theme["groove"] = "polka"
    theme["kit"] = "orchestra"
    groove, samples = music._rhythm(theme, RATE)
    assert groove in GROOVES.values()
    assert samples["kick"], "unknown kit must still render drums"


def _resolved_groove(theme: dict) -> str:
    groove, _samples = music._rhythm(theme, RATE)
    for name, table in GROOVES.items():
        if table is groove:
            return name
    raise AssertionError("groove resolved to a table not in GROOVES")


def test_theme_identity_tags_are_valid():
    """A theme's groove/kit/scale keys are literals that must name a real
    table entry. A typo would silently fall back and quietly flatten the cue,
    so catch it in CI rather than in someone's ears."""
    for theme in music.THEMES + music.MENU_THEMES + music.BOSS_THEMES:
        if "groove" in theme:
            assert theme["groove"] in GROOVES, theme["name"]
        if "kit" in theme:
            assert theme["kit"] in KITS, theme["name"]
        assert theme.get("scale", "natural") in SCALES, theme["name"]


def test_stage_roster_has_its_own_rhythm_per_cue():
    """Tempo-bucketing alone makes every stage feel the same: the table must
    spread across the groove set and name enough cues by hand."""
    tagged = [t for t in music.THEMES if "groove" in t or "kit" in t]
    assert len(tagged) >= 18, "identity tags were stripped from the roster"
    used = {_resolved_groove(t) for t in music.THEMES}
    assert len(used) >= 4, f"stage cues only use {sorted(used)}"


def test_modes_are_used_not_just_declared():
    modes = {t.get("scale", "natural") for t in music.THEMES}
    assert len(modes) >= 5, f"only {sorted(modes)} in the stage roster"


# --------------------------------------------------------------- mix master
def test_soft_clip_survives_a_hot_sum_without_crackle():
    """Drums over the pad used to flip samples; that is what crackle is."""
    mix = music._Mix(2048, rate=RATE)
    for i in range(2048):
        mix.buf[i] = 1.6 * math.sin(2.0 * math.pi * 0.005 * i)
    pcm = mix.normalise()
    vals = array.array("h")
    vals.frombytes(pcm)
    assert max(vals) < 32767, "normalise left samples pinned at full scale"
    # 2048 samples at 0.005 cycles/sample = ~10 zero crossings. Hard clipping
    # (or a sign-flipping scale) shows up as extra crossings near each peak.
    flips = sum(1 for i in range(1, len(vals))
                if (vals[i] < 0) != (vals[i - 1] < 0))
    assert flips <= 22, f"soft-clip produced extra transitions: {flips}"


def test_the_gallop_groove_is_dense_by_design():
    """The gallop is a lurch, not a tempo: the kick owns the "a" of both beats,
    and the toms answer on the e. Measured against the baseline groove, which
    is what the pattern was written to beat."""
    gallop, straight = GROOVES["gallop"], GROOVES["straight"]
    kicks = {step for step, _ in gallop["kick"]}
    assert {0, 8} <= kicks, "the gallop has lost its downbeats"
    assert {6, 14} <= kicks, "the kick no longer anticipates: not a gallop"
    assert not {4, 12} & kicks, "a kick on the backbeat flattens the lurch"
    assert gallop["snare"] == straight["snare"], "the backbeat has to stay put"
    assert gallop.get("tom"), "no hooves"
    assert gallop["swing"] == 0.0, "a swung gallop is a shuffle"
    dense = sum(len(gallop.get(v, ())) for v in music.GROOVE_VOICES)
    baseline = sum(len(straight.get(v, ())) for v in music.GROOVE_VOICES)
    assert dense > baseline, "denser was the whole point"


def test_the_kit_is_audible_in_a_rendered_track():
    """The drums are not decoration: subtracting the drumless render of the
    same theme must leave a real signal, not numerical dust."""
    # Pinned by name, not index: the level table is data and gets retuned, and
    # this claim needs a groove with space in it. The gallop is dense on
    # purpose, so its density is checked as a pattern, one test up.
    theme = next(t for t in music.THEMES if t["name"] == "Cathedral Run")
    on = music.render_track(theme, rate=RATE)
    no_drums = dict(theme)
    no_drums["drums"] = False
    off = music.render_track(no_drums, rate=RATE)
    assert on != off, "the groove changed nothing in the render"
    a = array.array("h")
    b = array.array("h")
    a.frombytes(off)                      # same length: layout is unchanged
    b.frombytes(on[: len(off)])
    diff = [abs(x - y) / 32768.0 for x, y in zip(a, b, strict=False)]
    assert _rms(diff) > 0.02, f"drums contribute only {_rms(diff):.4f}"
    # ... and they contribute it as transients: the loudest 1 % of the
    # difference is far hotter than the average, which no pad fade can do.
    loud = sorted(diff, reverse=True)[: max(1, len(diff) // 100)]
    assert _rms(loud) > _rms(diff) * 4.0, "drum hits are not transients"
