"""Leaderboard and initials-entry flows through the App (SDL dummy driver)."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
import pytest  # noqa: E402

import config as C  # noqa: E402
import persistence as P  # noqa: E402
from app import App  # noqa: E402
from state import State  # noqa: E402


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "TEST_DATA_DIR", str(tmp_path), raising=False)
    a = App()
    a.init_display()
    a.sm.to(State.TITLE)
    a._build_title_menu()
    yield a
    a.shutdown()


def data_file(tmp_path):
    return tmp_path / C.APP_AUTHOR / C.APP_SLUG / P.SCORES_FILENAME


def ids(menu):
    assert menu is not None
    return [b.id for b in menu.buttons]


def key(app, code, unicode=""):
    pygame.event.post(pygame.event.Event(
        pygame.KEYDOWN, {"key": code, "unicode": unicode, "mod": 0}))
    pygame.event.post(pygame.event.Event(
        pygame.KEYUP, {"key": code, "unicode": "", "mod": 0}))
    app.process_events()


def finish_banner(app, after="game_over"):
    """Run the game-over/victory banner to the end of its transition.

    The caller must have started the game (and set a score); GAME_OVER is only
    reachable from PLAYING, so the craft is launched first.
    """
    app._launch_craft()
    app._begin_transition("GAME OVER", "", 0.05, after)
    app._update(0.06)


# ------------------------------------------------------------- title screen
def test_title_menu_offers_the_table(app):
    assert "scores" in ids(app._menu)


def test_high_scores_opens_from_title_and_closes_on_enter(app):
    app._activate("scores")
    assert app.sm.state == State.HIGH_SCORES
    assert app._menu is None, "the table has no menu buttons to steal focus"
    app._on_confirm()
    assert app.sm.state == State.TITLE


def test_high_scores_closes_on_back(app):
    app._activate("scores")
    app._on_back()
    assert app.sm.state == State.TITLE


def test_high_scores_from_pause_returns_to_pause(app):
    app._start_game()
    app._pause()
    app._activate("scores")
    assert app.sm.state == State.HIGH_SCORES
    app._on_back()
    assert app.sm.state == State.PAUSED
    assert "resume" in ids(app._menu)


# ------------------------------------------------------- banner rendering
def test_a_placing_run_renders_its_banner_without_a_menu(app):
    # Regression: for a run that places, the banner switches to GAME_OVER a
    # second and a half before the initials screen exists, and every frame of
    # it drew a menu that had not been built yet (AttributeError on screen).
    app._start_game()
    app.game.score = 50000
    app._launch_craft()
    app._begin_transition("GAME OVER", "", 0.5, "game_over")
    assert app._run_rank is not None
    assert app.sm.state == State.GAME_OVER
    assert app._menu is None, "no results menu while initials are pending"
    for _ in range(40):
        app._render()
        app._update(0.02)
    assert app.sm.state == State.NAME_ENTRY


def test_a_winning_run_renders_its_banner_without_a_menu(app):
    app._start_game()
    app.game.score = 250000
    app._launch_craft()
    app._begin_transition("SECTOR CLEAR", "All sectors down!", 0.5, "victory")
    assert app.sm.state == State.VICTORY
    for _ in range(40):
        app._render()
        app._update(0.02)
    assert app.sm.state == State.NAME_ENTRY


def test_a_non_placing_run_keeps_its_results_menu(app):
    P.save_scores([P.ScoreEntry(initials="PRO", score=9_000_000 + n)
                   for n in range(C.HIGH_SCORE_TABLE)])
    app._scores = P.load_scores()
    app._start_game()
    app.game.score = 10
    app._launch_craft()
    app._begin_transition("GAME OVER", "", 0.5, "game_over")
    assert app._run_rank is None
    for _ in range(40):
        app._render()
        app._update(0.02)
    assert app.sm.state == State.GAME_OVER
    assert "again" in ids(app._menu)


# -------------------------------------------------------------- name entry
def test_qualifying_run_asks_for_initials(app):
    app._start_game()
    app.game.score = 12345
    finish_banner(app)
    assert app._run_rank == 1
    assert app.sm.state == State.NAME_ENTRY


def test_entry_starts_at_the_arcade_default(app):
    app._start_game()
    app.game.score = 500
    finish_banner(app)
    assert "".join(app._initials) == C.INITIALS_START
    assert app._initial_index == 0


def test_typing_fills_slots_and_advances(app):
    app._start_game()
    app.game.score = 500
    finish_banner(app)
    key(app, pygame.K_z, "z")
    key(app, pygame.K_x, "x")
    assert app._initials[:2] == ["Z", "X"]
    assert app._initial_index == 2
    key(app, pygame.K_LEFT)
    assert app._initial_index == 1
    key(app, pygame.K_UP)
    assert app._initials[1] == "Y"
    key(app, pygame.K_DOWN)
    assert app._initials[1] == "X"
    key(app, pygame.K_DOWN)
    assert app._initials[1] == "W"


def test_letter_wheel_wraps_both_ways(app):
    app._start_game()
    app.game.score = 500
    finish_banner(app)
    key(app, pygame.K_UP)                     # A -> B
    assert app._initials[0] == "B"
    for _ in range(len(C.INITIALS_LETTERS)):
        key(app, pygame.K_UP)                 # one full turn lands back on B
    assert app._initials[0] == "B"
    key(app, pygame.K_DOWN)                   # ...and one step back is A
    assert app._initials[0] == "A"


def test_backspace_blanks_the_current_slot_and_steps_back(app):
    app._start_game()
    app.game.score = 500
    finish_banner(app)
    key(app, pygame.K_q, "q")
    key(app, pygame.K_x, "x")
    assert app._initial_index == 2
    key(app, pygame.K_BACKSPACE)
    assert app._initials[2] == C.INITIALS_BLANK
    assert app._initial_index == 1
    assert "".join(app._initials).rstrip() == "QX"


def test_cursor_stays_inside_the_three_slots(app):
    app._start_game()
    app.game.score = 500
    finish_banner(app)
    for _ in range(6):
        key(app, pygame.K_RIGHT)
    assert app._initial_index == C.INITIALS_LEN - 1
    for _ in range(6):
        key(app, pygame.K_LEFT)
    assert app._initial_index == 0


def test_unsupported_keys_are_ignored(app):
    app._start_game()
    app.game.score = 500
    finish_banner(app)
    key(app, pygame.K_AT, "@")
    key(app, pygame.K_PAGEUP, "")
    assert "".join(app._initials) == C.INITIALS_START


def test_confirming_signs_the_table(app):
    app._start_game()
    app.game.score = 31337
    finish_banner(app)
    for ch in "mok":
        key(app, getattr(pygame, f"K_{ch}"), ch)
    key(app, pygame.K_RETURN)
    assert app.sm.state == State.HIGH_SCORES

    rows = P.load_scores()
    assert [(e.initials, e.score) for e in rows] == [("MOK", 31337)]
    assert app._score_highlight == 0, "the new row should be the highlighted one"


def test_winning_run_records_a_clear(app, tmp_path):
    app._start_game()
    app.game.score = 999999
    finish_banner(app, after="victory")
    assert app.sm.state == State.NAME_ENTRY
    app._submit_initials()
    rows = P.load_scores()
    assert rows[0].won is True


def test_skipping_leaves_the_table_untouched(app, tmp_path):
    app._start_game()
    app.game.score = 4242
    finish_banner(app)
    app._on_back()
    assert app.sm.state == State.GAME_OVER
    assert "again" in ids(app._menu)
    assert P.load_scores() == []
    assert not data_file(tmp_path).exists()


def test_a_run_that_does_not_place_skips_the_entry(app):
    P.save_scores([P.ScoreEntry(initials="PRO", score=900000 + n)
                   for n in range(C.HIGH_SCORE_TABLE)])
    app._scores = P.load_scores()
    app._scores_loaded = True
    app._start_game()
    app.game.score = 100
    finish_banner(app)
    assert app._run_rank is None
    assert app.sm.state == State.GAME_OVER
    assert "again" in ids(app._menu)


def test_table_survives_the_session(app):
    app._start_game()
    app.game.score = 1000
    finish_banner(app)
    app._submit_initials()

    app._goto_title()
    app._start_game()
    app.game.score = 2000
    finish_banner(app)
    assert app._run_rank == 1, "the second run beats the first"
    app._submit_initials()

    rows = P.load_scores()
    assert [e.score for e in rows] == [2000, 1000]


def test_results_menu_offers_the_table(app):
    app._start_game()
    app.game.score = 10
    finish_banner(app)
    app._on_back()
    assert "scores" in ids(app._menu)
