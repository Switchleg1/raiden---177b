"""One explosion: sprite-sheet playhead + shockwave ring."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Explosion:
    """One sprite-explosion playhead (frame extraction is the renderer's;
    this stays pygame-free so Effects remains unit-testable)."""
    x: float
    y: float
    sheet: str
    t: float = 0.0

    def tiles(self) -> tuple[list[int], float]:
        import sprites
        frames, fps, _loop = sprites.anim_spec(self.sheet, "boom")
        return frames, fps

    def tile(self) -> int:
        frames, fps = self.tiles()
        i = int(self.t * fps)
        return frames[min(i, len(frames) - 1)]

    def done(self) -> bool:
        frames, fps = self.tiles()
        return self.t * fps >= len(frames)
