"""Font cache (built-in default font; no external font assets)."""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Font cache (built-in default font: no external font assets)
# ---------------------------------------------------------------------------
_font_cache: dict[int, Any] = {}


def get_font(size: int):
    import pygame
    size = max(8, int(size))
    f = _font_cache.get(size)
    if f is None:
        f = pygame.font.Font(None, size)
        _font_cache[size] = f
    return f


def clear_fonts() -> None:
    _font_cache.clear()
