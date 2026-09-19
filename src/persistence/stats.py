"""Lifetime statistics for this install."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Stats:
    """Lifetime numbers, one set per install (not per run).

    ``high_score`` is what the HUD's HI readout survives restarts with; the
    rest are career numbers kept for a future stats screen.
    """

    high_score: int = 0
    games_played: int = 0
    highest_sector: int = 0
    most_enemies_destroyed: int = 0
    longest_session: float = 0.0     # seconds, excludes paused time

    def merge_run(self, *, score: int, sector_reached: int,
                  enemies_destroyed: int, play_time: float) -> None:
        """Fold one finished run into lifetime statistics."""
        self.games_played += 1
        self.high_score = max(self.high_score, int(score))
        self.highest_sector = max(self.highest_sector, int(sector_reached))
        self.most_enemies_destroyed = max(self.most_enemies_destroyed,
                                          int(enemies_destroyed))
        self.longest_session = max(self.longest_session, float(play_time))
