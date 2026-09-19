"""Statistics file: validated on load (with old-key migration), atomic on save."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .json_store import atomic_write_json, quarantine, read_json
from .paths import STATS_FILENAME, app_data_dir
from .stats import Stats

# Renamed fields keep reading their old key, so an existing install keeps its
# career numbers after the Breakout-era names went away.
LEGACY_KEYS = {"highest_sector": "highest_level",
               "most_enemies_destroyed": "most_bricks"}


def _num(raw: dict[str, Any], key: str, default: float, lo: float,
         allow_float: bool) -> float:
    v = raw.get(key, raw.get(LEGACY_KEYS.get(key, ""), default))
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    f = float(v)
    if not (f == f and abs(f) != float("inf")):  # non-finite guard
        return default
    return max(lo, f if allow_float else float(int(f)))


def validate_stats(raw: Any) -> Stats:
    """Coerce a JSON payload into a usable Stats; anything odd becomes default."""
    s = Stats()
    if not isinstance(raw, dict):
        return s
    s.high_score = int(_num(raw, "high_score", 0, 0, False))
    s.games_played = int(_num(raw, "games_played", 0, 0, False))
    s.highest_sector = int(_num(raw, "highest_sector", 0, 0, False))
    s.most_enemies_destroyed = int(_num(raw, "most_enemies_destroyed", 0, 0,
                                        False))
    s.longest_session = _num(raw, "longest_session", 0.0, 0.0, True)
    return s


def load_stats(directory: Path | None = None) -> tuple[Stats, bool]:
    """Load statistics. Returns (stats, recovered_from_corrupt)."""
    d = directory or app_data_dir()
    path = d / STATS_FILENAME
    raw, corrupt = read_json(path)
    if corrupt:
        quarantine(path)
        return Stats(), True
    return validate_stats(raw if raw is not None else {}), False


def save_stats(stats: Stats, directory: Path | None = None) -> None:
    d = directory or app_data_dir()
    atomic_write_json(d / STATS_FILENAME, {"version": 1, **asdict(stats)})
