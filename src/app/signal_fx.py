"""What a game signal looks and sounds like."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SignalFx:
    """The presentation of one kind of game event, as data.

    `at` says where an explosion or a burst goes: at the event's own position
    ("event"), or on the player's craft ("player").
    """

    sound: str | None = None
    shake: float = 0.0
    flash: float = 0.0
    explosion: str | None = None            # explosion sheet tier, or none
    burst: tuple[tuple[int, int, int], int] | None = None   # (colour, particles)
    at: str = "event"
