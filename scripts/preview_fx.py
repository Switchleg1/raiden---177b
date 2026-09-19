#!/usr/bin/env python3
"""Composite the FX sheets over real terrain, at game scale.

    python scripts/preview_fx.py
    python scripts/preview_fx.py --levels 0 3 7 --scale 1.0

Every FX sheet (both player shots, the missile, the enemy orb, the whip bead
and the three explosion tiers) is laid out frame by frame on top of a scrolled
sector.  A contact sheet on near-black flatters tiny sprites: a 12x16 bolt can
look crisp there and still vanish on glacier snow or volcanic ash, and a bloom
halo that touches its cell edge only shows up as a square once something is
behind it.  This is that check.  Output goes in screenshots/.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402
from PIL import Image  # noqa: E402

# Small things, medium bursts, big bursts: one panel each so nothing has to be
# shrunk below the size the player actually sees.
GROUPS = (
    ("shots", ("shot_vulcan", "shot_plasma", "shot_missile", "shot_enemy",
               "fx_whip")),
    ("mid", ("explosion_small", "explosion_mid")),
    ("big", ("explosion_big",)),
)


def _panel(pygame, ui, sprites, C, bank: Any, level_index: int,
           scroll: float, group: tuple[str, ...]) -> Image.Image:
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rend = ui.Renderer(canvas, C.Settings())
    rend.set_terrain(C.LEVELS[level_index], seed=level_index + 1)
    from game import Game
    game = Game()
    game.new_game()
    game.start_level(level_index)
    for _ in range(int(scroll * 120)):
        rend.update_background(C.SIM_DT)
    rend.draw_field(game)            # paints the scrolled terrain backdrop

    y = C.FIELD_TOP + 6
    for sheet_name in group:
        cw, ch = sprites.SPRITES[sheet_name]["cell"]
        anim = "boom" if sheet_name.startswith("explosion") else "run"
        frames = list(sprites.anim_spec(sheet_name, anim)[0])
        per_line = max(1, int((C.FIELD_RIGHT - C.FIELD_LEFT - 8) / (cw + 4)))
        lines = min(3, max(1, math.ceil(len(frames) / per_line)))
        shown = frames[:per_line * lines]
        if len(shown) < len(frames):      # keep the tail: that is where a
            step = len(frames) / len(shown)   # halo box or dead frame shows up
            shown = [frames[int(k * step)] for k in range(len(shown))]
        for slot, tile in enumerate(shown):
            row, col = divmod(slot, per_line)
            surf = bank.frame(bank.sheet(sheet_name), sheet_name, tile)
            canvas.blit(surf, (C.FIELD_LEFT + 4 + col * (cw + 4),
                               y + row * (ch + 4)))
        y += lines * (ch + 4) + 6
    used = min(y + 8 - C.FIELD_TOP, C.FIELD_BOTTOM - C.FIELD_TOP)
    view = canvas.subsurface(pygame.Rect(0, C.FIELD_TOP, C.LOGICAL_W, used))
    return Image.frombytes("RGB", view.get_size(),
                           pygame.image.tostring(view, "RGB"), "raw")


def _items_panel(pygame, ui, sprites, C, bank: Any, level_index: int,
                 scroll: float, shots: int = 4) -> Image.Image:
    """All nine pods with the shared orbiting marker, over a scrolled sector.

    Driven through the renderer's own item path, but ``update_background`` is
    stepped by an exact amount so each band is one deterministic slice of the
    orbit instead of whatever the wall clock read. A marker that looks obvious
    on black can be invisible over glacier snow, and an aura drawn *behind* a
    pod only proves it frames the icon when there is terrain showing through.
    """
    from game import Game
    from items import Item

    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rend = ui.Renderer(canvas, C.Settings())
    rend.set_terrain(C.LEVELS[level_index], seed=level_index + 1)
    game = Game()
    game.new_game()
    game.start_level(level_index)
    for _ in range(int(scroll * 120)):
        rend.update_background(C.SIM_DT)
    kinds = [str(k.value) for k in C.ItemKind]
    _, aura_fps, _ = sprites.anim_spec("fx_item_aura", "orbit")
    n_aura = len(sprites.SPRITES["fx_item_aura"]["anims"]["orbit"]["frames"])
    top, band_h = C.FIELD_TOP, 214
    out = Image.new("RGB", (C.LOGICAL_W, band_h * shots), (0, 0, 0))
    for s in range(shots):
        want = s * (n_aura / shots) / aura_fps   # one slice of the orbit loop
        if want > rend._scroll:
            rend.update_background(want - rend._scroll)
        rend.draw_field(game)
        for idx, kind in enumerate(kinds):
            row, col = divmod(idx, 3)
            it = Item(C.ItemKind(kind), 0.0, 0.0)
            it.x, it.y = 150.0 + col * 220.0, top + 42.0 + row * 64.0
            rend._draw_item(it)
        view = canvas.subsurface(pygame.Rect(0, top, C.LOGICAL_W, band_h))
        out.paste(Image.frombytes("RGB", view.get_size(),
                                  pygame.image.tostring(view, "RGB"), "raw"),
                  (0, s * band_h))
    return out


def _shield_panel(pygame, ui, sprites, C, bank: Any, level_index: int,
                  scroll: float) -> Image.Image:
    """The shield bubble at game scale: deploy pop, mid-spin, and a threat.

    Every stage is drawn through the renderer's own player path with the real
    ship sprite underneath, because the one thing worth checking here is the
    relationship between the two: the bubble has to sit outside the hull. A
    contact sheet of the bubble alone would prove nothing about that, and a
    shield that swallows the craft looks fine in a preview and terrible in play.
    """
    from entities.bullet import Bullet
    from game import Game

    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rend = ui.Renderer(canvas, C.Settings())
    rend.set_terrain(C.LEVELS[level_index], seed=level_index + 1)
    game = Game()
    game.new_game()
    game.start_level(level_index)
    for _ in range(int(scroll * 120)):
        rend.update_background(C.SIM_DT)
    pl = game.player
    pl.x, pl.y = 400.0, 430.0
    _, spin_fps, _ = sprites.anim_spec("fx_shield", "spin")
    span = 1.0 / spin_fps
    # (label, shield value, bullet offset or None)
    stages = [
        ("deploy", C.SHIELD_TIME - 0.04, None),
        ("deploy", C.SHIELD_TIME - 0.20, None),
        ("deploy", C.SHIELD_TIME - 0.40, None),
        ("spin", C.SHIELD_TIME - 2.0, None),
        ("spin", C.SHIELD_TIME - 2.0 - span, None),
        ("threat", C.SHIELD_TIME - 2.0, (-52.0, -34.0)),
    ]
    box = 200
    out = Image.new("RGB", (box * len(stages), box), (0, 0, 0))
    for i, (_label, left, bullet) in enumerate(stages):
        game.bullets.clear()
        pl.shield = left
        if bullet is not None:
            game.bullets.append(Bullet(pl.x + bullet[0], pl.y + bullet[1],
                                       0.0, 90.0, C.ENEMY_BULLET_R, 1,
                                       friendly=False))
        rend.draw_field(game)
        rend._draw_player(pl, game.bullets)
        view = canvas.subsurface(pygame.Rect(int(pl.x) - box // 2,
                                             int(pl.y) - box // 2, box, box))
        out.paste(Image.frombytes("RGB", view.get_size(),
                                  pygame.image.tostring(view, "RGB"), "raw"),
                  (i * box, 0))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--levels", type=int, nargs="*", default=None)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--scroll", type=float, default=2.0)
    ap.add_argument("--out", default=str(ROOT / "screenshots" /
                                         "_preview_fx.png"))
    ap.add_argument("--only", default=None,
                    help="limit to one panel group: "
                         "shots | mid | big | items | shield")
    args = ap.parse_args()

    pygame.init()
    pygame.display.set_mode((8, 8))
    import config as C
    import sprites
    import ui

    bank = sprites.Bank()
    if args.only == "shield":
        li = (args.levels if args.levels else [0])[0]
        img = _shield_panel(pygame, ui, sprites, C, bank, li, args.scroll)
        img = img.resize((round(img.width * args.scale),
                          round(img.height * args.scale)),
                         Image.Resampling.LANCZOS)
        img.save(args.out)
        print(f"shield over level {li} -> {args.out}")
        return
    if args.only == "items":
        li = (args.levels if args.levels else [0])[0]
        img = _items_panel(pygame, ui, sprites, C, bank, li, args.scroll)
        img = img.resize((round(img.width * args.scale),
                          round(img.height * args.scale)),
                         Image.Resampling.LANCZOS)
        img.save(args.out)
        print(f"items over level {li} -> {args.out}")
        return
    groups = GROUPS if args.only is None else tuple(
        g for g in GROUPS if g[0] == args.only)
    if not groups:
        raise SystemExit(f"no such group: {args.only}")
    levels = args.levels if args.levels is not None else [0, 3, 7]
    rows = []
    for li in levels:
        rows.append([_panel(pygame, ui, sprites, C, bank, li, args.scroll,
                            group) for _label, group in groups])
    tile = [r for line in rows for r in line]
    sized = [img.resize((round(img.width * args.scale),
                         round(img.height * args.scale)), Image.Resampling.LANCZOS)
             for img in tile]
    cw = max(img.width for img in sized)
    out = Image.new("RGB", (cw * len(groups),
                            sum(max(img.height for img in
                                    sized[r * len(groups):
                                          (r + 1) * len(groups)])
                                for r in range(len(levels)))),
                    (0, 0, 0))
    y = 0
    for r in range(len(levels)):
        row = sized[r * len(groups):(r + 1) * len(groups)]
        for c, img in enumerate(row):
            out.paste(img, (c * cw, y))
        y += max(img.height for img in row)
    out.save(args.out)
    print(f"{len(tile)} panels -> {args.out}")


if __name__ == "__main__":
    main()
