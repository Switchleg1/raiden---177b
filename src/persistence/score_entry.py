"""One row of the high-score table."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScoreEntry:
    """One run on the high-score table."""

    initials: str = "AAA"
    score: int = 0
    sector: int = 1
    won: bool = False
    created: int = 0                    # unix seconds (0 = unknown)

    def to_dict(self) -> dict[str, Any]:
        return {"initials": self.initials, "score": int(self.score),
                "sector": int(self.sector), "won": bool(self.won),
                "created": int(self.created)}
