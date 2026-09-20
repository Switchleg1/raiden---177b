"""Music content: the nine sector cues, the menu playlist and the boss cues.

Pure data - no synthesis here. Each theme is a chord progression plus the
colour choices the synth in :mod:`music` needs: ``root`` (MIDI note of the
tonic), ``bpm``, ``lead`` waveform, ``prog`` (eight scale-degree roots, one per
bar, so harmony moves every bar) and optional ``scale`` / ``drums`` / ``drive``
/ ``layout`` overrides.

Editing a sector's theme is a data change: pick a different mode, retune the
progression, swap the lead. Nothing in the engine has to move.
"""
from __future__ import annotations

# Natural minor by default; a theme opts into another mode with "scale".
# Natural-minor scale (semitones from the root), used for triads and melody.
SCALE = (0, 2, 3, 5, 7, 8, 10)
# Optional per-theme scale variants. Each is 7 degrees so the index math
# (divmod by 7) is unchanged; only the semitone content differs:
#   harmonic -> raised 7th, so the v chord becomes a major V (the gothic
#              cadence used all over Castlevania and JRPG final battles).
#   major    -> bright heroic fanfares.
#   lydian   -> major with a raised 4th; the dreamy, questing colour of
#              classic Zelda overworld themes.
SCALES: dict[str, tuple[int, ...]] = {
    "natural": SCALE,
    "harmonic": (0, 2, 3, 5, 7, 8, 11),
    "major": (0, 2, 4, 5, 7, 9, 11),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    # Dorian: minor with a raised 6th - the mode of tense-but-grooving cues
    # (brawl alleys, sleazy night stages). Phrygian: flat 2nd - the "occult"
    # semitone under the tonic, for dungeons and tombs.
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
}

# --- bar motifs -------------------------------------------------------------
# Each motif is a list of (start_beat, dur_beats, scale_degree_offset) relative
# to the current bar's chord root scale-degree, so melodies always stay in key.
# Named motif sets live in this same table: MOTIFS["A"]/MOTIFS["B"] are the
# base set (what an untagged cue uses), the other keys are extra melodies in
# the same format. MOTIF_SETS maps a cue's `"motifs"` tag onto an (A, B) pair,
# so a cue can own its own tune without the engine knowing anything about it.
MOTIF_SETS = {"base": ("A", "B"), "hero": ("hero_A", "hero_B"),
              "lyric": ("lyric_A", "lyric_B")}

MOTIFS = {
    "A": (
        ((0.0, 1.0, 4), (1.0, 0.5, 2), (1.5, 0.5, 0), (2.0, 1.0, 2), (3.0, 1.0, 0)),
        ((0.0, 1.0, 2), (1.0, 1.0, 0), (2.0, 0.5, 3), (2.5, 0.5, 2), (3.0, 1.0, -1)),
        ((0.0, 0.5, 0), (0.5, 0.5, 2), (1.0, 1.0, 4), (2.0, 1.0, 2), (3.0, 1.0, 0)),
        ((0.0, 1.5, 7), (1.5, 0.5, 4), (2.0, 1.0, 2), (3.0, 1.0, 4)),
    ),
    "B": (
        ((0.0, 0.5, 7), (0.5, 0.5, 6), (1.0, 1.0, 4), (2.0, 0.5, 7), (2.5, 0.5, 9), (3.0, 1.0, 7)),
        ((0.0, 1.0, 4), (1.0, 0.5, 5), (1.5, 0.5, 4), (2.0, 1.0, 2), (3.0, 1.0, 0)),
        ((0.0, 0.5, 9), (0.5, 0.5, 7), (1.0, 0.5, 6), (1.5, 0.5, 7), (2.0, 1.0, 4), (3.0, 1.0, 2)),
        ((0.0, 1.0, 2), (1.0, 0.5, 4), (1.5, 0.5, 5), (2.0, 2.0, 4)),
    ),
    # --- heroic set ---------------------------------------------------------
    # Structural profile of a certain SNES knight-errant theme: aeolian minor,
    # dotted fanfare rhythm, an anacrusis-style leap up to the fifth/octave that
    # answers downward, and cadences that walk i-VI-VII instead of resolving.
    # Profile only: these note sequences are written here, not transcribed.
    "hero_A": (
        ((0.0, 0.75, 7), (0.75, 0.25, 2), (1.0, 1.0, 4), (2.0, 0.5, 2),
         (2.5, 0.5, 0), (3.0, 1.0, 2)),
        ((0.0, 0.5, 4), (0.5, 0.5, 7), (1.0, 1.5, 9), (2.5, 0.5, 7),
         (3.0, 1.0, 4)),
        ((0.0, 1.0, 2), (1.0, 0.5, 4), (1.5, 0.5, 2), (2.0, 1.0, 0),
         (3.0, 0.5, -1), (3.5, 0.5, 0)),
        ((0.0, 1.5, 7), (1.5, 0.5, 9), (2.0, 1.0, 7), (3.0, 1.0, 4)),
    ),
    "hero_B": (
        ((0.0, 0.5, 11), (0.5, 0.5, 9), (1.0, 1.0, 7), (2.0, 1.0, 9),
         (3.0, 1.0, 7)),
        ((0.0, 1.0, 9), (1.0, 0.5, 7), (1.5, 0.5, 4), (2.0, 2.0, 7)),
        ((0.0, 0.75, 7), (0.75, 0.25, 9), (1.0, 1.5, 11), (2.5, 0.5, 9),
         (3.0, 1.0, 7)),
        ((0.0, 1.0, 12), (1.0, 1.0, 11), (2.0, 0.5, 9), (2.5, 0.5, 7),
         (3.0, 1.0, 4)),
    ),
    # --- lyrical set --------------------------------------------------------
    # Structural profile of a certain SNES seeress theme: whole-note phrases,
    # stepwise descent, a raised fourth used as a colour tone (works because the
    # cue is tagged Lydian), and a long note held across the chord change.
    "lyric_A": (
        ((0.0, 2.0, 7), (2.0, 1.0, 6), (3.0, 1.0, 4)),
        ((0.0, 1.5, 9), (1.5, 1.5, 7), (3.0, 1.0, 6)),
        ((0.0, 2.0, 4), (2.0, 1.0, 6), (3.0, 1.0, 7)),
        ((0.0, 1.0, 11), (1.0, 2.0, 9), (3.0, 1.0, 7)),
    ),
    "lyric_B": (
        ((0.0, 2.0, 4), (2.0, 1.0, 2), (3.0, 1.0, 0)),
        ((0.0, 1.5, 7), (1.5, 1.5, 6), (3.0, 1.0, 4)),
        ((0.0, 2.0, 2), (2.0, 1.0, 4), (3.0, 1.0, 5)),
        ((0.0, 1.0, 7), (1.0, 1.0, 6), (2.0, 1.0, 4), (3.0, 1.0, 2)),
    ),
}
CADENCE = ((0.0, 2.0, 0), (2.0, 1.0, 4), (3.0, 1.0, 7))
# Bass 8th-note patterns: indices into the current triad (0=root, 2=fifth).
BASS = {
    "intro": (0, 0, 0, 0, 0, 0, 0, 0),
    "A": (0, 0, 2, 0, 0, 2, 0, 2),
    "B": (0, 1, 0, 2, 0, 1, 0, 2),
    "outro": (0, 0, 0, 0, 2, 2, 0, 0),
}

# --- named bass lines -------------------------------------------------------
# A cue may name one of these with `"bass": "<name>"`; otherwise it plays BASS.
# Each line is the eight 8ths of a bar as (chord tone, extra octaves), where
# chord tone 0/1/2 is the root/third/fifth of the current chord and 3 is the
# chromatic approach a semitone *below* the root (the note that pulls the ear
# into the next bar's chord). The engine adds the bass octave; these numbers are
# relative, so a line sounds right under any chord in any progression.
BASS_LINES: dict[str, dict[str, tuple[tuple[int, int], ...]]] = {
    # The chugging heroic line: root 8ths, octave pops on the back half of
    # beats 2 and 4, and an approach tone walking into the next chord. Arranged
    # under a fanfare lead, this is what makes a slow-ish cue feel driven.
    "chug": {
        "intro": ((0, 0), (0, 0), (0, 12), (0, 0), (0, 0), (0, 12), (0, 0),
                  (3, 0)),
        "A": ((0, 0), (0, 0), (0, 12), (0, 0), (2, 0), (2, 0), (0, 12), (3, 0)),
        "B": ((0, 0), (0, 12), (0, 0), (1, 0), (0, 0), (2, 12), (0, 0), (3, 0)),
        "outro": ((0, 0), (0, 0), (0, 12), (0, 0), (2, 0), (2, 0), (0, 0),
                  (0, 0)),
    },
    # The running line: root / fifth alternation with octave pops, written to
    # carry a long, slow melody without fighting it. The bass moves in 8ths
    # while the lead holds whole notes - the two layers never compete for the
    # same rhythm, which is the whole trick behind an upbeat ballad cue.
    "run": {
        "intro": ((0, 0), (2, 0), (0, 0), (2, 0), (0, 0), (2, 0), (0, 12),
                  (2, 0)),
        "A": ((0, 0), (2, 0), (0, 12), (2, 0), (0, 0), (2, 0), (0, 12), (2, 0)),
        "B": ((0, 0), (2, 0), (1, 0), (2, 0), (0, 0), (2, 0), (1, 0), (3, 0)),
        "outro": ((0, 0), (2, 0), (0, 0), (2, 0), (0, 0), (0, 0), (0, 0),
                  (0, 0)),
    },
}

# --- drum kits -------------------------------------------------------------
# Parameters for src/drum_kit.py: pitch, decay, brightness and playback gain.
# Velocities in GROOVES stay 0..1 and each kit decides how loud *its* voices
# sit against the synth, so re-balancing drums vs. leads never means touching
# a groove. Every key is optional; drum_kit.<VOICE>_DEFAULTS fills the rest.
KITS: dict[str, dict] = {
    # Tight, bright, front-of-the-mix. The default for mid/fast stage cues.
    "crisp": {
        "kick": {"f0": 165.0, "f1": 52.0, "glide": 0.026, "decay": 8.0,
                 "click": 0.5, "punch": 0.55, "dur": 0.36},
        "snare": {"body_f": 195.0, "body_dec": 46.0, "noise_f": 2100.0,
                  "noise_dec": 23.0, "snap": 0.6},
        "hat": {"base": 860.0, "decay": 70.0, "bp": 8600.0},
        "open": {"dur": 0.30, "decay_scale": 0.18},
        "tom": {"decay": 10.0, "dur": 0.30},
        "gain": {"kick": 0.40, "snare": 0.30, "hat": 0.115, "open": 0.085,
                 "ride": 0.085, "crash": 0.13, "rim": 0.13, "clap": 0.15,
                 "tom": 0.21},
    },
    # Rounder kick, more membrane than crack. Mid-tempo grooves.
    "punch": {
        "kick": {"f0": 150.0, "f1": 47.0, "glide": 0.034, "decay": 6.8,
                 "click": 0.38, "punch": 0.45, "dur": 0.44},
        "snare": {"body_f": 178.0, "body_dec": 38.0, "noise_f": 1750.0,
                  "noise_dec": 27.0, "snap": 0.45},
        "hat": {"base": 780.0, "decay": 60.0, "bp": 8000.0},
        "tom": {"decay": 8.0},
        "gain": {"kick": 0.42, "snare": 0.31, "hat": 0.105, "open": 0.08,
                 "ride": 0.08, "crash": 0.125, "rim": 0.12, "clap": 0.15,
                 "tom": 0.22},
    },
    # Big and low: deep kick, fat snare, dark metal. Slow dread and bosses.
    "heavy": {
        "kick": {"f0": 140.0, "f1": 41.0, "glide": 0.045, "decay": 5.6,
                 "click": 0.32, "punch": 0.4, "sat": 2.0, "dur": 0.52},
        "snare": {"body_f": 158.0, "body_dec": 30.0, "noise_f": 1450.0,
                  "noise_dec": 32.0, "wash": 0.95, "snap": 0.42},
        "hat": {"base": 700.0, "decay": 52.0, "hp": 4600.0, "bp": 7400.0},
        "crash": {"base": 240.0, "decay": 3.4, "wash_dec": 2.8, "dur": 1.3},
        "tom": {"decay": 6.5, "dur": 0.42, "glide": -0.14},
        "gain": {"kick": 0.46, "snare": 0.34, "hat": 0.10, "open": 0.08,
                 "ride": 0.08, "crash": 0.16, "rim": 0.12, "clap": 0.16,
                 "tom": 0.26},
    },
    # Industrial and bright: saturated kick, prominent rim/clap, cutting hats.
    "metal": {
        "kick": {"f0": 175.0, "f1": 55.0, "glide": 0.022, "decay": 9.0,
                 "click": 0.62, "click_f": 3200.0, "punch": 0.62,
                 "sat": 2.2, "dur": 0.34},
        "snare": {"body_f": 210.0, "ratio": 1.9, "body_dec": 50.0,
                  "noise_f": 2500.0, "noise_q": 0.7, "noise_dec": 21.0,
                  "snap": 0.7, "snap_f": 4200.0},
        "hat": {"base": 950.0, "decay": 80.0, "hp": 5600.0, "bp": 9000.0,
                "chick": 0.55},
        "rim": {"f": 2400.0, "blip": 700.0},
        "clap": {"f": 1350.0, "tail_dec": 16.0},
        "crash": {"base": 360.0, "decay": 5.0, "bell_level": 0.2},
        "tom": {"decay": 11.0, "noise": 0.2, "dur": 0.28},
        "gain": {"kick": 0.44, "snare": 0.33, "hat": 0.125, "open": 0.09,
                 "ride": 0.09, "crash": 0.15, "rim": 0.16, "clap": 0.19,
                 "tom": 0.23},
    },
    # Brushed back: quiet hats, soft transient, long-ish snare wash. For the
    # slow, atmospheric cues (and anything that has to sit under an alarm).
    "soft": {
        "kick": {"f0": 130.0, "f1": 45.0, "glide": 0.040, "decay": 6.0,
                 "click": 0.22, "punch": 0.32, "dur": 0.46},
        "snare": {"body_f": 168.0, "body_dec": 30.0, "noise_f": 1500.0,
                  "noise_dec": 34.0, "wash": 0.9, "snap": 0.3},
        "hat": {"base": 720.0, "decay": 48.0, "hp": 4400.0, "bp": 7000.0,
                "noise": 0.26, "chick": 0.25},
        "open": {"dur": 0.42, "decay_scale": 0.12},
        "ride": {"decay": 5.0, "dur": 0.75, "ping_level": 0.26},
        "tom": {"decay": 7.0, "dur": 0.4},
        "gain": {"kick": 0.34, "snare": 0.25, "hat": 0.085, "open": 0.07,
                 "ride": 0.075, "crash": 0.11, "rim": 0.10, "clap": 0.12,
                 "tom": 0.19},
    },
}

# --- grooves ---------------------------------------------------------------
# One bar = 16 sixteenth-note steps. Every entry is (step, velocity 0..1) and
# every voice is optional. Voice names are the drum_kit sample names, plus
# "ghost" (a snare played at a fraction of the level - the thing that makes a
# breakbeat feel played rather than programmed).
#
#   fill  rotated by phrase on the last bar of each 8-bar section
#   roll  crescendo the boss intro bar uses instead of the groove
#   swing how far odd 16ths are pushed late, as a fraction of a 16th
GROOVES: dict[str, dict] = {
    # Baseline synthwave: kick 1 and 3, snare 2 and 4, 8th hats, open hat on
    # the "a" of 4 so the bar lifts into the next one.
    "straight": {
        "kick": ((0, 1.0), (8, 0.95), (14, 0.4)),
        "snare": ((4, 0.95), (12, 0.95)),
        "ghost": ((10, 0.18),),
        "hat": ((0, 0.75), (2, 0.4), (4, 0.7), (6, 0.4), (8, 0.75), (10, 0.4),
                (12, 0.7), (14, 0.45)),
        "open": ((14, 0.3),),
        "swing": 0.0,
        "fill": (
            ((8, "tom", 0.7), (10, "tom", 0.6), (12, "snare", 0.85),
             (13, "tom", 0.7), (14, "tom", 0.55), (15, "kick", 0.6)),
            ((9, "tom", 0.6), (10, "tom", 0.5), (11, "tom", 0.45),
             (12, "snare", 0.8), (13, "snare", 0.5), (14, "snare", 0.4),
             (15, "crash", 0.6)),
        ),
    },
    # The riding cue: a gallop, and the gallop is in the kick, not in the tempo.
    # Kick on 1 and 3 plus the "a" of each, so the beat lurches forward into the
    # next one; tom pairs on the e and the a are the hooves. Straight, no swing:
    # a swung gallop stops being a charge and starts being a shuffle.
    "gallop": {
        "kick": ((0, 1.0), (6, 0.72), (8, 0.95), (14, 0.72)),
        "snare": ((4, 0.95), (12, 0.95)),
        "ghost": ((10, 0.2),),
        "hat": ((0, 1.0), (2, 0.55), (4, 0.9), (6, 0.55), (8, 1.0), (10, 0.55),
                (12, 0.9), (14, 0.55)),
        "tom": ((2, 0.3), (3, 0.2), (10, 0.3), (11, 0.2)),
        "open": ((14, 0.4),),
        "swing": 0.0,
        "fill": (
            ((8, "tom", 0.7), (9, "tom", 0.5), (10, "tom", 0.65),
             (11, "tom", 0.45), (12, "snare", 0.85), (13, "snare", 0.5),
             (14, "crash", 0.6), (15, "kick", 0.7)),
            ((8, "snare", 0.55), (9, "snare", 0.65), (10, "snare", 0.75),
             (11, "snare", 0.85), (12, "crash", 0.7), (14, "kick", 0.9)),
        ),
    },
    # Mega Man X / breakbeat: syncopated kick, ghost snares between the
    # backbeats, hats on every 16th with a light swing.
    "break": {
        "kick": ((0, 1.0), (6, 0.75), (10, 0.9), (13, 0.45)),
        "snare": ((4, 1.0), (12, 1.0)),
        "ghost": ((2, 0.16), (7, 0.2), (9, 0.16), (14, 0.22)),
        "hat": ((0, 0.8), (2, 0.42), (3, 0.26), (4, 0.62), (6, 0.42),
                (7, 0.26), (8, 0.78), (10, 0.42), (11, 0.26), (12, 0.62),
                (14, 0.42), (15, 0.26)),
        "open": ((10, 0.26),),
        "swing": 0.06,
        "fill": (
            ((8, "snare", 0.8), (9, "ghost", 0.3), (10, "tom", 0.65),
             (11, "tom", 0.55), (12, "kick", 0.8), (13, "tom", 0.6),
             (14, "snare", 0.7), (15, "crash", 0.55)),
            ((6, "tom", 0.6), (7, "tom", 0.5), (8, "snare", 0.75),
             (10, "snare", 0.6), (12, "snare", 0.85), (13, "snare", 0.5),
             (14, "snare", 0.45), (15, "kick", 0.7)),
        ),
    },
    # F-Zero chase: four-on-the-floor kick, backbeat snare, hats on every 16th
    # and ride on the quarters, so nothing in the bar is ever empty.
    "drive16": {
        "kick": ((0, 1.0), (4, 0.82), (8, 1.0), (12, 0.82), (10, 0.38)),
        "snare": ((4, 0.9), (12, 0.9)),
        "hat": ((0, 0.8), (1, 0.28), (2, 0.45), (3, 0.28), (4, 0.7), (5, 0.28),
                (6, 0.45), (7, 0.28), (8, 0.8), (9, 0.28), (10, 0.45),
                (11, 0.28), (12, 0.7), (13, 0.28), (14, 0.45), (15, 0.3)),
        "ride": ((0, 0.32), (4, 0.26), (8, 0.32), (12, 0.26)),
        "open": ((14, 0.32),),
        "swing": 0.0,
        "fill": (
            ((8, "tom", 0.75), (9, "tom", 0.65), (10, "tom", 0.55),
             (11, "tom", 0.5), (12, "snare", 0.9), (13, "snare", 0.6),
             (14, "snare", 0.5), (15, "crash", 0.7)),
            ((10, "tom", 0.6), (11, "tom", 0.55), (12, "kick", 0.9),
             (13, "tom", 0.6), (14, "snare", 0.8), (15, "kick", 0.7)),
        ),
    },
    # DKC "Fear Factory" dread: one kick, one huge snare on 3, ride on the
    # quarters. Space is the effect; the bass line carries the bar.
    "halftime": {
        "kick": ((0, 1.0), (11, 0.45)),
        "snare": ((8, 1.0),),
        "hat": ((0, 0.5), (4, 0.34), (8, 0.5), (12, 0.34)),
        "ride": ((0, 0.4), (4, 0.26), (8, 0.38), (12, 0.26))
        ,
        "clap": ((8, 0.22),),
        "swing": 0.0,
        "fill": (
            ((8, "tom", 0.8), (10, "tom", 0.65), (12, "tom", 0.6),
             (14, "snare", 0.85), (15, "crash", 0.75)),
            ((9, "tom", 0.7), (10, "tom", 0.6), (11, "tom", 0.5),
             (12, "snare", 0.8), (13, "ghost", 0.35), (14, "snare", 0.5),
             (15, "kick", 0.8)),
        ),
    },
    # Castlevania "Simon's Theme" march: kick on the quarters, heavy snare on
    # 3, rim on the off-beats (the military gallop), 16th pickup at bar end.
    "march": {
        "kick": ((0, 0.95), (4, 0.55), (8, 0.95), (12, 0.55)),
        "snare": ((8, 0.95), (14, 0.5), (15, 0.6)),
        "rim": ((2, 0.3), (6, 0.3), (10, 0.3), (14, 0.28)),
        "hat": ((0, 0.45), (4, 0.32), (8, 0.45), (12, 0.32)),
        "swing": 0.0,
        "fill": (
            ((10, "rim", 0.4), (11, "rim", 0.35), (12, "snare", 0.9),
             (13, "snare", 0.6), (14, "snare", 0.45), (15, "kick", 0.8)),
            ((8, "tom", 0.7), (10, "tom", 0.6), (12, "snare", 0.85),
             (14, "crash", 0.7), (15, "snare", 0.5)),
        ),
    },
    # Boss bed: double kick, 16th hats, backbeat snare and a low tom pulse on
    # the last 16th so every bar pushes into the next one.
    "grind": {
        "kick": ((0, 1.0), (3, 0.45), (4, 0.8), (8, 1.0), (11, 0.45),
                 (12, 0.8)),
        "snare": ((4, 0.9), (12, 0.9)),
        "ghost": ((6, 0.2), (14, 0.2)),
        "hat": ((0, 0.82), (1, 0.3), (2, 0.48), (3, 0.3), (4, 0.72), (5, 0.3),
                (6, 0.48), (7, 0.3), (8, 0.82), (9, 0.3), (10, 0.48),
                (11, 0.3), (12, 0.72), (13, 0.3), (14, 0.48), (15, 0.32)),
        "tom": ((15, 0.45),),
        "clap": ((7, 0.2),),
        "swing": 0.0,
        "fill": (
            ((8, "tom", 0.85), (9, "tom", 0.75), (10, "tom", 0.65),
             (11, "tom", 0.6), (12, "snare", 0.95), (13, "snare", 0.7),
             (14, "snare", 0.6), (15, "crash", 0.8)),
            ((6, "tom", 0.7), (7, "tom", 0.6), (8, "kick", 0.9),
             (10, "tom", 0.65), (11, "tom", 0.55), (12, "snare", 0.9),
             (13, "snare", 0.6), (14, "snare", 0.5), (15, "kick", 0.8)),
        ),
        # The one bar of alarm before the fight: 16th snare crescendo.
        "roll": ((0, 0.3), (1, 0.34), (2, 0.38), (3, 0.42), (4, 0.46),
                 (5, 0.5), (6, 0.55), (7, 0.6), (8, 0.65), (9, 0.7),
                 (10, 0.75), (11, 0.8), (12, 0.85), (13, 0.88), (14, 0.92),
                 (15, 1.0)),
    },
}

# Fallback selection when a theme does not name a groove/kit: tempo decides,
# because that is what actually makes a groove feel fast or heavy. A theme can
# always override with "groove" / "kit".
GROOVE_BY_TEMPO = ((240, "gallop"), (200, "drive16"), (132, "break"),
                   (108, "straight"), (0, "halftime"))
KIT_BY_TEMPO = ((230, "crisp"), (190, "punch"), (0, "soft"))
GROOVE_BOSS = "grind"
KIT_BOSS = "metal"

# (section, bars) layout -> 2 + 8 + 8 + 2 = 20 bars per loop.
LAYOUT = (("intro", 2), ("A", 8), ("B", 8), ("outro", 2))
# A playlist of calmer tracks for the title / options / game-over menus. They
# use the same synth engine but drop the drums and use a shorter, more spacious
# layout so they sit quietly under menu navigation instead of driving gameplay.
# The App picks a *random* one on entering the menus and a random *next* one
# when a track finishes (see AudioManager.play_menu_music / menu_finished).
MENU_LAYOUT = (("intro", 2), ("A", 8), ("outro", 2))
# --- boss battle music ------------------------------------------------------
# The level cues are deliberately slow-burn synthwave (~58-70 effective BPM).
# A boss has to flip the mood in one second: one bar of alarm, then a cue that
# is a quarter faster (75-88 effective BPM), in harmonic minor where the level
# pool is mostly natural minor, with the `drive` rhythm bed (16th hats,
# four-on-the-floor, tritone stabs). Short intro on purpose - the fight starts
# NOW - and no long outro, since the sector jingle takes over when it dies.
BOSS_LAYOUT = (("intro", 1), ("A", 8), ("B", 8), ("outro", 1))

# One theme per level. `prog` lists 8 natural-minor scale-degree roots (the
# progression moves every bar, so the harmony never loops on a 2-second cell).
THEMES: tuple[dict, ...] = (
    {"name": "Neon Grid",   "root": 57, "bpm": 214, "lead": "pulse",
     "prog": (0, 5, 2, 6, 3, 0, 5, 4), "kit": "punch"},
    {"name": "Chrome Run",  "root": 55, "bpm": 252, "lead": "square",
     "prog": (0, 6, 5, 6, 3, 5, 0, 4)},
    {"name": "Laser Night", "root": 60, "bpm": 220, "lead": "pulse",
     "prog": (0, 3, 5, 4, 6, 3, 2, 4)},
    {"name": "Turbo Drift", "root": 53, "bpm": 250, "lead": "saw",
     "prog": (0, 5, 3, 6, 0, 4, 5, 6), "kit": "crisp"},
    {"name": "Final Wave",  "root": 58, "bpm": 232, "lead": "pulse",
     "prog": (0, 6, 5, 4, 3, 6, 5, 4),
     "instruments": {"pad": "strings"}, },
    # Extra level cues: the level playlist picks a random track per level (never
    # the same one back-to-back), so the pool is deliberately larger than the
    # number of levels. New original progressions in classic synthwave archetypes
    # (Retro Cascade i-VI-VII-VI, driving i-VII-VI-VII, daydream i-VI-III-VII,
    # minor 4-chord cycles) written in natural-minor scale degrees.
    {"name": "Retro Cascade", "root": 53, "bpm": 212, "lead": "square",
     "prog": (0, 5, 6, 5, 3, 5, 6, 4)},
    {"name": "Midnight Run", "root": 57, "bpm": 252, "lead": "saw",
     "prog": (0, 6, 5, 0, 6, 4, 5, 6)},
    {"name": "Daydream Vector", "root": 62, "bpm": 172, "groove": "straight", "lead": "pulse",
     "prog": (0, 5, 2, 4, 5, 3, 2, 6), "kit": "soft",
     "instruments": {"arp": "bell"}, },
    {"name": "Sunset Circuit", "root": 55, "bpm": 178, "lead": "triangle",
     "prog": (0, 3, 6, 5, 3, 0, 4, 6), "kit": "soft",
     "instruments": {"lead": "flute"}, },
    {"name": "Hyper Grid", "root": 60, "bpm": 240, "lead": "square",
     "prog": (0, 4, 5, 6, 3, 4, 5, 0)},
    # Original cues channelled from classic NES/SNES action-score archetypes
    # (belt-scroll brawlers, gothic-horror platformers, and JRPG adventure
    # themes). These are stylistic homages only: original natural-minor degree
    # progressions, no borrowed melodies and no trademarked titles.
    {"name": "Steel Fist", "root": 57, "bpm": 244, "lead": "saw",
     "kit": "heavy",
     "prog": (0, 6, 5, 6, 0, 6, 5, 4)},          # driving belt-scroll riff
    {"name": "Back Alley", "root": 53, "bpm": 212, "lead": "square",
     "scale": "dorian", "kit": "heavy",
     "prog": (0, 0, 5, 6, 3, 0, 6, 4),  # tense verse/chorus brawl
     "instruments": {"arp": "pluck"}, },
    {"name": "Cathedral Run", "root": 55, "bpm": 186, "groove": "straight", "lead": "saw",
     "kit": "metal",
     "prog": (0, 5, 6, 5, 0, 3, 6, 4),  # gothic heroic gallop
     "instruments": {"pad": "strings", "arp": "bell"}, },
    {"name": "Crypt March", "root": 57, "bpm": 210, "lead": "pulse",
     "scale": "phrygian", "groove": "march", "kit": "heavy",
     "prog": (0, 6, 5, 0, 3, 6, 5, 4),  # brooding dungeon crawl
     "instruments": {"bass": "pluck"}, },
    {"name": "Clockwork Tide", "root": 60, "bpm": 228, "lead": "pulse",
     "groove": "drive16",
     "prog": (0, 2, 5, 4, 0, 2, 6, 4)},          # hopeful mediant (III) lift
    {"name": "Knight's Resolve", "root": 58, "bpm": 222, "lead": "triangle",
     "groove": "march", "kit": "punch",
     "prog": (0, 3, 2, 4, 5, 3, 0, 6),  # noble quest fanfare
     "instruments": {"lead": "flute", "lead_b": "violin"}, },
    # ---- researched NES/SNES archetypes (see docs) -------------------------------
    # Original degree progressions channelled from real chord *analyses* of these
    # scores (structure only, never copied melodies, never trademarked titles).
    # `scale: harmonic` raises the 7th so the v chord becomes a major V -- the
    # gothic cadence that defines Castlevania and JRPG battle music.
    {"name": "Blood Moon Rite", "root": 57, "bpm": 228, "lead": "saw",
     "scale": "harmonic", "kit": "heavy",
     "prog": (0, 5, 6, 4, 0, 5, 6, 4),  # i-VI-vii degree-V ritual
     "instruments": {"arp": "bell"}, },
    {"name": "Candelabra Hall", "root": 55, "bpm": 216, "lead": "saw",
     "scale": "harmonic", "kit": "soft",
     "prog": (0, 3, 4, 0, 0, 3, 4, 5),  # i-iv-V-i
     "instruments": {"lead": "bell"}, },
    {"name": "Night Fortress", "root": 57, "bpm": 234, "lead": "pulse",
     "scale": "harmonic", "kit": "metal",
     "prog": (0, 6, 5, 4, 0, 3, 5, 4),  # descending gothic
     "instruments": {"pad": "strings"}, },
    {"name": "Battle Verge", "root": 62, "bpm": 244, "lead": "square",
     "scale": "harmonic", "prog": (0, 3, 4, 0, 5, 3, 4, 0),  # i-iv-V (CT battle)
     "instruments": {"bass": "pluck"}, },
    {"name": "Magus Gate", "root": 64, "bpm": 218, "lead": "saw",
     "scale": "harmonic", "kit": "soft",
     "prog": (0, 2, 0, 4, 0, 5, 2, 4),  # III+ aug mystery
     "instruments": {"lead": "violin", "pad": "strings"}, },
    {"name": "Hyrule Ascent", "root": 60, "bpm": 226, "lead": "pulse",
     "scale": "lydian", "groove": "march", "kit": "punch",
     "prog": (0, 4, 5, 3, 0, 4, 1, 0),  # heroic Lydian
     "instruments": {"lead": "flute"}, },
    {"name": "Kakariko Heights", "root": 62, "bpm": 226, "lead": "triangle",
     "scale": "lydian", "groove": "break", "kit": "punch",
     "prog": (0, 1, 3, 4, 0, 1, 4, 0)},      # Lydian II lift
    {"name": "Rooftop Duel", "root": 53, "bpm": 248, "lead": "saw",
     "kit": "heavy",
     "prog": (0, 6, 0, 5, 6, 0, 4, 0),  # belt-scroll i-VII
     "instruments": {"lead": "violin"}, },
    # Secret of Mana "Fear of the Heavens" homage: analyses give Am with a major
    # V (D/E) and chromatic mediants -> A harmonic minor, i-VI-iv-V.
    {"name": "Empyrean Dread", "root": 57, "bpm": 176, "lead": "saw",
     "scale": "harmonic", "groove": "halftime", "kit": "heavy",
     "prog": (0, 5, 3, 4, 0, 5, 3, 4),  # i-VI-iv-V (SoM)
     "instruments": {"pad": "strings"}, },
    # ---- more classics -----------------------------------------------------------
    # Original degree progressions in the spirit of these scores (structure only;
    # no copied melodies, no trademarked names as track titles).
    {"name": "Oath of Flame", "root": 57, "bpm": 246, "lead": "saw",      # Soul Blazer
     "scale": "harmonic", "kit": "metal",
     "prog": (0, 3, 4, 0, 0, 5, 3, 4),  # noble i-iv-V
     "instruments": {"lead": "violin"}, },
    {"name": "Peak of Regret", "root": 55, "bpm": 196, "lead": "saw",     # Soul Blazer
     "groove": "halftime", "kit": "heavy",
     "prog": (0, 6, 5, 4, 0, 6, 3, 4),  # epic descent
     "instruments": {"lead": "flute", "lead_b": "violin", "pad": "strings"}, },
    {"name": "Overture of Field", "root": 61, "bpm": 224, "lead": "triangle",  # ALttP
     "scale": "major", "groove": "march",
     "prog": (0, 3, 4, 0, 5, 3, 4, 0),  # bright heroic
     "instruments": {"lead": "flute", "pad": "strings"}, },
    {"name": "Neon Freeway", "root": 62, "bpm": 256, "lead": "square",    # Mega Man X
     "prog": (0, 0, 3, 4, 0, 5, 3, 4),  # driving i-VII
     "instruments": {"arp": "bell"}, },
    {"name": "Crater Wastes", "root": 53, "bpm": 188, "lead": "saw",      # Metroid
     "scale": "dorian", "groove": "halftime", "kit": "soft",
     "prog": (0, 6, 5, 0, 3, 6, 5, 4)},                                   # eerie expanse
    {"name": "Gearwork Cathedral", "root": 57, "bpm": 236, "lead": "pulse",   # Castlevania
     "scale": "harmonic", "kit": "metal",
     "prog": (0, 4, 5, 6, 0, 4, 3, 4),  # clockwork gothic
     "instruments": {"arp": "bell"}, },
    # ---- SNES action-score profiles, driving-bass arrangements --------------
    # Structural homages only: mode, meter, cadence shape and layer roles were
    # taken from analyses of the scores; the notes here are written, the titles
    # are original. Each of these three cues arranges its melody over a named
    # BASS_LINES pattern instead of the stock 8ths, which is what makes a
    # mid-tempo cue read as "driven" rather than "mid-tempo".
    # Knight-errant profile: aeolian fanfare, dotted lead, i-VI-VII cadences,
    # chug bass (octave pops + approach tone), heavy kit on a march groove.
    {"name": "Knight of the Marsh", "root": 57, "bpm": 220, "lead": "square",
     "scale": "natural", "motifs": "hero", "bass": "chug",
     "groove": "march", "kit": "heavy",
     "prog": (0, 5, 6, 0, 3, 5, 6, 4),
     "instruments": {"lead": "flute", "lead_b": "violin", "pad": "strings"}, },
    # Seeress profile in a level arrangement: Lydian whole-note melody over the
    # running bass - the slow line and the fast line never share a rhythm, so
    # the cue can be tender and fast at the same time.
    {"name": "Starfall Vale", "root": 60, "bpm": 238, "lead": "triangle",
     "scale": "lydian", "motifs": "lyric", "bass": "run",
     "groove": "drive16", "kit": "soft",
     "prog": (0, 3, 4, 0, 5, 3, 4, 0),
     "instruments": {"lead": "violin", "pad": "strings"}, },
)

MENU_THEMES: tuple[dict, ...] = (
    {"name": "Title Attract", "root": 57, "bpm": 100, "lead": "pulse",
     "prog": (0, 3, 4, 0, 5, 3, 4, 0), "drums": False, "layout": MENU_LAYOUT},
    {"name": "Chrome Reverie", "root": 55, "bpm": 96, "lead": "triangle",
     "prog": (0, 5, 3, 6, 0, 4, 5, 3), "drums": False, "layout": MENU_LAYOUT},
    {"name": "Night Drive Home", "root": 60, "bpm": 104, "lead": "saw",
     "prog": (0, 4, 5, 3, 6, 4, 0, 5), "drums": False, "layout": MENU_LAYOUT},
    {"name": "Afterglow", "root": 58, "bpm": 92, "lead": "pulse",
     "prog": (0, 3, 0, 4, 5, 3, 6, 0), "drums": False, "layout": MENU_LAYOUT},
    {"name": "Neon Lagoon", "root": 50, "bpm": 98, "lead": "triangle",
     "prog": (0, 5, 3, 0, 6, 5, 4, 3), "drums": False, "layout": MENU_LAYOUT},
    {"name": "Starlit Idle", "root": 65, "bpm": 90, "lead": "saw",
     "prog": (0, 4, 3, 5, 0, 6, 4, 5), "drums": False, "layout": MENU_LAYOUT},
    {"name": "Dusk Protocol", "root": 57, "bpm": 102, "lead": "pulse",
     "prog": (0, 6, 3, 4, 5, 0, 6, 3), "drums": False, "layout": MENU_LAYOUT},
    # Calm menu homages in the same NES/SNES spirit (gothic-horror ballads and
    # JRPG town/inn themes) — original progressions, drums off.
    {"name": "Moonlit Keep", "root": 55, "bpm": 90, "lead": "triangle",
     "prog": (0, 5, 3, 6, 0, 6, 5, 4), "drums": False, "layout": MENU_LAYOUT},
    {"name": "Wandering Star", "root": 60, "bpm": 94, "lead": "pulse",
     "prog": (0, 2, 4, 5, 0, 3, 2, 4), "drums": False, "layout": MENU_LAYOUT,
     "instruments": {"lead": "flute"}, },
    {"name": "Old Chapel", "root": 58, "bpm": 88, "lead": "triangle",
     "prog": (0, 3, 4, 0, 2, 5, 4, 3), "drums": False, "layout": MENU_LAYOUT,
     "instruments": {"pad": "strings", "arp": "bell"}, },
    # Calm menu homages in the same researched NES/SNES spirit (major / Lydian
    # town-and-overworld themes for the bright ones, harmonic-minor for the
    # gothic ballad) -- original progressions, drums off.
    {"name": "Hyrule Dusk", "root": 60, "bpm": 92, "lead": "triangle",
     "scale": "lydian", "prog": (0, 3, 4, 0, 1, 3, 4, 0),
     "drums": False, "layout": MENU_LAYOUT},
    {"name": "Wandering Merchant", "root": 62, "bpm": 94, "lead": "pulse",
     "scale": "major", "prog": (0, 3, 5, 4, 0, 3, 4, 0),
     "drums": False, "layout": MENU_LAYOUT},
    {"name": "Aurora's Wake", "root": 58, "bpm": 88, "lead": "triangle",
     "scale": "harmonic", "prog": (0, 5, 3, 4, 0, 5, 2, 4),
     "drums": False, "layout": MENU_LAYOUT},
    {"name": "Undying Oath", "root": 57, "bpm": 86, "lead": "pulse",
     "scale": "harmonic", "prog": (0, 3, 4, 0, 0, 5, 3, 4),
     "drums": False, "layout": MENU_LAYOUT},
    # Secret of Mana "Spirit of the Night" (Banished) homage: analyses give the
    # gentle melancholy Am-F-C-Dm loop -> A natural minor, i-VI-bVII-iv.
    {"name": "Veil of Midnight", "root": 57, "bpm": 92, "lead": "triangle",
     "prog": (0, 5, 6, 3, 0, 5, 6, 4),
     "drums": False, "layout": MENU_LAYOUT},
    {"name": "Prelude to Memory", "root": 60, "bpm": 96, "lead": "triangle",   # Final Fantasy
     "scale": "major", "prog": (0, 4, 5, 3, 0, 4, 3, 0),
     "drums": False, "layout": MENU_LAYOUT,
     "instruments": {"lead": "flute", "pad": "strings"}, },
    {"name": "Home Town Haze", "root": 62, "bpm": 90, "lead": "pulse",    # EarthBound/Mother
     "scale": "major", "prog": (0, 3, 5, 4, 0, 5, 3, 0),
     "drums": False, "layout": MENU_LAYOUT},
    {"name": "Skystone City", "root": 62, "bpm": 92, "lead": "triangle",  # ActRaiser
     "scale": "lydian", "prog": (0, 3, 0, 4, 1, 3, 4, 0),
     "drums": False, "layout": MENU_LAYOUT},
    {"name": "Gaia's Lament", "root": 57, "bpm": 92, "lead": "triangle",  # Illusion of Gaia
     "prog": (0, 5, 3, 4, 0, 6, 5, 4),
     "drums": False, "layout": MENU_LAYOUT,
     "instruments": {"lead": "violin", "pad": "strings"}, },
    # The seeress profile again, arranged as a menu cue: no drums at all, but
    # the running bass line keeps moving under the whole-note melody. Proof that
    # "driving" is a bass-line decision, not a percussion decision.
    {"name": "Vale of the Sleeping Star", "root": 62, "bpm": 104,
     "lead": "triangle", "scale": "lydian", "motifs": "lyric", "bass": "run",
     "prog": (0, 4, 5, 3, 0, 4, 3, 0),
     "drums": False, "layout": MENU_LAYOUT},
)

# Back-compat alias (used by tests and single-track callers).
MENU_THEME: dict = MENU_THEMES[0]

BOSS_THEMES: tuple[dict, ...] = (
    {"name": "Iron Cathedral", "root": 57, "bpm": 288, "lead": "saw",
     "scale": "harmonic", "prog": (0, 0, 5, 5, 3, 3, 6, 6),
     "drive": True, "layout": BOSS_LAYOUT},
    {"name": "Clockwork Gauntlet", "root": 52, "bpm": 320, "lead": "square",
     "scale": "harmonic", "prog": (0, 1, 0, 1, 4, 4, 6, 4),
     "drive": True, "layout": BOSS_LAYOUT},
    {"name": "Crimson Descent", "root": 49, "bpm": 302, "lead": "saw",
     "scale": "harmonic", "prog": (0, 0, 6, 6, 5, 5, 4, 4),
     "drive": True, "layout": BOSS_LAYOUT},
    {"name": "Terminal Velocity", "root": 55, "bpm": 330, "lead": "pulse",
     "scale": "natural", "prog": (0, 3, 0, 3, 5, 3, 6, 3),
     "drive": True, "layout": BOSS_LAYOUT},
    # Dragon's Fury / Xavius energy: harmonic-minor i-iv descent at speed. The
    # 74 BPM tag is doubled here because a boss cue is eight bars of tension,
    # not a long loop; the drive bed keeps it moving regardless.
    {"name": "Angel of Fear", "root": 62, "bpm": 292, "lead": "saw",
     "scale": "harmonic", "prog": (0, 0, 3, 0, 5, 5, 4, 4),
     "drive": True, "layout": BOSS_LAYOUT,
     "instruments": {"pad": "strings"}, },
    {"name": "Death Gaze", "root": 60, "bpm": 312, "lead": "square",
     "scale": "harmonic", "prog": (0, 6, 5, 4, 0, 6, 5, 3),
     "drive": True, "layout": BOSS_LAYOUT},
)

# Which cues each sector may play, by name. A sector owns a short pool of cues
# that suit the ground it flies over, and picks one at random per visit, so a
# sector has a sound without always being the same tune.
#
# The first name is the sector's identity cue: it is the one played when the
# rest of the pool has not rendered yet, so every sector sounds right from the
# first second of launch. Every cue in THEMES appears in at least one pool - an
# unreachable cue would be a cue that never gets played or heard.
LEVEL_CUES: dict[int, tuple[str, ...]] = {
    0: ("Overture of Field", "Daydream Vector", "Sunset Circuit",
        "Starfall Vale"),
    1: ("Knight of the Marsh", "Back Alley", "Crypt March", "Crater Wastes"),
    2: ("Neon Grid", "Midnight Run", "Neon Freeway", "Rooftop Duel"),
    3: ("Peak of Regret", "Empyrean Dread", "Hyrule Ascent",
        "Kakariko Heights", "Clockwork Tide"),
    4: ("Cathedral Run", "Gearwork Cathedral", "Candelabra Hall",
        "Magus Gate", "Night Fortress"),
    5: ("Oath of Flame", "Blood Moon Rite", "Battle Verge", "Steel Fist"),
    6: ("Laser Night", "Hyper Grid", "Chrome Run", "Retro Cascade"),
    7: ("Clockwork Tide", "Gearwork Cathedral", "Turbo Drift", "Cathedral Run"),
    # The fortress at the end of the run, so the march returns - plus the one
    # drumless cue from the valley, for the sector's empty middle.
    8: ("Final Wave", "Knight's Resolve", "Neon Freeway", "Night Fortress",
        "Vale of the Sleeping Star"),
}

__all__ = ["SCALE", "SCALES", "MOTIFS", "MOTIF_SETS", "CADENCE", "BASS",
           "BASS_LINES", "KITS", "GROOVES",
           "GROOVE_BY_TEMPO", "KIT_BY_TEMPO", "GROOVE_BOSS", "KIT_BOSS",
           "LAYOUT", "MENU_LAYOUT", "BOSS_LAYOUT",
           "THEMES", "MENU_THEMES", "MENU_THEME", "BOSS_THEMES",
           "LEVEL_CUES"]
