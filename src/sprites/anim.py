"""Animation playheads: frame sequences over a loaded sheet."""
from __future__ import annotations

from .manifest import SPRITES


# ---------------------------------------------------------------------------
# Runtime: animation playhead + sheet bank
# ---------------------------------------------------------------------------
class Anim:
    """Pure-playback frame sequence (plain numbers; pygame-free)."""

    __slots__ = ("frames", "fps", "loop", "t")

    def __init__(self, frames: list[int], fps: float, loop: bool) -> None:
        self.frames = frames
        self.fps = fps
        self.loop = loop
        self.t = 0.0

    def advance(self, dt: float) -> None:
        self.t += dt

    @property
    def index(self) -> int:
        """Frame index into Anim.frames (clamped when non-looping)."""
        i = int(self.t * self.fps)
        n = len(self.frames)
        if self.loop:
            return i % n
        return min(max(i, 0), n - 1)

    @property
    def done(self) -> bool:
        return (not self.loop) and self.t * self.fps >= len(self.frames)

    @property
    def tile(self) -> int:
        """Tile index into the sheet grid."""
        return self.frames[self.index]


def anim_spec(sheet: str, anim: str = "run") -> tuple[list[int], float, bool]:
    meta = SPRITES[sheet]["anims"][anim]
    return list(meta["frames"]), float(meta["fps"]), bool(meta["loop"])
