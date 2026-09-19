#!/usr/bin/env python3
"""Bake all sprite-sheet textures into data/textures/sprites/ (deterministic).

Run after changing anything in src/sprites.py paint code; the test
suite compares shipped PNGs against a fresh procedural bake and fails on
drift (stale-art detector).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame  # noqa: E402

import sprites  # noqa: E402


def main() -> int:
    pygame.init()
    total = 0
    for name in sprites.SPRITES:
        path = sprites.bake(name)
        size = path.stat().st_size
        total += size
        print(f"baked {path.name:24s} {size:8d} bytes")
    print(f"done: {len(sprites.SPRITES)} sheets, {total / 1024:.1f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
