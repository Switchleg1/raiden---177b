"""Centralised game-state machine and legal transitions.

Every state change flows through :class:`StateMachine`, which refuses
invalid transitions so the app cannot enter an inconsistent screen
after a restart or a return to the menu.
"""
from __future__ import annotations

from .errors import InvalidTransition
from .game_state import State
from .machine import StateMachine, can_transition
from .transitions import TRANSITIONS

__all__ = [
    "InvalidTransition",
    "State",
    "StateMachine",
    "TRANSITIONS",
    "can_transition",
]
