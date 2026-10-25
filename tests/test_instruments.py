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
    """The roster, spelled out: every contract below runs against every name
    here, so adding a voice means it inherits the whole suite - and a voice
    added by accident shows up as a failure rather than as a new sound nobody
    checked."""
    assert set(I.NAMES) == {
        # acoustic / orchestral: the expressiveness set
        "flute", "violin", "strings", "pluck", "bell",
        # electronic: the trance / electro set
        "supersaw", "stab", "acid", "reese",
    }


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


# ------------------------------------------------------- portamento and lines
def _bin(sig, rate, from_s, to_s, freq) -> float:
    """Exact single-bin DFT magnitude at ``freq`` over a window.

    Deliberately not an FFT: one bin at a known pitch is what a question about
    pitch needs, and it cannot be fooled by the bow noise the way a zero-crossing
    rate can.
    """
    seg = sig[int(from_s * rate):int(to_s * rate)]
    re = sum(v * math.cos(2.0 * math.pi * freq * i / rate)
             for i, v in enumerate(seg))
    im = sum(v * math.sin(2.0 * math.pi * freq * i / rate)
             for i, v in enumerate(seg))
    return math.hypot(re, im) / max(1, len(seg))


def _old_over_new(sig, onset, old, new) -> float:
    """How much of the *previous* pitch is audible just after a note starts.

    A teleporting synth leaves none; a hand moving along a string leaves a lot.
    """
    return (_bin(sig, RATE, onset, onset + 0.07, old)
            / _bin(sig, RATE, onset, onset + 0.07, new))


SLIDE = [(0.0, 0.4, 440.0), (0.4, 0.6, 554.37)]      # A4 up to C#5, no bow break


def test_a_connected_note_travels_in_from_the_previous_pitch():
    """The thing a wave table cannot do and a violin does: the pitch moves."""
    slid = I.phrase("violin", SLIDE, RATE)
    detached = I.phrase("violin", [(0.0, 0.4, 440.0), (0.9, 0.6, 554.37)], RATE)
    assert _old_over_new(slid, 0.4, 440.0, 554.37) > 3.0 * _old_over_new(
        detached, 0.9, 440.0, 554.37)


def test_a_slide_lands_on_the_pitch_and_stays_there():
    """A portamento that never arrives is just a wrong note with extra steps."""
    slid = I.phrase("violin", SLIDE, RATE)
    assert _bin(slid, RATE, 0.55, 0.85, 440.0) < 0.05 * _bin(
        slid, RATE, 0.55, 0.85, 554.37)


def test_a_wide_leap_is_placed_cleanly_rather_than_slid():
    """Players slide what they can reach. An octave is a shift, not a gliss."""
    leap = I.phrase("violin", [(0.0, 0.4, 440.0), (0.4, 0.6, 880.0)], RATE)
    slid = I.phrase("violin", SLIDE, RATE)
    assert _old_over_new(leap, 0.4, 440.0, 880.0) < _old_over_new(
        slid, 0.4, 440.0, 554.37) / 3.0


def test_portamento_can_be_switched_off():
    """An arranger writing fast runs wants them clean; ``portamento=0.0`` does."""
    clean = I.phrase("violin", SLIDE, RATE, portamento=0.0)
    assert _old_over_new(clean, 0.4, 440.0, 554.37) < 0.06


def test_a_line_stops_each_note_when_the_next_begins():
    """One bow, one pitch. Stacked notes are what makes synth strings muddy."""
    held = I.phrase("violin", [(0.0, 0.9, 440.0)], RATE)
    line = I.phrase("violin", SLIDE, RATE)
    assert _bin(line, RATE, 0.55, 0.85, 440.0) < 0.1 * _bin(
        held, RATE, 0.55, 0.85, 440.0)


def test_a_joined_note_does_not_click():
    """A phase reset would show as a step larger than the waveform's own peak."""
    line = I.phrase("violin", SLIDE, RATE)
    window = line[int(0.395 * RATE):int(0.415 * RATE)]
    step = max(abs(window[i] - window[i - 1]) for i in range(1, len(window)))
    assert step < 0.8 * max(abs(v) for v in window)


def test_a_plucked_line_is_not_cut_short():
    """The cut is a bow rule. A plucked string keeps ringing under the next note."""
    line = I.phrase("pluck", [(0.0, 1.0, 440.0), (0.2, 0.3, 554.37)], RATE)
    assert len(line) / RATE > 0.95


def test_a_phrase_sorts_its_notes_and_ignores_dead_ones():
    line = I.phrase("violin", [(0.6, 0.3, 440.0), (0.0, 0.0, 300.0),
                               (0.2, 0.4, 554.37)], RATE)
    assert 0.85 < len(line) / RATE < 0.95
    assert I.phrase("violin", [], RATE) == []


# ------------------------------------------------------- the electronic set
# The four new voices exist because the acoustic set cannot make a trance pad, a
# gated stab, a resonant bass or a reese. Each test below asserts the one
# property that makes the voice *that* voice - the sweep in the acid, the beat in
# the reese, the gate in the stab, the width in the supersaw. Take the property
# away and the voice becomes a saw, which the engine already had.

def _brightness(sig, rate, from_s, to_s) -> float:
    """Zero crossings per second over a window: a crude brightness measure."""
    seg = sig[int(from_s * rate):int(to_s * rate)]
    flips = sum(1 for i in range(1, len(seg))
                if (seg[i] < 0.0) != (seg[i - 1] < 0.0))
    return flips / (len(seg) / rate)


def _release(sig, rate, win: float = 0.002) -> float:
    """Seconds the envelope takes to fall from half its plateau to a twentieth.

    Release *length* rather than release *shape* is what tells a gated stab from
    a pad, and it is the property the arranger hears: one is a percussion hit
    with a pitch, the other is a sustained layer. The window has to be a couple of
    milliseconds or a 40 ms gate is not resolvable at all.
    """
    w = int(win * rate)
    env = []
    for i in range(0, max(1, len(sig) - w), w):
        seg = sig[i:i + w]
        env.append((i / rate, (sum(x * x for x in seg) / len(seg)) ** 0.5))
    plateau = max(v for t, v in env if t < 0.5 * (len(sig) / rate))
    half = max(t for t, v in env if v >= 0.5 * plateau)
    below = [t for t, v in env if t > half and v <= 0.05 * plateau]
    return min(below) - half if below else float("nan")


def test_supersaw_is_a_section_and_not_one_oscillator():
    """Detuning has to show up as beating, or "super" is a lie about the voice.

    The pitch check is energy on the root against energy a semitone away, which
    works for any timbre; correlating against one sine would just score how
    sinusoidal the wave is, and a saw stack is not sinusoidal by design.
    """
    wide = I.renderers()["supersaw"](F, 2.0, RATE)
    assert _amplitude_variation(wide, RATE, 0.3) > 0.04, "no chorus in supersaw"
    assert _dft_ratio(wide, RATE, F, F * 2 ** (1.0 / 12.0)) > 30.0, \
        "the detuning smeared the pitch"


def test_supersaw_keeps_breathing_while_one_note_is_held():
    """The slow amplitude swell is what stops a held pad sounding like an organ."""
    sig = I.renderers()["supersaw"](F, 4.0, RATE)
    late = _amplitude_variation(sig, RATE, 2.0, win=0.3)
    assert late > 0.05, f"held pad is static ({late:.3f})"


def test_stab_is_a_gate_and_not_a_pad():
    """A stab's identity is its envelope: it holds, then it is cut.

    The same harmonics under a pad-length release would be a dull pad, and the
    two voices would be one voice. So the claim is about release *length*: a stab
    lets go in tens of milliseconds, a pad in a fifth of a second.
    """
    for dur in (0.5, 1.0):
        for freq in (220.0, 440.0):
            stab = _release(I.renderers()["stab"](freq, dur, RATE), RATE)
            pad = _release(I.renderers()["supersaw"](freq, dur, RATE), RATE)
            assert stab < 0.06, f"stab release {stab * 1000:.0f} ms is not a gate"
            assert pad > 2.5 * stab, (
                f"pad release {pad * 1000:.0f} ms vs stab {stab * 1000:.0f} ms: "
                "one voice, not two")


def test_the_stab_holds_full_level_until_it_is_cut():
    """No fade in the body: the level at four fifths in is the level at the top."""
    sig = I.renderers()["stab"](F, 1.0, RATE)
    n = len(sig)

    def at(a, b):
        seg = sig[int(a * n):int(b * n)]
        return _rms(seg)
    assert at(0.6, 0.8) > 0.7 * at(0.1, 0.3), "the stab faded instead of gating"
    assert at(0.86, 0.94) > 0.6 * at(0.1, 0.3), "the gate closed too early"


def test_the_acid_filter_falls_over_the_note():
    """The acid voice is a falling resonant filter, so it must start bright.

    A saw with a fixed rolloff would be a different - and much duller - voice:
    the sweep is the performance, and it has to happen inside one note.
    """
    sig = I.renderers()["acid"](110.0, 1.0, RATE)
    early = _brightness(sig, RATE, 0.02, 0.12)
    late = _brightness(sig, RATE, 0.75, 0.95)
    assert early > late * 1.4, f"filter did not close: {early:.0f} vs {late:.0f}"


def test_acid_sits_low_at_the_end_of_its_own_note():
    """The sweep has to end *closed*, which is the 'wah' a player leaves in."""
    sig = I.renderers()["acid"](110.0, 1.0, RATE)
    end = _bin(sig, RATE, 0.8, 0.98, 110.0)
    top = _bin(sig, RATE, 0.8, 0.98, 110.0 * 6)
    assert end > top, "the note ends on its upper partials, not its root"


def test_reese_beats_against_itself():
    """A reese is two detuned saws: the beat frequency IS the voice."""
    sig = I.renderers()["reese"](110.0, 2.0, RATE)
    var = _amplitude_variation(sig, RATE, 0.4, win=0.12)
    assert var > 0.05, f"no beating between the two saws ({var:.3f})"


def test_reese_keeps_its_root_when_the_fundamental_gets_small():
    """The sub octave is the difference between a bass and a fuzzy texture."""
    reese = I.renderers()["reese"](110.0, 1.0, RATE)
    other = I.renderers()["supersaw"](110.0, 1.0, RATE)
    assert _dft_ratio(reese, RATE, 55.0, 110.0) > _dft_ratio(
        other, RATE, 55.0, 110.0) * 1.5, "no sub in the reese"


def test_the_electronic_voices_arrive_at_a_predictable_level():
    """A slot's volume number has to mean the same loudness whatever timbre is
    handed it, or re-voicing a cue silently re-mixes it."""
    for name in ("supersaw", "stab", "acid", "reese"):
        for freq, dur in ((110.0, 1.0), (220.0, 0.5), (440.0, 0.25)):
            peak = max(abs(v) for v in I.renderers()[name](freq, dur, RATE))
            assert 0.85 <= peak <= 1.05, f"{name} @ {freq}Hz/{dur}s = {peak:.2f}"


def test_the_electronic_voices_are_not_one_voice_four_times():
    """Four timbres must occupy different bands, or three of them are redundant."""
    order = {
        "reese": _brightness(I.renderers()["reese"](220.0, 1.0, RATE), RATE,
                             0.2, 0.9),
        "supersaw": _brightness(I.renderers()["supersaw"](220.0, 1.0, RATE),
                                RATE, 0.2, 0.9),
        "stab": _brightness(I.renderers()["stab"](220.0, 1.0, RATE), RATE,
                            0.2, 0.9),
    }
    assert order["reese"] < order["supersaw"] < order["stab"], order
    acid = I.renderers()["acid"](220.0, 1.0, RATE)
    assert _brightness(acid, RATE, 0.02, 0.2) > order["stab"], \
        "acid opens duller than the stab, so its sweep has nowhere to go"
