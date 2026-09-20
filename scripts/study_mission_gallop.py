"""Study: a riding cue - "giddy up, we are on a mission".

A one-off arrangement to hear the engine do something the stage music never
tries. Nothing here enters the game; it exists so the writing can be judged by
ear and, if something in it works, promoted into ``music_content.py`` as a cue.

Why the previous (ballad) direction was wrong for a mission, and what this does
instead. A ballad carries its weight on long notes and one chord per bar; a
mission carries it on **the floor moving while the tune stays singable**:

  * **the gallop is in the kick, not the tempo.** Kick on 1, 3 and the "a" of
    each - the anticipation before the beat is what makes it lurch forward. The
    pulse never speeds up; the *push* does. 150 BPM, straight four.
  * **hooves.** Tom pairs on the e and the "a", quiet, so the beat has a gait
    rather than a metronome.
  * **a bass that hammers the same note.** Repetition is the trick: it makes the
    listener's foot go before the melody does anything.
  * **brass calls the tune, the fiddle answers it.** The call is three saw notes
    in unison octaves; the answer is a bowed line, in a register a real player
    could hold, with the portamento ``instruments.phrase`` now provides.
  * **the fiddle bows repeated notes.** Two attacks on one pitch read as a fiddle
    changing bow, and cost nothing: ``phrase`` cuts the first and does not slide
    to an identical pitch.
  * **no octave climax.** The last section adds players and a snare roll, not
    altitude.

Run: ``python scripts/study_mission_gallop.py`` -> assets/music/.
"""
from __future__ import annotations

import os
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import instruments  # noqa: E402
from drum_kit import kit_samples  # noqa: E402
from music import KITS, _Mix  # noqa: E402

RATE = 44100
BPM = 150.0
QUARTER = 60.0 / BPM
SIXTEENTH = QUARTER / 4.0
BAR = QUARTER * 4.0
BARS = 28

ROOT = 64                       # E4: the fiddle's comfortable singing register
KIT = "crisp"

# --- harmony, one chord per bar ---------------------------------------------
# Em for the work, C for the outlook, D to push back into Em. Am is the climb.
EM, CM, DM, AM = 64, 60, 62, 69
CHORDS = (
    EM, EM,                                               # call
    EM, EM, CM, DM, EM, EM, CM, DM,                       # A: the ride
    AM, EM, CM, DM, AM, EM, CM, DM,                       # B: the climb
    EM, EM,                                               # break and roll-in
    EM, EM, CM, DM, EM, EM, CM, DM,                       # A': everything
)
MINOR = (0, 2, 3, 5, 7, 8, 10)    # E natural minor, in semitones from ROOT

# --- the fiddle line --------------------------------------------------------
# (beat, beats, scale degree) per bar. Degree 7 = the octave: the tune lives a
# fourth or so above the chord and only visits the top for one beat at a time.
RIDE = (
    ((0, .75, 7), (.75, .25, 5), (1, .5, 4), (1.5, .5, 5), (2, .75, 7),
     (2.75, .25, 7), (3, .5, 5), (3.5, .5, 4)),
    ((0, .75, 5), (.75, .25, 4), (1, .5, 3), (1.5, .5, 4), (2, 2, 0)),
    ((0, .5, 4), (.5, .5, 4), (1, .75, 3), (1.75, .25, 4), (2, .5, 5),
     (2.5, .5, 7), (3, 1, 5)),
    ((0, .75, 7), (.75, .25, 9), (1, .5, 7), (1.5, .5, 5), (2, 2, 4)),
)
ANSWER = (
    ((0, .5, 2), (.5, .5, 4), (1, .5, 5), (1.5, .5, 7), (2, 1, 4), (3, 1, 2)),
    ((0, .75, 4), (.75, .25, 2), (1, .5, 0), (1.5, .5, 2), (2, .75, 4),
     (2.75, .25, 5), (3, 1, 7)),
    ((0, .25, 7), (.25, .25, 5), (.5, .5, 4), (1, .5, 3), (1.5, .5, 2),
     (2, .5, 0), (2.5, .5, 2), (3, 1, 4)),
    ((0, 1, 5), (1, .75, 7), (1.75, .25, 9), (2, 1, 7), (3, 1, 5)),
)
# A' repeats the ride but ends each pair a step higher: same tune, more at stake.
FINALE_TAIL = ((0, .75, 5), (.75, .25, 4), (1, .5, 3), (1.5, .5, 4), (2, 2, 7))


def deg_to_midi(degree: int) -> int:
    """Scale degree -> midi, wrapping past the octave with the right spelling."""
    octave, index = divmod(degree, len(MINOR))
    return ROOT + MINOR[index] + 12 * octave


def at(seconds: float) -> int:
    """Seconds -> sample index: the mix addresses by sample, not by time."""
    return int(seconds * RATE)


def lay(buf: list[float], when: float, samples: list[float], vol: float) -> None:
    """Add rendered instrument samples into a mix buffer at ``when`` seconds."""
    s0 = int(when * RATE)
    end = min(s0 + len(samples), len(buf))
    for i in range(s0, end):
        buf[i] += samples[i - s0] * vol


# --- the floor ---------------------------------------------------------------
def gallop(mix: _Mix, bar: int, *, hooves: bool, roll: bool, hard: bool,
           bare: bool = False, ride: bool = False) -> None:
    """Kick on 1, 3 and the anticipations; backbeat; 8ths; gait from the toms.

    ``bare`` is the break: no kick and no backbeat, only the hats holding time
    under the fiddle, so the return has somewhere to come back from. A break that
    keeps the backbeat is not a break, it is a bar with less bass.
    """
    base = int(bar * BAR * RATE)

    def hit(voice: str, sixteenth: float, vel: float,
            freq: float | None = None) -> None:
        mix.drum(voice, base + int(sixteenth * SIXTEENTH * RATE), vel,
                 freq=freq)

    if not bare:
        for sixteenth in (0, 6, 8, 14):
            hit("kick", sixteenth, 0.92 if sixteenth in (0, 8) else 0.72)
        for sixteenth in (4, 12):
            hit("snare", sixteenth, 0.95)
    if ride:
        for sixteenth in range(0, 16, 4):
            hit("ride", sixteenth, 0.5)
    # a ghost note is a snare played barely: the kit has no separate voice
    if hard:
        hit("snare", 7, 0.9)
        hit("snare", 10, 0.22)
    else:
        hit("snare", 10, 0.2)
    for sixteenth in range(0, 16, 2):
        hit("hat", sixteenth, 1.0 if sixteenth % 4 == 0 else 0.55)
    hit("open", 14, 0.4)
    if hooves:
        hit("tom", 2, 0.3, freq=180.0)
        hit("tom", 3, 0.2, freq=150.0)
        hit("tom", 10, 0.3, freq=180.0)
        hit("tom", 11, 0.2, freq=150.0)
    if roll:
        # a roll that starts at a whisper only the last third of it counts
        for step in range(16):
            hit("snare", step, 0.42 + 0.036 * step)
        hit("crash", 0, 0.9)


def bass(mix: _Mix, bar: int, root: int, *, gallop_fig: bool) -> None:
    """The hooves below the hooves: a hammered tonic, a fifth, and a gallop pair."""
    t0 = bar * BAR
    low = root - 24
    pattern = ((0, 0), (.5, 0), (1, 7), (1.5, 0), (2, 0), (2.5, 0), (3, 7),
               (3.5, 12)) if gallop_fig else (
              (0, 0), (.5, 0), (1, 0), (1.5, 0), (2, 7), (2.5, 0), (3, 0),
              (3.5, 0))
    for beat, offset in pattern:
        freq = 440.0 * pow(2.0, (low + offset - 69) / 12.0)
        mix.instr(at(t0 + beat * QUARTER), SIXTEENTH * 3.4, freq, "pluck", 0.22)


def brass(mix: _Mix, bar: int, root: int, beats: float, *, loud: bool) -> None:
    """A call in octaves: saw, fast attack, no decay to speak of."""
    t0 = bar * BAR
    for offset, vol in ((0, 0.14), (7, 0.11), (12, 0.12), (19, 0.07)):
        freq = 440.0 * pow(2.0, (root + offset - 12 - 69) / 12.0)
        mix.voice(int(t0 * RATE), beats * QUARTER, freq, "saw",
                  vol * (1.25 if loud else 1.0), attack=0.012, decay=1.4)


def fiddle_line(mix: _Mix, bars_notes: list[tuple[int, tuple]]) -> None:
    """One bowed player across the whole cue: cuts, slides, repeated bows."""
    notes: list[tuple[float, float, float]] = []
    for bar, phrase in bars_notes:
        for beat, beats, degree in phrase:
            midi = deg_to_midi(degree)
            freq = 440.0 * pow(2.0, (midi - 69) / 12.0)
            notes.append(((bar * BAR + beat * QUARTER), beats * QUARTER * 0.96,
                          freq))
    samples = instruments.phrase("violin", notes, RATE)
    lay(mix.buf, 0.0, samples, 0.40)


def pad(mix: _Mix, bar: int, root: int) -> None:
    for offset in (0, 7, 12):
        freq = 440.0 * pow(2.0, (root + offset - 12 - 69) / 12.0)
        mix.instr(at(bar * BAR), BAR * 0.98, freq, "strings", 0.05)


def render() -> bytes:
    drums = kit_samples(KIT, KITS[KIT], RATE)
    mix = _Mix(int((BARS * BAR + 5.0) * RATE), rate=RATE, drums=drums)

    # the fiddle's whole part, built at once so the bow rules hold across joins
    solo: list[tuple[int, tuple]] = []
    for bar in range(2, 10):                       # A
        solo.append((bar, RIDE[(bar - 2) % 4] if (bar - 2) // 4 == 0
                     else ANSWER[(bar - 2) % 4]))
    for bar in range(10, 18):                      # B
        solo.append((bar, ANSWER[(bar - 2) % 4] if bar % 2 else
                     RIDE[(bar - 10) % 4]))
    for bar in range(20, 27):                      # A'
        solo.append((bar, RIDE[(bar - 20) % 4]))
    solo.append((27, FINALE_TAIL))
    # over the break the fiddle is the only thing keeping the promise: one note
    # held while the floor is gone, then a climb up into the last chorus
    solo.append((18, ((0, 4.0, 7),)))
    solo.append((19, ((0, 1.0, 5), (1, 1.0, 7), (2, 2.0, 9))))
    solo.sort(key=lambda item: item[0])
    fiddle_line(mix, solo)

    for bar, root in enumerate(CHORDS):
        brk = 18 <= bar < 20            # floor gone; the fiddle holds it together
        gallop(mix, bar, hooves=(bar >= 2 and not brk), roll=(bar == 19),
               hard=(bar >= 10 and not brk), bare=brk, ride=(bar >= 20))
        if bar >= 2 and not brk:
            bass(mix, bar, root, gallop_fig=bar >= 20)
        # the call opens the cue and answers the break - never over the break
        if bar in (0, 1, 2, 20, 27):
            brass(mix, bar, root, 1.5 if bar in (0, 1) else 1.0, loud=bar >= 20)
        if brk or bar >= 20:
            pad(mix, bar, root)

    # the hit that ends it
    end = int(BARS * BAR * RATE)
    mix.drum("crash", end, 0.9)
    mix.drum("kick", end, 1.0)
    for offset in (0, 7, 12, 19):
        freq = 440.0 * pow(2.0, (EM + offset - 12 - 69) / 12.0)
        mix.voice(end, QUARTER * 3.0, freq, "saw", 0.16, attack=0.008,
                  decay=1.1)
    return mix.normalise()


def main() -> None:
    out_dir = ROOT / "assets" / "music"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "study_mission_gallop.wav"
    pcm = render()
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(pcm)
    print(f"{path}\n  {len(pcm) / 2 / RATE:.1f} s  {len(pcm) / 1048576:.1f} MiB"
          f"  {BPM:.0f} BPM  {BARS} bars")


if __name__ == "__main__":
    main()
