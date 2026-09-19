"""State machine enforcing :data:`TRANSITIONS`."""
from __future__ import annotations

from .errors import InvalidTransition
from .game_state import State
from .transitions import TRANSITIONS


def can_transition(src: State, dst: State) -> bool:
    if src == dst:
        return False
    return dst in TRANSITIONS.get(src, frozenset())


class StateMachine:
    """Holds the current state and enforces :data:`TRANSITIONS`."""

    def __init__(self, initial: State = State.BOOT) -> None:
        self._state = initial

    @property
    def state(self) -> State:
        return self._state

    def can(self, dst: State) -> bool:
        return can_transition(self._state, dst)

    def to(self, dst: State) -> State:
        """Transition to ``dst``; raises :class:`InvalidTransition` if illegal."""
        if not can_transition(self._state, dst):
            raise InvalidTransition(self._state, dst)
        self._state = dst
        return self._state

    def reset(self, dst: State = State.TITLE) -> State:
        """Hard-set the state unconditionally (top-level reset to the menu)."""
        self._state = dst
        return self._state

    def try_to(self, dst: State) -> bool:
        """Transition if legal, returning whether it happened."""
        if can_transition(self._state, dst):
            self._state = dst
            return True
        return False

    def is_gameplay(self) -> bool:
        return self._state in (State.READY, State.PLAYING, State.LIFE_LOST,
                               State.LEVEL_COMPLETE)
