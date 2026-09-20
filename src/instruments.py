"""Synthesised instruments: flute, violin, strings, pluck, bell.

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


RENDERERS: dict[str, Callable[..., list[float]]] = {
    "flute": flute,
    "violin": violin,
    "strings": strings,
    "pluck": pluck,
    "bell": bell,
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
