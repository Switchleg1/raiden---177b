"""Render shipped cues to WAV so they can be heard without starting the game.

The soundtrack ships no audio files - every cue is synthesised at runtime - which
is a good system until someone wants to know what a cue actually sounds like.
This renders cues from the real tables (the ones the game plays) into
``assets/music/cues/`` so a cue can be judged by ear, then re-rendered
byte-for-byte later.

    python scripts/render_cue.py                    # list every cue
    python scripts/render_cue.py "Freeway Pulse"    # one cue
    python scripts/render_cue.py --dance            # the trance / electro set

Rate note: the game's mixer opens at 22050 Hz and cues are *generated* at that
rate, so this renders at 22050 too. Rendering at 44100 (which the study scripts
do, for listening comfort) produces a brighter result than the one that actually
plays - see assets/music/README.md.
"""
from __future__ import annotations

import argparse
import array
import math
import os
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from audio import MIXER_RATE as RATE  # noqa: E402
from music import engine as music  # noqa: E402

OUT_DIR = ROOT / "assets" / "music" / "cues"

# The trance / electro set, by name: every cue written in the dance bed, so the
# fastest way to hear the bed is one flag rather than fifteen quoted names.
DANCE = ("Freeway Pulse", "Neon Ascension", "Voltage Sky", "Static Bloom",
         "Chrome Circuit", "Midnight Signal", "Ion Drift", "Signal Rain",
         "Turbo Prism", "Chrome Prayer", "Vapor Line", "Night Reactor",
         "Open Circuit", "Static Sunrise", "Overdrive Halo", "Terminal Bloom",
         "Hard Light")


def _rms(values: array.array) -> float:
    return math.sqrt(sum(v * v for v in values) / max(1, len(values))) / 32768.0


def write_wav(name: str, pcm: bytes) -> dict:
    vals = array.array("h")
    vals.frombytes(pcm)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name.replace(' ', '_')}.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm)
    return {"path": path, "seconds": len(vals) / RATE, "rms": _rms(vals),
            "peak": max(abs(v) for v in vals) / 32768.0}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="*", help="cue names, quoted as needed")
    ap.add_argument("--dance", action="store_true",
                    help="render the trance / electro cues")
    args = ap.parse_args(argv)

    if not args.names and not args.dance:
        for table, label in ((music.THEMES, "stage"), (music.MENU_THEMES,
                             "menu"), (music.BOSS_THEMES, "boss")):
            for row in table:
                flags = []
                if float(row.get("pump", 0.0) or 0.0) > 0.0:
                    flags.append(f"pump {row['pump']}")
                if row.get("groove"):
                    flags.append(row["groove"])
                if row.get("arp_mode"):
                    flags.append(f"arp:{row['arp_mode']}")
                print(f"{label:5s} {row['name']:26s} bpm {row['bpm']:4d} "
                      f"{' '.join(flags)}")
        return 0

    wanted = list(args.names) or (list(DANCE) if args.dance else [])
    missing: list[str] = []
    for name in wanted:
        theme = music.theme_by_name(name)
        if theme is None:
            missing.append(name)
            continue
        info = write_wav(name, music.render_track(theme, RATE))
        print(f"{name:26s} {info['seconds']:5.1f}s  rms {info['rms']:.3f}  "
              f"peak {info['peak']:.3f}  -> {info['path'].relative_to(ROOT)}")
    if missing:
        print(f"no such cue(s): {', '.join(missing)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
