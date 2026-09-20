# `assets/music/` - arrangement studies

Rendered WAVs for **listening**, not game data. The game ships no audio files at
all: every cue is synthesised at runtime by `src/music.py` (see `docs/music.md`).
A study exists so an arrangement can be judged by ear before any of it is
promoted into a cue table, and re-rendered deterministically afterwards.

Nothing here is packaged. By the `data/` vs `assets/` rule in
`docs/architecture.md`, `assets/` is material the work is *made from* - delete it
and a checkout still builds, bakes and plays.

## Contents

| file | what it is | how to re-render |
| --- | --- | --- |
| `study_mission_gallop.wav` | a riding cue - "giddy up, on a mission". 150 BPM, 28 bars, Em. Gallop in the kick, hooves on the toms, hammered tonic bass, brass calls, fiddle answers. | `python scripts/study_mission_gallop.py` |

## Conventions

- One script per study in `scripts/study_*.py`, one WAV out, same stem. A study
  is disposable; the script is the thing worth keeping, because it regenerates
  the WAV byte-for-byte.
- Rendered at 44100 Hz for listening. The game's mixer opens at 22050 Hz, so a
  study always sounds brighter than the shipped cue.
- Melodies are originals. Where a study borrows the *feel* of a piece the writer
  has in mind, it takes structure - mode, meter, tempo, register, arrangement,
  cadence shape - and never a tune. That is the same melodic-material policy the
  soundtrack follows (`docs/music.md`).
