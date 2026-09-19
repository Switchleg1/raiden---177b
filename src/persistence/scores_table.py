"""High-score table rules: what a stored row must look like, how it sorts.

Ranking follows the arcade rule the players already know: the table is sorted
best-first, a tie belongs to the run that got there first, and only a strictly
better new run can take a rank.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import config as C

from .score_entry import ScoreEntry


def validate_scores(raw: Any) -> list[ScoreEntry]:
    """Coerce a JSON payload into a valid, sorted, capped table."""
    if isinstance(raw, dict):
        rows = raw.get("scores")
    elif isinstance(raw, list):
        rows = raw
    else:
        rows = None
    if not isinstance(rows, list):
        return []
    out: list[ScoreEntry] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        score = int(score)
        if score <= 0 or score != score:            # non-finite / junk guard
            continue
        sector = item.get("sector", 1)
        if isinstance(sector, bool) or not isinstance(sector, int) or sector < 1:
            sector = 1
        created = item.get("created", 0)
        if isinstance(created, bool) or not isinstance(created, int) or created < 0:
            created = 0
        out.append(ScoreEntry(
            initials=C.sanitize_initials(str(item.get("initials", ""))),
            score=score, sector=sector,
            won=bool(item.get("won", False)), created=created))
    return trim_scores(out)


def trim_scores(entries: Iterable[ScoreEntry],
                limit: int = C.HIGH_SCORE_TABLE) -> list[ScoreEntry]:
    """Sort best-first (earlier runs keep their rank on ties) and cap length."""
    # sorted() is stable, so equal scores keep their original order: the run
    # that got there first stays above the run that matched it.
    return sorted(entries, key=lambda e: -e.score)[:max(0, int(limit))]


def rank_of(entries: Sequence[ScoreEntry], score: int,
            limit: int = C.HIGH_SCORE_TABLE) -> int | None:
    """1-based rank this score would take, or ``None`` when it misses the table.

    A tie goes to the run already on the table, so a new score only takes rank
    ``n`` when it strictly beats what sits at ``n``.
    """
    if score <= 0:
        return None
    scores = [e.score for e in entries][:limit]
    if len(scores) >= limit and score <= min(scores):
        return None
    return 1 + sum(1 for s in scores if s >= score)


def add_score(entries: Sequence[ScoreEntry], entry: ScoreEntry,
              limit: int = C.HIGH_SCORE_TABLE) -> list[ScoreEntry]:
    """Return a new table with ``entry`` inserted, sorted and capped."""
    return trim_scores(list(entries) + [entry], limit)
