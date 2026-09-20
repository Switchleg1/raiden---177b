# Music and drums

The soundtrack is **rendered, not played**: every cue is generated offline-style
into one 16-bit mono PCM buffer, and pygame only ever pushes bytes it never has
to think about. No instrument runs during a game frame, so the fixed 120 Hz
simulation never waits on audio.

```
music_content.py   literals only: scales, motifs, cadence, bass, KITS, GROOVES,
                   LAYOUT, THEMES / MENU_THEMES / BOSS_THEMES, LEVEL_CUES
music.py           the engine: _Mix (voices + master), bar rendering, rhythm
                   selection, render_track(), the playlist builders, which cue
                   a sector plays
instruments.py     flute / violin / strings / pluck / bell: one pitch and one
                   length in, one shaped buffer out
drum_kit.py        procedural rompler: renders each drum voice once per kit,
                   playback is one add + one multiply per sample
audio.py           the only pygame-aware layer: opens the mixer, publishes
                   tracks incrementally on a background thread
```

Sample rate note (this *was* the "music sounds fast" bug): generation rate must
equal the mixer's **opened** frequency. `render_track(theme, rate)` takes the
rate from `AudioManager`; never assume 22050 or 44100.

## Tempo convention

`spb = 120.0 / bpm` — one "beat" is a *half note* of the tag, so a theme tagged
134 moves at 67 effective quarter notes per minute. In practice: 4 beats per
bar, 8 bars per section, so a bar at `bpm 128` is `4 * 120/128` = 3.75 s. Groove
and kit selection thresholds read the **tag** bpm, which is what makes a cue
feel fast or heavy.

## Signal chain

* `_Mix.voice()` — one oscillator (implementation wave keys `square`/`tri`/`saw`,
  anything else is sine) with an exponential-decay envelope.
  `WAVE_ALIASES` maps the names the tables use (`pulse`, `triangle`, `sawtooth`)
  onto those keys. Before the alias map existed, every `pulse` lead in the
  roster silently played as a sine — that is why the leads used to sound tame.
* `_Mix.drum()` — mixes one kit hit at a sample offset.
* `normalise(peak=0.9, knee=0.68)` — soft-clip then scale, **then** quantise to
  int16. Layers routinely pass full scale; hard-clipping those samples flips
  their sign and that flip is the crackle people heard. The knee bends them
  with `tanh` instead, so no sample is ever pinned at ±32767.

## Drum kit (`drum_kit.py`)

A tiny rompler, not a per-hit synth. `kit_samples(name, params, rate)` renders
every voice **once** and caches it under `(name, rate)`; `play()` then copies a
hit into the mix. A kit costs ~0.12 s once, a 20-hit bar costs ~2 ms.

| voice | how it is actually made |
|-------|-------------------------|
| kick | sine with a pitch **glide** (155 Hz → 48 Hz), body + punch partials, click transient |
| snare | two detuned bodies + band-passed noise wash + a high snap; ghosts are the same voice at low velocity |
| hat / open | 6 inharmonic metallic partials, gated on alternate hits, high-passed; `open` just sustains longer |
| crash / ride | 8 inharmonic partials whose upper notes are quieter *and* die sooner (`partial_fall`), phase wobble (`shimmer`), pink-noise wash, bell for the crash |
| tom ×8 | tuned membrane with a short downward glide, one pre-rendered note per `TOM_FREQS` entry |
| rim | resonant band-pass click + a low blip |
| clap | 4-burst noise train through a band-pass, then a short body ring |

Every voice is normalised into the same peak band (0.85–0.92) so a groove
velocity means the same loudness whatever it hits. Kits (`KITS` in
`music_content.py`) are **parameter diffs** on those defaults: `crisp`, `punch`,
`heavy`, `metal`, `soft`. A preset never replaces a renderer, it bends numbers.

Robustness: an unknown voice name is a silent no-op, never an exception — the
renderer runs on the audio thread and a typo in a groove must not kill the
soundtrack.

## Instruments (`instruments.py`)

Four waves are a synth; a melody needs an instrument. `flute`, `violin`,
`strings`, `pluck` and `bell` are rendered per note and cached by
`(name, pitch, length)` — an arrangement repeats its material constantly, so the
cache is what keeps a 40 s cue from costing a minute of CPU.

What each one is, and what it is for:

| instrument | how | what it buys |
|-----|-----|-----|
| `flute` | sine + weak partials, breath noise, vibrato that fades in after ~0.2 s | a line that breathes; the wobble arrives like a lip, not like an LFO |
| `violin` | 8 harmonics at 1/h, ~0.14 s attack, wide late vibrato, bow hiss | the voice that can sing a melody instead of punching it |
| `strings` | three detuned bows, slow attack, long release | a pad that beats against itself instead of one loud saw |
| `pluck` | additive partials that rot at different rates | a harp/harpsichord arp that goes dull as it dies |
| `bell` | FM, inharmonic modulator with a decaying index | glass and metal, for stabs and arps |

They cost real time (a flute note renders at ~3 % of real time, strings at ~8 %),
which is why voicing is per cue and most cues stay plain synths: the retro
sectors are supposed to sound like chips. Voicing is data — the `instruments`
key above — and `_play()` in `music.py` decides per slot whether a name means an
instrument or one of the original waves, so every cue written before this module
existed renders byte-for-byte as it did.

`lead_b` exists for the two-voice writing that motivates the whole module: a
flute states the A phrase and the violin takes it up in the answer.

## Grooves

`GROOVES` are 16-step patterns (`(step, velocity)` per voice) plus optional
`swing`, `fill` variants and a boss `roll`. Rules the engine applies:

* **Swing** displaces odd 16th steps only, never the downbeat.
* **Ghost notes** are snare hits at low velocity.
* **Fills** replace the snare backbeat on the last bar of a section while kick
  and hats keep playing at reduced level (`duck`) — the groove bends, it does
  not stop. `FILL_VARIANT` picks a different fill for A and B phrases.
* **Tom pitches are positional**: the N toms in a bar take the lowest N kit
  notes, descending, so a run is a cadence and one tom is a low pulse.
* **Crash** lights the first bar of a boss/outro bar only. Accent, not wallpaper.

## Rhythm selection

`_rhythm(theme, rate)` returns `(groove, kit_samples)`, or `(None, None)` for a
drumless cue:

1. a theme's own `"groove"` / `"kit"` tag wins;
2. otherwise the tempo picks it through `GROOVE_BY_TEMPO` / `KIT_BY_TEMPO`;
3. a `drive: True` (boss) cue defaults to `GROOVE_BOSS` / `KIT_BOSS`;
4. an unknown name falls back (`straight` / `crisp`) instead of raising.

Most stage cues **are** tagged by hand, because tempo-bucketing alone makes
every stage feel the same: `Crypt March` is a phrygian `march` on the `heavy`
kit, `Crater Wastes` is `halftime` on `soft`, `Turbo Drift` is `drive16` on
`crisp`. `tests/test_drum_kit.py` enforces that the tags name real table entries
and that the roster still spans the groove set.

## Cue keys

| key | meaning |
|-----|---------|
| `name` | cue title (never a trademarked title) |
| `root` | MIDI root of the tonic |
| `bpm` | tempo tag (see the tempo convention above) |
| `lead` | lead wave name, resolved by `WAVE_ALIASES` |
| `prog` | 8 chord degrees (scale degrees of `scale`) for the 8 bars of a section |
| `scale` | `natural` (default), `harmonic`, `major`, `lydian`, `dorian`, `phrygian` |
| `groove` / `kit` | explicit rhythm identity; omit to select by tempo |
| `motifs` | melody family: `base` (default), `hero`, `lyric` — see `MOTIF_SETS` |
| `bass` | bass line name (`chug`, `run`); omit for the plain root-on-bar-one bass |
| `instruments` | slots handed to a synthesised instrument: `{"lead": "flute", "lead_b": "violin", "pad": "strings", "arp": "bell", "bass": "pluck"}` |
| `drums` | `False` = no percussion at all (menu / attract) |
| `drive` | `True` = boss bed: 16th octave ghosts under the bass, tritone stabs, crash on bar 1 |
| `layout` | section layout override (`LAYOUT`, `MENU_LAYOUT`, `BOSS_LAYOUT`) |

Adding a cue = adding one literal dict to the right table. The engine needs no
edit, the playlist builders pick it up, and `test_drum_kit.py` (rhythm tags) and
`test_music_arrangement.py` (motif, bass and voicing tags) validate it.

## Per-sector cue pools

One cue per sector, chosen once, is why a long run starts to feel like the same
tune. `LEVEL_CUES` gives each sector a **pool of 3–5 cues** that suit the ground
it flies over, and a visit draws one at random:

```python
LEVEL_CUES = {0: ("Overture of Field", "Daydream Vector", ...),
              1: ("Knight of the Marsh", "Back Alley", "Crypt March", ...), ...}
```

The rules live in `music.pick_level_cue()`, not in the table:

- only cues belonging to **this** sector are eligible, and only ones that have
  finished rendering;
- the cue that just played is skipped — repetition across sectors was the old
  bug, and repeating it here would only trade one bug for another;
- if the only thing rendered for the sector is its first-listed **identity
  cue**, that plays (it is the one the pool starts with, so a sector sounds
  right from the first second of launch);
- if nothing for the sector is ready yet, `AudioManager` falls back to *any*
  ready cue, because a live sector with no music is worse than the wrong tune.

A cue may appear in two pools (it is then registered under both sectors, via
`levels_for_cue`), and every cue in `THEMES` must appear in at least one pool —
tests enforce both, because a cue no sector can reach is a cue that never gets
heard. Sectors not in the table get the whole table rather than silence.

Rendering order follows the pools: `AudioManager._music_build_plan` schedules the
menu cue, then this run's starting identity cue, then one boss cue, then the
remaining cues **round-robin across sectors**, so every sector has a cue of its
own within the first seconds instead of sector 1 getting four while sector nine
waits behind them.

## Melodic identity

Rhythm alone does not make two cues feel like different levels: the melody and
the bass do the narrative work. A cue therefore names a **melody family** and a
**bass line**, both resolved by tables so the engine stays generic:

- `MOTIF_SETS` maps a family name to the `(A, B)` motif pair used for the two
  four-bar halves of a section. `base` is the original material; `hero` opens on
  a leap of an octave and answers by stepping down over a driving bass (the
  profile of a march); `lyric` lifts by a third then settles back over two
  bars — the profile of a ballad.
- `BASS_LINES` holds eight eighth-note `(tone, octave)` slots per bar. Tones are
  **relative to the chord that is sounding**: 0 root, 1 chord third, 2 chord
  fifth, 3 chromatic approach (a semitone below the root). That is what lets one
  written line follow any progression the cue uses, and why the approach tone is
  the one thing a plain root/fifth bass cannot fake.
- Octave pops (`octave == 12`) are played 12 % louder: without the accent they
  read as a wrong note instead of a deliberate pop.

Untagged cues keep the historical behaviour exactly — root on bar one, plain
eighth drive, `A`/`B` motifs — so the existing roster is byte-for-byte unchanged
(`test_music_arrangement.py::test_untagged_cue_keeps_the_stock_bass`).

## Melodic material policy

Reference material is **structural only**: mode, meter, tempo, layer roles,
cadence shape, arrangement density. No transcribed melodies, no borrowed
note-sequences, no trademarked titles in the roster. Motives come from `MOTIFS`
(transposed by the current chord degree) with `CADENCE` closing bar 8 of each
phrase, so every tune stays in key without a per-cue melody.

The three cues that lean on a specific reference (two stage tracks and the menu
ballad) are written from that profile only: mode, meter, tempo, which layer
owns the motion, and where the phrase resolves. `test_music_arrangement.py` locks the
fingerprints that define each family — the hero set must open with a leap of at
least an octave, the lyric set must not — so a later edit cannot silently turn
one family into the other.

## Build and publish

`build_cues` / `build_menu_playlist` / `build_bosses` are cached per sample rate
and guarded by a lock. `AudioManager` renders the plan **one cue at a time on a
background thread** and publishes each buffer as it finishes, so the title theme
is not blocked by the other 58 cues; a cue that fails to render is skipped, not
fatal, and cannot stop the rest (see `test_audio_music.py`).

Perf at 22050 Hz (this machine, whole plan = 59 cues):

| milestone | wall time |
|-----|-----|
| menu cue ready | 0.7 s |
| this run's starting sector cue ready | 3.0 s |
| first boss cue ready | 4.4 s |
| every sector has its own cue | ~26 s |
| whole soundtrack | ~105 s |

~2.5 s per stage cue with voicing, ~1.1 s without — the instruments are the
reason the total went from half a minute to two. It runs on a daemon thread while
the game plays: the simulation costs 0.016 ms/frame and 0.033 ms with a cue
rendering next to it, against a 8.3 ms budget, so nobody can feel it.

## How to listen without the game

```python
import sys; sys.path.insert(0, "src")
import music, wave
pcm = music.render_track(music.THEMES[3], rate=22050)
w = wave.open("out.wav", "wb"); w.setnchannels(1); w.setsampwidth(2)
w.setframerate(22050); w.writeframes(pcm); w.close()
```
