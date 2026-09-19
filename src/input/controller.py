"""Keyboard + mouse input collection for the app loop."""
from __future__ import annotations

from typing import Any

import config as C

from .actions import (
    ACT_BACK,
    ACT_BOMB,
    ACT_CONFIRM,
    ACT_FULLSCREEN,
    ACT_NAV_DOWN,
    ACT_NAV_LEFT,
    ACT_NAV_RIGHT,
    ACT_NAV_UP,
    ACT_PAUSE,
    DEV_KEYBOARD,
    DEV_MOUSE,
)
from .ship_axis import ShipAxis
from .viewport import Viewport, map_mouse_to_logical


# ---------------------------------------------------------------------------
# pygame-backed controller
# ---------------------------------------------------------------------------
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
        import pygame
        t = event.type
        if t == pygame.KEYDOWN:
            self._key_down(event.key)
        elif t == pygame.KEYUP:
            self._key_up(event.key)
        elif t == pygame.MOUSEMOTION:
            lx, ly = map_mouse_to_logical(event.pos[0], event.pos[1], view)
            self.mouse_x, self.mouse_y = lx, ly
            self.active_device = DEV_MOUSE
        elif t == pygame.MOUSEBUTTONDOWN:
            lx, ly = map_mouse_to_logical(event.pos[0], event.pos[1], view)
            self.mouse_x, self.mouse_y = lx, ly
            self.active_device = DEV_MOUSE
            if event.button == 1:
                # Left click is handled directly by the menu layer
                # (_handle_click); it must NOT also emit ACT_CONFIRM or the
                # focused button would activate a second time in one frame.
                self.fire_held = True
            elif event.button == 3:
                self.actions.add(ACT_BOMB)
        elif t == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.fire_held = False
        elif t == pygame.WINDOWFOCUSLOST:
            self.clear_all()

    def _key_down(self, key: int) -> None:
        import pygame
        moved = False
        if key in (pygame.K_a, pygame.K_LEFT):
            self.axis.set("left", True)
            self.actions.add(ACT_NAV_LEFT)
            moved = True
        elif key in (pygame.K_d, pygame.K_RIGHT):
            self.axis.set("right", True)
            self.actions.add(ACT_NAV_RIGHT)
            moved = True
        elif key in (pygame.K_w, pygame.K_UP):
            self.axis.set("up", True)
            self.actions.add(ACT_NAV_UP)
            moved = True
        elif key in (pygame.K_s, pygame.K_DOWN):
            self.axis.set("down", True)
            self.actions.add(ACT_NAV_DOWN)
            moved = True
        if moved:
            self.active_device = DEV_KEYBOARD
        elif key == pygame.K_SPACE:
            self.fire_held = True
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.actions.add(ACT_CONFIRM)
        elif key in (pygame.K_x, pygame.K_l):
            self.actions.add(ACT_BOMB)
        elif key == pygame.K_p:
            self.actions.add(ACT_PAUSE)
        elif key == pygame.K_ESCAPE:
            self.actions.add(ACT_BACK)
        elif key == pygame.K_F11:
            self.actions.add(ACT_FULLSCREEN)

    def _key_up(self, key: int) -> None:
        import pygame
        if key in (pygame.K_a, pygame.K_LEFT):
            self.axis.set("left", False)
        elif key in (pygame.K_d, pygame.K_RIGHT):
            self.axis.set("right", False)
        elif key in (pygame.K_w, pygame.K_UP):
            self.axis.set("up", False)
        elif key in (pygame.K_s, pygame.K_DOWN):
            self.axis.set("down", False)
        elif key == pygame.K_SPACE:
            self.fire_held = False

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
