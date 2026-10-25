"""Keyboard + mouse input collection for the app loop."""
from __future__ import annotations

from typing import Any

import config as C

from .actions import (
    DEV_KEYBOARD,
    DEV_MOUSE,
)
from .keymap_table import (
    ACTION_KEYS,
    BUTTON_ACTIONS,
    EVENT_HANDLERS,
    FIRE_BUTTON,
    FIRE_KEYS,
    MOVE_KEYS,
)
from .ship_axis import ShipAxis
from .viewport import Viewport, map_mouse_to_logical

_RESOLVED: tuple | None = None


def _resolved() -> tuple:
    """The keymap with pygame's numbers in place of the constant names: (move
    keys, action keys, event handlers, fire keys). Built once."""
    global _RESOLVED
    if _RESOLVED is None:
        import pygame
        _RESOLVED = (
            {getattr(pygame, k): v for k, v in MOVE_KEYS.items()},
            {getattr(pygame, k): v for k, v in ACTION_KEYS.items()},
            {getattr(pygame, k): v for k, v in EVENT_HANDLERS.items()},
            frozenset(getattr(pygame, k) for k in FIRE_KEYS),
        )
    return _RESOLVED


class InputController:
    """Turns pygame events into gameplay input + high-level actions."""

    def __init__(self) -> None:
        self.axis = ShipAxis()
        self.active_device: str = DEV_KEYBOARD
        self.mouse_x: float = C.LOGICAL_W / 2
        self.mouse_y: float = float(C.PLAYER_START_Y)
        self.fire_held: bool = False
        self.actions: set[str] = set()

    # ---- event handlers (called from App with a pygame.Event) --------------
    def handle_event(self, event: Any, view: Viewport) -> None:
        method = _resolved()[2].get(event.type)
        if method is not None:
            getattr(self, method)(event, view)

    def _on_key_down(self, event: Any, view: Viewport) -> None:
        moves, actions, _events, fire = _resolved()
        key = event.key
        if key in moves:
            axis, nav = moves[key]
            self.axis.set(axis, True)
            self.actions.add(nav)
            self.active_device = DEV_KEYBOARD
        elif key in fire:
            self.fire_held = True
        elif key in actions:
            self.actions.add(actions[key])

    def _on_key_up(self, event: Any, view: Viewport) -> None:
        moves, _actions, _events, fire = _resolved()
        key = event.key
        if key in moves:
            self.axis.set(moves[key][0], False)
        elif key in fire:
            self.fire_held = False

    def _on_motion(self, event: Any, view: Viewport) -> None:
        self.mouse_x, self.mouse_y = map_mouse_to_logical(event.pos[0],
                                                          event.pos[1], view)
        self.active_device = DEV_MOUSE

    def _on_press(self, event: Any, view: Viewport) -> None:
        self._on_motion(event, view)
        if event.button == FIRE_BUTTON:
            self.fire_held = True
        elif event.button in BUTTON_ACTIONS:
            self.actions.add(BUTTON_ACTIONS[event.button])

    def _on_release(self, event: Any, view: Viewport) -> None:
        if event.button == FIRE_BUTTON:
            self.fire_held = False

    def _on_focus_lost(self, event: Any, view: Viewport) -> None:
        self.clear_all()

    def clear_all(self) -> None:
        self.axis.clear()
        self.fire_held = False

    def drain_actions(self) -> set[str]:
        out = self.actions
        self.actions = set()
        return out

    # ---- per-frame derived input -----------------------------------------
    def uses_mouse(self) -> bool:
        """True when the pointer is the most-recent device (craft follows it)."""
        return self.active_device == DEV_MOUSE
