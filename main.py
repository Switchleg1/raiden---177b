#!/usr/bin/env python3
"""Raiden Shadow — main launcher.

    python main.py                  # play
    python main.py --self-test 240  # headless smoke run (CI)

Game source lives in ``src/`` (plain modules, no install step); this script
just puts ``src`` on the import path and starts the app.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
