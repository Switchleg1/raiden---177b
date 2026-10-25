"""Which key and which button does what. Keys are pygame constant NAMES, resolved
once at first use, so the table stays readable and imports without pygame."""
from __future__ import annotations

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
)

#: movement keys: key -> (ship axis direction, menu navigation action)
MOVE_KEYS: dict[str, tuple[str, str]] = {
    "K_a": ("left", ACT_NAV_LEFT), "K_LEFT": ("left", ACT_NAV_LEFT),
    "K_d": ("right", ACT_NAV_RIGHT), "K_RIGHT": ("right", ACT_NAV_RIGHT),
    "K_w": ("up", ACT_NAV_UP), "K_UP": ("up", ACT_NAV_UP),
    "K_s": ("down", ACT_NAV_DOWN), "K_DOWN": ("down", ACT_NAV_DOWN),
}

#: keys held to fire
FIRE_KEYS = frozenset({"K_SPACE"})

#: one-shot keys: key -> action
ACTION_KEYS: dict[str, str] = {
    "K_RETURN": ACT_CONFIRM, "K_KP_ENTER": ACT_CONFIRM,
    "K_x": ACT_BOMB, "K_l": ACT_BOMB,
    "K_p": ACT_PAUSE,
    "K_ESCAPE": ACT_BACK,
    "K_F11": ACT_FULLSCREEN,
}

#: mouse button held to fire. Left click is ALSO handled by the menu layer
#: (`_handle_click`), so it must not emit ACT_CONFIRM, or the focused button would
#: activate twice in one frame.
FIRE_BUTTON = 1
#: one-shot mouse buttons: button -> action
BUTTON_ACTIONS: dict[int, str] = {3: ACT_BOMB}

#: pygame event type NAME -> the InputController method that handles it
EVENT_HANDLERS: dict[str, str] = {
    "KEYDOWN": "_on_key_down",
    "KEYUP": "_on_key_up",
    "MOUSEMOTION": "_on_motion",
    "MOUSEBUTTONDOWN": "_on_press",
    "MOUSEBUTTONUP": "_on_release",
    "WINDOWFOCUSLOST": "_on_focus_lost",
}

__all__ = ["ACTION_KEYS", "BUTTON_ACTIONS", "EVENT_HANDLERS", "FIRE_BUTTON",
           "FIRE_KEYS", "MOVE_KEYS"]
