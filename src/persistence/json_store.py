"""Atomic JSON writes with corrupt-file quarantine.

Every save goes through a temporary sibling followed by :func:`os.replace`, so
an interrupted write can never clobber the last good file. A file that fails to
parse is renamed ``<name>.corrupt-<ts>`` and kept for inspection; the caller
proceeds with defaults.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent),
                                    prefix=path.stem + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup of the temp file; never leave a half-written target.
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        finally:
            raise


def quarantine(path: Path) -> Path:
    """Rename a corrupt file to ``<name>.corrupt-<ts>`` preserving it."""
    suffix = f".corrupt-{int(time.time() * 1000) % 1_000_000}"
    target = path.with_name(path.name + suffix)
    try:
        os.replace(path, target)
    except OSError:
        target = path  # could not move; caller proceeds with defaults
    return target


def read_json(path: Path) -> tuple[dict[str, Any] | None, bool]:
    """Return (payload, corrupt). corrupt=True when the file existed but failed."""
    if not path.exists():
        return None, False
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("top-level JSON must be an object")
        return data, False
    except (json.JSONDecodeError, ValueError, OSError, UnicodeDecodeError):
        return None, True
