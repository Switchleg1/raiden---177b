"""Error raised for illegal state transitions."""
from __future__ import annotations

from .game_state import State


class InvalidTransition(Exception):
    """Raised when an illegal state transition is attempted."""

    def __init__(self, src: State, dst: State) -> None:
        super().__init__(f"illegal transition: {src.value} -> {dst.value}")
        self.src = src
        self.dst = dst
