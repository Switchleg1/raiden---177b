"""Arrangement hooks: per-cue melody sets and named bass lines.

A cue is data, so the engine needs two lookups to let one cue own a tune and a
bass line: ``motifs`` (a ``MOTIF_SETS`` pair) and ``bass`` (a ``BASS_LINES``
pattern). These tests keep the tables well-formed, keep untagged cues on the
stock material, and prove the tags actually reach the bar renderer.
"""

import array
import math

import pytest

import config as C
import instruments
import music
from music_content import (
    BASS,
    BASS_LINES,
    BOSS_THEMES,
    LEVEL_CUES,
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
        self.instrs: list[tuple[float, float, float, str, float]] = []

    def voice(self, s0, dur, freq, wave, vol, **_kw) -> None:
        self.calls.append((s0, dur, freq, wave, vol))

    def instr(self, s0, dur, freq, name, vol) -> None:
        self.instrs.append((s0, dur, freq, name, vol))

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


# ------------------------------------------------------ per-sector cue pools
# A sector owns a pool of cues and draws one at random, so it keeps an identity
# without every lap through it being the same tune. The table is names; these
# keep the names honest and the drawing honest.

def test_sector_pools_name_cues_that_exist():
    known = {t["name"] for table in music.theme_tables() for t in table}
    for level, pool in LEVEL_CUES.items():
        assert pool, f"sector {level} has an empty pool"
        for name in pool:
            assert name in known, f"sector {level} lists unknown cue {name!r}"


def test_no_cue_is_unreachable():
    """A cue no sector lists is a cue that never gets played."""
    reachable = {name for pool in LEVEL_CUES.values() for name in pool}
    missing = {t["name"] for t in THEMES} - reachable
    assert not missing, f"cues in no sector pool: {sorted(missing)}"


def test_every_sector_has_pools_covering_the_whole_campaign():
    assert set(LEVEL_CUES) == set(range(len(C.LEVELS)))


def test_pools_are_big_enough_to_vary_and_small_enough_to_mean_something():
    for level, pool in LEVEL_CUES.items():
        assert 3 <= len(pool) <= 5, f"sector {level} pool is {len(pool)} cues"
        assert len(set(pool)) == len(pool), f"sector {level} lists a cue twice"


def test_no_two_sectors_share_the_same_identity_cue():
    """The first name is what a sector plays before its pool finishes
        rendering, so two sectors opening on the same cue is two sectors with no
        identity."""
    identities = [LEVEL_CUES[i][0] for i in sorted(LEVEL_CUES)]
    assert len(set(identities)) == len(identities)


def test_landmark_cues_stay_where_the_ground_says_they_belong():
    """The pools are curated to the terrain, not shuffled."""
    assert "Overture of Field" in music.level_cues(0)      # the approach
    assert "Knight of the Marsh" in music.level_cues(1)    # the bayou
    assert "Final Wave" in music.level_cues(len(C.LEVELS) - 1)   # the last one


def test_an_unlisted_sector_falls_back_to_the_whole_table():
    assert set(music.level_cues(999)) == {t["name"] for t in THEMES}


def test_theme_by_name_resolves_and_misses_quietly():
    assert music.theme_by_name("Neon Grid")["root"] == 57
    assert music.theme_by_name("no such cue") is None


def test_pick_never_leaves_the_sector():
    import random

    ready = music.cue_names()
    rng = random.Random(7)
    for level in sorted(LEVEL_CUES):
        pool = set(LEVEL_CUES[level])
        for _ in range(40):
            assert music.pick_level_cue(level, ready, None, rng) in pool


def test_pick_does_not_repeat_the_cue_that_just_played():
    import random

    rng = random.Random(11)
    ready = music.cue_names()
    for level, pool in LEVEL_CUES.items():
        for just_played in pool:
            picked = music.pick_level_cue(level, ready, just_played, rng)
            assert picked != just_played or len(pool) == 1


def test_pick_uses_only_what_has_rendered():
    import random

    rng = random.Random(3)
    for _ in range(30):
        got = music.pick_level_cue(0, ["Sunset Circuit"], None, rng)
        assert got == "Sunset Circuit"


def test_pick_falls_back_to_the_identity_cue_when_that_is_all_there_is():
    import random

    cue = music.pick_level_cue(1, ["Knight of the Marsh"], "Knight of the Marsh",
                              random.Random(5))
    assert cue == "Knight of the Marsh", "repetition avoided by going silent"


def test_pick_returns_none_when_nothing_for_the_sector_is_ready():
    assert music.pick_level_cue(2, ["Overture of Field"], None) is None


def test_every_pool_cue_resolves_whatever_table_wrote_it():
    """A pool name that no table defines is a cue that never plays. The pools
    reach across THEMES, MENU_THEMES and BOSS_THEMES on purpose, so the check
    is against the lookup the planner actually uses."""
    for level, pool in LEVEL_CUES.items():
        for name in pool:
            assert music.theme_by_name(name) is not None, (
                f"sector {level} lists {name!r}, which nothing defines")


def test_a_pool_really_does_reach_across_tables():
    """The valley flies under a drumless cue written for the menu table; if the
    pools ever stop reaching, this fails instead of silently dropping it."""
    level_names = {t["name"] for t in THEMES}
    cross = {n for pool in LEVEL_CUES.values() for n in pool if n not in level_names}
    assert cross, "no pool reaches beyond THEMES any more"


def test_a_shared_cue_belongs_to_every_sector_that_lists_it():
    for level, pool in LEVEL_CUES.items():
        for name in pool:
            assert level in music.levels_for_cue(name)
    assert set(music.levels_for_cue("no such cue")) == set()


# ------------------------------------------------------------------- voicing
# A cue may hand a slot to one of the synthesised instruments. The table is
# names in fixed slots; the engine decides what a name means.

VOICE_SLOTS = ("lead", "lead_b", "pad", "arp", "bass")


def test_voicings_name_real_instruments_in_real_slots():
    for theme in THEMES + MENU_THEMES + BOSS_THEMES:
        for slot, name in (theme.get("instruments") or {}).items():
            assert slot in VOICE_SLOTS, f"{theme['name']} voices {slot}"
            assert instruments.is_instrument(name), f"{theme['name']}.{slot}={name}"


def test_most_cues_are_still_plain_synths():
    """The instruments are seasoning. If everything is orchestrated the retro
    sectors stop sounding retro, so the raw palette has to stay populated."""
    raw = [t["name"] for t in THEMES if not t.get("instruments")]
    assert len(raw) >= 10, "the whole roster got orchestrated"


def test_a_voiced_slot_renders_through_the_instrument_path():
    log = _bar(voices={"lead": "flute"})
    assert log.instrs
    assert all(entry[3] == "flute" for entry in log.instrs)
    assert "flute" not in {c[3] for c in log.calls}


def test_a_wave_in_a_voice_slot_stays_a_wave():
    log = _bar(voices={"lead": "saw"})
    assert not log.instrs
    assert "saw" in {c[3] for c in log.calls}


def test_an_unvoiced_cue_never_touches_the_instrument_path():
    assert _bar().instrs == []


def test_each_slot_voices_its_own_layer():
    plain = _bar()
    for slot, expected in (("pad", 2), ("bass", 8), ("arp", 8)):
        log = _bar(voices={slot: "strings"})
        assert len(log.instrs) == expected, f"{slot} voiced {len(log.instrs)} notes"
        assert len(log.calls) < len(plain.calls), f"{slot} did not replace anything"


def _render(theme: dict, layout) -> bytes:
    cue = dict(theme)
    cue["layout"] = layout
    return music.render_track(cue, rate=RATE)


def test_lead_b_colours_the_answer_and_not_the_question():
    cue = _by_name("Neon Grid")
    a_plain = _render(cue, [("A", 1)])
    a_voiced = _render({**cue, "instruments": {"lead_b": "violin"}}, [("A", 1)])
    b_plain = _render(cue, [("B", 1)])
    b_voiced = _render({**cue, "instruments": {"lead_b": "violin"}}, [("B", 1)])
    assert a_plain == a_voiced, "lead_b leaked into the A section"
    assert b_plain != b_voiced, "lead_b never reached the B section"


def test_a_voiced_cue_sounds_different_from_itself_unvoiced():
    cue = _by_name("Cathedral Run")
    whole = [("A", 2)]
    assert _render(cue, whole) != _render(
        {k: v for k, v in cue.items() if k != "instruments"}, whole)
