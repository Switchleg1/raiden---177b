"""Bake every gameplay terrain map to data/textures/terrain/*.png.

Run once after changing terrain art:

    python scripts/bake_terrain.py

The game loads these PNGs (milliseconds). Re-bake whenever painters,
palettes, LEVELS themes, or the SS scale change. Deterministic: same code
version -> byte-identical files (seeded RNG).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

import config as C  # noqa: E402
import terrain as T  # noqa: E402


def level_art() -> list[tuple[int, C.StageTheme]]:
    """Every (seed, theme) pair the shipped LEVELS schedule loads."""
    out: list[tuple[int, C.StageTheme]] = []
    seen = set()
    for i, level in enumerate(C.LEVELS):
        seed = i + 1
        themes = [p.theme for p in level.phases] or [level.theme]
        for theme in themes:
            if (seed, theme) not in seen:
                seen.add((seed, theme))
                out.append((seed, theme))
    return out


def main() -> int:
    pygame.init()
    pygame.display.set_mode((8, 8))   # convert() format for tile loading
    pairs = level_art()
    out = T.baked_paths(C.LEVELS[0].theme, 1)[0].parent
    print(f"baking {len(pairs)} sector maps into {out}")
    total = 0.0
    for seed, theme in pairs:
        t0 = time.perf_counter()
        paths = T.bake(theme, seed)
        dt = time.perf_counter() - t0
        total += dt
        size_kb = sum(p.stat().st_size for p in paths) // 1024
        print(f"  {seed}_{C.StageTheme(theme).name.lower()}_*.png"
              f" ({size_kb} KB) [{dt * 1000:.0f} ms]")
    print(f"done in {total:.2f} s")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
