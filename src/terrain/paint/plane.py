"""A bake-space ground layer held as numpy arrays while it is painted."""
from __future__ import annotations

from typing import Any

from .numpy_import import _numpy


class Plane:
    """A bake-space ground layer held as numpy arrays while it is painted.

    Every feature here is a mask filled with a material, which is arithmetic.
    The canvas used to be a pygame surface, so each of the ~24 fills read 1.8 M
    pixels out of the surface and wrote them back: 5.2 s for one map. The plane
    keeps the pixels as arrays, folds in the sprite layer only when a fill needs
    to see it, and converts to a surface once. It is also what makes a strip
    paintable in windows: a window is a row range of the same arrays.
    """

    def __init__(self, w: int, h: int, x0: int = 0, y0: int = 0,
                 wrap: float = 0.0, scale: int = 1) -> None:
        import pygame
        np = _numpy()
        # where this window sits in plan coordinates. A strip is painted as a
        # run of windows; the world position is what keeps materials, masks and
        # props in the same place in every window that touches them.
        self.x0, self.y0 = int(x0), int(y0)
        # a plan that loops in y paints its seam copies; a strip does not
        self.wrap = float(wrap)
        # Plan (bake) pixels per PAINTED pixel. One is the historic default: the
        # plan is designed in the same units the plane is painted in, which is what
        # a baked one-screen map wants.
        #
        # Two is what a strip on screen wants. The ground is designed at 2x because
        # the baked PNG pipeline was authored that way - "baked PNGs live at 2x for
        # extra detail; runtime loads them once and downscales" - and the strip
        # inherited it, painting a 2x window and filtering it down per slice.
        # Following one material's texel through that: 256 -> 160 (the bake pitch)
        # -> 80 (the per-slice halving) -> 156 on the screen at a 1.95x window.
        # The supersample therefore ends with FEWER pixels than the material
        # already had before it was halved, and what it definitely buys is a filter
        # pass on every slice. Painting at 2 pixels per painted pixel makes the
        # painted plane the size the game blits, so there is nothing left to filter
        # and four times fewer pixels to paint.
        self.scale = max(1, int(scale))
        self.w, self.h = max(1, w // self.scale), max(1, h // self.scale)
        self.rgb = np.zeros((self.w, self.h, 3), dtype=np.float32)
        self.a = np.zeros((self.w, self.h), dtype=np.float32)   # 0..1
        self._layer = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        self._dirty = False
        self._box: tuple[int, int, int, int] | None = None

    def shifts(self) -> tuple[float, ...]:
        """y offsets a shape must be stamped at: the seam copies of a looping
        map, nothing else for a strip."""
        if not self.wrap:
            return (0.0,)
        return (0.0, -self.wrap, self.wrap)

    def local(self, x: float, y: float) -> tuple[int, int]:
        s = self.scale
        return int(round((x - self.x0) / s)), int(round((y - self.y0) / s))

    @property
    def stamp(self) -> Any:
        """The sprite layer: props, decks, strokes. Reading it marks it dirty."""
        self._dirty = True
        return self._layer

    def touch_box(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """Register where a stamp or stroke landed, so the fold-in only has to
        read that part of the sprite layer."""
        self._dirty = True
        bx0, by0 = max(0, int(x0)), max(0, int(y0))
        bx1 = min(self.w, int(x1) + 1)
        by1 = min(self.h, int(y1) + 1)
        if bx1 <= bx0 or by1 <= by0:
            return
        if self._box is None:
            self._box = (bx0, by0, bx1, by1)
        else:
            px0, py0, px1, py1 = self._box
            self._box = (min(px0, bx0), min(py0, by0),
                         max(px1, bx1), max(py1, by1))

    def sync(self) -> None:
        """Fold the sprite layer into the arrays - only over the box that was
        stamped since the last fold, which for a prop or a stroke is a small
        fraction of the canvas."""
        if not self._dirty:
            return
        import pygame
        np = _numpy()
        box = self._box or (0, 0, self.w, self.h)
        x0, y0, x1, y1 = box
        view = self._layer.subsurface(pygame.Rect(x0, y0, x1 - x0, y1 - y0))
        s = np.asarray(pygame.surfarray.array3d(view), dtype=np.float32)
        sa = np.asarray(pygame.surfarray.array_alpha(view),
                        dtype=np.float32) * (1.0 / 255.0)
        m = sa[:, :, None]
        rgb = self.rgb[x0:x1, y0:y1]
        rgb[...] = rgb * (1.0 - m) + s * m
        a = self.a[x0:x1, y0:y1]
        a[...] = np.maximum(a, sa)
        self._layer.fill((0, 0, 0, 0), pygame.Rect(x0, y0, x1 - x0, y1 - y0))
        self._dirty = False
        self._box = None

    def surface(self) -> Any:
        """The finished layer as a pygame surface."""
        import pygame
        np = _numpy()
        self.sync()
        rgba = np.dstack([np.clip(self.rgb, 0.0, 255.0).astype(np.uint8),
                          np.clip(self.a * 255.0, 0.0, 255.0).astype(np.uint8)])
        out = pygame.image.fromstring(
            np.ascontiguousarray(rgba.transpose(1, 0, 2)).tobytes(),
            (self.w, self.h), "RGBA")
        if pygame.display.get_init():
            out = out.convert_alpha()
        return out
