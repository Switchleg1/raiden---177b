"""Atomic, validated JSON persistence for settings, statistics and scores.

Files live in the platform-appropriate per-user application-data directory
(:func:`app_data_dir`). Each kind of data has its own module; this package
re-exports the public surface so callers keep saying ``persistence.load_scores``.

One module holds a model class, the matching ``*_store`` module holds its file
I/O: ``stats.py`` / ``stats_store.py``, ``score_entry.py`` + ``scores_table.py``
/ ``scores_store.py``, and ``settings_store.py`` for the settings object that
lives in :mod:`config`.
"""
from __future__ import annotations

from .json_store import atomic_write_json, quarantine, read_json
from .paths import SCORES_FILENAME, SETTINGS_FILENAME, STATS_FILENAME, app_data_dir
from .score_entry import ScoreEntry
from .scores_store import load_scores, save_scores
from .scores_table import add_score, rank_of, trim_scores, validate_scores
from .settings_store import load_settings, save_settings
from .stats import Stats
from .stats_store import load_stats, save_stats, validate_stats

__all__ = [
    "SCORES_FILENAME",
    "SETTINGS_FILENAME",
    "STATS_FILENAME",
    "ScoreEntry",
    "Stats",
    "add_score",
    "app_data_dir",
    "atomic_write_json",
    "load_scores",
    "load_settings",
    "load_stats",
    "quarantine",
    "rank_of",
    "read_json",
    "save_scores",
    "save_settings",
    "save_stats",
    "trim_scores",
    "validate_scores",
    "validate_stats",
]
