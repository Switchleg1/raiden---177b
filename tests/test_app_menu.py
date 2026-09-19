"""Mouse-driven menu regression tests (SDL dummy driver, no real window).

Regression: clicking "Quit to Desktop" in the pause menu once did nothing
because the MOUSEBUTTONDOWN both activated the button (menu layer) and, via
the InputController, emitted ACT_CONFIRM which immediately answered the
confirmation dialog with the focused "No".
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
import pytest  # noqa: E402

from app import App  # noqa: E402
from state import State  # noqa: E402


@pytest.fixture()
def app(monkeypatch, tmp_path):
    import config as C
    # keep the tests off the real per-user save location
    monkeypatch.setattr(C, "TEST_DATA_DIR", str(tmp_path), raising=False)
    a = App()
    a.init_display()
    a.sm.to(State.TITLE)
    a._build_title_menu()
    yield a
    a.shutdown()


def buttons(app, menu_id):
    assert app._menu is not None and app._menu.id == menu_id
    return {b.id: b for b in app._menu.buttons}


def click(app, btn):
    cx = btn.rect[0] + btn.rect[2] // 2
    cy = btn.rect[1] + btn.rect[3] // 2
    pygame.event.post(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, {"pos": (cx, cy), "button": 1}))
    pygame.event.post(pygame.event.Event(
        pygame.MOUSEBUTTONUP, {"pos": (cx, cy), "button": 1}))
    app.process_events()


def test_pause_menu_click_shows_confirm_and_yes_quits(app):
    app._start_game()
    app._pause()
    assert app.sm.state == State.PAUSED
    click(app, buttons(app, "pause")["quit_desktop"])
    assert app._pending_confirm == "quit_desktop", \
        "click must open the confirm dialog and leave it open"
    assert app.running, "a single click must not self-answer the dialog"
    click(app, buttons(app, "confirm")["confirm_yes"])
    assert app.running is False


def test_pause_menu_confirm_no_returns_to_pause(app):
    app._start_game()
    app._pause()
    click(app, buttons(app, "pause")["title"])
    click(app, buttons(app, "confirm")["confirm_no"])
    assert app.sm.state == State.PAUSED and app._menu.id == "pause"
    assert app.running


def test_title_play_click_keeps_ready_state(app):
    click(app, buttons(app, "title")["play"])
    # a click must activate Play exactly once: land in READY, not launch
    assert app.sm.state == State.READY


def test_title_quit_click_exits(app):
    click(app, buttons(app, "title")["quit"])
    assert app.running is False
