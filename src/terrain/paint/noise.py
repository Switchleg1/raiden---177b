"""World-position noise for terrain detail."""
from __future__ import annotations

from typing import Any

from .numpy_import import _numpy
from .relief_table import HILL_OCTAVES


def _hash01(ix: Any, iy: Any, seed: int) -> Any:
    """A value in 0..1 for each integer lattice point, from its coordinates alone.

    uint32 arithmetic that wraps on purpose: the same lattice point gives the same
    value in every window, every process and every run, which is what lets terrain
    detail be painted in slices that agree at their seams.
    """
    np = _numpy()
    with np.errstate(over="ignore"):
        h = (ix.astype(np.uint32) * np.uint32(374761393)
             + iy.astype(np.uint32) * np.uint32(668265263)
             + np.uint32(seed & 0xFFFFFFFF))
        h = (h ^ (h >> np.uint32(13))) * np.uint32(1274126177)
        h = h ^ (h >> np.uint32(16))
    return h.astype(np.float32) * (1.0 / 4294967296.0)


def _world_noise(xs: Any, ys: Any, cell: float, seed: int) -> Any:
    """Smooth value noise over WORLD coordinates, shape (len(xs), len(ys))."""
    np = _numpy()
    fx = xs / cell
    fy = ys / cell
    ix = np.floor(fx).astype(np.int64)
    iy = np.floor(fy).astype(np.int64)
    tx = (fx - ix).astype(np.float32)
    ty = (fy - iy).astype(np.float32)
    tx = tx * tx * (3.0 - 2.0 * tx)
    ty = ty * ty * (3.0 - 2.0 * ty)
    X0, Y0 = ix[:, None], iy[None, :]
    v00 = _hash01(X0, Y0, seed)
    v10 = _hash01(X0 + 1, Y0, seed)
    v01 = _hash01(X0, Y0 + 1, seed)
    v11 = _hash01(X0 + 1, Y0 + 1, seed)
    a = v00 + (v10 - v00) * tx[:, None]
    b = v01 + (v11 - v01) * tx[:, None]
    return a + (b - a) * ty[None, :]


def _ridged(xs: Any, ys: Any, seed: int) -> Any:
    """Ridged multifractal: sharp crests and the gullies between them - what a
    mountainside looks like from the air, and what a smooth relief blob is not."""
    np = _numpy()
    out = np.zeros((len(xs), len(ys)), dtype=np.float32)
    amp, tot = 1.0, 0.0
    for k, cell in enumerate(HILL_OCTAVES):
        n = _world_noise(xs, ys, cell, seed + 7919 * k)
        r = 1.0 - np.abs(2.0 * n - 1.0)
        out += r * r * amp
        tot += amp
        amp *= 0.5
    return out / tot
