"""Which states each state may move to.

Data only, keyed by :class:`state.game_state.State`. A missing key would mean
"nowhere", so the test suite asserts the table covers every state exactly.
Moves not listed here are refused by :class:`state.machine.StateMachine`
with :class:`state.errors.InvalidTransition`.
"""
from __future__ import annotations

from .game_state import State

# Map of every state to the set of states it may transition to.
TRANSITIONS: dict[State, frozenset[State]] = {
    State.BOOT: frozenset({State.TITLE, State.SHUTDOWN}),
    State.TITLE: frozenset({
        State.READY, State.SETTINGS, State.HOW_TO_PLAY, State.HIGH_SCORES,
        State.SHUTDOWN,
    }),
    State.READY: frozenset({
        State.PLAYING, State.PAUSED, State.TITLE, State.SHUTDOWN,
    }),
    State.PLAYING: frozenset({
        # VICTORY is reachable straight from PLAYING: downing the final boss
        # ends the run where it happened, exactly like GAME_OVER does.
        State.PAUSED, State.LIFE_LOST, State.LEVEL_COMPLETE,
        State.GAME_OVER, State.VICTORY, State.SHUTDOWN,
    }),
    State.PAUSED: frozenset({
        State.PLAYING, State.READY, State.SETTINGS, State.HOW_TO_PLAY,
        State.HIGH_SCORES, State.TITLE, State.SHUTDOWN,
    }),
    State.LIFE_LOST: frozenset({
        State.READY, State.PLAYING, State.GAME_OVER, State.TITLE, State.SHUTDOWN,
    }),
    State.LEVEL_COMPLETE: frozenset({
        State.READY, State.PLAYING, State.VICTORY, State.TITLE, State.SHUTDOWN,
    }),
    # A run that lands on the leaderboard goes GAME_OVER -> NAME_ENTRY ->
    # HIGH_SCORES; one that does not keeps the classic results menu.
    State.GAME_OVER: frozenset({
        State.READY, State.TITLE, State.NAME_ENTRY, State.HIGH_SCORES,
        State.SHUTDOWN,
    }),
    State.VICTORY: frozenset({
        State.READY, State.TITLE, State.NAME_ENTRY, State.HIGH_SCORES,
        State.SHUTDOWN,
    }),
    State.SETTINGS: frozenset({
        State.TITLE, State.PAUSED, State.SHUTDOWN,
    }),
    State.HOW_TO_PLAY: frozenset({
        State.TITLE, State.PAUSED, State.SHUTDOWN,
    }),
    State.NAME_ENTRY: frozenset({
        State.HIGH_SCORES, State.TITLE, State.GAME_OVER, State.VICTORY,
        State.SHUTDOWN,
    }),
    State.HIGH_SCORES: frozenset({
        State.TITLE, State.PAUSED, State.GAME_OVER, State.VICTORY,
        State.NAME_ENTRY, State.SHUTDOWN,
    }),
    State.SHUTDOWN: frozenset(),
}

__all__ = ["TRANSITIONS"]
