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
from collections.abc import Sequence
from typing import Any

import drum_kit
import instruments
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
    LEVEL_CUES,
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
        # The drums live on their own bus. That is not mixer decoration: the
        # trance/electro cues want a sidechain pump, and a pump that ducks the
        # kick as well as the pad is just a tremolo. Keeping the rhythm separate
        # is what lets the synths breathe around every kick while the kick itself
        # stays rock steady.
        self.dbuf = [0.0] * nsamples
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
            drum_kit.play(self.dbuf, self.rate, s0, voice, vel, self.drums,
                          freq=freq)

    def instr(self, s0: int, dur: float, freq: float, name: str,
              vol: float) -> None:
        """Add one note of a synthesised instrument (see ``instruments``).

        The instrument owns its envelope - attack, vibrato, release all arrive on
        their own schedule - so this is one multiply-add per sample, exactly like
        a drum hit. Rendering the same pitch and length twice is free: the
        instrument module caches by ``(name, pitch, length)``.
        """
        if s0 >= len(self.buf) or dur <= 0 or vol <= 0:
            return
        samples = instruments.note(name, freq, dur, self.rate)
        if not samples:
            return
        buf = self.buf
        end = min(s0 + len(samples), len(buf))
        for i in range(s0, end):
            buf[i] += samples[i - s0] * vol

    def pump(self, depth: float, period: float,
             recover: float = 0.28) -> None:
        """Duck the synth bus once per beat, then let it swim back up.

        This is the sidechain pump that the whole trance and electro idiom runs
        on: the pad and bass step down every time the kick lands and climb back
        into the next one. Played by a dance record it is the reason a cue feels
        like it is *moving* rather than looping, and it is also the cheapest
        rhythm there is - no extra notes, no extra CPU in the bar render.

        Only the synth bus is touched, because that is what a real sidechain does
        (the kick owns its own trigger). ``depth`` is the fraction of level lost
        at the bottom of the dip, ``period`` is the spacing of the dips - the
        quarter-note beat for a four-on-the-floor cue - and ``recover`` is the
        seconds it takes to come back, which is what makes a pump a pump: a dip
        that never returns is a sustain, and one that returns in 40 ms is a click.
        """
        if depth <= 0.0 or period <= 0.0:
            return
        step = int(period * self.rate)
        if step < 2:
            return
        bottom = max(0.0, 1.0 - depth)
        # The climb back is exponential, which is how a compressor release
        # behaves: ``recover`` is the time to come back *most* of the way (92 %
        # of the gap), not all of it. That distinction is the whole sound. If the
        # release is treated as "fully back in 0.15 s", the dip lasts a sixth of
        # the beat and the cue gains a click instead of a pulse; a real dance
        # record is still substantially ducked when the next kick arrives, and so
        # is this. One pow per call, not per sample.
        span = max(1.0, recover * self.rate)
        rec = 1.0 - pow(0.08, 1.0 / span)
        buf = self.buf
        n = len(buf)
        g = 1.0
        for start in range(0, n, step):
            end = min(start + step, n)
            g = bottom
            for i in range(start, end):
                g += (1.0 - g) * rec
                buf[i] *= g

    def normalise(self, peak: float = 0.9, knee: float = 0.68) -> bytes:
        """Sum the buses, soft-clip, scale to ``peak``, quantise to 16-bit mono.

        Drum transients land on top of the sustained pad and bass, so the sum
        regularly passes full scale. Hard-clipping those flips the waveform and
        audibly crackles; bending the over-knee part with ``tanh`` keeps the
        punch, and only costs a ``tanh`` on samples that are actually hot.
        """
        head = 1.0 - knee
        buf = self.buf
        if any(self.dbuf):
            for i, v in enumerate(self.dbuf):
                buf[i] += v
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
                 "clap", "tom", "shaker", "cowbell", "riser")
# A fill leaves the pulse alone and pulls the busy layers down, so the fill
# reads as a bend in the groove rather than a wall of noise.
FILL_DUCK = ("kick", "hat", "shaker")
# The riser is baked about a bar and a half long, so the build sits one bar
# ahead of the fill: riser, then the fill lands where the sweep peaked.
BUILD_BAR = 6


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
        if groove.get("build"):
            # the same build the sections use, so a cue that builds also builds
            # its way in from the top of the loop
            for step, voice, vel in groove["build"]:  # type: ignore[misc]
                mix.drum(voice, at(step * 0.25), vel * 0.8)
        return

    fill = bar_in_sec == 7
    build = bar_in_sec == BUILD_BAR and bool(groove.get("build"))
    loud = 0.8 if section == "outro" else 1.0
    swing = float(groove.get("swing", 0.0))

    def pos(step: int) -> float:
        return step * 0.25 + (swing * 0.25 if step % 2 else 0.0)

    hits: list[tuple[float, str, float]] = []
    for name in GROOVE_VOICES:
        if fill and name == "snare":
            continue                       # the fill owns the backbeat
        duck = 0.55 if (fill and name in FILL_DUCK) else 1.0
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
    if build:
        for step, voice, vel in groove["build"]:  # type: ignore[misc]
            hits.append((pos(step), "snare" if voice == "ghost" else voice,
                         vel * loud))
    hits.sort(key=lambda h: h[0])
    # Tom pitches are positional: the toms in this bar, in order, take the
    # lowest N kit notes descending.
    tom_slots = [i for i, hit in enumerate(hits) if hit[1] == "tom"]
    tom_pitches = dict(zip(tom_slots, TOM_DESC[-len(tom_slots):], strict=False))
    # A crash lights the top of a section. On a boss that is alarm; on a groove
    # that builds, it is the drop the sweep was reaching for.
    if bar_in_sec == 0 and (drive or section == "outro" or groove.get("build")):
        mix.drum("crash", at(0), 0.9 if drive else 0.7)
    for i, (beat, voice, vel) in enumerate(hits):
        mix.drum(voice, at(beat), vel, freq=tom_pitches.get(i))


def _play(mix, s0: int, dur: float, freq: float, spec: str | None, vol: float,
          *, wave: str = "sine", **kw: Any) -> None:
    """Play one note: a synthesised instrument if ``spec`` names one, else a wave.

    Arrangement data may name an instrument from ``instruments.NAMES`` ("flute",
    "violin") or a raw wave ("pulse"), and both live in the same slot. That is
    what lets a cue be re-voiced by editing one string, and what keeps every cue
    written before instruments existed rendering exactly as it did.
    """
    if spec and instruments.is_instrument(spec):
        mix.instr(s0, dur, freq, spec, vol)
    else:
        mix.voice(s0, dur, freq, spec or wave, vol, **kw)


# Pad level, and the level a three-note pad uses per note. A triad has to fit the
# same slot a dyad already occupies, so each note gives up a third of its level:
# widening the harmony is not allowed to be a volume increase.
PAD_VOL = 0.055
PAD_CHORD_VOL = 0.037

# How the arpeggiated layer moves. This layer decides whether a cue sits still
# or runs, and until now every cue in the roster played the same figure - a
# large part of why they all felt like one tune.
#   stock   the original eighth-note figure: three chord tones, one octave
#   run16   sixteenth gates climbing an octave then resetting: the trance arp
#   off     whole triads slammed on the offbeats: the house / electro stab
ARP_MODES = ("stock", "run16", "off")
ARP_STOCK = (0, 1, 2, 1, 0, 1, 2, 1)


def _arpeggio(mix, chord: list[int], at, spb: float, eighth: float,
              voice: str | None, mode: str) -> None:
    """Play the arpeggiated backing layer in one of :data:`ARP_MODES`."""
    if mode == "run16":
        # two passes an octave apart: the figure climbs, the second pass lifts,
        # and the reset at the bar line is what makes the bar feel like a run
        for e in range(16):
            tone = chord[ARP_STOCK[e % 8] % 3] + (12 if e < 8 else 24)
            _play(mix, at(e * 0.25), spb * 0.17, _freq(tone), voice,
                  0.075, wave="pulse", duty=0.15, decay=13.0)
        return
    if mode == "off":
        # the stab: all three chord tones at once on the "and" of each beat,
        # gated short. Chords rather than single notes, because a stab is a
        # chord hit - a one-note stab is just an arp with the rest of it missing
        for beat in (0.5, 1.5, 2.5, 3.5):
            for tone in chord:
                _play(mix, at(beat), eighth * 0.55, _freq(tone + 12), voice,
                      0.062, wave="pulse", duty=0.3, decay=11.0)
        return
    for e in range(8):
        tone = chord[ARP_STOCK[e] % 3] + 12
        _play(mix, at(e * 0.5), eighth * 0.8, _freq(tone), voice,
              0.09, wave="pulse", duty=0.15, decay=10.0)


def _add_bar(mix, section, bar_in_sec, root, prog, lead_wave,
             spb, bar_t, drums: bool = True, groove: dict | None = None,
             scale: tuple[int, ...] = SCALE, drive: bool = False,
             motif_keys: tuple[str, str] = ("A", "B"),
             bass_line: dict[str, tuple[tuple[int, int], ...]] | None = None,
             voices: dict[str, str] | None = None, arp_mode: str = "stock",
             pad_chord: bool = False
             ) -> None:
    """Render one bar's voices into the mix.

    ``drive`` is the boss flag. It does not change the tune, only the density
    and aggression of the rhythm bed: the busiest groove, a 16th octave ghost
    line under the bass and a tritone alarm stab. Same engine, same scale,
    noticeably more urgent.

    ``motif_keys`` selects which ``MOTIFS`` melodies the lead plays (a cue's
    ``motifs`` tag) and ``bass_line`` a named ``BASS_LINES`` pattern (its
    ``bass`` tag); both fall back to the stock tables when the cue is untagged.

    ``voices`` gives a slot an instrument instead of a wave - ``{"lead":
    "flute", "lead_b": "violin", "pad": "strings"}`` - where ``lead_b`` colours
    the B section only. A two-voice cue (the flute line of the A phrase taken up
    by the violin in the answer) is the reason that key exists.

    ``arp_mode`` picks the figure the arpeggiated layer plays and ``pad_chord``
    widens the pad from a dyad to a triad. Both default to the shape every cue
    in the roster has always used.
    """
    voices = voices or {}
    eighth = spb / 2.0
    degree = prog[bar_in_sec % len(prog)]
    chord = _triad(root, degree, scale)

    def at(beat: float) -> int:
        return int((bar_t + beat * spb) * mix.rate)

    # --- pad: sustained chord tones (root + third, or the whole triad) ---
    if section in ("A", "B", "outro"):
        # A triad instead of a dyad is a small change with a big effect: the
        # missing fifth is why a two-note pad sounds thin under a wide lead.
        pad_tones = ((chord[0], chord[1], chord[2]) if pad_chord
                     else (chord[0], chord[1]))
        pv = PAD_CHORD_VOL if pad_chord else PAD_VOL
        for tone in pad_tones:
            _play(mix, at(0), spb * 3.9, _freq(tone), voices.get("pad"), pv,
                  wave="tri", decay=0.6, attack=0.08)

    # --- bass: 8ths, one octave below the pad, pattern per section or named ---
    line = (bass_line or {}).get(section)
    tones: list[tuple[int, int]] = (list(line) if line is not None
                                    else [(t, 0) for t in BASS[section]])
    bass_oct = -12
    bvol = 0.20 if section != "intro" else 0.12
    for e, (tone, octv) in enumerate(tones):
        if tone < 0:
            continue          # a rest: the gap is the groove - an offbeat bass
            # is defined by what it refuses to play
        note = _bass_tone(chord, tone) + bass_oct + octv
        # An octave pop sits a hair louder, or it just reads as a wrong note.
        _play(mix, at(e * 0.5), eighth * 0.92, _freq(note), voices.get("bass"),
              bvol * (1.12 if octv else 1.0), wave="square", decay=7.0)

    # --- drive (boss): 16th octave ghosts under the bass line ---
    if drive and section in ("A", "B"):
        for s in range(16):
            if s % 2 == 0:
                continue                      # the 8ths are already playing
            tone = tones[s // 2][0]
            if tone < 0:
                continue                      # a rest stays a rest in the ghosts
            note = _bass_tone(chord, tone) + bass_oct + 12
            mix.voice(at(s * 0.25), spb * 0.10, _freq(note), "square",
                      0.07, decay=14.0)

    # --- arpeggiated backing (octave up, quiet texture) ---
    if section in ("A", "B"):
        _arpeggio(mix, chord, at, spb, eighth, voices.get("arp"), arp_mode)

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
    lead = voices.get("lead_b" if section == "B" else "lead") or lead_wave
    for start, dur, off in motif:
        note = _scale_tone(root, degree + off, scale) + octv
        _play(mix, at(start), dur * spb * 0.9, _freq(note), lead, 0.14,
              wave=lead_wave, duty=0.2, decay=5.5)

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
    # Voicing lives in one dict per cue so a slot can name an instrument without
    # colliding with the wave name in "lead" or the bass-pattern name in "bass".
    voices = theme.get("instruments") or {}
    # Three more arrangement choices, all opt-in and all falling back to what
    # every cue already did: how the arp moves, whether the pad is a triad, and
    # whether the whole synth bus pumps against the kick.
    arp_mode = str(theme.get("arp_mode", "stock"))
    if arp_mode not in ARP_MODES:
        arp_mode = "stock"
    pad_chord = bool(theme.get("pad_chord", False))
    pump_depth = float(theme.get("pump", 0.0) or 0.0)
    mix = _Mix(int(bar * total_bars * rate) + 2048, rate=rate, drums=samples)

    bar_index = 0
    for section, nbars in layout:
        for k in range(nbars):
            _add_bar(mix, section, k, root, prog, lead, spb, bar_index * bar,
                     drums=drums, groove=groove, scale=scale, drive=drive,
                     motif_keys=motif_keys, bass_line=bass_line, voices=voices,
                     arp_mode=arp_mode, pad_chord=pad_chord)
            bar_index += 1

    # The pump rides the quarter-note beat, which is where a four-on-the-floor
    # kick lives; a drumless cue has no kick to duck under, so it never pumps.
    if pump_depth > 0.0 and drums and groove is not None:
        mix.pump(min(0.85, pump_depth), spb,
                 float(theme.get("pump_recover", 0.28)))

    return mix.normalise()


# Process-level caches keyed by sample rate. Rendering is expensive (each track
# is a multi-second loop) and the values are immutable, so every App instance
# and every test reuses the same buffers instead of re-rendering. The App's
# background thread reads through these, so only the first caller pays.
_TRACKS_CACHE: dict[int, dict[str, bytes]] = {}
_MENU_PL_CACHE: dict[int, tuple[bytes, ...]] = {}
_BUILD_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Which cue a sector plays: a sector owns a pool (LEVEL_CUES) and draws from it,
# so a sector has a sound of its own without always being the same tune. The
# table is names only; everything that decides is here.
# --------------------------------------------------------------------------

def cue_names() -> tuple[str, ...]:
    """Every level cue name, in table order."""
    return tuple(str(t["name"]) for t in THEMES)


def theme_tables() -> tuple[tuple[dict, ...], ...]:
    """Every cue table, level cues first. A pool may reach across them: the cue
    the valley flies under was written as a drumless menu cue, and a pool is
    allowed to want it."""
    return (THEMES, MENU_THEMES, BOSS_THEMES)


def theme_by_name(name: str) -> dict | None:
    """The cue called ``name``, or None. Looked up fresh, so a patched table
    (tests) cannot be shadowed by a stale index."""
    for table in theme_tables():
        for theme in table:
            if theme.get("name") == name:
                return dict(theme)
    return None


def level_cues(level_index: int) -> tuple[str, ...]:
    """The cues a sector may play. A sector without a listed pool gets the
    whole table rather than silence - an unassigned sector is a table edit, not
    a reason to stop the music."""
    pool = LEVEL_CUES.get(level_index)
    return pool if pool else cue_names()


def levels_for_cue(name: str) -> tuple[int, ...]:
    """Which sectors may play this cue (the inverse of :func:`level_cues`).

    A cue shared by two sectors is registered under both, which is what lets a
    sector fall back to a cue that happens to be ready instead of waiting.
    """
    return tuple(i for i, pool in sorted(LEVEL_CUES.items()) if name in pool)


def pick_level_cue(level_index: int, ready: Sequence[str],
                   exclude: str | None = None, rng: Any = random) -> str | None:
    """Choose which of a sector's cues plays now, from the ones that are ready.

    In order: only this sector's cues; never the cue that just played (hearing
    the same tune every sector is the mistake the old shared pool made); the
    sector's identity cue when it is the only thing rendered yet. ``None`` means
    nothing for this sector exists yet - the caller's signal to fall back.
    """
    pool = level_cues(level_index)
    mine = [name for name in pool if name in set(ready)]
    choices = [name for name in mine if name != exclude]
    if not choices:
        return mine[0] if mine else None
    return rng.choice(choices)


def build_cues(rate: int = RATE) -> dict[str, bytes]:
    """Build (or return cached) every level cue, keyed by cue name."""
    cached = _TRACKS_CACHE.get(rate)
    if cached is not None:
        return cached
    with _BUILD_LOCK:
        cached = _TRACKS_CACHE.get(rate)
        if cached is None:
            cached = {str(t["name"]): render_track(t, rate) for t in THEMES}
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


__all__ = ["THEMES", "BOSS_THEMES", "MENU_THEMES", "MENU_THEME", "LEVEL_CUES",
           "render_track", "build_cues", "build_menu", "build_menu_playlist",
           "build_bosses", "build_boss", "cue_names", "theme_by_name",
           "level_cues", "levels_for_cue", "pick_level_cue"]
