"""Generated tileset kit: loads data/textures/tiles/ (seamless
materials, props, splats + manifest.json).
"""
from __future__ import annotations

import json
import os
from typing import Any

TILE = 160                      # material tile pitch in bake space


GRID_C, GRID_R = 10, 7          # 10*160 x 7*160 = 1600 x 1120


CW, CH = GRID_C * TILE, GRID_R * TILE


def _tex_root() -> Any:
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "data" / "textures" / "tiles"
    override = os.environ.get("RAIDEN_TILE_DIR")
    return Path(override) if override else root


class TileKit:
    """Loaded tileset; materials pre-scaled to the 160px bake pitch."""

    def __init__(self) -> None:
        root = _tex_root()
        self.manifest = json.loads((root / "manifest.json").read_text("utf-8"))
        import pygame

        def _load(sub: str, name: str, alpha: bool) -> Any:
            s = pygame.image.load(str(root / sub / f"{name}.png"))
            return s.convert_alpha() if alpha else s.convert()

        tiles = self.manifest["tiles"]
        self.mats = {n: _load("materials", n, False)
                     for n in tiles if tiles[n]["kind"] == "material"}
        self.props = {n: _load("props", n, True)
                      for n in tiles if tiles[n]["kind"] == "prop"}
        self.splats = {n: _load("splats", n, True)
                       for n in tiles if tiles[n]["kind"] == "splat"}
        self.mats = {n: pygame.transform.smoothscale(s, (TILE, TILE))
                     for n, s in self.mats.items()}
        # feathered variant: radial alpha (opaque core, transparent rim) so
        # patch boundaries melt into the base material instead of hard grid
        # lines.  Built with numpy when available, else == plain material.
        self.masked = dict(self.mats)
        try:
            import numpy as np
            r = np.arange(TILE, dtype=np.float32)
            dx = np.minimum(r, TILE - 1 - r)
            dmap = np.minimum(dx[:, None], dx[None, :]) / (TILE * 0.50)
            ramp = np.clip(dmap, 0.0, 1.0)
            ramp = ramp * ramp * (3.0 - 2.0 * ramp)      # smoothstep rim
            amask = (ramp ** 1.25 * 255).astype(np.uint8)
            for n, m in self.mats.items():
                rgb = np.asarray(pygame.surfarray.array3d(m))      # (x,y,3)
                rgba = np.ascontiguousarray(
                    np.dstack([rgb, amask]).transpose(1, 0, 2))    # (y,x,4)
                self.masked[n] = pygame.image.fromstring(
                    rgba.tobytes(), (TILE, TILE), "RGBA")
        except ImportError:
            pass

    def material(self, name: str) -> Any:
        return self.mats[name]

    def patch(self, name: str) -> Any:
        """Radially feathered version of a material tile (soft edges)."""
        return self.masked[name]


_SHIP: bool | None = None       # filesystem verdict (no display needed)


_KIT: TileKit | None = None     # loaded surfaces (display required)


def kit_available() -> bool:
    """True when the tileset ships (manifest + every entry present).

    Filesystem check only, safe before display init; result cached."""
    global _SHIP
    if _SHIP is None:
        _SHIP = False
        root = _tex_root()
        mpath = root / "manifest.json"
        if mpath.is_file():
            try:
                man = json.loads(mpath.read_text("utf-8"))
                _SHIP = all((root / f"{meta['kind']}s" / f"{name}.png").is_file()
                            for name, meta in man["tiles"].items())
            except (OSError, KeyError, ValueError):
                _SHIP = False
    return _SHIP


def kit() -> TileKit:
    """Load (once) and return the tileset. Requires an initialised display."""
    global _KIT
    if _KIT is None:
        assert kit_available(), "tileset not present"
        _KIT = TileKit()
    return _KIT
