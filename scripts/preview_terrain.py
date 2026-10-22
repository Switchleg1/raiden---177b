"""Dev preview: composite a terrain map (base + far + near) to a PNG.

    python scripts/preview_terrain.py                     # every scheduled pair
    python scripts/preview_terrain.py countryside 1       # one (theme, seed)

Writes to screenshots/terrain/ - dev-review dumps, gitignored, never packaged.
This is how a terrain change gets *looked at* rather than asserted about.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

import config as C  # noqa: E402
import terrain as T  # noqa: E402


def _pairs(argv: list[str]) -> list[tuple[int, str]]:
    if len(argv) >= 2:
        return [(int(argv[1]), argv[0])]
    out: list[tuple[int, str]] = []
    seen = set()
    for i, level in enumerate(C.LEVELS):
        for phase in (level.phases or [C.ThemePhase(level.theme, 1.0)]):
            key = (i + 1, phase.theme.value)
            if key not in seen:
                seen.add(key)
                out.append((i + 1, key))
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    pygame.init()
    pygame.display.set_mode((8, 8))
    out_dir = ROOT / "screenshots" / "terrain"
    out_dir.mkdir(parents=True, exist_ok=True)
    for seed, theme in _pairs(argv):
        base, far, near = T.build_procedural(theme, seed)
        shot = pygame.Surface(base.get_size())
        shot.blit(base, (0, 0))
        shot.blit(far, (0, 0))
        shot.blit(near, (0, 0))
        path = out_dir / f"{seed}_{theme}.png"
        pygame.image.save(shot, str(path))
        print(f"{theme} seed {seed}: {shot.get_size()} -> {path}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
