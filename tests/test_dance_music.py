"""The dance layer: pump, arp figures, chord pads, resting bass, and the cues.

Every cue in the roster used to ride one rock beat with one arp figure and one
two-note pad. This module covers the arrangement choices that change that - and
each test names the *heard* consequence, not the parameter: a pump that is still
ducked when the next kick arrives, an arp that spans an octave, a bass line whose
silences fall on the beat.
"""

import array
import math

import music
from music_content import (
    BASS_LINES,
    BOSS_THEMES,
    GROOVES,
    KITS,
    LEVEL_CUES,
    MENU_THEMES,
    MOTIF_SETS,
    SCALES,
    THEMES,
)

RATE = 22050

# Layer levels as the arranger sets them (read from the engine, so they cannot
# drift), which is how a test picks one layer out of the note log.
PAD_VOL = music.PAD_VOL
PAD_CHORD_VOL = music.PAD_CHORD_VOL
BASS_LO, BASS_HI = 0.19, 0.241
ARP_VOL = 0.09
ARP_RUN16_VOL = 0.075
ARP_STAB_VOL = 0.062
# The probe bar renders at beat = 0.5 s, so a sixteenth is RATE/8 samples and an
# eighth is RATE/4. Getting this wrong turns "on the offbeat" into "on the beat".
BAR_S = 2.0
EIGHTH = int(BAR_S * RATE / 8)

DANCE_CUES = ("Freeway Pulse", "Neon Ascension", "Voltage Sky", "Static Bloom",
              "Chrome Circuit", "Midnight Signal", "Ion Drift", "Signal Rain",
              "Turbo Prism", "Chrome Prayer", "Vapor Line", "Night Reactor",
              "Open Circuit", "Static Sunrise")
DANCE_GROOVES = ("offbeat", "electro", "hypnotic")
DANCE_KITS = ("trance", "electro", "future")
# Two cues pair a dance groove with a rock kit on purpose: one brings an 808 bed
# in on a metal kit, the other plays a major tune on a crisp kit. They are the
# handrails between the beds, so "not a dance kit" must not be read as "not a
# dance cue".
BRIDGE_CUES = ("Chrome Prayer", "Static Sunrise")


class VoiceLog:
    """Stand-in for ``_Mix``: records note positions, swallows the drums."""

    rate = RATE
    drums = None

    def __init__(self) -> None:
        self.calls: list[tuple[int, float, float, str, float]] = []

    def voice(self, s0, dur, freq, wave, vol, **_kw) -> None:
        self.calls.append((s0, dur, freq, wave, vol))

    def instr(self, s0, dur, freq, name, vol) -> None:
        self.calls.append((s0, dur, freq, name, vol))

    def drum(self, *_a, **_kw) -> None:
        pass

    def layer(self, low: float, high: float) -> list[tuple[int, float]]:
        return [(s0, round(freq, 4))
                for s0, _d, freq, _w, vol in self.calls
                if low <= vol <= high]


def _bar(**kw) -> VoiceLog:
    """One A-section bar through the real arranger, beat = 0.5 s."""
    log = VoiceLog()
    music._add_bar(log, "A", 0, 57, (0, 5, 6, 0, 3, 5, 6, 4), "pulse", 0.5,
                   0.0, drums=False, **kw)
    return log


def _by_name(name: str) -> dict:
    for table in (THEMES, MENU_THEMES, BOSS_THEMES):
        for theme in table:
            if theme["name"] == name:
                return theme
    raise AssertionError(f"cue {name!r} is gone from the roster")


def _rms(samples) -> float:
    return math.sqrt(sum(s * s for s in samples) / max(1, len(samples)))


def _pcm(theme: dict) -> array.array:
    vals = array.array("h")
    vals.frombytes(music.render_track(theme, rate=RATE))
    return vals


# ------------------------------------------------------------------ arp
def test_the_arp_modes_play_different_figures():
    stock = _bar().layer(ARP_VOL - 1e-9, ARP_VOL + 1e-9)
    run = _bar(arp_mode="run16").layer(ARP_RUN16_VOL - 1e-9,
                                       ARP_RUN16_VOL + 1e-9)
    off = _bar(arp_mode="off").layer(ARP_STAB_VOL - 1e-9, ARP_STAB_VOL + 1e-9)
    assert len(stock) == 8, "stock figure moved"
    assert len(run) == 16, "run16 is not a sixteenth figure"
    assert len(off) == 12, "the stab is not three chord tones on four beats"


def test_run16_arp_spans_two_octaves_and_resets():
    """The climb and the reset are the figure: one octave would just be an arp."""
    run = _bar(arp_mode="run16").layer(ARP_RUN16_VOL - 1e-9,
                                       ARP_RUN16_VOL + 1e-9)
    pitches = [f for _s, f in run]
    assert max(pitches) / min(pitches) >= 2.0, \
        f"arp spans {max(pitches) / min(pitches):.2f}x, not an octave+"
    # the pass boundary is beat 2 of a two-second bar
    first = [f for s, f in run if s < int(RATE * BAR_S / 2)]
    second = [f for s, f in run if s >= int(RATE * BAR_S / 2)]
    assert len(first) == 8 and len(second) == 8, (len(first), len(second))
    assert min(second) > max(first), "the second pass never lifted"


def test_off_arp_stabs_on_the_offbeats_only():
    """A stab on the beat is just a chord: the offbeat placement is the voice."""
    off = _bar(arp_mode="off").layer(ARP_STAB_VOL - 1e-9, ARP_STAB_VOL + 1e-9)
    slots = sorted({round(s / EIGHTH) for s, _f in off})
    assert slots == [1, 3, 5, 7], f"stab slots {slots} (want the 'ands' only)"


def test_arp_mode_names_are_valid_everywhere():
    """An unknown mode falls back silently, which would quietly flatten a cue."""
    for theme in THEMES + MENU_THEMES + BOSS_THEMES:
        mode = theme.get("arp_mode", "stock")
        assert mode in music.ARP_MODES, f"{theme['name']} arp_mode {mode!r}"


# ------------------------------------------------------------------ pad
def test_pad_chord_adds_the_fifth():
    dyad = _bar().layer(PAD_VOL - 1e-9, PAD_VOL + 1e-9)
    triad = _bar(pad_chord=True).layer(PAD_CHORD_VOL - 1e-9,
                                       PAD_CHORD_VOL + 1e-9)
    assert len(dyad) == 2 and len(triad) == 3
    highest = max(triad, key=lambda item: item[1])[1]
    lowest = min(f for _s, f in triad)
    assert abs(highest / lowest - 2 ** (7.0 / 12.0)) < 0.02, \
        f"the third note is not a fifth: {highest / lowest:.3f}"


def test_a_chord_pad_does_not_get_louder_than_a_dyad():
    """Three notes have to fit the mix slot a two-note pad already occupies."""
    dyad = sum(v for _s, _d, _f, _w, v in _bar().calls
               if abs(v - PAD_VOL) < 1e-9)
    triad = sum(v for _s, _d, _f, _w, v in _bar(pad_chord=True).calls
                if abs(v - PAD_CHORD_VOL) < 1e-9)
    assert triad <= dyad * 1.05, f"triad total {triad:.3f} vs dyad {dyad:.3f}"


# ----------------------------------------------------------------- bass
def test_a_rest_in_a_bass_line_is_silence_not_a_note():
    line = BASS_LINES["offbeat"]["A"]
    rests = sum(1 for tone, _o in line if tone < 0)
    played = _bar(bass_line=BASS_LINES["offbeat"]).layer(BASS_LO, BASS_HI)
    assert rests == 4
    assert len(played) == 8 - rests, f"{len(played)} notes for {8 - rests} tones"


def test_the_offbeat_bass_never_plays_on_the_beat():
    """The whole point: the kick owns the downbeat, the bass answers it."""
    played = _bar(bass_line=BASS_LINES["offbeat"]).layer(BASS_LO, BASS_HI)
    slots = [round(s / EIGHTH) for s, _f in played]      # eighth-note index
    assert all(slot % 2 for slot in slots), f"bass on the downbeat: {slots}"


def test_the_electro_bass_line_owns_its_own_rhythm():
    played = _bar(bass_line=BASS_LINES["electro"]).layer(BASS_LO, BASS_HI)
    stock = _bar().layer(BASS_LO, BASS_HI)
    assert len(played) < len(stock), "the electro line plays as much as the stock"
    assert [s for s, _f in played] != [s for s, _f in stock]


# ----------------------------------------------------------------- pump
def test_the_pump_is_still_ducked_when_the_next_kick_arrives():
    """A dip that fully recovers early is a click; a pump is still down there.

    This is the difference between the effect reading as motion and reading as a
    glitch, so it is asserted on the curve rather than on a rendered mix where
    the drums swamp the measurement.
    """
    mix = music._Mix(RATE, rate=RATE)
    for i in range(RATE):
        mix.buf[i] = 0.5
    mix.pump(0.5, 0.5, 0.28)              # depth, beat spacing, release

    def rms(a: float, b: float) -> float:
        return _rms(mix.buf[int(a * RATE):int(b * RATE)])

    assert rms(0.0, 0.03) < 0.35, "no dip at the beat"
    assert rms(0.42, 0.48) > 0.32, "it recovered too early to still be pumping"
    assert rms(0.42, 0.48) < 0.5, "it was back to full before the next kick"


def test_the_pump_leaves_the_drum_bus_alone():
    """A pump that ducks the kick too is a tremolo, not a sidechain."""
    import drum_kit
    mix = music._Mix(RATE, rate=RATE,
                     drums=drum_kit.kit_samples("trance", KITS["trance"], RATE))
    mix.drum("kick", 0, 1.0)
    before = list(mix.dbuf)
    for i in range(RATE):
        mix.buf[i] = 0.5
    mix.pump(0.6, 0.5, 0.28)
    assert mix.dbuf == before, "the kick got ducked along with the pad"
    assert _rms(mix.buf[: int(0.03 * RATE)]) < 0.3, "the synth bus did not duck"


def test_the_pump_moves_a_real_cue_at_the_beat_rate():
    """Rendered evidence: the difference between pumped and not is concentrated
    in the first half of each beat, which is what a sidechain looks like."""
    th = _by_name("Neon Ascension")
    lay = (("A", 4),)
    on = [v / 32768 for v in _pcm({**th, "layout": lay})]
    off = [v / 32768 for v in _pcm({**th, "layout": lay, "pump": 0})]
    diff = [abs(a - b) for a, b in zip(on, off, strict=False)]
    beat = int(120.0 / th["bpm"] * RATE)
    half = beat // 2
    early = [_rms(diff[i:i + half]) for i in range(0, len(diff) - beat, beat)]
    late = [_rms(diff[i + half:i + beat])
            for i in range(0, len(diff) - beat, beat)]
    assert _rms(diff) > 0.004, "the pump changed nothing audible"
    assert max(early) > max(late) * 2.0, (
        f"pump not modulated at the beat: early {max(early):.4f} "
        f"late {max(late):.4f}")


def test_a_drumless_cue_never_pumps():
    """Nothing to duck under: a menu cue that breathes is a mistake, not a mood."""
    th = {**MENU_THEMES[0], "layout": (("intro", 1), ("A", 2), ("outro", 1)),
          "pump": 0.6}
    assert _pcm(th).tobytes() == _pcm({**th, "pump": 0}).tobytes()


def test_pump_depths_are_bounded():
    for theme in THEMES + BOSS_THEMES:
        depth = float(theme.get("pump", 0.0) or 0.0)
        assert 0.0 <= depth <= 0.85, f"{theme['name']} pump {depth}"


# ------------------------------------------------------- the dance cues
def test_every_dance_cue_is_wired_into_a_sector():
    reachable = {name for pool in LEVEL_CUES.values() for name in pool}
    for name in DANCE_CUES:
        assert name in reachable, f"{name} can never be heard"


def test_the_dance_cues_are_tagged_as_dance_cues():
    for name in DANCE_CUES:
        th = _by_name(name)
        assert th.get("groove") in DANCE_GROOVES, name
        assert th.get("kit") in DANCE_KITS or name in BRIDGE_CUES, \
            f"{name} is on {th.get('kit')} and is not a bridge cue"
        assert th.get("bass") in BASS_LINES, f"{name} has no named bass line"
        assert th.get("motifs") in MOTIF_SETS, f"{name} has no named melody set"
        assert float(th.get("pump", 0.0)) > 0.0, f"{name} does not pump"


def test_more_dance_cues_does_not_mean_the_same_cue_twelve_times():
    """Every extra cue has to buy something the bed did not already have. The
    signature is the arrangement, not the name: groove, kit, bass line, melody
    family and arp figure together, unique per cue."""
    sigs: dict[tuple, str] = {}
    for name in DANCE_CUES:
        th = _by_name(name)
        sig = (th.get("groove"), th.get("kit"), th.get("bass"),
               th.get("motifs"), th.get("arp_mode", "stock"),
               bool(th.get("pad_chord")))
        assert sig not in sigs, \
            f"{name} repeats {sigs[sig]}: {sig}"
        sigs[sig] = name


def test_the_dance_bed_covers_every_scale_the_engine_has():
    """'Tracks sound too similar' is partly a harmony complaint. The dance bed
    now says each mode the roster has, so the beat is a family and not a
    template: gothic is phrygian, cathedral is harmonic, dusk is dorian, euphoria
    is major. A cue with no ``scale`` key is running on the stock scale, and the
    stock scale is natural minor - so those cues count as ``natural``."""
    covered = {_by_name(n).get("scale", "natural") for n in DANCE_CUES}
    missing = set(SCALES) - covered
    assert not missing, f"no dance cue in {sorted(missing)}"


def test_dance_cues_render_audibly_and_do_not_clip():
    for name in DANCE_CUES:
        vals = _pcm(_by_name(name))
        level = _rms([v / 32768 for v in vals])
        assert 0.05 < level < 0.3, f"{name} rms {level:.3f}"
        assert max(abs(v) for v in vals) < 32767, f"{name} pinned samples"
        assert len(vals) / RATE > 20.0, f"{name} is too short to loop"


def test_a_dance_cue_is_not_just_the_same_cue_retagged():
    """The tags have to reach audio. Stripping them must produce a different
    render, or the whole layer is decoration."""
    for name in DANCE_CUES:
        th = _by_name(name)
        stripped = {k: v for k, v in th.items()
                    if k not in ("groove", "kit", "bass", "motifs", "arp_mode",
                                 "pad_chord", "pump", "instruments")}
        assert _pcm(th).tobytes() != _pcm(stripped).tobytes(), \
            f"{name} renders the same without its dance tags"


def test_the_dance_cues_are_upbeat_by_table_not_by_wish():
    """'More upbeat' has to mean something in the data, not just in the mix."""
    slowest_dance = min(_by_name(n)["bpm"] for n in DANCE_CUES)
    assert slowest_dance > min(t["bpm"] for t in THEMES)
    assert max(t["bpm"] for t in THEMES) < min(
        t["bpm"] for t in BOSS_THEMES), "the boss ordering broke"


def test_dance_cues_are_deterministic():
    for name in DANCE_CUES[:3]:
        first = _pcm(_by_name(name)).tobytes()
        assert _pcm(_by_name(name)).tobytes() == first, f"{name} moved"


def test_the_boss_pool_keeps_a_dance_option():
    dance = [t for t in BOSS_THEMES if t.get("groove") in DANCE_GROOVES]
    assert len(dance) >= 2, "no dance boss cues reached the boss pool"
    for th in dance:
        assert th["drive"] is True, f"{th['name']} is not a fight cue"
        assert th["groove"] in GROOVES


def test_groove_and_kit_tables_still_resolve_for_every_cue():
    for theme in THEMES + BOSS_THEMES:
        groove, samples = music._rhythm(theme, RATE)
        assert groove in GROOVES.values(), theme["name"]
        assert samples is not None and samples["kick"], theme["name"]
