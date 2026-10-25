"""Dev review: paint a whole streamed sector into one PNG and look at it.

The unit tests assert properties of a sector ("a lake is water in the middle",
"a neighbourhood is a street with houses on it"). They cannot say whether the
result *looks* like a place, and a picture is how that gets judged. This paints
the whole strip in one window - the same painters the streaming path runs, in
the same order - and writes it to `screenshots/terrain/`, which is gitignored:
dev-review dumps, never packaged.

    python scripts/dump_sector.py                       # sector 1, a real sector
    python scripts/dump_sector.py countryside --seed 7
    python scripts/dump_sector.py countryside --seed 7 --slices 8

`--slices` counts ground in `STRIP_SLICE` chunks - the unit the streaming path
paints in - and exists to make a short strip for a quick look. A real sector is
longer than any screen: sector 1 is about 28 of them.

A sector is several screens tall, so the PNG is tall: read it in a viewer that
scrolls, or crop it. What to look for, in the order the user asked for it:

 - neighbourhoods read as streets: a collector, houses facing it on both sides
   at one setback, intersections, a loop or a cul-de-sac at the end;
 - woods read as a place: an edge, a dense interior, glades, and a lake in it;
 - lakes read as water: filled, a shore band, no roadway running through them
   and no centre lines on the surface;
 - trees stand in the wood rather than sprinkled over everything.
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

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from config import LEVELS  # noqa: E402
from level.level import strip_length  # noqa: E402
from level.strip import STRIP_MARGIN, STRIP_SLICE, TerrainStrip  # noqa: E402
from terrain.siteplan import CELL, Geom, plan_site  # noqa: E402

OUT = ROOT / "screenshots" / "terrain"


def main(argv: list[str]) -> int:
    """Run the dev dump. `--seed N` and `--slices N` are consumed here so the
    remaining bare words are the themes: a positional scan that leaves an
    option's value behind answers "no site spec for theme '7'".
    """
    argv = list(argv)
    pygame.init()
    pygame.display.set_mode((40, 30))     # SDL needs a window to blit through

    def take(name: str, default: int) -> int:
        if name in argv:
            i = argv.index(name)
            if i + 1 < len(argv) and argv[i + 1].lstrip("-").isdigit():
                value = int(argv[i + 1])
                del argv[i:i + 2]
                return value
        return default

    seed = take("--seed", 1)
    slices_ = take("--slices", 8)
    themes = [a for a in argv if not a.startswith("--")]
    OUT.mkdir(parents=True, exist_ok=True)

    for theme in themes or [str(getattr(LEVELS[0], "theme", "countryside"))]:
        spec = next((s for s in LEVELS
                     if str(getattr(s, "theme", "")).endswith(theme)), None)
        rows = (STRIP_SLICE * slices_ if slices_ else
                strip_length(spec or LEVELS[0]))
        t0 = time.perf_counter()
        plan = plan_site(theme, seed, Geom(h=rows, cell=CELL, cyclic=False))
        strip = TerrainStrip(plan, "near", slice_h=rows, margin=STRIP_MARGIN)
        band = strip.paint(0)
        # The strip hands back the near side of the band upside down (its column
        # 0 is the far edge of the window); unflip it so the PNG runs top of the
        # sector to bottom of the sector.
        img = pygame.transform.flip(band, False, True)
        path = OUT / f"sector_{theme}_s{seed}_{rows}rows.png"
        pygame.image.save(img, str(path))
        print(f"{theme:12s} seed {seed} {rows} bake rows "
              f"({rows // STRIP_SLICE} slices): "
              f"{len(plan.buildings)} buildings, "
              f"{sum(len(w.items) for w in plan.woods)} trees, "
              f"{len(plan.roads)} roads, {len(plan.water)} water bodies in "
              f"{time.perf_counter() - t0:.1f} s -> {path}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
