"""Attract-mode high-score table: size and initials entry rules."""
from __future__ import annotations

#: How many runs the table remembers (attract-mode classic: 10).
HIGH_SCORE_TABLE = 10

#: Initials are exactly this many characters, arcade-style.
INITIALS_LEN = 3

#: Letters offered by the up/down selectors (no keyboard typing required).
INITIALS_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

#: Characters accepted from direct keyboard entry (slot keeps one of these).
INITIALS_TYPED = INITIALS_LETTERS + "0123456789 "

#: What a fresh entry starts as, and what a padded slot renders like.
INITIALS_START = "AAA"
INITIALS_BLANK = " "


def sanitize_initials(text: str) -> str:
    """Uppercase, drop unsupported characters, pad/trim to :data:`INITIALS_LEN`."""
    keep = [ch for ch in (text or "").upper() if ch in INITIALS_TYPED]
    out = "".join(keep)[:INITIALS_LEN]
    return out.ljust(INITIALS_LEN, INITIALS_BLANK)


__all__ = ["HIGH_SCORE_TABLE", "INITIALS_LEN", "INITIALS_LETTERS",
           "INITIALS_TYPED", "INITIALS_START", "INITIALS_BLANK",
           "sanitize_initials"]
