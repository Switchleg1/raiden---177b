"""Turning a :mod:`~terrain.siteplan` into pixels.

The plan says what the ground *is*; this paints it, and the two halves agree on
one thing: **a feature is a shape with an edge, not a stamp**. Roads, rivers,
fields and ridge flanks are cut out as masks and filled with the tileset
material through them, which is why their boundaries are curves instead of the
square steps a row of 160 px tile blits leaves behind. Props stay stamps - a
tree is a sprite - but they now sit where the plan put them: in woods that
cluster, along water that meanders, on the contour where the hillside turns, and
in lines along a ridge foot, which is what makes a ridge read as a ridge.

Relief is the one thing that cannot be a sprite. The plan's 40 px relief grid is
upsampled to canvas resolution, smoothed, and shaded from its own slope with the
light coming from the top left, so a ridge has a lit flank and a shadowed one
and a mesa's cliff edge is an actual edge.

Everything here is bake-time only: the game loads the PNGs that
``scripts/bake_terrain.py`` writes from this code.
"""
from __future__ import annotations

import math
import random
from typing import Any

from .siteplan import CH, CW, SitePlan
from .theme_table import ROCK
from .tilekit import TILE, TileKit

_TILED: dict[str, Any] = {}          # material tiled to canvas size, cached
_ARR: dict[str, Any] = {}            # the same, as a numpy array (W,H,3)
_SOFT: list[Any] = []                # one soft shadow blob, built once


# ---------------------------------------------------------------------------
# small shared pieces
# ---------------------------------------------------------------------------

def _numpy() -> Any:
    try:
        import numpy as np
        return np
    except ImportError:                                   # pragma: no cover
        return None


def _tiled(kit: TileKit, mat: str) -> Any:
    """A canvas-sized surface of one material, cached by name."""
    import pygame
    key = mat
    if key not in _TILED:
        surf = pygame.Surface((CW, CH))
        tile = kit.material(mat)
        for y in range(0, CH, TILE):
            for x in range(0, CW, TILE):
                surf.blit(tile, (x, y))
        _TILED[key] = surf
    return _TILED[key]


def _mat_array(kit: TileKit, mat: str) -> Any:
    """The canvas-sized material as a numpy array (W,H,3), cached. Filling a
    mask and shading a relief field both need the same material as numbers, and
    tiling it once per material is why a map bakes in a second, not a minute."""
    import pygame
    np = _numpy()
    if mat not in _ARR:
        _ARR[mat] = np.asarray(pygame.surfarray.array3d(_tiled(kit, mat)))
    return _ARR[mat]


def _blur(a: Any, passes: int) -> Any:
    np = _numpy()
    out = a
    for _ in range(passes):
        out = (out + np.roll(out, 1, 0) + np.roll(out, -1, 0)
               + np.roll(out, 1, 1) + np.roll(out, -1, 1)) / 5.0
    return out


def _soft_shadow() -> Any:
    """A radial alpha blob, reused for every prop shadow."""
    import pygame
    if not _SOFT:
        r = 64
        s = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        for i in range(r, 0, -1):
            a = int(120 * (1.0 - i / r) ** 1.6)
            pygame.draw.circle(s, (0, 0, 0, a), (r, r), i)
        _SOFT.append(s)
    return _SOFT[0]


def _shadow_on(canvas: Any, x: float, y: float, rx: float, ry: float,
               alpha: int = 90) -> None:
    import pygame
    s = _soft_shadow()
    w = max(4, int(rx * 2))
    h = max(4, int(ry * 2))
    sh = pygame.transform.smoothscale(s, (w, h))
    sh.set_alpha(alpha)
    _blit_wrap(canvas, sh, x - w / 2, y - h / 2)


def _blit_wrap(canvas: Any, img: Any, x: float, y: float) -> None:
    xi, yi = int(round(x)), int(round(y % CH))
    canvas.blit(img, (xi, yi))
    if yi + img.get_height() > CH:
        canvas.blit(img, (xi, yi - CH))
    if yi - img.get_height() < 0:
        canvas.blit(img, (xi, yi + CH))


def _path_mask(path: list[tuple[float, float]], width: float) -> Any:
    """Alpha mask (numpy, H x W) of a path painted with a **round brush**.

    A thick ``pygame.draw.lines`` has no round joins: at any bend it leaves
    square steps, and those steps are exactly the "the ground shows its
    construction grid" artefact the tileset used to produce. Walking the path in
    small steps and stamping a disc gives a real road edge, and lets the width
    vary along the run - a road that widens at a junction and narrows on a
    bridge approach is a road a player believes.
    """
    import pygame
    np = _numpy()
    surf = pygame.Surface((CW, CH))
    surf.fill((0, 0, 0))
    r = max(1.0, width * 0.5)
    for shift in (0, -CH, CH):
        pts = [(x, y + shift) for x, y in path]
        if max(p[1] for p in pts) < -60 or min(p[1] for p in pts) > CH + 60:
            continue
        for i in range(len(pts) - 1):
            (ax, ay), (bx, by) = pts[i], pts[i + 1]
            ln = math.hypot(bx - ax, by - ay)
            n = max(1, int(ln / max(2.0, r * 0.35)))
            for s in range(n + 1):
                t = s / n
                pygame.draw.circle(surf, (255, 255, 255),
                                   (int(ax + (bx - ax) * t),
                                    int(ay + (by - ay) * t)), int(r))
    arr = pygame.surfarray.array3d(surf)              # (W,H,3)
    m = arr[:, :, 0].astype(np.float32) / 255.0
    for _ in range(2):                                # feather the edge
        m = (m + np.roll(m, 1, 0) + np.roll(m, -1, 0)
             + np.roll(m, 1, 1) + np.roll(m, -1, 1)) / 5.0
    return m


def _poly_mask(poly: list[tuple[float, float]], feather: int = 3) -> Any:
    import pygame
    np = _numpy()
    surf = pygame.Surface((CW, CH))
    surf.fill((0, 0, 0))
    for shift in (0, -CH, CH):
        pts = [(int(x), int(y + shift)) for x, y in poly]
        if max(p[1] for p in pts) < -40 or min(p[1] for p in pts) > CH + 40:
            continue
        pygame.draw.polygon(surf, (255, 255, 255), pts)
    arr = pygame.surfarray.array3d(surf)
    m = arr[:, :, 0].astype(np.float32) / 255.0
    for _ in range(feather):
        m = (m + np.roll(m, 1, 0) + np.roll(m, -1, 0)
             + np.roll(m, 1, 1) + np.roll(m, -1, 1)) / 5.0
    return m


def _fill_mask(canvas: Any, kit: TileKit, mat: str, mask: Any,
               strength: float = 1.0) -> None:
    """Blit a material through a mask, keeping canvas alpha. The curve comes
    from the mask, not from the tile grid - which is exactly where the old
    square-edged road shoulders came from."""
    import pygame
    np = _numpy()
    if np is None:                                    # pragma: no cover
        return
    m = np.clip(np.asarray(mask, dtype=np.float32) * strength, 0.0, 1.0)
    if m.ndim == 3:
        m = m[:, :, 0]
    base = np.asarray(pygame.surfarray.array3d(canvas)).astype(np.float32)
    alpha = np.asarray(pygame.surfarray.array_alpha(canvas)).astype(np.uint8)
    src = _mat_array(kit, mat).astype(np.float32)
    mm = m[:, :, None]
    out = base * (1.0 - mm) + src * mm
    a = np.maximum(alpha, (m * 255.0).astype(np.uint8))
    rgba = np.dstack([np.clip(out, 0, 255).astype(np.uint8), a]) \
        .transpose(1, 0, 2)                       # (W,H,4) -> (H,W,4)
    canvas.blit(pygame.image.fromstring(
        np.ascontiguousarray(rgba).tobytes(), (CW, CH), "RGBA"), (0, 0))


def _darken_band(canvas: Any, mask: Any, factor: float) -> None:
    """Multiply the pixels under a mask by ``factor``: the same surface, less
    light. Water is read as much by its value as by its hue."""
    import pygame
    np = _numpy()
    if np is None:                                    # pragma: no cover
        return
    m = np.clip(np.asarray(mask, dtype=np.float32), 0.0, 1.0)
    if m.ndim == 3:
        m = m[:, :, 0]
    base = np.asarray(pygame.surfarray.array3d(canvas)).astype(np.float32)
    alpha = np.asarray(pygame.surfarray.array_alpha(canvas)).astype(np.uint8)
    want = base * factor
    out = base * (1.0 - m[:, :, None]) + want * m[:, :, None]
    rgba = np.dstack([np.clip(out, 0, 255).astype(np.uint8), alpha]) \
        .transpose(1, 0, 2)
    canvas.blit(pygame.image.fromstring(
        np.ascontiguousarray(rgba).tobytes(), (CW, CH), "RGBA"), (0, 0))


def _tint_lines(canvas: Any, pts: list[tuple[float, float]], col: Any,
                width: float, shift_wraps: bool = True) -> None:
    import pygame
    for shift in ((0, -CH, CH) if shift_wraps else (0,)):
        seg = [(x, y + shift) for x, y in pts]
        if max(p[1] for p in seg) < -20 or min(p[1] for p in seg) > CH + 20:
            continue
        pygame.draw.lines(canvas, col, False,
                          [(int(x), int(y)) for x, y in seg],
                          max(1, int(width)))


def _splat(kit: TileKit, canvas: Any, name: str, x: float, y: float,
           s: float, rng: random.Random) -> None:
    import pygame
    p = pygame.transform.rotozoom(kit.splats[name], rng.randint(0, 359), s)
    _blit_wrap(canvas, p, x - p.get_width() / 2, y - p.get_height() / 2)


def _prop(kit: TileKit, canvas: Any, name: str, x: float, y: float,
          s: float, rng: random.Random, rot4: bool = True,
          shadow: float = 0.0) -> None:
    import pygame
    if name not in kit.props:
        return
    p = kit.props[name]
    ang = rng.choice((0, 90, 180, 270)) if rot4 else 0
    p = pygame.transform.rotozoom(p, ang, s)
    if rng.random() < 0.5:
        p = pygame.transform.flip(p, True, False)
    if shadow > 0:
        _shadow_on(canvas, x + shadow * 0.5, y + shadow * 0.7,
                   p.get_width() * 0.45, p.get_height() * 0.4, 70)
    _blit_wrap(canvas, p, x - p.get_width() / 2, y - p.get_height() / 2)


# ---------------------------------------------------------------------------
# relief: the one thing that has to be painted, not stamped
# ---------------------------------------------------------------------------

def _upsample(grid: Any, w: int, h: int) -> Any:
    """Resample the planning grid to canvas resolution with **Catmull-Rom**,
    returning a numpy array in pygame's (x, y) order.

    Bilinear was the wrong interpolant: it is only C0, so its derivative jumps
    at every cell boundary, and a slope-shaded field paints those jumps as lit
    and dark stripes - exactly the "blurred vertical bands" and "separate
    raised blobs" the art review kept naming. A cubic kernel is C1, so the
    shading has nothing to draw.
    """
    np = _numpy()
    g = np.asarray(grid, dtype=np.float32)            # (y, x)

    def cr(n: int, m: int) -> tuple:
        xs = np.linspace(0, n - 1, m)
        i1 = np.floor(xs).astype(np.int32)
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
    a0, a1, a2, a3, q0, q1, q2, q3 = cr(rows, h)
    tmp = (g[a0] * q0[:, None] + g[a1] * q1[:, None]
           + g[a2] * q2[:, None] + g[a3] * q3[:, None])       # (h, cols)
    b0, b1, b2, b3, r0, r1, r2, r3 = cr(cols, w)
    out = (tmp[:, b0] * r0[None, :] + tmp[:, b1] * r1[None, :]
           + tmp[:, b2] * r2[None, :] + tmp[:, b3] * r3[None, :])
    return np.ascontiguousarray(np.clip(out, 0.0, 1.2).T)      # (x, y)


def paint_relief(canvas: Any, kit: TileKit, plan: SitePlan,
                 rng: random.Random, far: bool = False) -> bool:
    """Shade the relief field: colour ramps with height, light from the top
    left, a rock material where the ground is steep, snow above the snowline on
    ice themes. Returns False when numpy is missing (the caller then keeps the
    prop-only read of a ridge)."""
    np = _numpy()
    if np is None or not plan.ridges:                 # pragma: no cover
        return False
    import pygame
    pal = ROCK.get(plan.theme)
    if pal is None:
        return False
    low, high, scree_col, mat = pal
    h_raw = _upsample(plan.relief, CW, CH)
    # The COVER comes from the field as planned (a ridge keeps its edge); the
    # SLOPE is measured on the same field smoothed at *planning* resolution,
    # where a blur pass costs almost nothing and removes the cell-scale wobble
    # that shading would otherwise turn into stripes.
    h = h_raw
    hs = _blur(_upsample(_blur(np.asarray(plan.relief, dtype=np.float32),
                               2 if not far else 4), CW, CH),
               3 if not far else 8)
    # Compress the field away from its floor: a hollow that reaches h 0 lands on
    # the base tone and reads as a stain of "unexplained depression", while a
    # hollow that only dips a little reads as what it is - shallow ground
    h = 0.24 + 0.76 * h
    hs = 0.24 + 0.76 * hs
    if far:
        h = h * 0.75
        hs = hs * 0.75
    gy, gx = np.gradient(hs)
    # --- slope lighting, normalised per map ---
    # An unnormalised coefficient is either invisible on a gentle hillside or
    # clipped to near-black on a cliff, and that clipped black is what made the
    # canyon mesas read as rectangular rendering artefacts. Normalise by the
    # map's own 98th-percentile slope, then bound with tanh: the darkest shadow
    # is a dark tone, never a hole.
    gmag = np.hypot(gy, gx)
    # Normalise by the map's BIGGEST slope, not by its typical one. The 98th
    # percentile is dominated by cell-scale wobble, which puts every little
    # bump at full lighting and turns a range into "separate shaded blobs" with
    # dark halos at their feet: the small slopes were being lit as hard as the
    # cliff. With the extreme as the reference, the dominant mass carries the
    # light and a swale stays a swale.
    scale = float(np.percentile(gmag, 99.6)) or 1.0
    # a second, mid reference: how steep the ground usually is on this map. It
    # decides where the surface turns to bare rock - a steep flank is rock at any
    # absolute height, a tall but gentle dome stays soil
    scale_mid = float(np.percentile(gmag, 85)) or 1.0
    slope_n = np.clip(gmag / scale_mid, 0.0, 1.0)
    # one fixed sun for every map, from the top left: the player learns to read
    # "lit flank = the side facing the sun" once and applies it everywhere
    light = math.radians(200.0)
    lx, ly = math.cos(light), math.sin(light)
    gdot = np.clip((lx * gy + ly * gx) / scale, -3.0, 3.0)
    # Height itself barely brightens: a pale wash along the high ground reads as
    # fog or a rendering seam. The MASS is carried by which flank is lit.
    lit = 0.70 + h * 0.20 + 0.52 * np.tanh(gdot * 1.05) \
        + 0.16 * np.tanh(np.clip(gx / scale, -3.0, 3.0))
    # the floor matters: a deep shadow at the foot of every rise is a dark ring,
    # and a dark ring around nothing reads as a painted halo, not as ground
    lit = np.clip(lit, 0.55, 1.6)
    lo = np.asarray(low, dtype=np.float32)
    hi = np.asarray(high, dtype=np.float32)
    rgb = (lo[None, None, :] * (1.0 - h[:, :, None])
           + hi[None, None, :] * h[:, :, None])
    rgb *= lit[:, :, None]
    # a steep flank is rock, not soil: the material only shows where the ground
    # is actually steep, so the foot of a green hill stays green
    rock_m = np.clip((h - 0.30) / 0.30, 0.0, 1.0) \
        * (0.4 + 0.6 * slope_n) * (0.85 if not far else 0.5)
    # The ramp has to actually PAINT the hillside: starting at h 0.30 left most
    # of every slope showing base material with a faint tint, which is why
    # reviewers wrote "no convincing elevation" for every theme. Ground above
    # a quarter height is now fully in the relief palette.
    # The ramp PAINTS the high ground, but never replaces the base: full
    # coverage over a broad area is a pale band with dark margins, which is how
    # "blurred fog / unfinished texture strip" got written twice. 0.72 lets the
    # ground's own material keep showing through the mass.
    cover = np.clip((h - 0.22) / 0.40, 0.0, 1.0) * (0.5 if far else 0.72)
    mask = np.clip(cover * rock_m * 3.0, 0.0, 1.0)
    # contour lines: see below
    # contour lines: one heavy RIM at the foot of the mass, one thinner level
    # partway up. More levels than that read as tracks and cables, not
    # topography - the reviewer kept calling them "infrastructure".
    rim = tuple(int(c * 0.5) for c in low)
    line = np.zeros_like(h)
    # Two levels: the foot of the mass (a rim - the edge that says "this is a
    # landform and here is where it starts") and one mid-slope contour, which is
    # what gives a reader the slope DIRECTION. Both sit on the uphill side of the
    # level, so a hollow never gets outlined around nothing.
    for level, weight in ((0.20, 1.0), (0.46, 0.45)):
        band = (h >= level) & (h < level + (0.022 if not far else 0.04))
        line = np.maximum(line, band.astype(np.float32) * weight)
    # Only along a planned mass. A height line anywhere the ground happens to
    # cross a level outlines every swale and reads as "an unexplained pit" or "a
    # painted boundary". Note this replaces an earlier gate on local slope: once
    # the slope scale was normalised properly that gate killed the rim too, and
    # every mass went edgeless - "soft-edged raised strips, no readable crest".
    flank = np.zeros_like(h)
    for ridge in plan.ridges:
        flank = np.maximum(flank, _path_mask(ridge.spine, ridge.width * 3.4))
    line = line * np.clip(flank * 1.7, 0.0, 1.0)
    cover = np.maximum(cover, line * 0.6)
    mask = np.maximum(mask, line * 0.2)
    base = np.asarray(pygame.surfarray.array3d(canvas)).astype(np.float32)
    alpha = np.asarray(pygame.surfarray.array_alpha(canvas)).astype(np.uint8)
    src = _mat_array(kit, mat).astype(np.float32)
    blended = base * (1.0 - mask[:, :, None]) + src * mask[:, :, None]
    blended = blended * (1.0 - cover[:, :, None]) + rgb * cover[:, :, None]
    blended = blended * (1.0 - line[:, :, None] * 0.62) \
        + np.asarray(rim, dtype=np.float32)[None, None, :] \
        * (line[:, :, None] * 0.62)
    # (a lit crest band along the spine was tried: it painted pale bands across
    # the map and the review's verdict became "competing terrain directions" -
    # a mass has to be carried by its slope shading, not by a stripe)
    out_a = np.maximum(alpha, (cover * 255.0).astype(np.uint8))
    rgba = np.dstack([np.clip(blended, 0, 255).astype(np.uint8), out_a]) \
        .transpose(1, 0, 2)
    canvas.blit(pygame.image.fromstring(
        np.ascontiguousarray(rgba).tobytes(), (CW, CH), "RGBA"), (0, 0))
    # scree and slumps at the foot: debris where the slope lets go. Small and
    # dark, and in the theme's own rock tone - a bright grey belt across the
    # middle of a green valley is a landslide of decoration, not a landform.
    foot = tuple(int(c * 0.8) for c in low)
    for wd in plan.woods:
        if wd.kind != "scree":
            continue
        for x, y, s in wd.items:
            r = int(3 + 7 * s)
            pygame.draw.circle(canvas, foot, (int(x), int(y % CH)), r)
            pygame.draw.circle(canvas, scree_col,
                               (int(x + rng.uniform(-r, r) * 1.6),
                                int((y + rng.uniform(-r, r)) % CH)),
                               max(1, r // 3))
    return True


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------

def paint_fields(canvas: Any, kit: TileKit, plan: SitePlan,
                 rng: random.Random) -> None:
    for f in plan.fields:
        mask = _poly_mask(f.poly)
        _fill_mask(canvas, kit, f.mat, mask, 0.92)
        if f.kind in ("crop", "paddy", "lot", "orchard"):
            # tilled and built parcels are brighter than the waste around them:
            # the material alone leaves them at the same value as the field next
            # door, and the reviewer's verdict was "striped enclosures, purpose
            # unknown"
            _darken_band(canvas, mask, 1.22)
        # the boundary first: a hedgerow or fence reads as a LINE on the ground,
        # and a field without one is just a patch of different colour
        if f.hedge:
            edge = list(f.poly) + [f.poly[0]]
            _tint_lines(canvas, edge, (12, 16, 12), 2.2)
        if f.furrows and f.kind in ("crop", "paddy"):
            # plough: a dark rut with a lit ridge beside it. On tilled earth the
            # rows are the whole reason the parcel reads as farmed.
            for a, b in f.furrows:
                ln = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
                nx, ny = -(b[1] - a[1]) / ln, (b[0] - a[0]) / ln
                _tint_lines(canvas, [a, b], (18, 14, 10), 2.0)
                off = [(a[0] + nx * 3.0, a[1] + ny * 3.0),
                       (b[0] + nx * 3.0, b[1] + ny * 3.0)]
                _tint_lines(canvas, off, (86, 66, 44), 1.2)
        if f.hedge:
            pts = list(f.poly) + [f.poly[0]]
            # (the stroke above is the hedgerow; city parcels get neither it nor
            # the hedge props, and read as plots with a kerb instead of as
            # fenced planking)
            for i in range(len(pts) - 1):
                (ax, ay), (bx, by) = pts[i], pts[i + 1]
                ln = math.hypot(bx - ax, by - ay)
                n = max(1, int(ln / 26.0))
                for s in range(n):
                    t = (s + 0.5) / n
                    x, y = ax + (bx - ax) * t, ay + (by - ay) * t
                    if rng.random() < 0.82:      # hedges have gaps and gates
                        _prop(kit, canvas, "tree_clump", x, y,
                              rng.uniform(0.22, 0.34), rng, shadow=3.0)


def paint_water(canvas: Any, kit: TileKit, plan: SitePlan,
                rng: random.Random) -> None:
    from .theme_table import ROCK, WATER_MAT
    pal = ROCK.get(plan.theme, ((40, 40, 36), (120, 120, 110),
                                (80, 80, 70), "gravel_rubble"))
    # the tones come from the theme's own rock palette: the near-black shore
    # line that reads as a bank in a green valley is a hole in the ground on
    # tan sand
    bank = tuple(int(c * 0.55) for c in pal[0])
    bank_mat = {"glacier": "ice_sheet", "canyon": "sand_canyon",
                "wasteland": "sand_canyon", "volcanic": "obsidian",
                "swamp": "mud_flat"}.get(plan.theme, "gravel_rubble")
    for w in plan.water:
        mat = WATER_MAT.get(plan.theme, "water_river")
        # A bank of material first, water on top of it. Water_river is lum 35 on
        # a lum 42 grass base - almost no value separation - and a *stroke*
        # along the shore reads as a drawn outline. A real band of pale gravel,
        # sand or snow around the channel gives the dark/light adjacency the eye
        # uses to find water, without looking drawn.
        _fill_mask(canvas, kit, bank_mat,
                   _path_mask(w.path, w.half * 2.0 + 10.0), 0.55)
        _fill_mask(canvas, kit, mat, _path_mask(w.path, w.half * 2.0), 1.0)
        dry = w.kind in ("wash", "arroyo")
        # a wet channel is darkened - water reads by value. A DRY wash is
        # lightened instead: a desert arroyo is pale bare sand between darker
        # desert pavement, and darkening one turns it into a black scratch
        _darken_band(canvas, _path_mask(w.path, w.half * 2.0),
                     1.12 if dry else 0.62)
        # floodplain: ground beside a river is not ground away from it - but at
        # under half the width, or it becomes one more pale smear
        # The floodplain is a *hint*: at the old width and alpha it was a band
        # of pale mud three times wider than the river itself, and reviewers read
        # the whole corridor as "ambiguous pale strip - stream or track?". The
        # dark river material is the feature; the mud only softens its edge.
        if w.half >= 34.0:      # only a wide channel earns a floodplain
            _fill_mask(canvas, kit, "mud_flat" if plan.theme != "glacier"
                       else "ice_sheet", _path_mask(w.path, w.flood * 0.45),
                       0.10)
        edge = "splat_mud" if plan.theme not in ("glacier", "volcanic") \
            else "splat_snow"
        for i in range(0, len(w.path) - 1, 3):
            if rng.random() < 0.34:
                (ax, ay), (bx, by) = w.path[i], w.path[i + 1]
                side = 1.0 if rng.random() < 0.5 else -1.0
                ang = math.atan2(by - ay, bx - ax) + side * math.pi / 2
                d = w.half + rng.uniform(4.0, 16.0)
                _splat(kit, canvas, edge, ax + math.cos(ang) * d,
                       ay + math.sin(ang) * d, rng.uniform(0.18, 0.34), rng)
        # a bank line on each side: water needs an edge to be read against, or a
        # river is just a dark smear with rocks in it
        for side in (-1.0, 1.0):
            pts = []
            for i in range(len(w.path) - 1):
                (ax, ay), (bx, by) = w.path[i], w.path[i + 1]
                ln = math.hypot(bx - ax, by - ay) or 1.0
                nx, ny = -(by - ay) / ln, (bx - ax) / ln
                d = w.half * side
                pts.append((ax + nx * d, ay + ny * d))
            _tint_lines(canvas, pts, bank, 3.0)
            # no bright inner lip: it reads as a drawn outline - "its thin
            # bright banks look drawn on" - which is the opposite of a bank
        # glints along the flow, so water reads as moving
        for i in range(2, len(w.path) - 2, 3):
            (ax, ay), (bx, by) = w.path[i], w.path[i + 1]
            ln = math.hypot(bx - ax, by - ay)
            if ln > 1:
                nx, ny = -(by - ay) / ln, (bx - ax) / ln
                off = rng.uniform(0.0, w.half * 0.7)
                a = (ax + nx * off, ay + ny * off)
                b = (bx + nx * off, by + ny * off)
                _tint_lines(canvas, [a, b], (255, 255, 255), 1)


def paint_roads(canvas: Any, kit: TileKit, plan: SitePlan,
                rng: random.Random) -> None:
    from .theme_table import ROAD_MAT
    np = _numpy()
    for r in plan.roads:
        mat = ROAD_MAT.get(plan.theme, "road_dirt")
        # shoulders first: dirt/grass soiling under the road edge, then the
        # road itself. Order matters: the road has a crisp edge, the shoulder
        # is what stops it looking pasted on.
        shoulder = "splat_oil" if plan.theme == "industrial" else "splat_dirt"
        # Small and sparse: at the old scale these soiling blobs merged with the
        # road into one wide pale corridor whose identity - road? track? bare
        # ground? - stopped being readable.
        for i in range(0, len(r.path) - 1, 3):
            if rng.random() < 0.3:
                (ax, ay), (bx, by) = r.path[i], r.path[i + 1]
                side = 1.0 if rng.random() < 0.5 else -1.0
                ang = math.atan2(by - ay, bx - ax) + side * math.pi / 2
                d = r.width + rng.uniform(10.0, 22.0)
                _splat(kit, canvas, shoulder, ax + math.cos(ang) * d,
                       ay + math.sin(ang) * d, rng.uniform(0.16, 0.3), rng)
        surf = _path_mask(r.path, r.width * 1.7)
        # A road that crosses a river does so on a bridge: the carriageway must
        # not smear into the channel, or the two become one corridor again. Cut
        # the water out of the road mask, then put the deck back at each
        # crossing so the bridge still spans its gap.
        if plan.water and r.bridges:
            wet = np.zeros_like(surf)
            for w in plan.water:
                wet = np.maximum(wet, _path_mask(w.path, w.half * 2.0))
            deck = np.zeros_like(surf)
            for bx, by in r.bridges:
                d = _path_mask([(bx - 40.0, by), (bx + 40.0, by)],
                               r.width * 2.6)
                deck = np.maximum(deck, d)
            surf = np.maximum(surf * (1.0 - wet), deck)
        _fill_mask(canvas, kit, mat, surf, 1.0)
        # a lit edge on both sides: a road that is only a darker band disappears
        # into dirt and shadow while it scrolls. The edges are what make it read
        # as a formed surface with a thickness.
        # A shoulder of the SAME material, wider and softer - but only a few px
        # wider: at the old width and alpha the soft band plus the carriageway
        # made a pale corridor the length of the map, and the review's verdict
        # was "a broad pale strip: dry channel, dirt clearing, or enormous road".
        _fill_mask(canvas, kit, mat, _path_mask(r.path, r.width * 1.7 + 8.0),
                   0.22)
        if mat == "road_asphalt" and r.kind == "main":
            step = 0.0
            for i in range(len(r.path) - 1):
                (ax, ay), (bx, by) = r.path[i], r.path[i + 1]
                ln = math.hypot(bx - ax, by - ay)
                step += ln
                if step > 46.0:
                    step = 0.0
                    mx, my = (ax + bx) / 2, (ay + by) / 2
                    _tint_lines(canvas, [(ax, ay), (mx, my)],
                                (190, 180, 120), 1)
        else:                                   # dirt: two wheel ruts
            for side in (-1.0, 1.0):
                pts = []
                for i in range(len(r.path) - 1):
                    (ax, ay), (bx, by) = r.path[i], r.path[i + 1]
                    ln = math.hypot(bx - ax, by - ay) or 1.0
                    nx, ny = -(by - ay) / ln, (bx - ax) / ln
                    d = r.width * 0.45 * side
                    pts.append((ax + nx * d, ay + ny * d))
                _tint_lines(canvas, pts, (0, 0, 0), 1)
    for r in plan.roads:
        for (bx, by) in r.bridges:
            _bridge(canvas, kit, r, bx, by, rng)


def _bridge(canvas: Any, kit: TileKit, road: Any, x: float, y: float,
            rng: random.Random) -> None:
    """A deck across the water with abutments: where the road meets a river,
    the road does not simply continue over it."""
    import pygame
    ln = road.width * 3.0
    ang = 0.0
    for i in range(len(road.path) - 1):
        ax, ay = road.path[i]
        if math.hypot(ax - x, ay - y) < 60.0:
            bx2, by2 = road.path[i + 1]
            ang = math.atan2(by2 - ay, bx2 - ax)
            break
    deck = pygame.Surface((int(ln * 2), int(road.width * 2.6)),
                          pygame.SRCALPHA)
    deck.fill((0, 0, 0, 0))
    pygame.draw.rect(deck, (96, 74, 48),
                     (0, 0, deck.get_width(), deck.get_height()))
    for px in range(0, deck.get_width(), 7):          # planks
        pygame.draw.line(deck, (70, 54, 36), (px, 0), (px, deck.get_height()))
    pygame.draw.rect(deck, (58, 44, 30),
                     (0, 0, deck.get_width(), deck.get_height()), 2)
    d = pygame.transform.rotozoom(deck, math.degrees(ang), 1.0)
    _shadow_on(canvas, x + 4, y + 5, d.get_width() * 0.5, d.get_height() * 0.5,
               80)
    _blit_wrap(canvas, d, x - d.get_width() / 2, y - d.get_height() / 2)


def paint_greens(canvas: Any, kit: TileKit, plan: SitePlan,
                 rng: random.Random) -> None:
    import pygame
    for g in plan.greens:
        r = int(g.radius)
        mask_surf = pygame.Surface((CW, CH))
        mask_surf.fill((0, 0, 0))
        for shift in (0, -CH, CH):
            pygame.draw.circle(mask_surf, (255, 255, 255),
                               (int(g.x), int(g.y + shift)), r)
        np = _numpy()
        if np is not None:
            m = np.asarray(pygame.surfarray.array3d(mask_surf))[:, :, 0]
            m = m.astype(np.float32) / 255.0
            for _ in range(4):
                m = (m + np.roll(m, 1, 0) + np.roll(m, -1, 0)
                     + np.roll(m, 1, 1) + np.roll(m, -1, 1)) / 5.0
            _fill_mask(canvas, kit, g.mat, m, 0.95)
        for lane in g.lanes:
            _fill_mask(canvas, kit, "road_dirt",
                       _path_mask(lane, 11.0), 0.9)
        # a green has a stand of trees and often a stack of crates or a trough
        for _ in range(rng.randint(1, 3)):
            a = rng.uniform(0, math.tau)
            _prop(kit, canvas, "tree_clump", g.x + math.cos(a) * g.radius * 0.6,
                  g.y + math.sin(a) * g.radius * 0.6, rng.uniform(0.3, 0.45),
                  rng, shadow=4.0)


def paint_buildings(canvas: Any, kit: TileKit, plan: SitePlan,
                    rng: random.Random) -> None:
    for b in plan.buildings:
        # the approach first: a drive from the door to the road, and a yard
        if b.drive:
            _fill_mask(canvas, kit, "road_dirt", _path_mask(b.drive, 12.0),
                       0.8)
        if b.yard:
            yx, yy, yr = b.yard
            _splat(kit, canvas, "splat_dirt", yx, yy, yr / 60.0, rng)
        name = b.kind if b.kind in kit.props else "house_top"
        import pygame
        p = kit.props[name]
        ang = b.angle
        p = pygame.transform.rotozoom(p, ang, b.scale)
        _shadow_on(canvas, b.x + p.get_width() * 0.06,
                   b.y + p.get_height() * 0.09,
                   p.get_width() * 0.42, p.get_height() * 0.34, 60)
        _blit_wrap(canvas, p, b.x - p.get_width() / 2, b.y - p.get_height() / 2)
        # a house's near edge catches the light: this is what makes a sprite
        # read as a built thing sitting on ground rather than pasted on it
        pygame.draw.circle(canvas, (255, 255, 255),
                           (int(b.x - p.get_width() * 0.18),
                            int((b.y - p.get_height() * 0.2) % CH)), 1)


def _cover_props(theme: str, kind: str) -> tuple[str, ...]:
    from .siteplan import _DEFAULT, SPEC
    spec = SPEC.get(theme, _DEFAULT)
    if kind in ("outcrop", "scree"):
        return (spec.ridge_prop,)
    return spec.tree_props or ("tree_clump",)


def paint_cover(canvas: Any, kit: TileKit, plan: SitePlan,
                rng: random.Random) -> None:
    for wd in plan.woods:
        if wd.kind in ("scree", "outcrop"):
            # rock DEBRIS is not a landform. Stamping cluster sprites along a
            # crest gave "boulder fences" - a row of individually drawn rocks
            # instead of one mass of rock. The relief painter shades the ridge
            # itself; debris is only speckled into it
            continue
        names = _cover_props(plan.theme, wd.kind)
        for x, y, s in wd.items:
            name = names[rng.randrange(len(names))]
            _prop(kit, canvas, name, x, y, s, rng,
                  rot4=wd.kind not in ("riparian", "orchard"),
                  shadow=6.0 * s)


def paint_far(canvas: Any, kit: TileKit, plan: SitePlan,
              rng: random.Random) -> None:
    """The slow layer: the same ridge language, seen further off and softer,
    so the range the player is flying along keeps going behind it."""
    import pygame

    from .theme_table import FAR_PAIR
    for name in FAR_PAIR[plan.theme]:
        t = pygame.transform.smoothscale(kit.patch(name), (280, 280))
        for _ in range(3):
            t.set_alpha(rng.randint(22, 40))
            _blit_wrap(canvas, t, rng.uniform(0, CW), rng.uniform(0, CH))
    paint_relief(canvas, kit, plan, rng, far=True)


def paint_site(canvas: Any, kit: TileKit, plan: SitePlan,
               rng: random.Random) -> None:
    """The whole near layer, in the order a landscape is built up."""
    # In the order a landscape exists: ground, then the water in its hollows,
    # then whatever was cleared and enclosed on the flat parts. The old order
    # painted the relief ON TOP of fields and channels, washing out both the
    # cultivation and the elevation it was supposed to explain.
    paint_relief(canvas, kit, plan, rng)
    paint_water(canvas, kit, plan, rng)
    paint_fields(canvas, kit, plan, rng)
    paint_roads(canvas, kit, plan, rng)
    paint_greens(canvas, kit, plan, rng)
    paint_buildings(canvas, kit, plan, rng)
    paint_cover(canvas, kit, plan, rng)


__all__ = ["paint_site", "paint_far", "paint_relief", "paint_roads",
           "paint_fields", "paint_water", "paint_buildings", "paint_cover",
           "paint_greens"]
