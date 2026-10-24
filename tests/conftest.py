"""Make the in-repo package importable without installation."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pygame  # noqa: E402  (after sys.path so pygame-ce resolves the same way)
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def pygame_display():
    """Keep a display alive for any test that blits.

    Loading and converting surfaces needs a display context. App suites open
    their own window and leave it up; suites that call ``pygame.quit()`` would
    otherwise leave the next test without one, so this re-creates a scratch
    surface whenever none exists. Under a headless driver (``SDL_VIDEODRIVER``
    set to ``dummy``) that is exactly what the CI runs with.
    """
    try:
        pygame.display.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((32, 32))
    except pygame.error:
        pass                      # no video driver: display-free tests still run
    yield


@pytest.fixture(autouse=True)
def baked_terrain_for_suites(monkeypatch):
    """Keep the suites on the baked ground unless a test asks for the streamed kind.

    Streaming is the shipped default now - one designed strip per sector, painted
    in another process - and it is what a player gets. But most app tests are
    about menus, scores, state and the *baked* sector handoff, and none of that
    should be paying for a sector designer (seconds of design in a child process)
    or silently changing what "the terrain" means under them.

    A test that wants the streamed path says so by replacing the setting after
    building its App, which is what ``tests/test_streamed_sector.py`` does; that
    runs after this, so the request wins.
    """
    import dataclasses

    import app.app as app_mod

    real_init = app_mod.App.__init__

    def init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        self.settings = dataclasses.replace(self.settings, streamed_terrain=False)

    monkeypatch.setattr(app_mod.App, "__init__", init)
    yield
