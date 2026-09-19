"""Procedural drum kit: a tiny deterministic ROMpler for the music engine.

Why samples instead of per-hit synthesis
----------------------------------------
The music renderer is pure Python and already spends ~100 s building the whole
soundtrack on a background thread. A drum hit used to be re-synthesised at the
call site (noise x decay, or a triangle with a pitch ramp), which capped how
much shaping was affordable per hit - and cheap shaping is exactly why the kit
sounded like "shhh" and "boof" instead of drums.

Here each voice is rendered *once* per kit into an enveloped sample, and a hit
is one additive copy of that sample (one add, one multiply per sample). That
buys, per voice:

* **kick**   exponential pitch glide (155 -> 48 Hz) on a sine body, a separate
  fast "beater punch" partial one octave up, a high-passed noise click, and
  baked-in soft saturation so the transient rounds off instead of clipping.
* **snare**  two inharmonic membrane partials (185 Hz and 1.78x it), a body
  that dies faster than the noise wash, band-passed "wires" noise, and a 5 ms
  high-passed snap. Body-faster-than-wash is what separates a snare from a
  burst of hiss.
* **hat**    a metal ring from six *inharmonic* sine partials (the TR-808 hat
  ratio set) with per-partial decay, high-pass then band-pass shaped, plus the
  "chick" of the pedals. Open variant = the same ring, longer, dimmer.
* **ride / crash** wider partial sets and long rings; the ride adds a slow
  band-passed ping, the crash a pink-noise wash and a surviving bell partial.
* **tom**    sine with a small downward glide plus a filtered noise attack,
  rendered at eight tuned pitches so fills are musical, not noise.
* **rim / clap** very short band-passed bursts: the rim is dry, the clap is
  four staggered bursts with a tail (the industrial DKC flavour).

Nothing here reads a file and everything is seeded, so a build is bit-identical
and the whole kit costs a few hundred milliseconds the first time it is used.
Kit *parameters* (pitch, decay, brightness, level) are data and live in
:mod:`music_content` as ``KITS``; the patterns live there as ``GROOVES``. This
module only turns parameters into samples.
"""
from __future__ import annotations

import math
import random
import threading

from audio import MIXER_RATE as RATE

# --- noise banks ----------------------------------------------------------
# Fixed-length banks (power of two, so hit indexing wraps with a mask): white
# for bright transients, and a pink bank whose energy falls off with frequency,
# which is what makes a snare wash read as "airy" instead of "hissy".
_BANK_BITS = 13
_BANK_LEN = 1 << _BANK_BITS
_BANK_MASK = _BANK_LEN - 1


def _white(seed: int) -> tuple[float, ...]:
    rnd = random.Random(seed)
    return tuple(rnd.uniform(-1.0, 1.0) for _ in range(_BANK_LEN))


def _pink(seed: int) -> tuple[float, ...]:
    """Paul Kellet's pink filter over white noise (roughly -3 dB/octave)."""
    rnd = random.Random(seed)
    out: list[float] = []
    b = [0.0] * 7
    for _ in range(_BANK_LEN):
        w = rnd.uniform(-1.0, 1.0)
        b[0] = 0.99886 * b[0] + w * 0.0555179
        b[1] = 0.99332 * b[1] + w * 0.0750759
        b[2] = 0.96900 * b[2] + w * 0.1538520
        b[3] = 0.64538 * b[3] + w * 0.3104856
        b[4] = -0.40190 * b[4] - w * 0.1386200
        b[6] = w * 0.115926
        out.append((sum(b[:5]) + b[5] + b[6] * 0.5 + w * 0.5362) * 0.11)
        b[5] = b[6]
    return tuple(out)


WHITE = _white(0x5EED)
WHITE_ALT = _white(0xD0DE)
PINK = _pink(0xC0FFEE)


# --- filters ---------------------------------------------------------------
def _biquad(signal: list[float], rate: int, f0: float, q: float,
            kind: str) -> list[float]:
    """RBJ biquad, one pass. ``kind`` is 'lp', 'hp' or 'bp' (peak-gain).

    ``f0`` is clamped under Nyquist: at 22050 Hz there is no point designing an
    9 kHz band-pass, and coefficients above Nyquist are unstable (the filter
    sings, or explodes).
    """
    fs = float(rate)
    f0 = min(max(f0, 20.0), fs * 0.45)
    q = max(q, 0.05)
    w = 2.0 * math.pi * f0 / fs
    cw, sw = math.cos(w), math.sin(w)
    alpha = sw / (2.0 * q)
    if kind == 'hp':
        b0, b1, b2 = (1.0 + cw) / 2.0, -(1.0 + cw), (1.0 + cw) / 2.0
    elif kind == 'lp':
        b0, b1, b2 = (1.0 - cw) / 2.0, 1.0 - cw, (1.0 - cw) / 2.0
    else:
        b0, b1, b2 = alpha, 0.0, -alpha
    a0, a1, a2 = 1.0 + alpha, -2.0 * cw, 1.0 - alpha
    b0, b1, b2 = b0 / a0, b1 / a0, b2 / a0
    a1, a2 = a1 / a0, a2 / a0
    x1 = x2 = y1 = y2 = 0.0
    out = [0.0] * len(signal)
    for i, xn in enumerate(signal):
        yn = b0 * xn + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x1, x2 = xn, x1
        y1, y2 = yn, y1
        out[i] = yn
    return out


def _soft_tanh(values: list[float], drive: float) -> tuple[float, ...]:
    """Soft saturation: ``drive`` 1.0 is linear, 2.0+ audibly rounder.

    Baking this into the *sample* (not the mix) means the kit's transient
    headroom is free at playback time.
    """
    if drive <= 1.001:
        return tuple(values)
    norm = math.tanh(drive)
    return tuple(math.tanh(v * drive) / norm for v in values)


def _envelope(n: int, rate: int, decay: float, attack: float = 0.0004,
              floor: float = 0.0) -> list[float]:
    """Linear attack, exponential decay, optional floor (rides keep ringing)."""
    atk = max(1, min(int(attack * rate), n))
    k = math.exp(-decay / float(rate))
    env = [0.0] * n
    e = 1.0
    for i in range(n):
        if i < atk:
            env[i] = i / atk
            continue
        if i > atk:
            e *= k
        env[i] = e if not floor else (e if e > floor else floor)
    return env


def _normalise(sig: list[float], target: float, drive: float
               ) -> tuple[float, ...]:
    """Saturate *first*, then scale to ``target``.

    The order matters: tanh after scaling pushes peaks back over the target
    (a 0.90 peak with drive 1.7 lands at ~0.96), which eats the headroom the
    rest of the mix needs.
    """
    shaped = list(_soft_tanh(sig, drive))
    peak = 0.0
    for v in shaped:
        a = -v if v < 0 else v
        if a > peak:
            peak = a
    if peak <= 0:
        return tuple(shaped)
    scale = target / peak
    return tuple(v * scale for v in shaped)


# --- voice renderers -------------------------------------------------------
# Every renderer returns an already-enveloped, soft-saturated mono sample.
# Parameters come from music_content.KITS.

KICK_DEFAULTS = {"f0": 155.0, "f1": 48.0, "glide": 0.030, "decay": 7.2,
                 "punch": 0.5, "punch_dec": 26.0, "click": 0.45,
                 "click_f": 2600.0, "click_dur": 0.006, "body": 1.0,
                 "sat": 1.7, "dur": 0.42}


def render_kick(rate: int, p: dict) -> tuple[float, ...]:
    q = dict(KICK_DEFAULTS)
    q.update(p)
    n = int(q["dur"] * rate)
    sig = [0.0] * n
    f0, f1 = q["f0"], q["f1"]
    tau = max(q["glide"], 0.004)
    kb = math.exp(-q["decay"] / rate)
    kp = math.exp(-q["punch_dec"] / rate)
    atk = max(1, int(0.0008 * rate))
    e_body = e_punch = 1.0
    ph = 0.0
    for i in range(n):
        t = i / rate
        f = f1 + (f0 - f1) * math.exp(-t / tau)
        ph += f / rate
        if ph >= 1.0:
            ph -= 1.0
        if i < atk:
            r = i / atk
            e_body = e_punch = r
        else:
            if i > atk:
                e_body *= kb
                e_punch *= kp
        sig[i] = (math.sin(2.0 * math.pi * ph) * e_body * q["body"]
                  + math.sin(4.0 * math.pi * ph) * e_punch * q["punch"] * 0.5)
    cn = max(4, int(q["click_dur"] * rate))
    click = [WHITE[(i * 3 + 17) & _BANK_MASK] for i in range(cn)]
    click = _biquad(click, rate, q["click_f"], 0.7, "hp")
    cen = _envelope(cn, rate, 120.0, 0.0002)
    for i in range(cn):
        sig[i] += click[i] * cen[i] * q["click"]
    return _normalise(sig, 0.92, q["sat"])


SNARE_DEFAULTS = {"body_f": 185.0, "ratio": 1.78, "body_dec": 42.0,
                  "body_mix": 0.5, "noise_f": 1900.0, "noise_q": 0.85,
                  "noise_dec": 25.0, "wash": 0.8, "snap": 0.5,
                  "snap_f": 3600.0, "snap_dur": 0.005, "sat": 1.35,
                  "dur": 0.30}


def render_snare(rate: int, p: dict) -> tuple[float, ...]:
    q = dict(SNARE_DEFAULTS)
    q.update(p)
    n = int(q["dur"] * rate)
    sig = [0.0] * n
    f_a = q["body_f"]
    f_b = q["body_f"] * q["ratio"]
    ka = math.exp(-q["body_dec"] / rate)
    kb = math.exp(-q["body_dec"] * 1.4 / rate)
    atk = max(1, int(0.0004 * rate))
    e_a = e_b = 0.0
    pa = pb = 0.0
    for i in range(n):
        pa += f_a / rate
        pb += f_b / rate
        if pa >= 1.0:
            pa -= 1.0
        if pb >= 1.0:
            pb -= 1.0
        if i < atk:
            e_a = e_b = i / atk
        else:
            if i > atk:
                e_a *= ka
                e_b *= kb
        sig[i] = (math.sin(2.0 * math.pi * pa) * e_a
                  + math.sin(2.0 * math.pi * pb) * e_b * 0.6) * q["body_mix"]
    # the "wires": band-passed noise whose decay is *slower* than the head
    noise = [WHITE_ALT[i & _BANK_MASK] for i in range(n)]
    noise = _biquad(noise, rate, q["noise_f"], q["noise_q"], "bp")
    nenv = _envelope(n, rate, q["noise_dec"], 0.0003)
    for i in range(n):
        sig[i] += noise[i] * nenv[i] * q["wash"]
    sn = max(4, int(q["snap_dur"] * rate))
    snap = [WHITE[i & _BANK_MASK] for i in range(sn)]
    snap = _biquad(snap, rate, q["snap_f"], 0.6, "hp")
    senv = _envelope(sn, rate, 160.0, 0.0002)
    for i in range(sn):
        sig[i] += snap[i] * senv[i] * q["snap"]
    return _normalise(sig, 0.90, q["sat"])


# TR-808 hat partial ratios. Rendered as sines rather than squares so nothing
# folds back over 11 kHz at our 22.05 kHz mixer rate.
HAT_RATIOS = (1.0, 1.5091, 1.8943, 2.2571, 2.7339, 3.6649)
CRASH_RATIOS = (1.0, 1.2737, 1.6131, 1.9903, 2.5217, 3.0709, 3.8813, 4.9141)


def _metal(rate: int, dur: float, base: float, ratios: tuple[float, ...],
           decay: float, hp: float, hp_q: float, bp: float,
           noise: float, partial_fall: float, shimmer: float,
           offset: int) -> list[float]:
    """Inharmonic partial stack -> high-pass -> band-pass (``bp`` 0 = skip) -> noise.

    Upper partials are quieter *and* die sooner (``partial_fall``): that is the
    sizzle. A slow wobble on each partial's phase stops the ring from sounding
    like a static organ chord.
    """
    n = max(int(dur * rate), 8)
    sig = [0.0] * n
    for idx, ratio in enumerate(ratios):
        f = base * ratio
        if f >= rate * 0.45:
            continue
        k = math.exp(-decay * (1.0 + partial_fall * idx * 0.5) / rate)
        amp = 1.0 / (1.0 + 0.35 * idx)
        ph = (offset * 0.137 * (idx + 1)) % 1.0
        wob = 0.0
        e = 1.0
        for i in range(n):
            ph += f / rate
            if ph >= 1.0:
                ph -= 1.0
            wob += shimmer / rate
            sig[i] += math.sin(2.0 * math.pi * (ph + 0.02 * math.sin(wob))) \
                * e * amp
            e *= k
    sig = _biquad(sig, rate, hp, hp_q, "hp")
    if bp:
        band = _biquad(sig, rate, bp, 0.8, "bp")
        for i in range(n):
            sig[i] = sig[i] * 0.55 + band[i] * 0.85
    if noise:
        kn = math.exp(-decay / rate)
        e = 1.0
        for i in range(n):
            sig[i] += WHITE_ALT[(i * 3 + offset) & _BANK_MASK] * noise * e
            e *= kn
    return sig


HAT_DEFAULTS = {"base": 810.0, "decay": 62.0, "hp": 5200.0, "hp_q": 0.7,
                "bp": 8300.0, "noise": 0.2, "partial_fall": 0.9,
                "shimmer": 6.0, "chick": 0.45, "chick_dur": 0.0015,
                "gate": 0.0, "dur": 0.055, "decay_scale": 1.0, "sat": 1.15}


def render_hat(rate: int, p: dict) -> tuple[float, ...]:
    q = dict(HAT_DEFAULTS)
    q.update(p)
    dur = max(q["dur"], 0.01)
    sig = _metal(rate, dur, q["base"], HAT_RATIOS,
                 q["decay"] * q["decay_scale"], q["hp"], q["hp_q"], q["bp"],
                 q["noise"], q["partial_fall"], q["shimmer"], offset=7)
    n = len(sig)
    env = _envelope(n, rate, 3.2 / dur, 0.0002, floor=q["gate"])
    for i in range(n):
        sig[i] *= env[i]
    cn = max(4, int(q["chick_dur"] * rate))
    for i in range(cn):
        sig[i] += WHITE[(i * 5 + 3) & _BANK_MASK] * q["chick"] * (1.0 - i / cn)
    return _normalise(sig, 0.88, q["sat"])


OPEN_DEFAULTS = {"dur": 0.34, "decay_scale": 0.16, "gate": 0.0}


def render_open(rate: int, p: dict) -> tuple[float, ...]:
    q = dict(OPEN_DEFAULTS)
    q.update(p)
    hat = dict(HAT_DEFAULTS)
    hat.update({k: v for k, v in p.items() if k in HAT_DEFAULTS})
    hat["dur"] = q["dur"]
    hat["decay_scale"] = q["decay_scale"]
    hat["gate"] = q["gate"]
    return render_hat(rate, hat)


CRASH_DEFAULTS = {"base": 300.0, "decay": 4.2, "hp": 1500.0, "hp_q": 0.6,
                  "bp": 0.0, "noise": 0.45, "partial_fall": 0.22,
                  "shimmer": 3.0, "dur": 1.15, "wash_dec": 3.4,
                  "bell": 3150.0, "bell_level": 0.14, "sat": 1.25}


def render_crash(rate: int, p: dict) -> tuple[float, ...]:
    q = dict(CRASH_DEFAULTS)
    q.update(p)
    sig = _metal(rate, q["dur"], q["base"], CRASH_RATIOS, q["decay"],
                 q["hp"], q["hp_q"], q["bp"], q["noise"], q["partial_fall"],
                 q["shimmer"], offset=23)
    n = len(sig)
    wash = [PINK[i & _BANK_MASK] for i in range(n)]
    wash = _biquad(wash, rate, 4200.0, 0.5, "hp")
    wenv = _envelope(n, rate, q["wash_dec"], 0.001)
    for i in range(n):
        sig[i] = sig[i] * 0.8 + wash[i] * wenv[i] * 0.35
    if q["bell_level"]:
        kb = math.exp(-2.6 / rate)
        e = 1.0
        ph = 0.0
        for i in range(n):
            ph += q["bell"] / rate
            if ph >= 1.0:
                ph -= 1.0
            e *= kb
            sig[i] += math.sin(2.0 * math.pi * ph) * e * q["bell_level"]
    env = _envelope(n, rate, 2.4 / q["dur"], 0.0008)
    for i in range(n):
        sig[i] *= env[i]
    return _normalise(sig, 0.88, q["sat"])


RIDE_DEFAULTS = {"base": 420.0, "decay": 6.5, "hp": 2600.0, "hp_q": 0.6,
                 "bp": 5200.0, "noise": 0.18, "partial_fall": 0.35,
                 "shimmer": 2.2, "dur": 0.62, "ping": 4300.0,
                 "ping_level": 0.2, "gate": 0.02}


def render_ride(rate: int, p: dict) -> tuple[float, ...]:
    q = dict(RIDE_DEFAULTS)
    q.update(p)
    sig = _metal(rate, q["dur"], q["base"], CRASH_RATIOS, q["decay"],
                 q["hp"], q["hp_q"], q["bp"], q["noise"], q["partial_fall"],
                 q["shimmer"], offset=41)
    n = len(sig)
    kb = math.exp(-3.2 / rate)
    e = 1.0
    ph = 0.0
    for i in range(n):
        ph += q["ping"] / rate
        if ph >= 1.0:
            ph -= 1.0
        e *= kb
        sig[i] += math.sin(2.0 * math.pi * ph) * e * q["ping_level"]
    env = _envelope(n, rate, 2.6 / q["dur"], 0.0004, floor=q["gate"])
    for i in range(n):
        sig[i] *= env[i]
    return _normalise(sig, 0.86, 1.0)


TOM_DEFAULTS = {"decay": 8.5, "glide": -0.10, "glide_t": 0.055,
                "noise": 0.14, "noise_f": 900.0, "dur": 0.34, "sat": 1.3}


def render_tom(rate: int, freq: float, p: dict) -> tuple[float, ...]:
    q = dict(TOM_DEFAULTS)
    q.update(p)
    n = int(q["dur"] * rate)
    sig = [0.0] * n
    k = math.exp(-q["decay"] / rate)
    atk = max(1, int(0.0006 * rate))
    tau = max(q["glide_t"], 0.006)
    e = 0.0
    ph = 0.0
    for i in range(n):
        t = i / rate
        f = freq * (1.0 + q["glide"] * math.exp(-t / tau))
        ph += f / rate
        if ph >= 1.0:
            ph -= 1.0
        if i < atk:
            e = i / atk
        elif i > atk:
            e *= k
        sig[i] = (math.sin(2.0 * math.pi * ph) * e
                  + math.sin(4.0 * math.pi * ph) * e * e * 0.22)
    nz_n = min(n, 600)
    nz = _biquad([WHITE_ALT[i & _BANK_MASK] for i in range(nz_n)],
                 rate, q["noise_f"], 1.0, "bp")
    for i in range(nz_n):
        sig[i] += nz[i] * q["noise"] * (1.0 - i / nz_n)
    return _normalise(sig, 0.90, q["sat"])


RIM_DEFAULTS = {"f": 2100.0, "q": 6.0, "blip": 620.0, "blip_dec": 170.0,
                "blip_level": 0.32, "dur": 0.04}


def render_rim(rate: int, p: dict) -> tuple[float, ...]:
    q = dict(RIM_DEFAULTS)
    q.update(p)
    n = max(int(q["dur"] * rate), 8)
    sig = [WHITE[(i * 7 + 91) & _BANK_MASK] for i in range(n)]
    sig = _biquad(sig, rate, q["f"], q["q"], "bp")
    env = _envelope(n, rate, 190.0, 0.0002)
    kb = math.exp(-q["blip_dec"] / rate)
    e = 1.0
    ph = 0.0
    for i in range(n):
        ph += q["blip"] / rate
        if ph >= 1.0:
            ph -= 1.0
        e *= kb
        sig[i] = sig[i] * env[i] + math.sin(2.0 * math.pi * ph) * e \
            * q["blip_level"] * 0.4
    peak = max(abs(v) for v in sig) or 1.0
    return tuple(v * 0.85 / peak for v in sig)


CLAP_DEFAULTS = {"f": 1150.0, "q": 1.3, "bursts": 4, "spacing": 0.011,
                 "tail_dec": 13.0, "dur": 0.30}


def render_clap(rate: int, p: dict) -> tuple[float, ...]:
    q = dict(CLAP_DEFAULTS)
    q.update(p)
    n = int(q["dur"] * rate)
    sig = [PINK[i & _BANK_MASK] for i in range(n)]
    sig = _biquad(sig, rate, q["f"], q["q"], "bp")
    gap = max(2, int(q["spacing"] * rate))
    bursts = max(1, int(q["bursts"]))
    env = [0.0] * n
    for b in range(bursts):
        start = b * gap
        top = start + max(1, gap // 3)
        for i in range(start, min(n, top)):
            env[i] += (i - start) / (top - start) * (1.0 - b * 0.12)
    # After the burst train the clap keeps ringing as a short body; without
    # this the sample is silence past the last burst and reads as a click.
    tail_start = bursts * gap
    if tail_start < n:
        level = 0.55 * (1.0 - 0.12 * (bursts - 1))
        for i in range(tail_start, n):
            env[i] = level
    k = math.exp(-q["tail_dec"] / rate)
    e = 1.0
    for i in range(n):
        env[i] *= e
        e *= k
    for i in range(n):
        sig[i] *= env[i]
    peak = max(abs(v) for v in sig) or 1.0
    return tuple(v * 0.86 / peak for v in sig)


# --- kit assembly ----------------------------------------------------------
# Toms are a pitch *table*: a fill asks for a frequency and gets the nearest
# pre-rendered one, so tom pitches stay musical without a render per call.
TOM_FREQS = (98.0, 116.0, 138.0, 165.0, 196.0, 233.0, 277.0, 330.0)

RENDERERS = {
    "kick": render_kick,
    "snare": render_snare,
    "hat": render_hat,
    "open": render_open,
    "crash": render_crash,
    "ride": render_ride,
    "rim": render_rim,
    "clap": render_clap,
}

_KIT_CACHE: dict[tuple[str, int], dict] = {}
_LOCK = threading.Lock()


def kit_samples(name: str, params: dict, rate: int = RATE) -> dict:
    """Render (or return cached) one kit: voice samples + per-voice gain."""
    key = (name, rate)
    cached = _KIT_CACHE.get(key)
    if cached is not None:
        return cached
    with _LOCK:
        cached = _KIT_CACHE.get(key)
        if cached is not None:
            return cached
        voices: dict = {}
        for voice, renderer in RENDERERS.items():
            voices[voice] = renderer(rate, dict(params.get(voice, {})))
        voices["tom"] = tuple(
            render_tom(rate, f, dict(params.get("tom", {})))
            for f in TOM_FREQS)
        # Playback gain keeps groove velocities in 0..1 and lets the kit decide
        # how loud its own voices are against the synth.
        voices["gain"] = dict(params.get("gain", {}))
        _KIT_CACHE[key] = voices
        return voices


def tom_index(freq: float) -> int:
    """Index of the closest pre-rendered tom to ``freq``."""
    best, best_d = 0, float("inf")
    for i, f in enumerate(TOM_FREQS):
        d = abs(f - freq)
        if d < best_d:
            best, best_d = i, d
    return best


def play(buf: list[float], rate: int, s0: int, voice: str, vel: float,
         samples: dict, freq: float | None = None) -> None:
    """Mix one hit into ``buf`` additively: one add and one mul per sample.

    ``buf`` is the synth's float buffer. The caller soft-clips/normalises at
    the end, so overlapping hits may sum past 1.0 here without clipping.
    """
    if vel <= 0.0 or s0 < 0:
        return
    level = vel * float(samples.get("gain", {}).get(voice, 1.0))
    if level <= 0.0:
        return
    if voice == "tom":
        toms = samples.get("tom")
        if not toms:
            return
        data = toms[tom_index(freq if freq is not None else TOM_FREQS[3])]
    else:
        # A groove typo must silence one hit, never the whole soundtrack.
        data = samples.get(voice)
        if data is None:
            return
    room = len(buf) - s0
    if room <= 0:
        return
    n = len(data) if len(data) < room else room
    for i in range(n):
        buf[s0 + i] += data[i] * level


__all__ = ["WHITE", "WHITE_ALT", "PINK", "TOM_FREQS", "kit_samples",
           "play", "tom_index"]
