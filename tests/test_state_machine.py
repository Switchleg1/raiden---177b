"""State machine: the transition table is the app's traffic law."""

import pytest

from state import TRANSITIONS, InvalidTransition, State, StateMachine


def machine(state: State = State.BOOT) -> StateMachine:
    return StateMachine(state)


def test_boot_starts_at_the_title():
    sm = StateMachine()
    assert sm.state == State.BOOT
    assert sm.can(State.TITLE)
    sm.to(State.TITLE)
    assert sm.state == State.TITLE


def test_every_state_is_declared():
    assert set(TRANSITIONS) == set(State)


def test_targets_are_all_real_states():
    for src, targets in TRANSITIONS.items():
        for dst in targets:
            assert isinstance(dst, State), f"{src} points at {dst!r}"


def test_shutdown_is_reachable_from_everywhere_and_is_terminal():
    for src in State:
        if src is not State.SHUTDOWN:
            assert State.SHUTDOWN in TRANSITIONS[src], f"{src} cannot quit"
    assert TRANSITIONS[State.SHUTDOWN] == frozenset()


def test_no_state_transitions_to_itself():
    for src, targets in TRANSITIONS.items():
        assert src not in targets, f"{src} lists itself"


# --------------------------------------------------------------- the run arc
def test_a_full_winning_run_is_walkable():
    sm = StateMachine()
    route = [State.TITLE, State.READY, State.PLAYING, State.LEVEL_COMPLETE,
             State.PLAYING, State.VICTORY, State.NAME_ENTRY, State.HIGH_SCORES,
             State.TITLE]
    for dst in route:
        assert sm.try_to(dst), f"route breaks at {sm.state} -> {dst}"
    assert sm.state == State.TITLE


def test_a_lost_run_is_walkable():
    sm = machine(State.PLAYING)
    for dst in (State.LIFE_LOST, State.READY, State.PLAYING, State.GAME_OVER,
                State.NAME_ENTRY, State.HIGH_SCORES, State.TITLE):
        assert sm.try_to(dst), f"route breaks at {sm.state} -> {dst}"


def test_downing_the_last_boss_ends_the_run_from_playing():
    # Regression: the final SECTOR CLEAR banner asked for VICTORY while still
    # in PLAYING, the table refused it, and the win silently never happened.
    sm = machine(State.PLAYING)
    assert sm.can(State.VICTORY)
    assert sm.to(State.VICTORY) == State.VICTORY


def test_a_downed_craft_can_end_the_run():
    sm = machine(State.PLAYING)
    assert sm.try_to(State.LIFE_LOST)
    assert sm.can(State.GAME_OVER)


# ------------------------------------------------------------------ submenus
def test_submenus_open_from_title_and_pause_only():
    for opener in (State.TITLE, State.PAUSED):
        sm = machine(opener)
        for sub in (State.SETTINGS, State.HOW_TO_PLAY, State.HIGH_SCORES):
            assert sm.can(sub), f"{opener} cannot open {sub}"
            sm.reset(opener)


def test_no_submenu_can_nest_another_submenu():
    # The table may hand back to the results screen it was opened from, but no
    # submenu opens settings, how-to, or gameplay.
    extra = {State.GAME_OVER, State.VICTORY, State.NAME_ENTRY}
    for sub, allowed_extra in ((State.SETTINGS, set()),
                               (State.HOW_TO_PLAY, set()),
                               (State.HIGH_SCORES, extra)):
        assert TRANSITIONS[sub] <= \
            {State.TITLE, State.PAUSED, State.SHUTDOWN} | allowed_extra, sub


def test_score_entry_only_leads_to_the_table_or_back_out():
    assert TRANSITIONS[State.NAME_ENTRY] <= {
        State.HIGH_SCORES, State.TITLE, State.GAME_OVER, State.VICTORY,
        State.SHUTDOWN}


# ---------------------------------------------------------------- enforcement
def test_illegal_moves_are_refused_and_leave_the_state_alone():
    for src, dst in [(State.TITLE, State.PLAYING),
                     (State.PLAYING, State.SETTINGS),
                     (State.PLAYING, State.HOW_TO_PLAY),
                     (State.HIGH_SCORES, State.READY),
                     (State.NAME_ENTRY, State.SETTINGS),
                     (State.SHUTDOWN, State.TITLE)]:
        sm = machine(src)
        with pytest.raises(InvalidTransition):
            sm.to(dst)
        assert sm.state == src
        assert sm.try_to(dst) is False


def test_staying_put_is_not_a_transition():
    sm = machine(State.PLAYING)
    assert not sm.can(State.PLAYING)
    assert sm.try_to(State.PLAYING) is False


def test_reset_bypasses_the_table():
    sm = machine(State.SHUTDOWN)
    sm.reset(State.TITLE)
    assert sm.state == State.TITLE


def test_gameplay_states_are_marked_as_such():
    for st in (State.READY, State.PLAYING, State.LIFE_LOST,
               State.LEVEL_COMPLETE):
        assert machine(st).is_gameplay()
    for st in (State.TITLE, State.PAUSED, State.NAME_ENTRY, State.HIGH_SCORES,
               State.GAME_OVER, State.VICTORY):
        assert not machine(st).is_gameplay()
