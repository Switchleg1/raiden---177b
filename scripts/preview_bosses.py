#!/usr/bin/env python3
"""Stitch the nine sector bosses into one habit sheet: movement and bullet art.

    python scripts/preview_bosses.py
    python scripts/preview_bosses.py --seconds 9 --moments 3 --scale 0.5

A habit is a thing you feel in the hands, so a table of numbers cannot review
it. This drives the real fight - real director, real boss strategies, real
firing primitives, real terrain - and photographs three moments of each boss in
the upper band, which is where all nine live. Read each row left to right: the
shape the bullets describe over time is the personality, and the gaps between
them are the difficulty.

The player is given a shield and moved in a sweep. The shield keeps the sector
alive long enough to photograph and puts the new bubble at a real boss scale;
the sweep matters because aimed patterns are a conversation with the pilot, and
a motionless pilot flatters every gun on screen.

The legend prints in row order.
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

DT = 1.0 / 120.0


def _row(pygame: Any, ui: Any, C: Any, index: int, seconds: float,
         moments: int) -> list[Any]:
    """Photograph one sector boss at ``moments`` evenly spaced times."""
    from PIL import Image

    from game import Game

    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rend = ui.Renderer(canvas, C.Settings())
    rend.set_terrain(C.LEVELS[index], seed=index + 1)
    game = Game(rng=random.Random(2000 + index))
    game.new_game()
    game.start_level(index)
    game.lives = 99
    game._spawn_boss([])
    habit = C.habit_for(C.LEVELS[index].boss)
    shots: list[Any] = []
    times = [seconds * (i + 1) / moments for i in range(moments)]
    elapsed = 0.0
    want = 0
    while elapsed < seconds and want < len(times):
        # A sweep the player would actually fly: slow across, dipping in close.
        move_x = math.sin(elapsed * 0.9)
        move_y = 0.35 * math.sin(elapsed * 0.45)
        game.player.shield = 9999.0     # survive, and show the bubble in place
        game.update(DT, move_x, move_y, firing=True)
        elapsed += DT
        if elapsed >= times[want]:
            rend.update_background(DT)
            rend.draw_field(game)
            view = canvas.subsurface(pygame.Rect(0, C.FIELD_TOP, C.LOGICAL_W,
                                                 300))
            shots.append(Image.frombytes("RGB", view.get_size(),
                                         pygame.image.tostring(view, "RGB"),
                                         "raw"))
            want += 1
    print(f"  boss {index + 1}: {habit.name} / {habit.move} x {habit.speed} "
          f"[{', '.join(a.kind for a in habit.attacks)}] "
          f"enrage {habit.enrage_at:.0%}")
    return shots


def _footprint(pygame: Any, C: Any, index: int, seconds: float) -> Any:
    """Every bullet one boss fires, burned into one panel.

    Volleys are discrete, so a single frame cannot show whether a habit is a
    ring, a spiral, a wall with a gap or a sweeping lance. Accumulating them
    does: this is the pattern the pilot has to read, drawn as they will feel it.
    """
    from PIL import Image

    from game import Game

    board = pygame.Surface((C.LOGICAL_W, C.FIELD_BOTTOM - C.FIELD_TOP),
                           pygame.SRCALPHA)
    board.fill((6, 8, 12, 255))
    game = Game(rng=random.Random(2000 + index))
    game.new_game()
    game.start_level(index)
    game.lives = 99
    game._spawn_boss([])
    habit = C.habit_for(C.LEVELS[index].boss)
    steps = int(seconds / DT)
    for i in range(steps):
        t = i * DT
        game.player.shield = 9999.0
        game.update(DT, math.sin(t * 0.9), 0.35 * math.sin(t * 0.45),
                    firing=True)
        for b in game.bullets:
            if b.friendly:
                continue
            px, py = int(b.x), int(b.y - C.FIELD_TOP)
            if not (0 <= px < board.get_width() and 0 <= py < board.get_height()):
                continue
            # Age the ink a little: fresh shots are hot, old ones sink.
            pygame.draw.circle(board, (255, 196, 96, 200), (px, py),
                               max(1, int(b.r)))
    # The band the boss is allowed to live in, so a dip reads as a dip.
    for y, col in ((C.BOSS_TOP, (70, 110, 180, 120)),
                   (C.BOSS_BOTTOM, (70, 110, 180, 120))):
        pygame.draw.line(board, col, (0, y - C.FIELD_TOP),
                         (board.get_width(), y - C.FIELD_TOP), 1)
    print(f"  boss {index + 1}: {habit.name} / {habit.move} "
          f"[{', '.join(a.kind for a in habit.attacks)}]")
    return Image.frombytes("RGBA", board.get_size(),
                           pygame.image.tostring(board, "RGBA"), "raw")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--footprint", action="store_true",
                    help="burn whole-run bullet patterns instead of snapshots")
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--moments", type=int, default=3)
    ap.add_argument("--scale", type=float, default=0.5)
    ap.add_argument("--sectors", type=int, nargs="*", default=None)
    ap.add_argument("--out", default=str(ROOT / "screenshots" /
                                         "_preview_bosses.png"))
    args = ap.parse_args()

    pygame.init()
    pygame.display.set_mode((8, 8))
    from PIL import Image

    import config as C
    import ui

    sectors = (args.sectors if args.sectors is not None
               else list(range(len(C.LEVELS))))
    if args.footprint:
        shots = [_footprint(pygame, C, s, args.seconds) for s in sectors]
        sized = [sh.resize((round(sh.width * args.scale),
                            round(sh.height * args.scale)),
                           Image.Resampling.LANCZOS) for sh in shots]
        cols = 3
        cw = max(sh.width for sh in sized)
        chh = max(sh.height for sh in sized)
        out = Image.new("RGB", (cw * cols, chh * math.ceil(len(sized) / cols)),
                        (0, 0, 0))
        for i, sh in enumerate(sized):
            out.paste(sh, ((i % cols) * cw, (i // cols) * chh))
        out.save(args.out)
        print(f"{len(sized)} footprints -> {args.out}")
        return
    rows: list[list[Any]] = []
    print("legend (row order):")
    for s in sectors:
        rows.append(_row(pygame, ui, C, s, args.seconds, args.moments))

    sized = [[sh.resize((round(sh.width * args.scale),
                         round(sh.height * args.scale)),
                        Image.Resampling.LANCZOS)
              for sh in row] for row in rows]
    cw = max(sh.width for row in sized for sh in row)
    chh = max(sh.height for row in sized for sh in row)
    out = Image.new("RGB", (cw * args.moments, chh * len(sized)), (0, 0, 0))
    for r, row in enumerate(sized):
        for c, sh in enumerate(row):
            out.paste(sh, (c * cw, r * chh))
    out.save(args.out)
    print(f"{len(sized)} bosses x {args.moments} moments -> {args.out}")


if __name__ == "__main__":
    main()
