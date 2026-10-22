"""Synthesised instruments: flute, violin, strings, pluck, bell, and the
supersaw / stab / acid / reese electronic voices.

``music.py`` arranges notes; this module gives a note a *timbre*. Each renderer
turns one pitch, one duration into a mono float buffer, the same contract as
:meth:`music._Mix.voice` but with a shape a wave table cannot express: a flute
that has to breathe, a violin whose vibrato arrives late, a pluck whose string
is physically shorter at high pitch.

Why not wave tables: a ``square`` is the same sound at every length, which is
exactly right for arps and wrong for anything lyrical. The two-voice melodies
this soundtrack wants (flute over violin) live or die on attack shape and
vibrato timing, and those are functions of time, not of phase.

Cost model. Everything here runs per-sample in CPython at 44.1 kHz beside a
mixer thread, so the rules are: a sine lookup table instead of ``math.sin``,
one phase accumulator per voice (harmonics are ``phase * h``, so a harmonic
stack costs lookups, not accumulators), envelopes by multiply-accumulate
instead of ``math.exp``, and a per-note cache keyed by
(name, pitch, length) — arrangements repeat their material constantly, which
is what keeps a 40 s cue from costing a minute of CPU. Rendering happens on
the audio thread; concurrent renders may compute the same note twice, which is
wasted work but never corrupted output, so no lock is taken.

Two entry points. :func:`note` renders one isolated note, cached, and is what a
wave-table arrangement wants. :func:`phrase` renders a *line* - the notes of a
melody played by one pair of hands, so it stops each note when the next begins,
slides connected small intervals the way a bowing hand moves, and lets vibrato
phase carry across the joins. A melody of stacked ``note`` calls sounds like a
sequencer; the same data through ``phrase`` sounds like a player.

Pure module: no pygame, no numpy, no files, deterministic.
"""

from __future__ import annotations

import math
from collections.abc import Callable

__all__ = ["NAMES", "note", "phrase", "is_instrument", "renderers"]

RATE = 44100

# --- portamento --------------------------------------------------------------
# A bowed instrument does not teleport between pitches. When the bow stays on the
# string and the hand moves, the pitch *travels*, exponentially, over 40-120 ms,
# and a player only bothers to slide intervals they can reach without a jump.
# ``phrase`` applies this; ``note`` accepts it so an arranger can place a single
# intentional slide.
PORTAMENTO = 0.075          # seconds of travel for a connected shift
PORT_MAX_SEMITONES = 4.5    # bigger leaps are shifted cleanly, as on a real neck
LEGATO_GAP = 0.055          # a note this close to the last one keeps the bow down
BOW_TAIL = 0.018            # the old note rings on for this long after its stop
VIB_RATE = 5.1              # Hz: the rate of a bowed vibrato
VIB_DELAY = 0.25            # seconds before it arrives on a new bow stroke
VIB_RISE = 0.30             # seconds to reach full width
GLIDES = frozenset({"violin", "flute"})

# --- lookup tables -----------------------------------------------------------
# 4096 entries of sine over one cycle. Quantisation error is ~1e-4 of full
# scale, which is below the noise floor of an 8-bit-era arrangement.
_STEPS = 4096
_MASK = _STEPS - 1
_SIN = [math.sin(2.0 * math.pi * i / _STEPS) for i in range(_STEPS)]


def _sin(phase: float) -> float:
    """Sine of ``phase`` cycles (phase wraps, so a float index is enough)."""
    return _SIN[int(phase * _STEPS) & _MASK]


def _lcg_noise(count: int, seed: int) -> list[float]:
    """Deterministic noise table (not ``random``: a shared global RNG would let
    an unrelated seed change the sound of an instrument)."""
    out = []
    state = seed & 0x7FFFFFFF or 1
    for _ in range(count):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        out.append(state / 1073741824.0 - 1.0)
    return out


_NOISE = _lcg_noise(2048, 0x5DEECE6)
_NOISE_MASK = len(_NOISE) - 1


def _noise(t: int) -> float:
    return _NOISE[t & _NOISE_MASK]


# --- envelopes ---------------------------------------------------------------
class _Env:
    """Smooth attack, held body, linear release - evaluated without exp/log.

    ``math.exp`` per sample is the most expensive thing an envelope can do in
    CPython, so the shape is piecewise: a smoothstep in, a flat sustain, a ramp
    out. Instruments that need a true exponential tail (the bell) carry their own
    running coefficient instead of using this.
    """

    __slots__ = ("attack", "release", "sustain", "total")

    def __init__(self, dur: float, attack: float, release: float,
                 sustain: float = 1.0) -> None:
        self.attack = attack
        self.release = release
        self.sustain = sustain
        self.total = dur

    def value(self, t: float) -> float:
        if t < self.attack:
            x = t / self.attack if self.attack > 0 else 1.0
            return x * x * (3.0 - 2.0 * x)          # smooth, click-free
        if t > self.total - self.release:
            x = (self.total - t) / self.release if self.release > 0 else 0.0
            return max(0.0, x) * self.sustain
        return self.sustain


# --- the instruments ---------------------------------------------------------
def flute(freq: float, dur: float, rate: int = RATE, vel: float = 1.0,
          *, port_from: float | None = None, port_time: float = PORTAMENTO,
          t_off: float = 0.0, noise_off: int = 0) -> list[float]:
    """Air column: fundamental plus weak partials, breath, late vibrato.

    The vibrato fades in over ~0.2 s because a flute that wobbles from the first
    millisecond sounds like a sampler; the real player's lip takes time to arrive.

    ``port_from`` slides in from that pitch, ``t_off`` is the note's start time
    inside a longer line (so the vibrato *phase* carries across note boundaries
    instead of restarting), and ``noise_off`` does the same for the breath.
    """
    n = max(2, int(dur * rate))
    out = [0.0] * n
    env = _Env(dur, min(0.05, dur * 0.2), min(0.09, dur * 0.3), 0.85)
    phase = 0.0
    vib_rate, vib_delay, vib_rise = 5.3, 0.18, 0.25
    pitch, ratio, ramp_left = _glide(freq, port_from, port_time, rate)
    # the lip starts wobbling after the slide has arrived, as a player's does
    vib_hold = max(vib_delay, port_time) if port_from is not None else vib_delay
    for i in range(n):
        t = i / rate
        vib_on = 0.0 if t < vib_hold else min(1.0, (t - vib_hold) / vib_rise)
        vib = _sin((t + t_off) * vib_rate) * 0.006 * vib_on
        p = phase
        y = (_sin(p) + 0.14 * _sin(2.0 * p) + 0.05 * _sin(3.0 * p)
             + 0.02 * _sin(4.0 * p))
        y *= 0.9
        # breath: loud for the first moment of the note, then a thin remainder
        breath = _noise((noise_off + i) >> 1) * (0.09 * (1.0 if t < 0.06
                                                        else 0.12))
        out[i] = (y + breath) * env.value(t) * vel
        if ramp_left > 0:
            pitch *= ratio
            ramp_left -= 1
            if ramp_left == 0:
                pitch = freq
        phase += (pitch / rate) * (1.0 + vib)
    return out


def _glide(freq: float, port_from: float | None, port_time: float,
           rate: int) -> tuple[float, float, int]:
    """Return ``(starting pitch, per-sample ratio, samples of travel)``.

    A real shift is exponential in pitch, which is a constant ratio per sample -
    one multiply, no ``pow`` in the loop. ``port_time`` of zero or a missing
    ``port_from`` means start on pitch, which is what ``note`` does.
    """
    if port_from is None or port_from <= 0.0 or port_time <= 0.0 or \
            abs(port_from - freq) < 0.01:
        return freq, 1.0, 0
    nport = max(1, int(port_time * rate))
    return port_from, math.pow(freq / port_from, 1.0 / nport), nport


def violin(freq: float, dur: float, rate: int = RATE, vel: float = 1.0,
           *, port_from: float | None = None, port_time: float = PORTAMENTO,
           t_off: float = 0.0, noise_off: int = 0) -> list[float]:
    """Bowed string: a harmonic ramp, a slow attack, wide late vibrato, bow hiss.

    Eight harmonics falling as 1/h reads as a bowed string against a saw, and
    the slow attack is what lets it sing a melody instead of punching it.

    Portamento: with ``port_from`` the note travels in from that pitch instead of
    appearing on it, and the phase runs continuously through the travel - the way
    a finger moving along the string changes pitch without breaking the bow. The
    vibrato waits for the slide to land, because that is what players do: arrive,
    then widen. ``t_off`` keeps the vibrato *phase* continuous across the notes of
    a line while the attack still restarts per bow stroke.
    """
    n = max(2, int(dur * rate))
    out = [0.0] * n
    env = _Env(dur, min(0.14, dur * 0.35), min(0.2, dur * 0.4), 0.8)
    phase = 0.0
    pitch, ratio, ramp_left = _glide(freq, port_from, port_time, rate)
    vib_hold = (max(VIB_DELAY, port_time) if port_from is not None
                else VIB_DELAY)
    for i in range(n):
        t = i / rate
        vib_on = 0.0 if t < vib_hold else min(1.0, (t - vib_hold) / VIB_RISE)
        p = phase
        y = 0.0
        for h in range(1, 9):
            y += _sin(p * h) / h
        y *= 0.55
        bow = _noise((noise_off + i) >> 2) * 0.022 * (
            0.4 + 0.6 * min(1.0, t / 0.1))
        out[i] = (y + bow) * env.value(t) * vel
        if ramp_left > 0:
            pitch *= ratio
            ramp_left -= 1
            if ramp_left == 0:
                pitch = freq          # land exactly: a slide must not drift
        phase += (pitch / rate) * (1.0 + _sin((t + t_off) * VIB_RATE)
                                   * 0.008 * vib_on)
    return out


def strings(freq: float, dur: float, rate: int = RATE, vel: float = 1.0) -> list[float]:
    """String section: three detuned bows, very slow attack, long release.

    Detuning by a few cents per voice is what turns one saw into a section; the
    beat frequency between them is the chorus, so the offsets are coprime-ish
    rather than identical.
    """
    n = max(2, int(dur * rate))
    out = [0.0] * n
    env = _Env(dur, min(0.3, dur * 0.4), min(0.45, dur * 0.5), 0.9)
    detunes = (0.9965, 1.0, 1.0043)
    phases = [0.0, 0.31, 0.67]
    steps = tuple(freq * d / rate for d in detunes)
    for i in range(n):
        t = i / rate
        y = 0.0
        for v in range(3):
            phases[v] += steps[v]
            p = phases[v]
            voice = 0.0
            for h in range(1, 6):
                voice += _sin(p * h) / h
            y += voice
        out[i] = y * 0.27 * env.value(t) * vel
    return out


# Partial amplitudes and how much faster each one dies than the one below it.
# A string's brightness is its partials, and they rot at different rates; that
# is the whole difference between a pluck and an organ holding one chord.
PLUCK_PARTIALS = (1.0, 0.52, 0.33, 0.19, 0.11)
PLUCK_ROTTEN = (1.0, 1.6, 2.3, 3.1, 4.0)


def pluck(freq: float, dur: float, rate: int = RATE, vel: float = 1.0) -> list[float]:
    """Plucked string: partials that die at different rates over one pitch.

    Karplus-Strong was tried first and rejected: with the averaging loop damped
    enough to sound like a string, a high note lost its fundamental inside
    40 ms, and the loop settled onto DC. Additive costs one lookup more per
    partial, stays exactly in tune at every length, and gives the same decay
    curve the delay line was only pretending to.
    """
    n = max(2, int(dur * rate))
    out = [0.0] * n
    steps = tuple(freq * (k + 1) / rate for k in range(len(PLUCK_PARTIALS)))
    phases = [0.0] * len(steps)
    # Per-sample coefficients: the fundamental is down to -94 dB by the end of
    # its own note, each partial above it faster, so the note starts bright and
    # ends as a low hum no matter how long the arrangement asked for.
    total = max(2, n)
    decays = tuple(pow(0.00002, PLUCK_ROTTEN[k] / total)
                   for k in range(len(steps)))
    level = [1.0] * len(steps)
    ramp = max(2, int(0.0008 * rate))        # the pick, not a click
    tail = max(1, n // 8)
    for i in range(n):
        y = 0.0
        for k in range(len(steps)):
            y += PLUCK_PARTIALS[k] * level[k] * _sin(phases[k])
            phases[k] += steps[k]
            level[k] *= decays[k]
        fade = 1.0 if i <= n - tail else (n - i) / tail
        if i < ramp:
            fade *= i / ramp
        out[i] = y * 0.45 * fade * vel
    return out


def bell(freq: float, dur: float, rate: int = RATE, vel: float = 1.0) -> list[float]:
    """FM bell: a sine carrier bent by an inharmonic modulator that dies away.

    One operator with a decaying index gives the glassy, non-harmonic strike that
    no additive wave has, for two lookups and one running coefficient.
    """
    n = max(2, int(dur * rate))
    out = [0.0] * n
    phase = 0.0
    mphase = 0.0
    step = freq / rate
    mstep = freq * 3.5 / rate          # inharmonic: reads as metal, not as a chord
    idx = 4.0
    # -60 dB across the note's own length: a bell rings and stops rather than
    # holding. One pow per note, then a multiply per sample.
    amp_decay = pow(0.001, 1.0 / max(1.0, float(n)))
    idx_decay = pow(0.02, 1.0 / max(1.0, float(n)))
    amp = 1.0
    ramp = max(2, int(0.0012 * rate))   # ~1 ms, so the strike is not a click
    tail = max(1, n // 6)
    for i in range(n):
        y = _sin(phase + idx * _sin(mphase)) + 0.18 * _sin(2.0 * phase)
        fade = 1.0 if i <= n - tail else (n - i) / tail
        if i < ramp:
            fade *= i / ramp
        out[i] = y * amp * fade * vel
        phase += step
        mphase += mstep
        amp *= amp_decay
        idx *= idx_decay
    return out


# --- electronic voices: the trance / electro palette -----------------------
# The acoustic instruments above buy expressiveness. These buy *current*: a
# supersaw pad, a gated stab, a resonant bass line, a reese. They are still
# additive stacks rather than waveforms run through a live filter, because a
# biquad per sample per voice does not fit inside a soundtrack that already
# renders on a background thread beside a mixer. Where a filter is the whole
# point (``acid``) the filter is expressed as amplitudes over the harmonic
# series, which is the same thing a filter does to a saw, and costs a handful of
# multiplies per harmonic instead of a filter state per sample.

# Three detunings, deliberately not evenly spaced: evenly spaced detuning puts
# the beat frequencies at the same pitch and the chorus collapses into one
# pulsing voice. Coprime-ish offsets make the beating wander instead.
SUPER_DETUNE = (0.9951, 1.0, 1.0043)
SUPER_HARMONICS = 6

# The acoustic instruments above arrive at predictable peaks because the
# arrangements that use them were balanced against them by ear. A new voice has
# no such history, so it is levelled on the way out: otherwise handing a slot to
# ``supersaw`` instead of ``strings`` would change the mix balance as a side
# effect of changing the timbre, and the arrangement number would stop meaning
# what it says.
INSTRUMENT_PEAK = 0.95


def _level(buf: list[float], target: float = INSTRUMENT_PEAK) -> list[float]:
    """Scale a whole rendered note to ``target`` peak (its shape is untouched)."""
    peak = 0.0
    for v in buf:
        a = -v if v < 0 else v
        if a > peak:
            peak = a
    if peak <= 0.0:
        return buf
    g = target / peak
    return [v * g for v in buf]


def _saw_stack(phase: float, harmonics: int, rolloff: float) -> float:
    """Band-limited saw: the first ``harmonics`` partials, amplitude 1/h^
    ``rolloff``.

    A naive saw is the same sound at every pitch, which is exactly what makes a
    synth bass rip at low notes and buzz at high ones. Raising the rolloff
    trades upper partials for warmth, and that trade - not the waveform name -
    is what separates a trance lead from an acid line.
    """
    y = 0.0
    for h in range(1, harmonics + 1):
        y += _sin(phase * h) / (h ** rolloff)
    return y


def supersaw(freq: float, dur: float, rate: int = RATE,
             vel: float = 1.0) -> list[float]:
    """Detuned saw stack: the pad and lead voice of trance.

    Width comes from beats, not from loudness: three saws detuned by a few cents
    each sweep in and out of phase, and the outer two also breathe on a slow
    amplitude LFO so the pad moves even while one chord is held. That LFO is
    nearly free (two multiplies) and it is the difference between a pad and an
    organ holding a note.
    """
    n = max(2, int(dur * rate))
    out = [0.0] * n
    env = _Env(dur, min(0.06, dur * 0.25), min(0.35, dur * 0.45), 0.88)
    phases = [0.0, 0.23, 0.61]
    steps = tuple(freq * d / rate for d in SUPER_DETUNE)
    trem = 0.0
    trem_step = 2.0 * math.pi / rate * 0.9     # under a Hz: a swell, not a wobble
    for i in range(n):
        t = i / rate
        swell = 1.0 + 0.16 * math.sin(trem)
        y = 0.0
        for v in range(len(steps)):
            p = phases[v]
            # the outer pair breathes against each other; the middle holds
            amp = 1.0 if v == 1 else swell
            y += _saw_stack(p, SUPER_HARMONICS, 1.25) * amp
            phases[v] = p + steps[v]
        out[i] = y * 0.19 * env.value(t) * vel
        trem += trem_step
    return _level(out)


def stab(freq: float, dur: float, rate: int = RATE, vel: float = 1.0) -> list[float]:
    """Gated stab: a chord tone slammed on and cut off, the house/trance chop.

    The envelope is the timbre here. A three-millisecond attack and a hard
    forty-millisecond release make the note a *percussion* hit even when the
    arrangement wrote it at lead pitch; the same harmonics under a slow envelope
    would just be a dull pad. Two detunings are enough - a stab's width has to
    survive being cut short, and a wide stack with a fast gate beats against
    itself into mush.
    """
    n = max(2, int(dur * rate))
    out = [0.0] * n
    env = _Env(dur, min(0.0035, dur * 0.15), min(0.04, dur * 0.3), 1.0)
    phases = [0.0, 0.37]
    steps = (freq * 0.9968 / rate, freq * 1.0055 / rate)
    for i in range(n):
        y = 0.0
        for v in range(2):
            y += _saw_stack(phases[v], 5, 0.85)
            phases[v] += steps[v]
        out[i] = y * 0.34 * env.value(i / rate) * vel
    return _level(out)


# Acid: where the resonant peak starts, where it lands, and how wide a band of
# harmonics it lets through on the way down. The sweep *is* the performance.
ACID_C0 = 4200.0            # peak opens up here (Hz)
ACID_C1 = 300.0             # ...and falls to here
ACID_Q = 3.2                # resonance height at the peak
ACID_BAND = 0.75            # peak width as a fraction of the cutoff
ACID_TAIL = 0.35            # fraction of the note over which the sweep happens


def acid(freq: float, dur: float, rate: int = RATE, vel: float = 1.0) -> list[float]:
    """Resonant saw with a falling filter envelope: the 303 / electro bass.

    A real resonant low-pass is a feedback filter, and running one per note per
    sample is the expensive way to do it. The harmonics of a saw are discrete
    samples of the same spectrum, so shaping them with a moving peak gives the
    identical gesture - partials below the peak pass, the partial at the peak is
    pushed up by ``Q``, everything above falls off - for a few flops per
    harmonic. The peak travels exponentially (multiplying a constant per sample,
    the way a knob turn is exponential in frequency), and it stops early so the
    note ends closed, which is the "wah" a player leaves in the tail.
    """
    n = max(2, int(dur * rate))
    out = [0.0] * n
    harmonics = 12
    fh = tuple(freq * h for h in range(1, harmonics + 1))
    phases = [h * freq / rate * 0.11 for h in range(1, harmonics + 1)]
    steps = tuple(fh[h] / rate for h in range(harmonics))
    sweep_n = max(1, int(dur * ACID_TAIL * rate))
    ratio = pow(ACID_C1 / ACID_C0, 1.0 / sweep_n)
    cut = ACID_C0
    env = _Env(dur, min(0.002, dur * 0.1), min(0.05, dur * 0.25), 0.9)
    for i in range(n):
        if i < sweep_n:
            cut *= ratio
        inv = 1.0 / cut
        band = cut * ACID_BAND
        y = 0.0
        for h in range(harmonics):
            f = fh[h]
            # soft rolloff above the peak, and the peak itself pushed up: one
            # divide and one abs per partial, no logs and no exponentials
            over = f * inv
            amp = 1.0 / (1.0 + over * over * 2.2)
            near = 1.0 - abs(f - cut) / band
            if near > 0.0:
                amp += near * ACID_Q * 0.25
            y += amp * _sin(phases[h])
            phases[h] += steps[h]
        out[i] = y * 0.16 * env.value(i / rate) * vel
    return _level(out)


# A reese is two saws slightly apart: the beating between them is the whole
# effect, so the detuning is musical (a quarter tone) rather than a chorus trick.
REESE_DETUNE = 1.0142
REESE_HARMONICS = 6


def reese(freq: float, dur: float, rate: int = RATE, vel: float = 1.0) -> list[float]:
    """Reese bass: two detuned saws plus a sub, beating as one moves.

    The sub sine is not decoration. A reese played through small speakers loses
    its fundamental entirely, and an electro bass whose root vanishes in the room
    reads as a fuzzy texture rather than a note; the sine keeps the pitch while
    the saws keep the snarl.
    """
    n = max(2, int(dur * rate))
    out = [0.0] * n
    phases = [0.0, 0.41]
    steps = (freq / rate, freq * REESE_DETUNE / rate)
    env = _Env(dur, min(0.006, dur * 0.2), min(0.08, dur * 0.3), 0.92)
    sub_step = freq * 0.5 / rate
    sub_ph = 0.0
    for i in range(n):
        t = i / rate
        y = (_saw_stack(phases[0], REESE_HARMONICS, 1.15)
             + _saw_stack(phases[1], REESE_HARMONICS, 1.15) * 0.95)
        phases[0] += steps[0]
        phases[1] += steps[1]
        y += _sin(sub_ph) * 0.8
        sub_ph += sub_step
        out[i] = y * 0.22 * env.value(t) * vel
    return _level(out)


RENDERERS: dict[str, Callable[..., list[float]]] = {
    "flute": flute,
    "violin": violin,
    "strings": strings,
    "pluck": pluck,
    "bell": bell,
    "supersaw": supersaw,
    "stab": stab,
    "acid": acid,
    "reese": reese,
}
NAMES = tuple(sorted(RENDERERS))

# --- dispatch + cache --------------------------------------------------------
_CACHE: dict[tuple, tuple[float, ...]] = {}
_CACHE_LIMIT = 40000


def is_instrument(name: str) -> bool:
    """True when ``name`` is one of ours (anything else is a raw wave)."""
    return name in RENDERERS


def renderers() -> dict[str, Callable[..., list[float]]]:
    return RENDERERS


def note(name: str, freq: float, dur: float, rate: int = RATE,
         vel: float = 1.0) -> list[float]:
    """Render one note of ``name``; falls back to a plain sine for unknown names.

    Frequencies and lengths are quantised before the cache key because an
    arrangement plays the same scale degrees over and over, and re-rendering a
    flute G is pure waste.
    """
    if freq <= 0.0 or dur <= 0.0:
        return []
    key = (name, round(freq, 2), round(dur, 3), rate)
    hit = _CACHE.get(key)
    if hit is not None:
        return list(hit)
    render = RENDERERS.get(name)
    if render is None:
        n = max(2, int(dur * rate))
        env = _Env(dur, 0.01, 0.05, 0.9)
        buf = [_sin(i * freq / rate) * env.value(i / rate) * vel
               for i in range(n)]
    else:
        buf = render(freq, dur, rate, vel)
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.clear()
    _CACHE[key] = tuple(buf)
    return list(buf)


# --- connected lines ---------------------------------------------------------
def _semitones(a: float, b: float) -> float:
    return abs(12.0 * math.log2(a / b)) if a > 0.0 and b > 0.0 else 99.0


def _place(buf: list[float], s0: int, samples: list[float]) -> None:
    end = min(s0 + len(samples), len(buf))
    for i in range(s0, end):
        buf[i] += samples[i - s0]


def phrase(name: str, notes: list[tuple[float, float, float]], rate: int = RATE,
           vel: float = 1.0, *, portamento: float = PORTAMENTO,
           max_semitones: float = PORT_MAX_SEMITONES,
           gap: float = LEGATO_GAP) -> list[float]:
    """Render ``notes`` - ``(start, dur, freq)`` in seconds and Hz - as one player.

    ``note`` cannot express a melody, only its atoms: stacked independent notes
    ring over each other, every one of them re-attacks, and the vibrato starts
    from nothing four times a bar. Three things make a line read as one pair of
    hands on one instrument:

    *   a note stops when the next one begins (plus :data:`BOW_TAIL`) instead of
        sounding under it, because one bow makes one pitch at a time;
    *   a connected shift *travels* in from the previous pitch when it is small
        enough to be a position change; a leap larger than ``max_semitones`` is
        placed cleanly, which is exactly what a player does with a wide interval;
    *   vibrato phase and bow noise carry across the boundary while the attack
        still restarts per stroke.

    ``gap`` is how close a note has to arrive to keep the bow down. Instruments
    that cannot slide (``pluck``, ``bell``, ``strings``) are placed note by note,
    ringing as they please, through the same cache ``note`` uses.
    """
    items = sorted(((float(s), float(d), float(f)) for s, d, f in notes),
                   key=lambda item: item[0])
    items = [item for item in items if item[1] > 0.0 and item[2] > 0.0]
    if not items:
        return []
    glide = name in GLIDES
    render = RENDERERS.get(name)
    out = [0.0] * (int(max(s + d for s, d, _ in items) * rate) + 2)

    for index, (start, dur, freq) in enumerate(items):
        previous = items[index - 1] if index else None
        following = items[index + 1] if index + 1 < len(items) else None
        length = dur
        if glide and following is not None:
            length = min(dur, max(following[0] - start, 0.0) + BOW_TAIL)

        port_from = None
        if glide and previous is not None and portamento > 0.0:
            connected = previous[0] + previous[1] >= start - gap
            shift = _semitones(freq, previous[2])
            if connected and 0.0 < shift <= max_semitones:
                port_from = previous[2]

        if render is None or not glide:
            _place(out, int(start * rate), note(name, freq, length, rate, vel))
            continue
        _place(out, int(start * rate),
               render(freq, length, rate, vel, port_from=port_from,
                      port_time=portamento, t_off=start,
                      noise_off=int(start * rate)))
    return out
