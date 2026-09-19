"""Lazy PNG sheet loader (runtime loads art only; painters are for baking)."""
from __future__ import annotations

from typing import Any

from .manifest import SPRITES, pygame_rect, sheet_path


class Bank:
    """Lazy-loading cache of baked sheet textures."""

    def __init__(self) -> None:
        self._sheets: dict[str, Any | None] = {}
        self._tinted: dict[tuple[str, tuple[int, int, int]], Any] = {}

    def sheet(self, name: str) -> Any | None:
        if name in self._sheets:
            return self._sheets[name]
        surf = self._load(name)
        self._sheets[name] = surf
        return surf

    def _load(self, name: str) -> Any | None:
        meta = SPRITES.get(name)
        if meta is None:
            return None
        import pygame
        path = sheet_path(name)
        if not path.is_file():
            return None
        try:
            surf = pygame.image.load(str(path)).convert_alpha()
        except pygame.error:
            return None          # unreadable art: vector fallback, never crash
        cw, ch = meta["cell"]
        if surf.get_width() % cw or surf.get_height() % ch:
            return None          # stale/foreign sheet: fall back
        return surf

    @staticmethod
    def frame(surf: Any, sheet: str, tile: int) -> Any:
        """Sub-surface rect for one tile index."""
        cw, ch = SPRITES[sheet]["cell"]
        cols = surf.get_width() // cw
        x, y = (tile % cols) * cw, (tile // cols) * ch
        return surf.subsurface(pygame_rect(x, y, cw, ch))

    def white(self, surf: Any, sheet: str, tile: int) -> Any:
        """Solid-white silhouette copy (hit flash), alpha preserved."""
        import pygame
        tile_s = Bank.frame(surf, sheet, tile)
        w = tile_s.copy()
        w.fill((255, 255, 255), special_flags=pygame.BLEND_RGB_MAX)
        return w

    def tinted(self, sheet: str, colour: tuple[int, int, int]) -> Any | None:
        """Whole-sheet recoloured copy, alpha preserved (cached per tint).

        Baking one neutral sprite and tinting it at runtime is what lets the
        orbiting pickup marker be a single shared sheet: the animation, the
        transparency and the memory cost stay at one sheet while every item
        still wears its own colour. A colour is tinted once for the whole
        sheet, so frames are then addressed with ``frame()`` as usual.
        """
        key = (sheet, colour)
        cached = self._tinted.get(key)
        if cached is not None:
            return cached
        surf = self.sheet(sheet)
        if surf is None:
            return None
        import pygame
        tint = surf.copy()
        tint.fill(colour + (255,), special_flags=pygame.BLEND_RGB_MULT)
        self._tinted[key] = tint
        return tint

    def clear(self) -> None:
        self._sheets.clear()
        self._tinted.clear()
