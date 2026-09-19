#!/usr/bin/env python3
"""Render sprite sheets to a contact sheet for visual review.

    python scripts/preview_sprites.py                 # every sheet
    python scripts/preview_sprites.py e_boss1 e_grunt # a few
    python scripts/preview_sprites.py --scale 1.0     # native size

Frames are laid out in rows of up to 8 tiles; the generated art (enemies,
bosses) is the thing worth looking at, since a bad anchor or a clipped glow
only shows up once the animation is baked.  Output lands in screenshots/.
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


def _anchor_sheet(stems: list, scale: float, out_path: str) -> None:
    """Mark rawkit anchor fractions on keyed sources (for placing anchors)."""
    from PIL import Image, ImageDraw

    from sprites import rawkit

    cells = []
    for stem in stems:
        if not rawkit.has_source(stem):
            print(f"no keyed source: {stem}")
            continue
        w, h = rawkit.source_size(stem)
        src = rawkit.load_src(stem)          # (H, W, 4) float32 RGBA 0-255
        if src is None:
            print(f"source unreadable: {stem}")
            continue
        rgba = Image.frombytes("RGBA", (w, h),
                               bytes(src.astype("uint8", copy=False).tobytes()))
        img = Image.new("RGBA", (w, h), (9, 11, 15, 255))
        img.alpha_composite(rgba)
        d = ImageDraw.Draw(img)
        for key, col in (("glow", (255, 70, 70)), ("plume", (90, 200, 255)),
                         ("spin", (120, 255, 120))):
            for ax, ay, aw, *rest in rawkit.anchors_for(stem).get(key, ()):
                cx, cy, rr = ax * w, ay * h, max(3.0, aw * w)
                d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col)
                d.line([(cx - 6, cy), (cx + 6, cy)], fill=col)
                d.line([(cx, cy - 6), (cx, cy + 6)], fill=col)
                extra = rest[0] if rest else None
                if isinstance(extra, tuple) and len(extra) == 2:
                    label = f"len {extra[0]}-{extra[1]}"
                elif isinstance(extra, (int, float)) and key == "spin":
                    label = f"{int(extra)} blades"
                else:
                    label = ""
                if label:
                    d.text((cx + rr + 3, cy), label, fill=col)
        cells.append((stem, img))
    if not cells:
        raise SystemExit("no keyed sources for: " + ", ".join(stems))
    imgs = [im.resize((max(1, int(im.width * scale)),
                       max(1, int(im.height * scale))),
            Image.Resampling.LANCZOS)
            for _, im in cells]
    width = sum(im.width for im in imgs) + 6 * len(imgs)
    sheet = Image.new("RGB", (width, max(im.height for im in imgs) + 20),
                      (12, 12, 16))
    dr = ImageDraw.Draw(sheet)
    x = 3
    for (stem, _), im in zip(cells, imgs, strict=True):
        sheet.paste(im, (x, 18))
        dr.text((x, 4), f"{stem} {im.width}x{im.height}", fill=(235, 235, 245))
        x += im.width + 6
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    print(f"anchors for {len(cells)} source(s) -> {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("names", nargs="*", help="sheet names (default: all)")
    ap.add_argument("--scale", type=float, default=0.75)
    ap.add_argument("--out", default=str(ROOT / "screenshots" / "_preview_sprites.png"))
    ap.add_argument("--anchors", action="store_true",
                    help="mark rawkit anchor fractions on the keyed source instead")
    ap.add_argument("--motion", action="store_true",
                    help="print the motion rawkit applies to each keyed sheet")
    args = ap.parse_args()

    pygame.init()
    pygame.display.set_mode((8, 8))      # display context for convert_alpha only
    import sprites

    names = args.names or list(sprites.SPRITES)
    unknown = [n for n in names if n not in sprites.SPRITES]
    if unknown:
        raise SystemExit(f"unknown sheet(s): {', '.join(unknown)}")

    if args.motion:
        from sprites import rawkit
        for name in names:
            if rawkit.raw_stem(name) is None:
                continue          # vector-painted sheet: no keyed motion
            print(f"{name:16} {rawkit.motion_report(name)}")
        pygame.quit()
        return

    if args.anchors:
        out = (args.out if args.out.endswith("_anchors.png")
               else str(ROOT / "screenshots" / "_preview_anchors.png"))
        _anchor_sheet(args.names, args.scale, out)
        pygame.quit()
        return

    cols = 8
    rows = []
    for name in names:
        meta = sprites.SPRITES[name]
        cw, ch = meta["cell"]
        sheet = sprites.build_procedural(name)
        ncol = max(1, sheet.get_width() // cw)
        nrow = max(1, sheet.get_height() // ch)
        tiles = []
        for idx in range(ncol * nrow):
            tx, ty = sprites.tile_xy(name, idx)
            im = Image.frombytes(
                "RGBA", (cw, ch),
                pygame.image.tostring(sheet.subsurface((tx, ty, cw, ch)), "RGBA"),
                "raw")
            if args.scale != 1.0:
                im = im.resize((round(cw * args.scale), round(ch * args.scale)),
                               Image.Resampling.NEAREST)
            tiles.append(im)
        rows.append((name, tiles))

    pad = 6
    tw = max(t.width for _, r in rows for t in r)
    th = max(t.height for _, r in rows for t in r)
    out = Image.new("RGB", (cols * (tw + pad) + 40,
                            len(rows) * (th + pad) + 4), (36, 36, 42))
    from PIL import ImageDraw
    d = ImageDraw.Draw(out)
    label_x = 0
    for i, (name, tiles) in enumerate(rows):
        d.text((label_x + 2, i * (th + pad) + 2), name[:7], fill=(200, 200, 200))
        for j, t in enumerate(tiles[:cols]):
            out.paste(t, (label_x + 34 + j * (tw + pad), i * (th + pad)), t)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.save(args.out)
    print(f"{len(rows)} sheets -> {args.out}")


if __name__ == "__main__":
    main()
