"""Vertical button menu with keyboard/gamepad-style navigation."""
from __future__ import annotations

from dataclasses import dataclass

from .button import Button


@dataclass
class Menu:
    id: str
    buttons: list[Button]
    focus_index: int = 0
    hovered: int = -1
    pressed: int = -1

    def move(self, delta: int) -> None:
        self.focus_index = (self.focus_index + delta) % max(1, len(self.buttons))

    def current(self) -> Button | None:
        if 0 <= self.focus_index < len(self.buttons):
            return self.buttons[self.focus_index]
        return None

    def set_hover(self, lx: int, ly: int) -> None:
        self.hovered = -1
        for i, b in enumerate(self.buttons):
            if b.enabled and b.contains(lx, ly):
                self.hovered = i
                break

    def set_press(self, lx: int, ly: int) -> int:
        self.pressed = -1
        for i, b in enumerate(self.buttons):
            if b.enabled and b.contains(lx, ly):
                self.pressed = i
                return i
        return -1
