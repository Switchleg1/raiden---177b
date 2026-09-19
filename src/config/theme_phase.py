"""One terrain zone of a sector."""
from __future__ import annotations

from dataclasses import dataclass

from .stage_theme import StageTheme


@dataclass(frozen=True)
class ThemePhase:
    """One terrain zone of a sector: theme + share of the sector scroll."""
    theme: StageTheme
    weight: float
