"""Simple focusable menu button."""
from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------
@dataclass
class Button:
    id: str
    label: str
    rect: tuple[int, int, int, int]        # x, y, w, h (logical)
    enabled: bool = True
    hint: str = ""

    def contains(self, lx: int, ly: int) -> bool:
        x, y, w, h = self.rect
        return x <= lx < x + w and y <= ly < y + h
