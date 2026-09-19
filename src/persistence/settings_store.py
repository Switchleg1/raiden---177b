"""Settings file: validated on load, atomic on save."""
from __future__ import annotations

from pathlib import Path

import config as C

from .json_store import atomic_write_json, quarantine, read_json
from .paths import SETTINGS_FILENAME, app_data_dir


def load_settings(directory: Path | None = None) -> tuple[C.Settings, bool]:
    """Load validated settings. Returns (settings, recovered_from_corrupt)."""
    d = directory or app_data_dir()
    path = d / SETTINGS_FILENAME
    raw, corrupt = read_json(path)
    if corrupt:
        quarantine(path)
        return C.validate_settings(None), True
    return C.validate_settings(raw if raw is not None else {}), False


def save_settings(settings: C.Settings, directory: Path | None = None) -> None:
    d = directory or app_data_dir()
    payload = {"version": 1, **C.settings_to_dict(settings)}
    atomic_write_json(d / SETTINGS_FILENAME, payload)
