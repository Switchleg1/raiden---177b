"""Where this app keeps its files, and what they are called."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import config as C

SETTINGS_FILENAME = "settings.json"
STATS_FILENAME = "statistics.json"
SCORES_FILENAME = "scores.json"


def app_data_dir() -> Path:
    """Per-user application-data directory for this app (created on demand)."""
    if hasattr(C, "TEST_DATA_DIR") and C.TEST_DATA_DIR:  # test seam
        base = Path(C.TEST_DATA_DIR)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA")
                    or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME")
                    or (Path.home() / ".local" / "share"))
    path = base / C.APP_AUTHOR / C.APP_SLUG
    path.mkdir(parents=True, exist_ok=True)
    return path
