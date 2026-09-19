"""Display-mode / window-scale regression tests (SDL dummy driver).

Regression 1: toggling windowed <-> fullscreen called pygame.display.set_mode()
at runtime, which recreates the SDL window/swapchain; on some Windows drivers
the display then stops updating (game keeps running, screen frozen).

Regression 2: changing the window scale setting did the same thing (set_mode
with a new size), freezing the screen mid-game.

The architecture fix: the display is created ONCE with pygame.SCALED (surface
stays logical 800x600, SDL scales to the window). Runtime changes are then
attribute updates on the existing window - Window.size for window scale,
pygame.display.toggle_fullscreen() for fullscreen, SDL_GL_SetSwapInterval for
vsync. pygame.display.set_mode() must never run after startup.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
import pytest  # noqa: E402

import config as C  # noqa: E402
import persistence as Pers  # noqa: E402
from app import App  # noqa: E402
from input import Viewport  # noqa: E402


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "TEST_DATA_DIR", str(tmp_path), raising=False)
    a = App()
    a.init_display()
    yield a
    a.shutdown()


def _patched(app, monkeypatch):
    """Instrument every window-changing entry point."""
    calls = {"toggle": [], "resize": [], "set_mode": []}
    monkeypatch.setattr(pygame.display, "toggle_fullscreen",
                        lambda: calls["toggle"].append(True))
    monkeypatch.setattr(app, "_resize_window_px",
                        lambda size: calls["resize"].append(size) or True)
    real = pygame.display.set_mode
    def fake_set_mode(size=(0, 0), flags=0, *a, **k):
        calls["set_mode"].append((size, flags))
        return real(size, flags, *a, **k)
    monkeypatch.setattr(pygame.display, "set_mode", fake_set_mode)
    return calls


def test_toggle_fullscreen_avoids_flag_recreating_set_mode(app, monkeypatch):
    """Mode-only toggle uses toggle_fullscreen, never recreates the window."""
    calls = _patched(app, monkeypatch)
    before = app.settings.display_mode
    app.toggle_fullscreen()
    assert calls["toggle"] == [True]
    assert calls["set_mode"] == []
    assert app.settings.display_mode != before


def test_toggle_error_reverts_mode_never_recreates(app, monkeypatch):
    """A failed toggle must roll the setting back; recreating the display
    via set_mode is forbidden at runtime (frozen-screen regression)."""
    calls = _patched(app, monkeypatch)
    def boom():
        raise pygame.error("no toggle here")
    monkeypatch.setattr(pygame.display, "toggle_fullscreen", boom)
    before = app.settings.display_mode
    app.toggle_fullscreen()
    assert app.settings.display_mode == before
    assert calls["set_mode"] == []
    reloaded = Pers.load_settings()[0]
    assert reloaded.display_mode == before


def test_window_always_adopted_from_get_surface(app):
    app._sync_display_surface()
    assert app.window is pygame.display.get_surface()


def test_settings_apply_mode_only_uses_toggle(app, monkeypatch):
    calls = _patched(app, monkeypatch)
    app.settings_draft = app.settings.__class__(
        **{**app.settings.__dict__, "display_mode": "fullscreen"})
    app._settings_apply()
    assert calls["toggle"] == [True]
    assert calls["set_mode"] == []


def test_settings_apply_scale_change_never_set_mode(app, monkeypatch):
    """Window scale changes resize the existing window (Window.size)."""
    calls = _patched(app, monkeypatch)
    app.settings_draft = app.settings.__class__(
        **{**app.settings.__dict__, "window_scale": 2})
    app._settings_apply()
    assert calls["set_mode"] == []
    assert calls["resize"] == [C.window_size(2)]


def test_settings_apply_vsync_change_never_set_mode(app, monkeypatch):
    """vsync changes go through SDL_GL_SetSwapInterval, not set_mode."""
    calls = _patched(app, monkeypatch)
    monkeypatch.setattr(app, "_set_swap_interval",
                        lambda n: calls.setdefault("swap", []).append(n) or True)
    app.settings_draft = app.settings.__class__(
        **{**app.settings.__dict__, "vsync": not app.settings.vsync})
    app._settings_apply()
    assert calls["set_mode"] == []
    assert calls["swap"] == [1 if app.settings.vsync else 0]


def test_settings_apply_vsync_unsupported_still_never_set_mode(app, monkeypatch):
    """When live vsync is impossible the setting just applies next launch;
    the runtime must NOT recreate the window."""
    calls = _patched(app, monkeypatch)
    monkeypatch.setattr(app, "_set_swap_interval", lambda n: False)
    before = app.settings.vsync
    app.settings_draft = app.settings.__class__(
        **{**app.settings.__dict__, "vsync": not before})
    app._settings_apply()
    assert calls["set_mode"] == []
    assert app.settings.vsync == (not before)   # kept; applies next launch
    assert Pers.load_settings()[0].vsync == app.settings.vsync


def test_settings_apply_audio_only_touches_no_window(app, monkeypatch):
    calls = _patched(app, monkeypatch)
    app.settings_draft = app.settings.__class__(
        **{**app.settings.__dict__, "master_volume": 40})
    app._settings_apply()
    assert calls["toggle"] == [] and calls["resize"] == []
    assert calls["set_mode"] == []


def test_viewport_letterboxes_wide_window_in_logical_space(app):
    """16:9 desktop under SCALED: letterbox is pre-applied inside the
    logical surface so SDL's non-uniform stretch cancels out."""
    class FakeWin:
        size = (1920, 1080)
    app._sdl_window = FakeWin()
    app._recompute_viewport()
    v = app.viewport
    assert (v.x, v.y, v.w, v.h) == (100, 0, 600, 600)
    assert isinstance(v, Viewport)


def test_viewport_full_4x3_window(app):
    class FakeWin:
        size = (1600, 1200)
    app._sdl_window = FakeWin()
    app._recompute_viewport()
    assert (app.viewport.x, app.viewport.y) == (0, 0)
    assert (app.viewport.w, app.viewport.h) == (C.LOGICAL_W, C.LOGICAL_H)
