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

def _run(argv: list[str]) -> int:
    from app import main  # imports pygame, so it can fail with a missing dep

    return main(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(_run(sys.argv[1:]))
    except ModuleNotFoundError as exc:  # friendly hint instead of a traceback
        if exc.name in ("pygame", "pygame_ce"):
            sys.stderr.write(
                "pygame-ce is not installed for this interpreter\n"
                f"  interpreter: {sys.executable}\n"
                "  fix: run install.bat, then launch with run.bat "
                "(or .venv\\Scripts\\python.exe main.py)\n"
            )
            raise SystemExit(1) from None  # the message above is the diagnosis
        raise
