"""Synthesised instruments: pitch, envelope, timbre, cache.

These are not "does it run" tests. Each one asserts a property the instrument
is *named for*: the violin starts slower than the flute, the flute's vibrato
arrives late, the bell's partials are inharmonic, the pluck rots from the top
down, the strings beat against each other like several bows. If an edit makes an
instrument cheaper by taking away the thing that makes it that instrument, one
of these fails.

Measurements are deliberately crude (zero crossings, a single DFT bin, windowed
RMS) and taken at thresholds with a wide margin, because a per-sample DSP suite
would be testing maths rather than music. Everything here is deterministic -
the noise table is a fixed LCG, not the ``random`` module - so a threshold that
passes once passes forever.
"""
import math

import pytest

import instruments as I

RATE = 22050
F = 440.0


# ------------------------------------------------------------------ helpers
def _rms(seg) -> float:
    return math.sqrt(sum(v * v for v in seg) / max(1, len(seg)))


def _pitch_from_crossings(sig, rate, from_s):
    """Upward zero crossings per second over the sustained part.

    Only meaningful for near-sinusoidal voices: a bowed string or a bell crosses
    zero on its harmonics too, which is why the pitch test uses the flute.
    """
    seg = sig[int(from_s * rate):]
    crossings = sum(1 for i in range(1, len(seg)) if seg[i - 1] < 0 <= seg[i])
    return crossings / (len(seg) / rate)


def _dft_ratio(sig, rate, f_a, f_b):
    """Energy at one frequency relative to another (a single bin, no FFT)."""
    def mag(f):
        n = len(sig)
        k = int(round(n * f / rate))
        re = im = 0.0
        for j, x in enumerate(sig):
            a = -2.0 * math.pi * j * k / n
            re += x * math.cos(a)
            im += x * math.sin(a)
        return math.hypot(re, im)
    return mag(f_a) / max(1e-12, mag(f_b))


def _pitch_correlation(sig, rate, f, from_s, dur):
    """How strongly a window holds pitch ``f`` (best phase, RMS-normalised).

    A window whose pitch drifts correlates less with a steady sine: that is how
    a late vibrato shows up without having to track pitch through noise.
    """
    n = int(dur * rate)
    off = int(from_s * rate)
    level = _rms(sig[off:off + n])
    best = 0.0
    for step in range(16):
        a = math.pi * step / 16
        re = sum(sig[off + i] * math.cos(2 * math.pi * f * i / rate + a)
                 for i in range(n))
        im = sum(sig[off + i] * math.sin(2 * math.pi * f * i / rate + a)
                 for i in range(n))
        best = max(best, math.hypot(re, im) / n / max(1e-12, level))
    return best


def _amplitude_variation(sig, rate, from_s, win=0.05):
    """RMS spread between windows after the attack (chorus/beat detector)."""
    n = int(win * rate)
    vals = [_rms(sig[i:i + n]) for i in range(int(from_s * rate), len(sig) - n, n)]
    mean = sum(vals) / len(vals)
    return math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals)) / mean


# ------------------------------------------------------------------ contract
def test_the_roster_is_the_instruments_we_cared_about():
    assert set(I.NAMES) == {"flute", "violin", "strings", "pluck", "bell"}


def test_is_instrument_tells_instrument_from_wave():
    for name in I.NAMES:
        assert I.is_instrument(name)
    for wave in ("square", "pulse", "tri", "triangle", "saw", "sine", ""):
        assert not I.is_instrument(wave)


@pytest.mark.parametrize("name", I.NAMES)
def test_a_note_is_as_long_as_asked(name):
    assert len(I.note(name, F, 0.5, RATE)) == pytest.approx(0.5 * RATE, abs=2)


@pytest.mark.parametrize("name", I.NAMES)
def test_samples_are_finite_and_bounded(name):
    buf = I.note(name, F, 0.6, RATE)
    assert buf and not any(math.isnan(v) or math.isinf(v) for v in buf)
    assert max(abs(v) for v in buf) < 1.6       # the mix still has headroom


@pytest.mark.parametrize("bad", [(0.0, 0.5), (-1.0, 0.5), (F, 0.0), (F, -0.2)])
def test_a_note_that_cannot_exist_makes_no_sound(bad):
    assert I.note("flute", bad[0], bad[1], RATE) == []


def test_an_unknown_instrument_falls_back_instead_of_raising():
    buf = I.note("bagpipes", F, 0.2, RATE)
    assert buf and not any(math.isnan(v) for v in buf)


# ------------------------------------------------------------------- timbre
def test_the_instruments_are_not_the_same_sound():
    heard = {name: tuple(I.note(name, F, 0.35, RATE)) for name in I.NAMES}
    assert len({hash(v) for v in heard.values()}) == len(I.NAMES)


def test_sinusoidal_voices_hold_the_requested_pitch():
    for name in ("flute", "pluck"):
        got = _pitch_from_crossings(I.note(name, F, 1.0, RATE), RATE, 0.4)
        assert got == pytest.approx(F, rel=0.02), f"{name} is out of tune"


def test_the_violin_starts_more_slowly_than_the_flute():
    """The slow attack is the difference between a violin and a loud flute."""
    def attack_ratio(name):
        buf = I.note(name, F, 1.0, RATE)
        body = buf[int(0.4 * len(buf)):int(0.5 * len(buf))]
        return _rms(buf[:int(0.015 * RATE)]) / _rms(body)

    assert attack_ratio("violin") < attack_ratio("flute") / 3.0


def test_the_flute_vibrato_arrives_late_rather_than_at_the_attack():
    buf = I.note("flute", 880.0, 1.2, RATE)
    early = _pitch_correlation(buf, RATE, 880.0, 0.05, 0.19)
    late = _pitch_correlation(buf, RATE, 880.0, 0.6, 0.19)
    assert early > 0.6, "the note does not start in tune"
    assert late < early * 0.9, "wobbling from the first millisecond"


def test_a_plucked_string_dies_away():
    buf = I.note("pluck", F, 1.2, RATE)
    assert _rms(buf[int(0.8 * len(buf)):]) < 0.5 * _rms(buf[:int(0.2 * len(buf))])


def test_a_pluck_goes_dull_as_it_dies():
    """Partials rot at different rates: a string, not a held organ chord."""
    buf = I.note("pluck", F, 1.2, RATE)
    n = len(buf)
    bright = _dft_ratio(buf[:int(0.15 * n)], RATE, 3.0 * F, F)
    dark = _dft_ratio(buf[int(0.5 * n):int(0.7 * n)], RATE, 3.0 * F, F)
    assert dark < bright * 0.1


def test_the_bell_is_metal_and_the_flute_is_not():
    """Inharmonicity: a bell has real energy at 3.5x the fundamental."""
    assert _dft_ratio(I.note("bell", F, 0.8, RATE), RATE, 3.5 * F, F) > 0.1
    assert _dft_ratio(I.note("flute", F, 0.8, RATE), RATE, 3.5 * F, F) < 0.01


def test_the_strings_beat_like_several_bows():
    """Three detuned voices must produce beating, not one louder voice."""
    after = 1.0                      # past the slow attack
    strings = _amplitude_variation(I.note("strings", F, 3.0, RATE), RATE, after)
    flute = _amplitude_variation(I.note("flute", F, 3.0, RATE), RATE, after)
    assert strings > flute * 2.5


# -------------------------------------------------------------------- cache
def test_the_same_note_twice_is_the_same_note(monkeypatch):
    monkeypatch.setattr(I, "_CACHE", {})
    first = I.note("violin", F, 0.4, RATE)
    assert I.note("violin", F, 0.4, RATE) == first


def test_the_cache_key_is_the_material_not_the_caller(monkeypatch):
    monkeypatch.setattr(I, "_CACHE", {})
    I.note("flute", 440.0, 0.4, RATE)
    I.note("flute", 440.0, 0.5, RATE)
    I.note("violin", 440.0, 0.4, RATE)
    assert len(I._CACHE) == 3


def test_the_caller_gets_its_own_copy_of_a_cached_note(monkeypatch):
    """A caller adds its note into the mix; handing out the cached list would
    let one voice scribble on every later copy of it."""
    monkeypatch.setattr(I, "_CACHE", {})
    first = I.note("flute", F, 0.2, RATE)
    first[0] = 999.0
    assert I.note("flute", F, 0.2, RATE)[0] != 999.0


def test_the_cache_stays_bounded(monkeypatch):
    monkeypatch.setattr(I, "_CACHE", {})
    monkeypatch.setattr(I, "_CACHE_LIMIT", 6)
    for step in range(20):
        I.note("strings", 200.0 + step, 0.05, RATE)
    assert len(I._CACHE) <= 6
