"""A float mask plus the box of canvas it covers."""
from __future__ import annotations

from typing import Any

from ..tilekit import CH, CW
from .numpy_import import _numpy


class Mask:
    """A float32 mask plus the box of canvas it covers, stored as (x, y).

    Every fill is arithmetic over a mask, and a road, a river, a field or a
    tree crown only covers a corridor or a blob: painting that box instead of
    the whole 1.8 M-pixel canvas is the difference between ~100 ms and ~5 ms a
    fill, and it is what makes a window of a long strip paintable at all.
    """

    __slots__ = ("arr", "box")

    def __init__(self, arr: Any, box: tuple[int, int, int, int]) -> None:
        self.arr = arr
        self.box = box

    def clip(self, w: int, h: int):
        """This mask's box and array, limited to a `w` x `h` canvas.

        A mask is rasterised over its **own geometry**, not over the window it is
        being painted for. Clipping the box to the plane made a feature's shape
        depend on where the window happened to end, and the pixels that then
        disagreed with a one-window reference were the outer rows of the kept band -
        the rows at a slice boundary, magnitude ~10/255 on a tenth of the band. A
        box may therefore reach past the plane by `_PAD`; everything that writes
        pixels clips here instead.
        """
        x0, y0, x1, y1 = self.box
        cx0, cy0 = max(0, x0), max(0, y0)
        cx1, cy1 = min(w, x1), min(h, y1)
        if cx1 <= cx0 or cy1 <= cy0:
            return (0, 0, 0, 0), None
        return (cx0, cy0, cx1, cy1), self.arr[cx0 - x0: cx1 - x0, cy0 - y0: cy1 - y0]

    def full(self) -> Any:
        """A canvas-sized copy, for the few callers that shade the whole map."""
        np = _numpy()
        out = np.zeros((CW, CH), dtype=np.float32)
        self.paste(out)
        return out

    def paste(self, dst: Any) -> None:
        """Union this mask into a canvas-sized one."""
        np = _numpy()
        box, arr = self.clip(dst.shape[0], dst.shape[1])
        if arr is None:
            return
        x0, y0, x1, y1 = box
        dst[x0:x1, y0:y1] = np.maximum(dst[x0:x1, y0:y1], arr)
