"""World-keyed sampling: the relief grid, a window's features, jitter."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .numpy_import import _numpy

if TYPE_CHECKING:
    from .plane import Plane

import random
from typing import Any

from ..plan.site_plan import SitePlan


def _upsample(grid: Any, plane: Plane, gw: int, gh: int) -> Any:
    """Resample the planning grid over one window with **Catmull-Rom**, in
    pygame's (x, y) order.

    Bilinear was the wrong interpolant: it is only C0, so its derivative jumps
    at every cell boundary, and a slope-shaded field paints those jumps as lit
    and dark stripes - exactly the "blurred vertical bands" and "separate
    raised blobs" the art review kept naming. A cubic kernel is C1, so the
    shading has nothing to draw.

    Sampling is driven by WORLD position, so two windows of a strip meet mid
    curve instead of each resampling its own half.
    """
    np = _numpy()
    g = np.asarray(grid, dtype=np.float32)            # (y, x)
    w, h = plane.w, plane.h

    def cr(n: int, xs: Any) -> tuple:
        # Catmull-Rom weights for EXPLICIT sample positions. Building the samples
        # from two endpoints (linspace(lo, hi, m)) was the bug: when `hi` had to be
        # clamped to the last grid row - which happens for every window that runs
        # past the end of the plan - the whole interval was re-fitted into the same
        # number of samples, so the relief got stretched across the window instead
        # of reading flat ground beyond the end. Every interior row of that window
        # then sampled a different world row than its neighbour did: 37% of a slice
        # wrong, growing to the end, and invisible between two windows that were
        # both clamped the same way. Clamp the sample, never the interval.
        i1 = np.clip(np.floor(xs), 0, n - 1).astype(np.int32)
        t = (xs - i1).astype(np.float32)
        i0 = np.clip(i1 - 1, 0, n - 1)
        i2 = np.clip(i1 + 1, 0, n - 1)
        i3 = np.clip(i1 + 2, 0, n - 1)
        t2, t3 = t * t, t * t * t
        return (i0, i1, i2, i3,
                -0.5 * t3 + t2 - 0.5 * t,
                1.5 * t3 - 2.5 * t2 + 1.0,
                -1.5 * t3 + 2.0 * t2 + 0.5 * t,
                0.5 * t3 - 0.5 * t2)

    rows, cols = g.shape
    # Grid coordinate of every pixel row and column, from the window's world
    # position: identical to the full-canvas map when the window IS the whole map,
    # and identical to the neighbour wherever two windows overlap. Clamping is per
    # sample, so a window that reaches past the end of the plan reads the last grid
    # row (flat ground, the honest answer) rather than rescaling its own relief.
    rxs = np.clip((plane.y0 + np.arange(h, dtype=np.float64) * plane.scale)
                  * ((rows - 1) / max(1, gh)), 0.0, rows - 1)
    cxs = np.clip((plane.x0 + np.arange(w, dtype=np.float64) * plane.scale)
                  * ((cols - 1) / max(1, gw)), 0.0, cols - 1)
    a0, a1, a2, a3, q0, q1, q2, q3 = cr(rows, rxs)
    tmp = (g[a0] * q0[:, None] + g[a1] * q1[:, None]
           + g[a2] * q2[:, None] + g[a3] * q3[:, None])       # (h, cols)
    b0, b1, b2, b3, r0, r1, r2, r3 = cr(cols, cxs)
    out = (tmp[:, b0] * r0[None, :] + tmp[:, b1] * r1[None, :]
           + tmp[:, b2] * r2[None, :] + tmp[:, b3] * r3[None, :])
    return np.ascontiguousarray(np.clip(out, 0.0, 1.2).T)      # (x, y)


def _band(canvas: Any, plan: SitePlan, kind: str) -> list[int]:
    """The plan features of `kind` that this window can show.

    A thirty-screen strip carries tens of thousands of props. Walking all of
    them for every slice - rotating a tree sprite only to blit it off the edge -
    is what made a slice take half a minute to paint, and painting slices is
    what has to stay ahead of the scroll.
    """
    y0 = getattr(canvas, "y0", 0.0)
    h = getattr(canvas, "h", 0) or getattr(canvas, "get_height", lambda: 0)()
    # A plane's `h` is PAINTED pixels, and the plan is counted in PLAN pixels, so the
    # window's world range is `h * scale`. Both directions of this have now been
    # wrong once: dividing `h` by SS (an earlier commit, chasing a half-drawn house)
    # halved every query when plane and plan were the same resolution, and NOT
    # multiplying by the plane's scale halves it now that they differ. The rule is
    # neither divide nor multiply by a constant - it is that a query is made in plan
    # units, so a painted extent has to be converted by the plane's own scale.
    reach = h * getattr(canvas, "scale", 1)
    return plan.band(kind, y0, y0 + reach)


def _bytes(v: int) -> bytes:
    """Eight bytes of an integer, order-stable across runs (never `hash()`)."""
    if -(2 ** 63) <= v < 2 ** 63:
        return v.to_bytes(8, "little", signed=True)
    return str(v).encode()


def _at(*key: object) -> random.Random:
    """A stream belonging to one **place**, not to one paint call or one slice.

    The painter must be a pure function of world position, because that is the only
    way a strip painted in overlapping pieces can come out seamless: if the choice
    depends on which window asked, then the same tree is a different tree in each
    piece, and the seam is not a line to hide but a genuine disagreement that no
    margin or blend can fix. Everything a stamp needs - variant, rotation, flip -
    is therefore derived from where it stands, and `rng` arguments are no longer
    consulted for it.

    FNV-1a over the quantised coordinates, so a 1 px difference in the anchor gives
    a different stream (that is the point) while the same anchor gives the same one
    in every window, on every machine, in any interpreter.
    """
    mask = 0xFFFFFFFFFFFFFFFF
    h = 1469598103934665603 & mask
    for v in key:
        parts = (v.encode("utf-8", "ignore") if isinstance(v, str)
                 else _bytes(int(v)))
        for b in parts:
            h = ((h ^ b) * 1099511628211) & mask
    return random.Random(h)


def _frand(plan: SitePlan, index: int, salt: int) -> random.Random:
    """A jitter stream belonging to ONE feature rather than to a paint pass.

    A shared stream makes a chunk's contents depend on which features happened
    to be painted before it - so a strip painted in pieces would grow different
    hedges in the overlap than the piece next door, and the seam would show as
    half a hedgerow. Keyed by plan seed and feature index instead: the same
    jitter, every time, in every window that shows the feature.
    """
    return random.Random(plan.seed * 1_000_003 + index * 4093 + salt)
