#!/usr/bin/env python3
"""Composite the whole roster over real scrolling terrain, through the renderer.

    python scripts/preview_entities.py                 # all 9 sectors
    python scripts/preview_entities.py --levels 0 4     # a few sectors
    python scripts/preview_entities.py --scale 1.0      # native 800x600

Each panel is one sector: its own terrain (real tile kit + phase blend,
scrolled a while so props and splats are in place), its own boss (spawned
through Game._spawn_boss so the per-level sheet routing is exercised), and the
regular enemy roster laid out across the field.  Sprites that look fine on a
contact sheet can still vanish against bright terrain — this is the check that
catches it.  Output goes to screenshots/.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402
from PIL import Image  # noqa: E402

ROSTER = ["grunt", "weaver", "darter", "gunner", "sentry", "heavy",
          "bomber", "splitter", "rammer", "shard"]
PER_ROW = 5  # the wide kinds need room, so the roster runs over two lines


def _shot(pygame, ui, C, level_index: int, scroll: float) -> Image.Image:
    settings = C.Settings()
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rend = ui.Renderer(canvas, settings)
    spec = C.LEVELS[level_index]
    rend.set_terrain(spec, seed=level_index + 1)

    from entities import Enemy
    from game import Game
    game = Game()
    game.new_game()
    game.start_level(level_index)
    game._spawn_boss([])
    boss = next(e for e in game.enemies if e.kind is C.EnemyKind.BOSS)
    boss.y = C.BOSS_ENTRY_Y
    lo, hi = C.FIELD_LEFT + 60, C.FIELD_RIGHT - 60
    for i, kind in enumerate(ROSTER):
        e = C.EnemyKind(kind)
        row, col = divmod(i, PER_ROW)
        n_in_row = min(PER_ROW, len(ROSTER) - row * PER_ROW)
        frac = col / max(n_in_row - 1, 1)
        enemy = Enemy(e, lo + frac * (hi - lo),
                      C.FIELD_TOP + C.FIELD_H * (0.42 + 0.16 * row))
        game.enemies.append(enemy)
    for _ in range(int(scroll * 120)):
        rend.update_background(C.SIM_DT)
    rend.draw_field(game)
    return Image.frombytes("RGB", (C.LOGICAL_W, C.LOGICAL_H),
                           pygame.image.tostring(canvas, "RGB"), "raw")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--levels", type=int, nargs="*", default=None)
    ap.add_argument("--scale", type=float, default=0.5)
    ap.add_argument("--scroll", type=float, default=2.0, help="seconds of terrain scroll")
    ap.add_argument("--out", default=str(ROOT / "screenshots" / "_preview_entities.png"))
    args = ap.parse_args()

    pygame.init()
    pygame.display.set_mode((8, 8))
    import config as C
    import ui

    levels = args.levels if args.levels is not None else list(range(len(C.LEVELS)))
    shots = [_shot(pygame, ui, C, li, args.scroll) for li in levels]
    w = round(C.LOGICAL_W * args.scale)
    h = round(C.LOGICAL_H * args.scale)
    cols = 3
    rows = (len(shots) + cols - 1) // cols
    out = Image.new("RGB", (cols * w + 8, rows * h + 8), (12, 12, 18))
    for i, s in enumerate(shots):
        if args.scale != 1.0:
            s = s.resize((w, h), Image.Resampling.LANCZOS)
        out.paste(s, ((i % cols) * (w + 4) + 4, (i // cols) * (h + 4) + 4))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.save(args.out)
    print(f"{len(shots)} sectors -> {args.out}")


if __name__ == "__main__":
    main()
