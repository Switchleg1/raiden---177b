"""Arrangement hooks: per-cue melody sets and named bass lines.

A cue is data, so the engine needs two lookups to let one cue own a tune and a
bass line: ``motifs`` (a ``MOTIF_SETS`` pair) and ``bass`` (a ``BASS_LINES``
pattern). These tests keep the tables well-formed, keep untagged cues on the
stock material, and prove the tags actually reach the bar renderer.
"""

import array
import math

import pytest

import music
from music_content import (
    BASS,
    BASS_LINES,
    BOSS_THEMES,
    MENU_THEMES,
    MOTIF_SETS,
    MOTIFS,
    THEMES,
)

RATE = 22050
# The lead voice level inside ``_add_bar``. Bass is 0.20 (+12 % on octave
# pops), arps 0.09, pad 0.055 - so level separates the layers without having to
# re-derive what a bar is made of.
LEAD_VOL = 0.14


def _by_name(name: str) -> dict:
    for theme in THEMES + MENU_THEMES + BOSS_THEMES:
        if theme["name"] == name:
            return theme
    raise AssertionError(f"cue {name!r} is gone from the roster")


def _rms(samples) -> float:
    return math.sqrt(sum(s * s for s in samples) / max(1, len(samples)))


def _pcm(theme: dict) -> array.array:
    vals = array.array("h")
    vals.frombytes(music.render_track(theme, rate=RATE))
    return vals


class VoiceLog:
    """Stand-in for ``_Mix`` that records voices and swallows the drums."""

    rate = RATE
    drums = None

    def __init__(self) -> None:
        self.calls: list[tuple[float, float, float, str, float]] = []

    def voice(self, s0, dur, freq, wave, vol, **_kw) -> None:
        self.calls.append((s0, dur, freq, wave, vol))

    def drum(self, *_a, **_kw) -> None:
        pass

    def layer(self, low: float, high: float) -> list[tuple[float, float]]:
        return [(s0, round(freq, 4))
                for s0, _d, freq, _w, vol in self.calls
                if low <= vol <= high]


def _bar(**kw) -> VoiceLog:
    """Render one A-section bar through the real arranger with a fake mix."""
    log = VoiceLog()
    music._add_bar(log, "A", 0, 57, (0, 5, 6, 0, 3, 5, 6, 4), "pulse", 0.5,
                   0.0, drums=False, **kw)
    return log


# ------------------------------------------------------------- table shape
def test_motif_sets_point_at_real_melodies():
    for name, keys in MOTIF_SETS.items():
        assert len(keys) == 2, name
        for key in keys:
            assert len(MOTIFS[key]) == 4, f"{name}.{key} is not a 4-bar phrase"
    assert MOTIF_SETS["base"] == ("A", "B"), "the stock set moved"


def test_motif_notes_are_playable():
    for key, bars in MOTIFS.items():
        for bar_no, bar in enumerate(bars):
            assert bar, f"{key} bar {bar_no} is empty"
            for start, dur, off in bar:
                assert 0.0 <= start < 4.0, f"{key} starts outside the bar"
                assert 0.0 < dur <= 4.0, f"{key} note has no length"
                assert start + dur <= 4.0 + 1e-9, \
                    f"{key} note runs past the bar"
                assert isinstance(off, int), f"{key} degree {off!r}"


def test_the_heroic_set_opens_on_a_leap_and_the_stock_set_does_not():
    """The heroic profile is a fanfare that jumps up to (or over) the octave and
    answers downward; the stock motif starts inside the chord."""
    assert MOTIFS["hero_A"][0][0][2] >= 7, "hero phrase must open above the root"
    assert MOTIFS["A"][0][0][2] < 7, "stock motif changed character"


def test_bass_lines_are_eight_steps_of_relative_tones():
    for name, sections in BASS_LINES.items():
        for section, line in sections.items():
            assert section in BASS, f"{name} names a section the layout lacks"
            assert len(line) == 8, f"{name}.{section} is not 8 eighths"
            for tone, octv in line:
                assert tone in (0, 1, 2, 3), f"{name} tone {tone}"
                assert octv in (0, 12), f"{name} octave pop {octv}"


def test_named_lines_actually_pop_or_approach():
    """A named line that never pops or approaches is just the stock line."""
    for name, sections in BASS_LINES.items():
        for section, line in sections.items():
            if section == "outro":
                continue
            assert any(o for _t, o in line) or any(t == 3 for t, _o in line), \
                f"{name}.{section} is not a line"


def test_bass_tone_maps_the_approach_step_below_the_root():
    chord = [57, 60, 64]
    assert music._bass_tone(chord, 0) == 57
    assert music._bass_tone(chord, 2) == 64
    assert music._bass_tone(chord, 3) == 56, "approach must sit a semitone low"


# ------------------------------------------------- the renderer honours them
def test_motifs_tag_replaces_the_lead_line():
    stock = _bar().layer(LEAD_VOL - 1e-9, LEAD_VOL + 1e-9)
    hero = _bar(motif_keys=MOTIF_SETS["hero"]).layer(LEAD_VOL - 1e-9,
                                                     LEAD_VOL + 1e-9)
    assert stock and hero
    assert [f for _s, f in stock] != [f for _s, f in hero], \
        "the motifs tag changed nothing in the bar"


def test_untagged_bass_is_the_stock_pattern():
    stock = _bar().layer(0.199, 0.201)
    assert len(stock) == 8, "stock bass is not eight 8ths"
    offs = [s0 for s0, _f in stock]
    step = offs[1] - offs[0]
    # Sample offsets are integer truncations of beat times, so the grid is
    # even only to within a sample (22050/4 = 5512.5).
    assert step > 0 and all(abs(b - a - step) <= 1
                           for a, b in zip(offs, offs[1:], strict=False)), \
        "stock bass does not march in even 8ths"


def test_chug_bass_pops_an_octave_and_approaches_the_next_chord():
    root = music._freq(57 - 12)
    chug = [f for _s, f in _bar(bass_line=BASS_LINES["chug"]).layer(0.19, 0.24)]
    assert len(chug) == 8
    assert any(abs(f - 2.0 * root) < 1e-4 for f in chug), "no octave pop"
    assert any(abs(f - root * 2 ** (-1.0 / 12.0)) < 1e-4
               for f in chug), "no chromatic approach tone"
    stock = [f for _s, f in _bar().layer(0.19, 0.24)]
    assert not any(abs(f - 2.0 * root) < 1e-4 for f in stock), \
        "the stock line suddenly pops"


def test_octave_pops_are_louder_than_the_root_notes_they_sit_next_to():
    log = _bar(bass_line=BASS_LINES["chug"])
    bass = [(vol, freq) for _s, _d, freq, _w, vol in log.calls
            if vol >= 0.19]
    root = music._freq(57 - 12)
    loud = [v for v, f in bass if abs(f - 2.0 * root) < 1e-4]
    soft = [v for v, f in bass if abs(f - root) < 1e-4]
    assert loud and soft
    assert min(loud) > max(soft), "octave pops do not read as accents"


# ------------------------------------------------------------ cue wiring
def test_cue_tags_name_real_tables():
    for theme in THEMES + MENU_THEMES + BOSS_THEMES:
        if "motifs" in theme:
            assert theme["motifs"] in MOTIF_SETS, theme["name"]
        if "bass" in theme:
            assert theme["bass"] in BASS_LINES, theme["name"]


def test_the_profile_cues_ship_and_are_wired():
    """Two reference profiles, both arranged over a named bass line: a heroic
    aeolian fanfare for a level, a floating Lydian ballad for a menu (and a
    faster arrangement of the same melody family for a level)."""
    hero = _by_name("Knight of the Marsh")
    level = _by_name("Starfall Vale")
    menu = _by_name("Vale of the Sleeping Star")
    assert hero["motifs"] == "hero" and hero["bass"] == "chug"
    assert level["motifs"] == "lyric" and level["bass"] == "run"
    assert menu["motifs"] == "lyric" and menu["bass"] == "run"
    assert menu["drums"] is False, "the menu arrangement carries no drums"
    assert menu["layout"] is not None


def test_untagged_cues_still_make_up_the_bulk_of_the_roster():
    """The hooks are opt-in: converting the whole pool would be a rewrite, not
    an arrangement choice."""
    stock = [t for t in THEMES if "motifs" not in t and "bass" not in t]
    assert len(stock) >= len(THEMES) // 2
    assert len(stock) >= 25


@pytest.mark.parametrize("tag", sorted({*MOTIF_SETS, *BASS_LINES}))
def test_hooks_are_renderable_in_a_real_cue(tag):
    theme = dict(THEMES[0])
    theme["layout"] = (("intro", 1), ("A", 2), ("outro", 1))   # short loop
    if tag in MOTIF_SETS:
        theme["motifs"] = tag
    else:
        theme["bass"] = tag
    vals = _pcm(theme)
    assert len(vals) > RATE * 4
    assert 0.05 < _rms([v / 32768.0 for v in vals]) < 0.3
    assert max(abs(v) for v in vals) < 32767


def test_a_tagged_cue_differs_from_the_same_cue_untagged():
    hero = _by_name("Knight of the Marsh")
    stripped = {k: v for k, v in hero.items() if k not in ("motifs", "bass")}
    assert _pcm(hero).tobytes() != _pcm(stripped).tobytes()
