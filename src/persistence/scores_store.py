"""High-score table file: validated on load, atomic on save."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .json_store import atomic_write_json, quarantine, read_json
from .paths import SCORES_FILENAME, app_data_dir
from .score_entry import ScoreEntry
from .scores_table import trim_scores, validate_scores


def load_scores(directory: Path | None = None) -> list[ScoreEntry]:
    """Load the table. A corrupt file is quarantined; no file means no scores."""
    d = directory or app_data_dir()
    path = d / SCORES_FILENAME
    raw, corrupt = read_json(path)
    if corrupt:
        quarantine(path)
        return []
    return validate_scores(raw if raw is not None else [])


def save_scores(entries: Sequence[ScoreEntry],
                directory: Path | None = None) -> None:
    d = directory or app_data_dir()
    payload = {"version": 1,
               "scores": [e.to_dict() for e in trim_scores(entries)]}
    atomic_write_json(d / SCORES_FILENAME, payload)
