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
import threading

import drum_kit
from audio import MIXER_RATE as RATE
from music_content import (
    BASS,
    BASS_LINES,
    BOSS_THEMES,
    CADENCE,
    GROOVE_BOSS,
    GROOVE_BY_TEMPO,
    GROOVES,
    KIT_BOSS,
    KIT_BY_TEMPO,
    KITS,
    LAYOUT,
    MENU_THEME,
    MENU_THEMES,
    MOTIF_SETS,
    MOTIFS,
    SCALE,
    SCALES,
    THEMES,
)


def _freq(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def _scale_tone(root: int, index: int,
                scale: tuple[int, ...] = SCALE) -> int:
    """Semitone pitch of a scale-degree index (may run below/above one octave)."""
    octave, deg = divmod(index, 7)
    return root + scale[deg] + 12 * octave


def _bass_tone(chord: list[int], tone: int) -> float:
    """Semitone pitch of one bass-line step.

    ``BASS_LINES`` uses 0/1/2 for the root/third/fifth of the current chord and
    3 for the chromatic approach a semitone below the root - the note that pulls
    the ear into the next bar's chord. Keeping it relative is what lets one
    written line sit under any progression.
    """
    return chord[tone] if tone < 3 else chord[0] - 1.0


def _triad(root: int, degree: int,
           scale: tuple[int, ...] = SCALE) -> list[int]:
    """Triad built on a scale degree (0..6) of ``scale``."""
    return [_scale_tone(root, degree, scale),
            _scale_tone(root, degree + 2, scale),
            _scale_tone(root, degree + 4, scale)]


# Themes name waves the way the tracker world does ("pulse", "triangle");
# the loops below are keyed by their own short names. "pulse" is a narrow-duty
# square, which is exactly what the duty parameter already controls - without
# this alias every pulse/triangle lead in THEMES silently fell through to the
# sine branch and the whole soundtrack played one octave softer in harmonics.
WAVE_ALIASES = {"triangle": "tri", "tri": "tri", "pulse": "square",
                "square": "square", "sawtooth": "saw", "saw": "saw",
                "sine": "sine"}


class _Mix:
    """Additive float mixer. Voices use fast accumulator decay envelopes.

    ``rate`` is the sample rate the buffer will be *played back* at (the mixer's
    actual opened frequency). Generating at the playback rate is what keeps the
    pitch and tempo correct -- see ``AudioManager``.
    """

    def __init__(self, nsamples: int, rate: int = RATE,
                 drums: dict | None = None) -> None:
        self.buf = [0.0] * nsamples
        self.rate = rate
        self.drums = drums

    def voice(self, s0: int, dur: float, freq: float, wave: str, vol: float,
              *, duty: float = 0.5, decay: float = 6.0, attack: float = 0.01) -> None:
        """Add one oscillator note. Per-wave loops are written inline (no
        per-sample closure/branch) with split attack+decay for speed."""
        if s0 >= len(self.buf) or dur <= 0 or vol <= 0:
            return
        wave = WAVE_ALIASES.get(wave, wave)
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

    def drum(self, voice: str, s0: int, vel: float,
             freq: float | None = None) -> None:
        """Mix one drum-kit hit at sample ``s0``.

        ``vel`` is musical velocity 0..1; the kit's own per-voice gain decides
        how loud that is against the synth, so re-balancing drums against leads
        never means editing a groove. Playback is one multiply-add per sample:
        the expensive part (pitch glide, filtered noise, metal partials) was
        paid once when the kit was rendered.
        """
        if self.drums is not None:
            drum_kit.play(self.buf, self.rate, s0, voice, vel, self.drums,
                          freq=freq)

    def normalise(self, peak: float = 0.9, knee: float = 0.68) -> bytes:
        """Soft-clip, scale to ``peak``, then quantise to 16-bit mono.

        Drum transients land on top of the sustained pad and bass, so the sum
        regularly passes full scale. Hard-clipping those flips the waveform and
        audibly crackles; bending the over-knee part with ``tanh`` keeps the
        punch, and only costs a ``tanh`` on samples that are actually hot.
        """
        head = 1.0 - knee
        buf = self.buf
        mx = 1e-6
        for i, v in enumerate(buf):
            a = -v if v < 0 else v
            if a > knee:
                s = -1.0 if v < 0 else 1.0
                bent = s * (knee + head * math.tanh((a - knee) / head))
                buf[i] = bent
                a = -bent if bent < 0 else bent
            if a > mx:
                mx = a
        g = peak / mx if mx > peak else 1.0
        out = bytearray()
        for v in buf:
            iv = int(max(-1.0, min(1.0, v * g)) * 32767)
            out += (iv & 0xFFFF).to_bytes(2, "little", signed=False)
        return bytes(out)










# --- drum bar rendering ----------------------------------------------------
# Fill variants rotate by section so the A and B phrases do not end on the same
# fill. Tom hits take the lowest N kit pitches in descending order: a single
# tom is a low pulse, a run of toms is a cadence.
FILL_VARIANT = {"intro": 0, "A": 0, "B": 1, "outro": 1}
TOM_DESC = tuple(sorted(drum_kit.TOM_FREQS, reverse=True))
GROOVE_VOICES = ("kick", "snare", "ghost", "hat", "open", "ride", "rim",
                 "clap", "tom")


def _drum_bar(mix, groove: dict, section: str, bar_in_sec: int, at,
              drive: bool) -> None:
    """Render one bar of drums from a ``GROOVES`` record.

    Positions are 16th-note steps of the bar and ``swing`` pushes the odd steps
    late - the difference between a programmed bar and a played one. On the last
    bar of a section the snare backbeat swaps to a fill variant while kick and
    hats keep going at reduced level, so the groove bends instead of stopping.
    A boss bar opens on a crash; a boss intro bar is a crescendo snare roll.
    """
    if section == "intro":
        roll = groove.get("roll")
        if drive and roll:
            mix.drum("kick", at(0), 1.0)
            mix.drum("hat", at(0), 0.5)
            for step, vel in roll:  # type: ignore[misc]
                mix.drum("snare", at(step * 0.25), vel * 0.75)
            mix.drum("open", at(3.5), 0.55)
            return
        mix.drum("kick", at(0), 0.85)
        for e in range(8):
            mix.drum("hat", at(e * 0.5), 0.55 if e % 2 == 0 else 0.3)
        return

    fill = bar_in_sec == 7
    loud = 0.8 if section == "outro" else 1.0
    swing = float(groove.get("swing", 0.0))

    def pos(step: int) -> float:
        return step * 0.25 + (swing * 0.25 if step % 2 else 0.0)

    hits: list[tuple[float, str, float]] = []
    for name in GROOVE_VOICES:
        if fill and name == "snare":
            continue                       # the fill owns the backbeat
        duck = 0.55 if (fill and name in ("kick", "hat")) else 1.0
        for step, vel in groove.get(name, ()):  # type: ignore[misc]
            voice = "snare" if name == "ghost" else name
            hits.append((pos(step), voice, vel * loud * duck))
    if fill:
        variants = tuple(groove.get("fill") or ())
        if variants:
            pick = variants[FILL_VARIANT.get(section, 0) % len(variants)]
            for step, voice, vel in pick:
                hits.append((pos(step), "snare" if voice == "ghost" else voice,
                             vel * loud))
    hits.sort(key=lambda h: h[0])
    # Tom pitches are positional: the toms in this bar, in order, take the
    # lowest N kit notes descending.
    tom_slots = [i for i, hit in enumerate(hits) if hit[1] == "tom"]
    tom_pitches = dict(zip(tom_slots, TOM_DESC[-len(tom_slots):], strict=False))
    if bar_in_sec == 0 and (drive or section == "outro"):
        mix.drum("crash", at(0), 0.9 if drive else 0.7)
    for i, (beat, voice, vel) in enumerate(hits):
        mix.drum(voice, at(beat), vel, freq=tom_pitches.get(i))


def _add_bar(mix, section, bar_in_sec, root, prog, lead_wave,
             spb, bar_t, drums: bool = True, groove: dict | None = None,
             scale: tuple[int, ...] = SCALE, drive: bool = False,
             motif_keys: tuple[str, str] = ("A", "B"),
             bass_line: dict[str, tuple[tuple[int, int], ...]] | None = None
             ) -> None:
    """Render one bar's voices into the mix.

    ``drive`` is the boss flag. It does not change the tune, only the density
    and aggression of the rhythm bed: the busiest groove, a 16th octave ghost
    line under the bass and a tritone alarm stab. Same engine, same scale,
    noticeably more urgent.

    ``motif_keys`` selects which ``MOTIFS`` melodies the lead plays (a cue's
    ``motifs`` tag) and ``bass_line`` a named ``BASS_LINES`` pattern (its
    ``bass`` tag); both fall back to the stock tables when the cue is untagged.
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

    # --- bass: 8ths, one octave below the pad, pattern per section or named ---
    line = (bass_line or {}).get(section)
    tones: list[tuple[int, int]] = (list(line) if line is not None
                                    else [(t, 0) for t in BASS[section]])
    bass_oct = -12
    bvol = 0.20 if section != "intro" else 0.12
    for e, (tone, octv) in enumerate(tones):
        note = _bass_tone(chord, tone) + bass_oct + octv
        # An octave pop sits a hair louder, or it just reads as a wrong note.
        mix.voice(at(e * 0.5), eighth * 0.92, _freq(note), "square",
                  bvol * (1.12 if octv else 1.0), decay=7.0)

    # --- drive (boss): 16th octave ghosts under the bass line ---
    if drive and section in ("A", "B"):
        for s in range(16):
            if s % 2 == 0:
                continue                      # the 8ths are already playing
            note = _bass_tone(chord, tones[s // 2][0]) + bass_oct + 12
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
        motif = MOTIFS[motif_keys[0]][bar_in_sec % 4] if bar_in_sec != 7 \
            else CADENCE
        octv = 12
    elif section == "B":
        motif = MOTIFS[motif_keys[1]][bar_in_sec % 4] if bar_in_sec != 7 \
            else CADENCE
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

    # --- boss alarm stabs (rhythm bed, not a new tune) ---
    if drive and section in ("A", "B"):
        # Tritone: one degree of pure "the boss is on screen".
        mix.voice(at(0), spb * 0.22, _freq(chord[0] + 6 + 24), "pulse",
                  0.075, duty=0.5, decay=9.0)
        if bar_in_sec % 2 == 1:
            mix.voice(at(2.5), spb * 0.22, _freq(chord[0] + 6 + 24),
                      "pulse", 0.065, duty=0.5, decay=9.0)

    # --- drums (skipped entirely for the drumless menu/attract track) ---
    if not drums or groove is None:
        return
    _drum_bar(mix, groove, section, bar_in_sec, at, drive)


def _pick(table: tuple[tuple[int, str], ...], bpm: int) -> str:
    """First name in a (threshold, name) table that the tempo clears."""
    for limit, name in table:
        if bpm >= limit:
            return name
    return table[-1][1]


def _rhythm(theme: dict, rate: int) -> tuple[dict | None, dict | None]:
    """Resolve a theme's groove and drum kit (both ``None`` when drumless).

    A theme may name a ``groove`` / ``kit``; otherwise its tempo picks them,
    because tempo is what makes a pattern feel fast or heavy. Unknown names
    fall back rather than raising - a typo in a table must not silence the
    soundtrack on the audio thread.
    """
    if not bool(theme.get("drums", True)):
        return None, None
    drive = bool(theme.get("drive", False))
    gname = theme.get("groove") or (GROOVE_BOSS if drive
                                    else _pick(GROOVE_BY_TEMPO, theme["bpm"]))
    kname = theme.get("kit") or (KIT_BOSS if drive
                                 else _pick(KIT_BY_TEMPO, theme["bpm"]))
    return (GROOVES.get(gname) or GROOVES["straight"],
            drum_kit.kit_samples(kname, KITS.get(kname) or KITS["crisp"], rate))


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
    groove, samples = _rhythm(theme, rate)
    motif_keys = MOTIF_SETS.get(theme.get("motifs", "base"),
                                MOTIF_SETS["base"])
    bass_line = BASS_LINES.get(theme.get("bass", ""))
    mix = _Mix(int(bar * total_bars * rate) + 2048, rate=rate, drums=samples)

    bar_index = 0
    for section, nbars in layout:
        for k in range(nbars):
            _add_bar(mix, section, k, root, prog, lead, spb, bar_index * bar,
                     drums=drums, groove=groove, scale=scale, drive=drive,
                     motif_keys=motif_keys, bass_line=bass_line)
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
