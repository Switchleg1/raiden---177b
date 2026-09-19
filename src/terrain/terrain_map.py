"""A sector backdrop: static gradient + two wrapping scroll layers.

Loads baked PNGs when available (normal path); falls back to
procedural painting.
"""
from __future__ import annotations

import os
from typing import Any

import config as C

from .common import FAR_SPEED, NEAR_SPEED, TILE_H
from .layer import Layer
from .procedural import build_procedural


def _tex_root() -> Any:
    from pathlib import Path
    env = os.environ.get("RAIDEN_TEXTURE_DIR")
    base = Path(env) if env else Path(__file__).resolve().parents[2] \
        / "data" / "textures"
    return base / "terrain"


def baked_paths(theme: str, seed: int) -> Any:
    """(base, far, near) PNG paths for a baked (theme, seed) map."""
    root = _tex_root()
    key = f"{seed}_{C.StageTheme(theme).name.lower()}"
    return (root / f"{key}_base.png", root / f"{key}_far.png",
            root / f"{key}_near.png")


def bake(theme: str, seed: int) -> Any:
    """Render one map procedurally and write its three PNGs; returns paths."""
    paths = baked_paths(theme, seed)
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    import pygame
    base, far, near = build_procedural(theme, seed)
    for surf, path in ((base, paths[0]), (far, paths[1]), (near, paths[2])):
        pygame.image.save(surf, str(path))
    return paths


def _load_baked(path: Any) -> Any:
    import pygame
    surf = pygame.image.load(str(path))
    if pygame.display.get_init():
        surf = surf.convert_alpha()
    if surf.get_size() != (C.LOGICAL_W, TILE_H):
        surf = pygame.transform.smoothscale(surf, (C.LOGICAL_W, TILE_H))
    return surf


class Terrain:
    """A sector's backdrop: static gradient + two wrapping scroll layers.

    Loads baked PNGs from data/textures/terrain when available (the normal
    path — loads in milliseconds); falls back to procedural painting."""

    def __init__(self, theme: str, seed: int = 1) -> None:
        self.theme = theme
        paths = baked_paths(theme, seed)
        if all(p.is_file() for p in paths):
            base, far, near = (_load_baked(p) for p in paths)
        else:
            base, far, near = build_procedural(theme, seed)
        self.base = base
        self.layers = (Layer(far, FAR_SPEED), Layer(near, NEAR_SPEED))

    def update(self, dt: float, scale: float) -> None:
        for layer in self.layers:
            layer.update(dt, scale)

    def draw(self, canvas: Any, clip: Any = None) -> None:
        """Paint the map into the field band, or into a sub-band of it.

        ``clip`` lets the sector handoff draw only the strip above (or below)
        the reveal edge without the map having to know about handoffs.
        """
        import pygame
        band = pygame.Rect(0, C.HUD_H, C.LOGICAL_W, TILE_H)
        if clip is not None:
            band = band.clip(clip)
            if band.width <= 0 or band.height <= 0:
                return
        old = canvas.get_clip()
        canvas.set_clip(band)
        canvas.blit(self.base, (0, C.HUD_H))
        for layer in self.layers:
            layer.draw(canvas)
        canvas.set_clip(old)
