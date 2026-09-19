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
