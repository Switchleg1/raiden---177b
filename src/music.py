"""Procedural 80s synth music - one looping chiptune track per level.

Everything is synthesised at runtime as 16-bit mono PCM. There are **no audio
files** and no MIDI: the "synth" is a phase-accumulating oscillator bank
(square / pulse / triangle) plus a noise/tom drum kit, mixed additively.

Each level gets a *composed* ~25-45 s cue rather than a single bar that repeats:
a 2-bar intro, an 8-bar A section and an 8-bar B section over an 8-chord
natural-minor progression (so the harmony never resets on a 2-second cell), a
motif-based lead melody that varies phrase to phrase, a driving bass that changes
pattern between sections, arpeggiated backing, and drum fills at each 8-bar
boundary. Decay envelopes use an accumulator (no per-sample ``math.exp``) so the
whole soundtrack builds in well under a couple of seconds at mixer init.

The module is free of pygame so it can be unit-tested headlessly; the
`AudioManager` turns each ``bytes`` buffer into a looping mixer sound.
"""

from __future__ import annotations

import math
import random
import threading

from audio import MIXER_RATE as RATE
from music_content import (
    BASS,
    BOSS_THEMES,
    CADENCE,
    LAYOUT,
    MENU_THEME,
    MENU_THEMES,
    MOTIFS,
    SCALE,
    SCALES,
    THEMES,
)

# Pre-generated white noise (deterministic) for the drum channel.
_NOISE = tuple(random.Random(0x5EED).uniform(-1.0, 1.0) for _ in range(4096))


def _freq(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def _scale_tone(root: int, index: int,
                scale: tuple[int, ...] = SCALE) -> int:
    """Semitone pitch of a scale-degree index (may run below/above one octave)."""
    octave, deg = divmod(index, 7)
    return root + scale[deg] + 12 * octave


def _triad(root: int, degree: int,
           scale: tuple[int, ...] = SCALE) -> list[int]:
    """Triad built on a scale degree (0..6) of ``scale``."""
    return [_scale_tone(root, degree, scale),
            _scale_tone(root, degree + 2, scale),
            _scale_tone(root, degree + 4, scale)]


class _Mix:
    """Additive float mixer. Voices use fast accumulator decay envelopes.

    ``rate`` is the sample rate the buffer will be *played back* at (the mixer's
    actual opened frequency). Generating at the playback rate is what keeps the
    pitch and tempo correct -- see ``AudioManager``.
    """

    def __init__(self, nsamples: int, rate: int = RATE) -> None:
        self.buf = [0.0] * nsamples
        self.rate = rate

    def voice(self, s0: int, dur: float, freq: float, wave: str, vol: float,
              *, duty: float = 0.5, decay: float = 6.0, attack: float = 0.01) -> None:
        """Add one oscillator note. Per-wave loops are written inline (no
        per-sample closure/branch) with split attack+decay for speed."""
        if s0 >= len(self.buf) or dur <= 0 or vol <= 0:
            return
        RATE_ = self.rate
        n = int(dur * RATE_)
        end = min(s0 + n, len(self.buf))
        atk = min(max(1, int(attack * RATE_)), end - s0)
        aend = s0 + atk
        step = freq / RATE_
        k = math.exp(-decay / RATE_)          # per-sample decay factor
        buf = self.buf
        ph = 0.0
        if wave == "square":
            for i in range(s0, aend):
                buf[i] += (1.0 if ph < duty else -1.0) * ((i - s0) / atk) * vol
                ph += step
                if ph >= 1.0:
                    ph -= 1.0
            env = (aend - 1 - s0) / atk if atk else 1.0
            for i in range(aend, end):
                env *= k
                buf[i] += (1.0 if ph < duty else -1.0) * env * vol
                ph += step
                if ph >= 1.0:
                    ph -= 1.0
        elif wave == "tri":
            for i in range(s0, aend):
                tri = (4.0 * ph - 1.0) if ph < 0.5 else (3.0 - 4.0 * ph)
                buf[i] += tri * ((i - s0) / atk) * vol
                ph += step
                if ph >= 1.0:
                    ph -= 1.0
            env = (aend - 1 - s0) / atk if atk else 1.0
            for i in range(aend, end):
                env *= k
                buf[i] += ((4.0 * ph - 1.0) if ph < 0.5 else (3.0 - 4.0 * ph)) * env * vol
                ph += step
                if ph >= 1.0:
                    ph -= 1.0
        elif wave == "saw":
            for i in range(s0, aend):
                buf[i] += (2.0 * ph - 1.0) * ((i - s0) / atk) * vol
                ph += step
                if ph >= 1.0:
                    ph -= 1.0
            env = (aend - 1 - s0) / atk if atk else 1.0
            for i in range(aend, end):
                env *= k
                buf[i] += (2.0 * ph - 1.0) * env * vol
                ph += step
                if ph >= 1.0:
                    ph -= 1.0
        else:  # sine
            for i in range(s0, aend):
                buf[i] += math.sin(2.0 * math.pi * ph) * ((i - s0) / atk) * vol
                ph += step
                if ph >= 1.0:
                    ph -= 1.0
            env = (aend - 1 - s0) / atk if atk else 1.0
            for i in range(aend, end):
                env *= k
                buf[i] += math.sin(2.0 * math.pi * ph) * env * vol
                ph += step
                if ph >= 1.0:
                    ph -= 1.0

    def _noise_burst(self, s0: int, dur: float, vol: float, decay: float,
                     stride: int) -> None:
        if s0 >= len(self.buf):
            return
        RATE_ = self.rate
        n = int(dur * RATE_)
        end = min(s0 + n, len(self.buf))
        k = math.exp(-decay / RATE_)
        env = 1.0
        buf = self.buf
        for i in range(s0, end):
            buf[i] += _NOISE[(i * stride + 11) & 4095] * env * vol
            env *= k

    def kick(self, s0: int, vol: float) -> None:
        # pitch-descending triangle body
        if s0 >= len(self.buf):
            return
        RATE_ = self.rate
        n = int(0.13 * RATE_)
        end = min(s0 + n, len(self.buf))
        k = math.exp(-22.0 / RATE_)
        env = 1.0
        ph = 0.0
        buf = self.buf
        for i in range(s0, end):
            t = (i - s0) / RATE_
            f = 150.0 - 100.0 * min(1.0, t / 0.11)
            step = f / RATE_
            buf[i] += ((4.0 * ph - 1.0) if ph < 0.5 else (3.0 - 4.0 * ph)) * env * vol
            ph += step
            if ph >= 1.0:
                ph -= 1.0
            env *= k

    def snare(self, s0: int, vol: float) -> None:
        self._noise_burst(s0, 0.12, vol, 34.0, 2654435761)

    def hat(self, s0: int, vol: float) -> None:
        self._noise_burst(s0, 0.03, vol, 90.0, 40503)

    def tom(self, s0: int, freq: float, vol: float) -> None:
        if s0 >= len(self.buf):
            return
        RATE_ = self.rate
        n = int(0.16 * RATE_)
        end = min(s0 + n, len(self.buf))
        k = math.exp(-14.0 / RATE_)
        env = 1.0
        ph = 0.0
        step = freq / RATE_
        buf = self.buf
        for i in range(s0, end):
            buf[i] += ((4.0 * ph - 1.0) if ph < 0.5 else (3.0 - 4.0 * ph)) * env * vol
            ph += step
            if ph >= 1.0:
                ph -= 1.0
            env *= k

    def normalise(self, peak: float = 0.9) -> bytes:
        mx = 1e-6
        for v in self.buf:
            a = -v if v < 0 else v
            if a > mx:
                mx = a
        g = peak / mx if mx > peak else 1.0
        out = bytearray()
        for v in self.buf:
            iv = int(max(-1.0, min(1.0, v * g)) * 32767)
            out += (iv & 0xFFFF).to_bytes(2, "little", signed=False)
        return bytes(out)










def _add_bar(mix, section, bar_in_sec, root, prog, lead_wave,
             spb, bar_t, drums: bool = True,
             scale: tuple[int, ...] = SCALE, drive: bool = False) -> None:
    """Render one bar's voices into the mix.

    ``drive`` is the boss flag. It does not change the tune, only the density
    and aggression of the rhythm bed: 16th-note hats, a four-on-the-floor kick,
    a 16th octave ghost line under the bass, a low tom pulse and a tritone
    alarm stab. Same engine, same scale, noticeably more urgent.
    """
    eighth = spb / 2.0
    degree = prog[bar_in_sec % len(prog)]
    chord = _triad(root, degree, scale)

    def at(beat: float) -> int:
        return int((bar_t + beat * spb) * mix.rate)

    # --- pad: two sustained chord tones (root + third) ---
    if section in ("A", "B", "outro"):
        for tone in (chord[0], chord[1]):
            mix.voice(at(0), spb * 3.9, _freq(tone), "tri", 0.055,
                      decay=0.6, attack=0.08)

    # --- bass: driving 8ths, pattern per section, one octave below the pad ---
    bpat = BASS[section]
    bass_oct = -12 if section in ("intro",) else -12
    for e in range(8):
        idx = bpat[e] % 3
        note = chord[idx] + bass_oct
        mix.voice(at(e * 0.5), eighth * 0.92, _freq(note), "square",
                  0.20 if section != "intro" else 0.12, decay=7.0)

    # --- drive (boss): 16th octave ghosts under the bass line ---
    if drive and section in ("A", "B"):
        for s in range(16):
            if s % 2 == 0:
                continue                      # the 8ths are already playing
            note = chord[bpat[s // 2] % 3] + bass_oct + 12
            mix.voice(at(s * 0.25), spb * 0.10, _freq(note), "square",
                      0.07, decay=14.0)

    # --- arpeggiated backing (octave up, quiet texture) ---
    if section in ("A", "B"):
        arps = (0, 1, 2, 1, 0, 1, 2, 1)
        for e in range(8):
            tone = chord[arps[e] % 3] + 12
            mix.voice(at(e * 0.5), eighth * 0.8, _freq(tone), "pulse",
                      0.09, duty=0.15, decay=10.0)

    # --- lead melody: motif-based, cadence on the last bar of each phrase ---
    if section == "A":
        motif = MOTIFS["A"][bar_in_sec % 4] if bar_in_sec != 7 else CADENCE
        octv = 12
    elif section == "B":
        motif = MOTIFS["B"][bar_in_sec % 4] if bar_in_sec != 7 else CADENCE
        octv = 24
    elif section == "outro":
        motif = CADENCE
        octv = 12
    else:
        motif = ()
        octv = 12
    for start, dur, off in motif:
        note = _scale_tone(root, degree + off, scale) + octv
        mix.voice(at(start), dur * spb * 0.9, _freq(note), lead_wave, 0.14,
                  duty=0.2, decay=5.5)

    # --- drums (skipped entirely for the drumless menu/attract track) ---
    if not drums:
        return
    if drive and section == "intro":
        # Alarm bar: snare roll over a kick, then straight into the grind.
        mix.kick(at(0), 0.55)
        for s in range(8):
            mix.tom(at(s * 0.5), 240.0 - s * 8.0, 0.30)
            mix.hat(at(s * 0.25), 0.05)
    elif section == "intro":
        mix.kick(at(0), 0.45)
        for e in range(8):
            mix.hat(at(e * 0.5), 0.06)
    else:
        mix.kick(at(0), 0.5)
        mix.kick(at(2), 0.48)
        if section == "B":
            mix.kick(at(2.5), 0.4)
        if drive:
            # four-on-the-floor: the missing beats are what makes it run.
            mix.kick(at(1), 0.42)
            mix.kick(at(3), 0.42)
        mix.snare(at(1), 0.32)
        mix.snare(at(3), 0.32)
        if drive:
            for s in range(16):
                mix.hat(at(s * 0.25), 0.055 if s % 2 else 0.095)
            mix.tom(at(3.75), 120.0, 0.24)     # low tom pickup into next bar
        else:
            for e in range(8):
                mix.hat(at(e * 0.5), 0.07 if e % 2 else 0.10)
        if drive and section in ("A", "B"):
            # Tritone alarm: one degree of pure "the boss is on screen".
            mix.voice(at(0), spb * 0.22, _freq(chord[0] + 6 + 24), "pulse",
                      0.075, duty=0.5, decay=9.0)
            if bar_in_sec % 2 == 1:
                mix.voice(at(2.5), spb * 0.22, _freq(chord[0] + 6 + 24),
                          "pulse", 0.065, duty=0.5, decay=9.0)
        # fill on the last bar of each 8-bar phrase (A bar 7 / B bar 7) and outro
        if bar_in_sec == 7:
            for s in range(4):
                mix.tom(at(3.0 + s * 0.25), 220.0 - s * 30.0, 0.34)
        if section == "outro":
            for s in range(4):
                mix.tom(at(3.0 + s * 0.25), 200.0 - s * 24.0, 0.30)


def render_track(theme: dict, rate: int = RATE) -> bytes:
    """Render one level track as 16-bit mono PCM at ``rate`` Hz.

    ``rate`` must equal the mixer's actual opened frequency, otherwise the
    buffer is resampled on playback and the pitch/tempo shift (this was the
    cause of the music sounding too fast and an octave too high -- pygame's
    mixer opened at 44100 Hz while we generated at 22050).

    Tempo note (the underlying bug): ``spb`` (seconds per beat) was previously
    ``240.0 / bpm``, which was itself compensating for the 2x sample-rate
    mismatch -- the buffer was generated 2x too slow and then played 2x too
    fast, so the two errors partly cancelled and the result *sounded* near the
    intended tempo. Once generation happens at the real mixer rate (no
    resample), that 2x must be folded back into ``spb``, giving ``120.0 / bpm``.
    This keeps the slow downtempo synthwave feel (~53 BPM for a 106 tag) with
    correct pitch, and halves the loop back to ~90 s instead of ~180 s.
    """
    bpm = theme["bpm"]
    root = theme["root"]
    prog = theme["prog"]
    lead = theme["lead"]
    drums = bool(theme.get("drums", True))
    drive = bool(theme.get("drive", False))
    layout = theme.get("layout", LAYOUT)
    scale = SCALES.get(theme.get("scale", "natural"), SCALE)
    spb = 120.0 / bpm
    bar = 4.0 * spb
    total_bars = sum(n for _name, n in layout)
    mix = _Mix(int(bar * total_bars * rate) + 2048, rate=rate)

    bar_index = 0
    for section, nbars in layout:
        for k in range(nbars):
            _add_bar(mix, section, k, root, prog, lead, spb, bar_index * bar,
                     drums=drums, scale=scale, drive=drive)
            bar_index += 1

    return mix.normalise()


# Process-level caches keyed by sample rate. Rendering is expensive (each track
# is a multi-second loop) and the values are immutable, so every App instance
# and every test reuses the same buffers instead of re-rendering. The App's
# background thread reads through these, so only the first caller pays.
_TRACKS_CACHE: dict[int, dict[int, bytes]] = {}
_MENU_PL_CACHE: dict[int, tuple[bytes, ...]] = {}
_BUILD_LOCK = threading.Lock()


def build_tracks(rate: int = RATE) -> dict[int, bytes]:
    """Build (or return cached) every level's loop buffer once (index 0..4)."""
    cached = _TRACKS_CACHE.get(rate)
    if cached is not None:
        return cached
    with _BUILD_LOCK:
        cached = _TRACKS_CACHE.get(rate)
        if cached is None:
            cached = {i: render_track(t, rate) for i, t in enumerate(THEMES)}
            _TRACKS_CACHE[rate] = cached
    return cached


def build_menu_playlist(rate: int = RATE) -> tuple[bytes, ...]:
    """Build (or return cached) every calm, drumless menu track (the playlist)."""
    cached = _MENU_PL_CACHE.get(rate)
    if cached is not None:
        return cached
    with _BUILD_LOCK:
        cached = _MENU_PL_CACHE.get(rate)
        if cached is None:
            cached = tuple(render_track(t, rate) for t in MENU_THEMES)
            _MENU_PL_CACHE[rate] = cached
    return cached


def build_menu(rate: int = RATE) -> bytes:
    """Build the calm, drumless menu / attract loop (playlist[0])."""
    return build_menu_playlist(rate)[0]


_BOSS_CACHE: dict[int, tuple[bytes, ...]] = {}


def build_bosses(rate: int = RATE) -> tuple[bytes, ...]:
    """Build every boss cue once per sample rate (thread-safe, cached).

    The App renders these lazily on a background thread and picks a random one
    per boss, so a sector's fight does not always sound the same.
    """
    cached = _BOSS_CACHE.get(rate)
    if cached is not None:
        return cached
    with _BUILD_LOCK:
        cached = _BOSS_CACHE.get(rate)
        if cached is not None:
            return cached
        try:
            tracks = tuple(render_track(t, rate=rate) for t in BOSS_THEMES)
        except Exception:
            tracks = ()
        _BOSS_CACHE[rate] = tracks
        return tracks


def build_boss(rate: int = RATE) -> bytes:
    """Build the first boss cue (single-track callers / tests)."""
    tracks = build_bosses(rate)
    return tracks[0] if tracks else b""


__all__ = ["THEMES", "BOSS_THEMES", "MENU_THEMES", "MENU_THEME",
           "render_track", "build_tracks", "build_menu", "build_menu_playlist",
           "build_bosses", "build_boss"]
