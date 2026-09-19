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
}

# --- bar motifs -------------------------------------------------------------
# Each motif is a list of (start_beat, dur_beats, scale_degree_offset) relative
# to the current bar's chord root scale-degree, so melodies always stay in key.
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
}
CADENCE = ((0.0, 2.0, 0), (2.0, 1.0, 4), (3.0, 1.0, 7))
# Bass 8th-note patterns: indices into the current triad (0=root, 2=fifth).
BASS = {
    "intro": (0, 0, 0, 0, 0, 0, 0, 0),
    "A": (0, 0, 2, 0, 0, 2, 0, 2),
    "B": (0, 1, 0, 2, 0, 1, 0, 2),
    "outro": (0, 0, 0, 0, 2, 2, 0, 0),
}

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
    {"name": "Neon Grid",   "root": 57, "bpm": 106, "lead": "pulse",
     "prog": (0, 5, 2, 6, 3, 0, 5, 4)},
    {"name": "Chrome Run",  "root": 55, "bpm": 114, "lead": "square",
     "prog": (0, 6, 5, 6, 3, 5, 0, 4)},
    {"name": "Laser Night", "root": 60, "bpm": 120, "lead": "pulse",
     "prog": (0, 3, 5, 4, 6, 3, 2, 4)},
    {"name": "Turbo Drift", "root": 53, "bpm": 128, "lead": "saw",
     "prog": (0, 5, 3, 6, 0, 4, 5, 6)},
    {"name": "Final Wave",  "root": 58, "bpm": 134, "lead": "pulse",
     "prog": (0, 6, 5, 4, 3, 6, 5, 4)},
    # Extra level cues: the level playlist picks a random track per level (never
    # the same one back-to-back), so the pool is deliberately larger than the
    # number of levels. New original progressions in classic synthwave archetypes
    # (Retro Cascade i-VI-VII-VI, driving i-VII-VI-VII, daydream i-VI-III-VII,
    # minor 4-chord cycles) written in natural-minor scale degrees.
    {"name": "Retro Cascade", "root": 53, "bpm": 112, "lead": "square",
     "prog": (0, 5, 6, 5, 3, 5, 6, 4)},
    {"name": "Midnight Run", "root": 57, "bpm": 122, "lead": "saw",
     "prog": (0, 6, 5, 0, 6, 4, 5, 6)},
    {"name": "Daydream Vector", "root": 62, "bpm": 118, "lead": "pulse",
     "prog": (0, 5, 2, 4, 5, 3, 2, 6)},
    {"name": "Sunset Circuit", "root": 55, "bpm": 126, "lead": "triangle",
     "prog": (0, 3, 6, 5, 3, 0, 4, 6)},
    {"name": "Hyper Grid", "root": 60, "bpm": 138, "lead": "square",
     "prog": (0, 4, 5, 6, 3, 4, 5, 0)},
    # Original cues channelled from classic NES/SNES action-score archetypes
    # (belt-scroll brawlers, gothic-horror platformers, and JRPG adventure
    # themes). These are stylistic homages only: original natural-minor degree
    # progressions, no borrowed melodies and no trademarked titles.
    {"name": "Steel Fist", "root": 57, "bpm": 132, "lead": "saw",
     "prog": (0, 6, 5, 6, 0, 6, 5, 4)},          # driving belt-scroll riff
    {"name": "Back Alley", "root": 53, "bpm": 126, "lead": "square",
     "prog": (0, 0, 5, 6, 3, 0, 6, 4)},          # tense verse/chorus brawl
    {"name": "Cathedral Run", "root": 55, "bpm": 130, "lead": "saw",
     "prog": (0, 5, 6, 5, 0, 3, 6, 4)},          # gothic heroic gallop
    {"name": "Crypt March", "root": 57, "bpm": 116, "lead": "pulse",
     "prog": (0, 6, 5, 0, 3, 6, 5, 4)},          # brooding dungeon crawl
    {"name": "Clockwork Tide", "root": 60, "bpm": 124, "lead": "pulse",
     "prog": (0, 2, 5, 4, 0, 2, 6, 4)},          # hopeful mediant (III) lift
    {"name": "Knight's Resolve", "root": 58, "bpm": 120, "lead": "triangle",
     "prog": (0, 3, 2, 4, 5, 3, 0, 6)},          # noble quest fanfare
    # ---- researched NES/SNES archetypes (see docs) -------------------------------
    # Original degree progressions channelled from real chord *analyses* of these
    # scores (structure only, never copied melodies, never trademarked titles).
    # `scale: harmonic` raises the 7th so the v chord becomes a major V -- the
    # gothic cadence that defines Castlevania and JRPG battle music.
    {"name": "Blood Moon Rite", "root": 57, "bpm": 128, "lead": "saw",
     "scale": "harmonic", "prog": (0, 5, 6, 4, 0, 5, 6, 4)},   # i-VI-vii°-V
    {"name": "Candelabra Hall", "root": 55, "bpm": 122, "lead": "saw",
     "scale": "harmonic", "prog": (0, 3, 4, 0, 0, 3, 4, 5)},   # i-iv-V-i
    {"name": "Night Fortress", "root": 57, "bpm": 134, "lead": "pulse",
     "scale": "harmonic", "prog": (0, 6, 5, 4, 0, 3, 5, 4)},   # descending gothic
    {"name": "Battle Verge", "root": 62, "bpm": 130, "lead": "square",
     "scale": "harmonic", "prog": (0, 3, 4, 0, 5, 3, 4, 0)},   # i-iv-V (CT battle)
    {"name": "Magus Gate", "root": 64, "bpm": 126, "lead": "saw",
     "scale": "harmonic", "prog": (0, 2, 0, 4, 0, 5, 2, 4)},   # III+ aug mystery
    {"name": "Hyrule Ascent", "root": 60, "bpm": 124, "lead": "pulse",
     "scale": "lydian", "prog": (0, 4, 5, 3, 0, 4, 1, 0)},      # heroic Lydian
    {"name": "Kakariko Heights", "root": 62, "bpm": 130, "lead": "triangle",
     "scale": "lydian", "prog": (0, 1, 3, 4, 0, 1, 4, 0)},      # Lydian II lift
    {"name": "Rooftop Duel", "root": 53, "bpm": 128, "lead": "saw",
     "prog": (0, 6, 0, 5, 6, 0, 4, 0)},                          # belt-scroll i-VII
    # Secret of Mana "Fear of the Heavens" homage: analyses give Am with a major
    # V (D/E) and chromatic mediants -> A harmonic minor, i-VI-iv-V.
    {"name": "Empyrean Dread", "root": 57, "bpm": 118, "lead": "saw",
     "scale": "harmonic", "prog": (0, 5, 3, 4, 0, 5, 3, 4)},   # i-VI-iv-V (SoM)
    # ---- more classics -----------------------------------------------------------
    # Original degree progressions in the spirit of these scores (structure only;
    # no copied melodies, no trademarked names as track titles).
    {"name": "Oath of Flame", "root": 57, "bpm": 130, "lead": "saw",      # Soul Blazer
     "scale": "harmonic", "prog": (0, 3, 4, 0, 0, 5, 3, 4)},              # noble i-iv-V
    {"name": "Peak of Regret", "root": 55, "bpm": 124, "lead": "saw",     # Soul Blazer
     "prog": (0, 6, 5, 4, 0, 6, 3, 4)},                                   # epic descent
    {"name": "Overture of Field", "root": 61, "bpm": 126, "lead": "triangle",  # ALttP
     "scale": "major", "prog": (0, 3, 4, 0, 5, 3, 4, 0)},                 # bright heroic
    {"name": "Neon Freeway", "root": 62, "bpm": 140, "lead": "square",    # Mega Man X
     "prog": (0, 0, 3, 4, 0, 5, 3, 4)},                                   # driving i-VII
    {"name": "Crater Wastes", "root": 53, "bpm": 110, "lead": "saw",      # Metroid
     "prog": (0, 6, 5, 0, 3, 6, 5, 4)},                                   # eerie expanse
    {"name": "Gearwork Cathedral", "root": 57, "bpm": 134, "lead": "pulse",   # Castlevania
     "scale": "harmonic", "prog": (0, 4, 5, 6, 0, 4, 3, 4)},              # clockwork gothic
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
     "prog": (0, 2, 4, 5, 0, 3, 2, 4), "drums": False, "layout": MENU_LAYOUT},
    {"name": "Old Chapel", "root": 58, "bpm": 88, "lead": "triangle",
     "prog": (0, 3, 4, 0, 2, 5, 4, 3), "drums": False, "layout": MENU_LAYOUT},
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
     "drums": False, "layout": MENU_LAYOUT},
    {"name": "Home Town Haze", "root": 62, "bpm": 90, "lead": "pulse",    # EarthBound/Mother
     "scale": "major", "prog": (0, 3, 5, 4, 0, 5, 3, 0),
     "drums": False, "layout": MENU_LAYOUT},
    {"name": "Skystone City", "root": 62, "bpm": 92, "lead": "triangle",  # ActRaiser
     "scale": "lydian", "prog": (0, 3, 0, 4, 1, 3, 4, 0),
     "drums": False, "layout": MENU_LAYOUT},
    {"name": "Gaia's Lament", "root": 57, "bpm": 92, "lead": "triangle",  # Illusion of Gaia
     "prog": (0, 5, 3, 4, 0, 6, 5, 4),
     "drums": False, "layout": MENU_LAYOUT},
)

# Back-compat alias (used by tests and single-track callers).
MENU_THEME: dict = MENU_THEMES[0]

BOSS_THEMES: tuple[dict, ...] = (
    {"name": "Iron Cathedral", "root": 57, "bpm": 158, "lead": "saw",
     "scale": "harmonic", "prog": (0, 0, 5, 5, 3, 3, 6, 6),
     "drive": True, "layout": BOSS_LAYOUT},
    {"name": "Clockwork Gauntlet", "root": 52, "bpm": 172, "lead": "square",
     "scale": "harmonic", "prog": (0, 1, 0, 1, 4, 4, 6, 4),
     "drive": True, "layout": BOSS_LAYOUT},
    {"name": "Crimson Descent", "root": 49, "bpm": 166, "lead": "saw",
     "scale": "harmonic", "prog": (0, 0, 6, 6, 5, 5, 4, 4),
     "drive": True, "layout": BOSS_LAYOUT},
    {"name": "Terminal Velocity", "root": 55, "bpm": 176, "lead": "pulse",
     "scale": "natural", "prog": (0, 3, 0, 3, 5, 3, 6, 3),
     "drive": True, "layout": BOSS_LAYOUT},
    # Dragon's Fury / Xavius energy: harmonic-minor i-iv descent at speed. The
    # 74 BPM tag is doubled here because a boss cue is eight bars of tension,
    # not a long loop; the drive bed keeps it moving regardless.
    {"name": "Angel of Fear", "root": 62, "bpm": 156, "lead": "saw",
     "scale": "harmonic", "prog": (0, 0, 3, 0, 5, 5, 4, 4),
     "drive": True, "layout": BOSS_LAYOUT},
    {"name": "Death Gaze", "root": 60, "bpm": 168, "lead": "square",
     "scale": "harmonic", "prog": (0, 6, 5, 4, 0, 6, 5, 3),
     "drive": True, "layout": BOSS_LAYOUT},
)

__all__ = ["SCALE", "SCALES", "MOTIFS", "CADENCE", "BASS",
           "LAYOUT", "MENU_LAYOUT", "BOSS_LAYOUT",
           "THEMES", "MENU_THEMES", "MENU_THEME", "BOSS_THEMES"]
