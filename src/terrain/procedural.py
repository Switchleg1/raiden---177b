"""Procedural (no-tileset / no-bake) map painters.

build_procedural() first tries the generated tileset (terrain.compose),
then the classic vector painters below. Baked offline by
scripts/bake_terrain.py.
"""
from __future__ import annotations

import math
import random
from typing import Any

import config as C

from .common import RGB, SS, TILE2, TILE_H, W2, _blend, _npmod, _scale2, _theme_rng, _ys


def _grain(surf: Any, amp: int, rng: random.Random) -> None:
    """Fine per-pixel material grain on painted (alpha>0) pixels only."""
    import pygame.surfarray
    np = _npmod()
    if np is None:
        return
    arr = pygame.surfarray.pixels3d(surf)
    alpha = pygame.surfarray.pixels_alpha(surf)
    np_rng = np.random.default_rng(rng.getrandbits(64))
    w, h = arr.shape[0], arr.shape[1]
    delta = np_rng.integers(-amp, amp + 1, size=(w, h, 1), dtype=np.int16)
    rgb = arr.astype(np.int16) + delta
    np.clip(rgb, 0, 255, out=rgb)
    arr[...] = rgb.astype(arr.dtype)
    del arr, alpha


def _base_texture(base: Any, rng: random.Random, theme: str) -> None:
    """Low-frequency ground patches + fine grain so the base is never flat.

    Themes with water get horizontally stretched streaks (current bands);
    land themes get isotropic value-noise blotches.
    """
    import pygame.surfarray
    np = _npmod()
    if np is None:
        return
    np_rng = np.random.default_rng(rng.getrandbits(64))
    arr = pygame.surfarray.pixels3d(base)
    w, h = arr.shape[0], arr.shape[1]
    noise = np.zeros((w, h), dtype=np.float64)
    if C.StageTheme(theme) == C.StageTheme.OCEAN:
        octaves = [(64, 6, 3.2), (32, 4, 2.2), (96, 12, 1.1)]
    else:
        octaves = [(10, 8, 3.4), (24, 18, 2.4), (48, 40, 1.3)]

    def _soft(a: Any) -> Any:
        # 5-tap box blur turns kron blocks into soft blobs
        p = np.pad(a, 2, mode="edge")
        acc = np.zeros_like(a)
        for oy in (-1, 0, 1):
            for ox in (-1, 0, 1):
                acc += p[2 + oy:2 + oy + w, 2 + ox:2 + ox + h]
        return acc / 9.0

    for fx, fy, amp in octaves:
        small = np_rng.random((fx, fy))
        sx = max(1, -(-w // fx))   # round up so the crop always covers
        sy = max(1, -(-h // fy))
        big = np.kron(small, np.ones((sx, sy)))[:w, :h]
        noise += amp * (_soft(_soft(big)) - 0.5)
    noise += np_rng.uniform(-1.2, 1.2, size=(w, h))
    rgb = arr.astype(np.float64) + noise[..., None]
    np.clip(rgb, 0, 255, out=rgb)
    arr[...] = rgb.astype(arr.dtype)
    del arr


def build_procedural(theme: str, seed: int) -> Any:
    """Paint a (base, far, near) triple from primitives. Slow (~200 ms):
    the game loads baked PNGs instead; this backs the bake script and any
    (theme, seed) that has no baked art."""
    import pygame
    rng = _theme_rng(theme, seed)
    top, bottom = _theme_gradient(theme)
    base = pygame.Surface((C.LOGICAL_W, TILE_H))
    for yy in range(TILE_H):
        col = _blend(top, bottom, yy / (TILE_H - 1))
        pygame.draw.line(base, col, (0, yy), (C.LOGICAL_W - 1, yy))
    _base_texture(base, rng, theme)
    from . import compose
    layers = compose.build_layers(theme, rng)
    if layers is not None:
        far, near = layers                     # generated-tileset composition
    else:
        far = pygame.Surface((W2, TILE2), pygame.SRCALPHA)
        near = pygame.Surface((W2, TILE2), pygame.SRCALPHA)
        painter = _PAINTERS[C.StageTheme(theme)]
        painter(far, near, rng)
    _grain(far, 4, rng)
    _grain(near, 5, rng)
    if SS != 1:
        # one FULL period of the tile canvas (1120) or a classic TILE2 sheet;
        # stretching preserves vertical wrap continuity either way
        far = pygame.transform.smoothscale(far, (C.LOGICAL_W, TILE_H))
        near = pygame.transform.smoothscale(near, (C.LOGICAL_W, TILE_H))
    return base, far, near


def _blob(surf: Any, x: float, y: float, r: float, col: RGB,
          rng: random.Random, lobes: int = 6) -> None:
    import pygame
    cx, cy = _scale2(x), _scale2(y)
    dy_offs = [0]
    if y - r < 0:                 # crosses top seam: duplicate below
        dy_offs.append(TILE2)
    if y + r > TILE_H:            # crosses bottom seam: duplicate above
        dy_offs.append(-TILE2)
    for dy in dy_offs:
        yy = cy + dy
        for _ in range(lobes):
            a = rng.uniform(0, math.tau)
            d = rng.uniform(0, r * 0.6) * SS
            pygame.draw.circle(surf, col,
                               (int(cx + math.cos(a) * d),
                                int(yy + math.sin(a) * d)),
                               int(rng.uniform(r * 0.55, r)) * SS)


def _block(surf: Any, x: float, y: float, w: float, h: float,
           col: RGB, edge: RGB | None = None) -> None:
    import pygame
    for yy in _ys(y, h):
        pygame.draw.rect(surf, col,
                         (_scale2(x), _scale2(yy), _scale2(w), _scale2(h)))
        if edge:
            pygame.draw.rect(surf, edge,
                             (_scale2(x), _scale2(yy), _scale2(w), _scale2(h)),
                             SS)


def _specks(surf: Any, x: float, y: float, w: float, h: float,
            col: RGB, rng: random.Random, n: int, size: float = 1.0) -> None:
    """Fine grain inside a rect — the 'lots of detail' texture."""
    import pygame
    for _ in range(n):
        sx = x + rng.uniform(0, max(1.0, w - size))
        sy = y + rng.uniform(0, max(1.0, h - size))
        for yy in _ys(sy, size):
            pygame.draw.rect(surf, col,
                             (_scale2(sx), _scale2(yy),
                              max(SS, _scale2(size)), max(SS, _scale2(size))))


# ---------------------------------------------------------------------------
# realism helpers: soft directional shadows (light from top-left), organic
# plot outlines, foam edges, wear patches. Shadows accumulate on their own
# SRCALPHA sheet so overlapping ellipses blend instead of double-replacing.
# ---------------------------------------------------------------------------

def _shadow_sheet() -> Any:
    import pygame
    return pygame.Surface((W2, TILE2), pygame.SRCALPHA)


def _sh_ell(sh: Any, x: float, y: float, rx: float, ry: float,
            a: int = 46) -> None:
    import pygame
    for yy in _ys(y - ry, ry * 2):
        pygame.draw.ellipse(sh, (4, 5, 7, a),
                            (_scale2(x - rx), _scale2(yy),
                             _scale2(rx * 2), _scale2(ry * 2)))


def _sh_rect(sh: Any, x: float, y: float, w: float, h: float,
             dx: float, dy: float, a: int = 46) -> None:
    import pygame
    for yy in _ys(y + dy, h):
        pygame.draw.rect(sh, (4, 5, 7, a),
                         (_scale2(x + dx), _scale2(yy),
                          _scale2(w), _scale2(h)))


def _plot(surf: Any, x: float, y: float, w: float, h: float,
          col: RGB, edge: RGB, rowcol: RGB, rng: random.Random) -> None:
    """Crop plot with jittered (organic) outline + hedge dots + rows."""
    import pygame
    jx = min(7.0, w * 0.08)
    jy = min(7.0, h * 0.10)
    pts = []
    n = 4
    for i in range(n):                       # top edge L->R
        pts.append((x + w * i / n + rng.uniform(-jx, jx),
                    y + rng.uniform(-jy, jy)))
    for i in range(n):                       # right edge T->B
        pts.append((x + w + rng.uniform(-jx, jx),
                    y + h * i / n + rng.uniform(-jy, jy)))
    for i in range(n):                       # bottom edge R->L
        pts.append((x + w - w * i / n + rng.uniform(-jx, jx),
                    y + h + rng.uniform(-jy, jy)))
    for i in range(n):                       # left edge B->T
        pts.append((x + rng.uniform(-jx, jx),
                    y + h - h * i / n + rng.uniform(-jy, jy)))
    for dy in _dy_offs(y, h):
        p2 = [(int(px * SS), int((py + dy / SS) * SS)) for px, py in pts]
        pygame.draw.polygon(surf, col, p2)
        pygame.draw.polygon(surf, edge, p2, SS)
    for ry in range(int(y) + 3, int(y + h) - 2, 5):
        for yy in _ys(ry, 1):
            pygame.draw.line(surf, rowcol, (_scale2(x + 5), _scale2(yy)),
                             (_scale2(x + w - 5), _scale2(yy)), SS)
    # hedge: dense dark dots straddling the outline
    hedge = _blend(edge, (0, 0, 0), 0.25)
    per = int((2 * (w + h)) / 7)
    for _ in range(per):
        t = rng.random() * 4
        side = int(t)
        f = t - side
        if side == 0:
            hx, hy = x + w * f, y
        elif side == 1:
            hx, hy = x + w, y + h * f
        elif side == 2:
            hx, hy = x + w * (1 - f), y + h
        else:
            hx, hy = x, y + h * (1 - f)
        hx += rng.uniform(-2.5, 2.5)
        hy += rng.uniform(-2.5, 2.5)
        for yy in _ys(hy, 3):
            pygame.draw.circle(surf, hedge, (_scale2(hx), _scale2(yy)),
                               max(SS, _scale2(rng.uniform(1.1, 2.2))))


def _dy_offs(y: float, h: float) -> list[int]:
    out = [0]
    if y < 0:
        out.append(TILE2)
    if y + h > TILE_H:
        out.append(-TILE2)
    return out


def _foam_edge(surf: Any, x: float, y: float, r: float, col: RGB,
               rng: random.Random) -> None:
    """Broken foam line ringing an islet/shore."""
    import pygame
    k = max(10, int(r * 2.4))
    for _ in range(k):
        if rng.random() < 0.65:
            a = rng.uniform(0, math.tau)
            rr = r + rng.uniform(0.5, 2.5)
            fx, fy2 = x + math.cos(a) * rr, y + math.sin(a) * rr * 0.9
            for yy in _ys(fy2, 2):
                pygame.draw.circle(surf, col, (_scale2(fx), _scale2(yy)),
                                   max(SS, _scale2(rng.uniform(0.9, 1.7))))


def _crest(surf: Any, x: float, y: float, ln: float, col: RGB,
           rng: random.Random) -> None:
    """Small curved wave crest."""
    import pygame
    pts = [(x, y), (x + ln * 0.45, y - rng.uniform(1.5, 3.5)),
           (x + ln, y)]
    for dy in _dy_offs(y, 5):
        p2 = [(int(px * SS), int((py + dy / SS) * SS)) for px, py in pts]
        pygame.draw.lines(surf, col, False, p2, SS)


def _wear(surf: Any, x: float, y: float, w: float, h: float,
          col: RGB, rng: random.Random, n: int) -> None:
    """Repair patches / stains on roads and decks."""
    import pygame
    for _ in range(n):
        px2 = x + rng.uniform(0, max(1.0, w - 4))
        py2 = y + rng.uniform(0, max(1.0, h - 4))
        for yy in _ys(py2, 4):
            pygame.draw.circle(surf, col, (_scale2(px2), _scale2(yy)),
                               max(SS, _scale2(rng.uniform(1.2, 3.2))))


# ---------------------------------------------------------------------------
# composite helpers (Raiden motifs)
# ---------------------------------------------------------------------------

def _river_x(step: float, rx: float, amp: float) -> float:
    """x of river centre at vertical position `step` (tile-periodic)."""
    return rx + amp * math.sin(2 * math.pi * 2 * step / TILE_H)


def _river(surf: Any, rx: float, amp: float, col: RGB,
           width: float) -> None:
    """Vertical river with dark banks; seamless (whole sines per tile)."""
    import pygame
    bank = _blend(col, (0, 0, 0), 0.45)
    for step in range(0, TILE2, SS):          # 1-logical-px walk
        y1 = step / SS
        x = _river_x(y1, rx, amp)
        pygame.draw.circle(surf, bank, (_scale2(x), step),
                           _scale2(width) + SS * 2)
        pygame.draw.circle(surf, col, (_scale2(x), step), _scale2(width))


def _bridge(surf: Any, rx: float, amp: float, y: float,
           width: float, deck: RGB, rail: RGB) -> None:
    import pygame
    x = _river_x(y, rx, amp)
    bw = width * 2 + 10
    for yy in _ys(y - 6, 12):
        pygame.draw.rect(surf, deck,
                         (_scale2(x - bw / 2), _scale2(yy),
                          _scale2(bw), _scale2(12)))
        pygame.draw.rect(surf, rail,
                         (_scale2(x - bw / 2), _scale2(yy),
                          _scale2(bw), SS), 0)
        pygame.draw.rect(surf, rail,
                         (_scale2(x - bw / 2), _scale2(yy + 12 - 1),
                          _scale2(bw), SS), 0)


def _road_v(surf: Any, x: float, wdt: float, asphalt: RGB, dash: RGB,
            rng: random.Random) -> None:
    """Vertical asphalt strip with dashed centre line (full height)."""
    import pygame
    pygame.draw.rect(surf, asphalt,
                     (_scale2(x - wdt / 2), 0, _scale2(wdt),
                      surf.get_height()))
    for yy in range(0, surf.get_height(), 56 * SS):
        pygame.draw.rect(surf, dash,
                         (_scale2(x - 0.5), yy, SS, 18 * SS))
    _ = rng  # deterministic painters keep the same signature


def _road_h(surf: Any, y: float, wdt: float, asphalt: RGB, dash: RGB,
            rng: random.Random) -> None:
    import pygame
    for yy0 in _ys(y, wdt):
        pygame.draw.rect(surf, asphalt, (0, _scale2(yy0), W2, _scale2(wdt)))
        for xx in range(0, W2, 56 * SS):
            pygame.draw.rect(surf, dash, (xx, _scale2(yy0 + wdt / 2 - 0.5),
                                          18 * SS, SS))


def _tree_cluster(surf: Any, x: float, y: float, r: float,
                  rng: random.Random,
                  dark: RGB, mid: RGB, light: RGB) -> None:
    """Canopy from many small crowns with a shadow side — dense look."""
    import pygame
    n = max(4, int(r * r / 9))
    for _ in range(n):
        a = rng.uniform(0, math.tau)
        d = rng.uniform(0, r * 0.85)
        cx, cy2 = x + math.cos(a) * d, y + math.sin(a) * d * 0.7
        cr = rng.uniform(1.6, 3.4)
        col = rng.choice((dark, mid, light))
        for yy in _ys(cy2, cr * 2):
            pygame.draw.circle(surf, col, (_scale2(cx), _scale2(yy)),
                               max(SS, _scale2(cr)))
    # shadow crescent
    sh = _blend(dark, (0, 0, 0), 0.35)
    for yy in _ys(y + r * 0.4, r * 0.5):
        pygame.draw.circle(surf, sh, (_scale2(x), _scale2(yy)),
                           max(SS, _scale2(r * 0.55)))


def _farm(surf: Any, x: float, y: float, rng: random.Random,
          wall: RGB, roof: RGB) -> None:
    """Small farm compound: barn + yard + silo."""
    import pygame
    _block(surf, x, y, 16, 10, wall, roof)                 # barn body
    _block(surf, x, y, 16, 3, roof)                        # barn roof band
    _block(surf, x + 20, y + 2, 6, 6, _blend(wall, (0, 0, 0), 0.25))
    r = 2.2
    for yy in _ys(y - r, r * 2):                           # silo
        pygame.draw.circle(surf, roof, (_scale2(x + 30), _scale2(yy)),
                           max(SS, _scale2(r)))


def _crack(surf: Any, x: float, y: float, length: float,
           col: RGB, rng: random.Random, wide: int = 2) -> None:
    import pygame
    pts = [(_scale2(x), _scale2(y))]
    cx, cy = x, y
    for _ in range(6):
        cx += rng.uniform(-26, 26)
        cy += rng.uniform(12, length / 6.0)
        pts.append((_scale2(cx), _scale2(cy)))
    pygame.draw.lines(surf, col, False, pts, wide * SS)


def _islet(surf: Any, x: float, y: float, r: float, rng: random.Random,
           sand: RGB, scrub_dark: RGB, scrub: RGB) -> None:
    import pygame
    for yy in _ys(y - r, r * 2):
        pygame.draw.circle(surf, sand, (_scale2(x), _scale2(yy)),
                           _scale2(r))
    for _ in range(int(r * r / 6)):
        a = rng.uniform(0, math.tau)
        d = rng.uniform(0, r * 0.75)
        px2, py2 = x + math.cos(a) * d, y + math.sin(a) * d
        col = rng.choice((scrub_dark, scrub))
        for yy in _ys(py2, 2):
            pygame.draw.circle(surf, col, (_scale2(px2), _scale2(yy)),
                               max(SS, _scale2(rng.uniform(0.8, 1.8))))


def _platform(surf: Any, x: float, y: float, s: float,
              deck: RGB, leg: RGB) -> None:
    """Oil platform: square deck, legs, derrick mast."""
    import pygame
    for yy in _ys(y - s * 0.2, s * 1.6):
        pygame.draw.rect(surf, leg, (_scale2(x - s * 0.4), _scale2(yy),
                                     SS * 2, _scale2(s * 1.5)))
        pygame.draw.rect(surf, leg, (_scale2(x + s * 0.3), _scale2(yy),
                                     SS * 2, _scale2(s * 1.5)))
    _block(surf, x - s / 2, y, s, s * 0.7, deck, _blend(deck, (0, 0, 0), 0.3))
    pygame.draw.line(surf, leg, (_scale2(x), _scale2(y + s * 0.1)),
                     (_scale2(x), _scale2(y - s * 0.4)), SS)


def _ship(surf: Any, x: float, y: float, ln: float, hull: RGB,
          wake: RGB) -> None:
    """Dim cargo hull with bow wake streaks."""
    import pygame
    for yy in _ys(y - 3, 6):
        pygame.draw.polygon(surf, hull,
                            [(_scale2(x - ln / 2), _scale2(yy)),
                             (_scale2(x + ln / 2 - 4), _scale2(yy)),
                             (_scale2(x + ln / 2), _scale2(yy + 3 - 1.5)),
                             (_scale2(x + ln / 2 - 4), _scale2(yy + 6 - 3)),
                             (_scale2(x - ln / 2), _scale2(yy + 6 - 3))])
        pygame.draw.line(surf, wake, (_scale2(x - ln), _scale2(yy + 3)),
                         (_scale2(x - ln / 2 - 2), _scale2(yy + 3)), SS)


def _pier(surf: Any, x: float, y: float, ln: float, deck: RGB,
          pile: RGB) -> None:
    import pygame
    _block(surf, x - 3, y, 6, ln, deck)
    for py in range(int(y), int(y + ln), 14):
        for yy in _ys(py, 2):
            pygame.draw.circle(surf, pile, (_scale2(x), _scale2(yy)), SS)


# ---------------------------------------------------------------------------
# theme gradients
# ---------------------------------------------------------------------------

def _theme_gradient(theme: str) -> tuple[RGB, RGB]:
    return {
        C.StageTheme.COUNTRYSIDE: ((17, 30, 21), (22, 38, 25)),
        C.StageTheme.CITY: ((10, 12, 20), (15, 17, 28)),
        C.StageTheme.OCEAN: ((9, 24, 44), (13, 33, 58)),
        C.StageTheme.RUINS: ((28, 24, 20), (34, 29, 23)),
        C.StageTheme.WASTELAND: ((36, 19, 15), (44, 25, 17)),
        C.StageTheme.FOREST: ((11, 21, 13), (15, 28, 17)),
        C.StageTheme.CANYON: ((46, 31, 21), (56, 39, 25)),
        C.StageTheme.FARMLAND: ((15, 27, 18), (19, 33, 21)),
        C.StageTheme.AIRBASE: ((21, 24, 22), (27, 30, 27)),
        C.StageTheme.SWAMP: ((12, 22, 18), (17, 29, 22)),
        C.StageTheme.GLACIER: ((28, 40, 54), (38, 52, 68)),
        C.StageTheme.VOLCANIC: ((24, 16, 15), (42, 23, 18)),
        C.StageTheme.INDUSTRIAL: ((18, 20, 24), (25, 27, 32)),
    }[C.StageTheme(theme)]


# ---------------------------------------------------------------------------
# theme painters: (far, near, rng) -> None   (logical coords, 2x surfaces)
# ---------------------------------------------------------------------------

def _paint_countryside(far: Any, near: Any, rng: random.Random) -> None:
    sh = _shadow_sheet()
    # distant treeline bands
    for _ in range(14):
        _tree_cluster(far, rng.uniform(20, C.LOGICAL_W - 20),
                      rng.uniform(0, TILE_H), rng.uniform(9, 20), rng,
                      (13, 24, 15), (17, 31, 18), (21, 37, 21))
    # patchwork fields: organic outlines, crop rows, hedges
    for _ in range(9):
        w, h = rng.uniform(110, 260), rng.uniform(60, 150)
        x = rng.uniform(-30, C.LOGICAL_W - w + 30)
        y = rng.uniform(0, TILE_H - 40)
        col = rng.choice([(22, 40, 22), (28, 46, 26), (24, 36, 20),
                          (30, 44, 22)])
        _plot(near, x, y, w, h, col, (16, 30, 17),
              _blend(col, (0, 0, 0), 0.18), rng)
        # soil gaps / plough patches inside the plot
        _wear(near, x + 8, y + 8, w - 16, h - 16,
              _blend(col, (10, 6, 2), 0.25), rng, int(w * h / 2600))
    # near tree clumps overlapping fields, each casting a soft shadow
    for _ in range(12):
        tx, ty = rng.uniform(10, C.LOGICAL_W - 10), rng.uniform(0, TILE_H)
        tr = rng.uniform(6, 14)
        _sh_ell(sh, tx + tr * 0.75, ty + tr * 0.55, tr * 0.95, tr * 0.55, 28)
        _tree_cluster(near, tx, ty, tr, rng,
                      (16, 31, 18), (23, 41, 23), (30, 50, 28))
    # winding road with bridges + farm compounds
    vx = rng.uniform(120, 660)
    _road_v(near, vx, 9, (26, 26, 30), (48, 48, 54), rng)
    _wear(near, vx + 1, 0, 7, TILE_H, (21, 21, 25), rng, 26)
    for _ in range(2):
        fx, fy = rng.uniform(30, C.LOGICAL_W - 70), rng.uniform(0, TILE_H - 20)
        _sh_rect(sh, fx, fy, 30, 12, 3, 4, 50)
        _farm(near, fx, fy, rng, (34, 26, 22), (44, 30, 26))
    # pond with shore foam and shadowed bank
    px, py = rng.uniform(80, 700), rng.uniform(80, TILE_H - 80)
    _islet(near, px, py, rng.uniform(10, 20), rng,
           (18, 34, 44), (14, 26, 20), (18, 32, 22))
    # river (drawn last: crosses fields), banks + current + bridges
    rx = rng.uniform(200, 600)
    amp = rng.uniform(30, 70)
    _river(near, rx, amp, (24, 48, 66), 11)
    for _ in range(14):
        cy = rng.uniform(0, TILE_H)
        cx = _river_x(cy, rx, amp)
        _block(near, cx - 4, cy, rng.uniform(3, 7), SS, (34, 60, 82))
    for _ in range(2):
        _bridge(near, rx, amp, rng.uniform(60, TILE_H - 60), 11,
                (40, 38, 36), (18, 20, 22))
    # reed/fence specks along the river banks
    for _ in range(60):
        ry = rng.uniform(0, TILE_H)
        bx = _river_x(ry, rx, amp) + rng.uniform(-21, 21)
        _specks(near, bx - 1, ry, 2, 2, (20, 34, 22), rng, 2)
    # bomb-scars: Raiden's signature craters, dim warm cracks inside
    for _ in range(2):
        _crater(near, rng.uniform(60, C.LOGICAL_W - 60),
                rng.uniform(30, TILE_H - 30), rng.uniform(9, 15), rng,
                (14, 13, 11), (92, 38, 14))
    near.blit(sh, (0, 0))


def _paint_city(far: Any, near: Any, rng: random.Random) -> None:
    sh = _shadow_sheet()
    # elevated rail / canal silhouette on the far layer
    rx = rng.uniform(120, 680)
    _block(far, rx - 16, 0, 32, TILE_H, (18, 20, 30))
    for yy in range(0, TILE_H, 90):
        for yy2 in _ys(yy, 8):
            _block(far, rx - 22, yy2, 44, 8, (14, 16, 24))
    # dense city blocks with sidewalk, roof detail + lit windows
    for _ in range(16):
        w, h = rng.uniform(70, 170), rng.uniform(50, 130)
        x = rng.uniform(-20, C.LOGICAL_W - w + 20)
        y = rng.uniform(0, TILE_H - h - 2)
        body = rng.choice([(19, 21, 32), (22, 23, 33), (17, 19, 29)])
        # sidewalk band, then the block casts a soft shadow down-right
        _block(near, x - 2.5, y - 2.5, w + 5, h + 5,
               _blend(body, (255, 255, 255), 0.10))
        _sh_rect(sh, x, y, w, h, w * 0.10 + 3, h * 0.12 + 3, 55)
        _block(near, x, y, w, h, body, (27, 29, 41))
        # sunlit roof lip on top/left, shade plate inside + rooftop units
        _block(near, x, y, w, SS, _blend(body, (255, 255, 255), 0.16))
        _block(near, x + 4, y + 4, w - 8, h - 8,
               _blend(body, (255, 255, 255), 0.05))
        for _ in range(int(w * h / 1400)):
            ux = x + rng.uniform(6, w - 10)
            uy = y + rng.uniform(6, h - 10)
            _block(near, ux, uy, rng.uniform(2, 4), rng.uniform(2, 4),
                   _blend(body, (255, 255, 255), 0.14))
        for _ in range(int(w * h / 2200)):
            wx = x + rng.uniform(4, w - 8)
            wy = y + rng.uniform(4, h - 8)
            lit = rng.choice([(120, 112, 74), (96, 108, 120)])
            _block(near, wx, wy, 3, 3, lit)
    # sawtooth factory + smokestacks
    fx, fy = rng.uniform(0, C.LOGICAL_W - 200), rng.uniform(0, TILE_H - 120)
    _sh_rect(sh, fx, fy, 176, 70, 12, 14, 55)
    _block(near, fx, fy, 150, 70, (21, 23, 34), (29, 31, 43))
    import pygame
    for k in range(0, 150, 15):
        pygame.draw.polygon(near, (26, 28, 40),
                            [(_scale2(fx + k), _scale2(fy)),
                             (_scale2(fx + k + 7), _scale2(fy)),
                             (_scale2(fx + k + 7), _scale2(fy - 9))])
    for sx in (fx + 160, fx + 172):
        _block(near, sx, fy + 10, 5, 26, (24, 26, 36))
    # road network with gutter curbs, lane dashes, wear patches
    vx = rng.uniform(160, 640)
    _block(near, vx - 1.5, 0, 37, TILE_H, (33, 35, 45))     # curb band
    _road_v(near, vx, 34, (26, 28, 38), (58, 60, 72), rng)
    _wear(near, vx + 2, 0, 30, TILE_H, (22, 24, 33), rng, 40)
    hy = rng.uniform(120, TILE_H - 160)
    for yy0 in _ys(hy - 1.5, 29):
        _block(near, 0, yy0, C.LOGICAL_W, 29, (33, 35, 45))
    _road_h(near, hy, 26, (26, 28, 38), (58, 60, 72), rng)
    _wear(near, 0, hy + 2, C.LOGICAL_W, 22, (22, 24, 33), rng, 34)
    # crosswalks at the intersection
    for k in range(0, 34, 6):
        _block(near, vx + k, hy - 8, 3, 26, (52, 54, 66))
    # parking lot rows of cars
    cx, cy = rng.uniform(0, C.LOGICAL_W - 90), rng.uniform(0, TILE_H - 50)
    _block(near, cx, cy, 80, 40, (20, 22, 30), (25, 27, 36))
    for r_ in range(4):
        for c_ in range(8):
            if rng.random() < 0.6:
                ccx, ccy = cx + 4 + c_ * 9, cy + 4 + r_ * 9
                _sh_rect(sh, ccx, ccy, 5, 3, 1.5, 1.5, 40)
                _block(near, ccx, ccy, 5, 3,
                       rng.choice([(30, 32, 42), (36, 30, 30), (28, 34, 36)]))
    for _ in range(3):
        _crater(near, rng.uniform(40, C.LOGICAL_W - 40),
                rng.uniform(20, TILE_H - 20), rng.uniform(8, 14), rng,
                (12, 12, 15), (88, 40, 20))
    near.blit(sh, (0, 0))


def _paint_ocean(far: Any, near: Any, rng: random.Random) -> None:
    sh = _shadow_sheet()
    # swell bands on the deep-water layer
    for _ in range(6):
        _block(far, 0, rng.uniform(0, TILE_H), C.LOGICAL_W,
               rng.uniform(4, 9), (17, 40, 66))
    # islets: reef ring, broken surf line, shadowed land
    for _ in range(4):
        x, y = rng.uniform(80, C.LOGICAL_W - 80), rng.uniform(0, TILE_H)
        r = rng.uniform(24, 46)
        _blob(far, x, y, r + 10, (14, 36, 44), rng, 8)
        _foam_edge(far, x, y, r + 4, (44, 78, 116), rng)
        _sh_ell(sh, x + r * 0.22, y + r * 0.25, r, r * 0.9, 30)
        _islet(far, x, y, r, rng, (32, 46, 36), (15, 32, 24), (20, 38, 27))
    # wave streaks + crests + foam caps (denser than before)
    for _ in range(70):
        x, y = rng.uniform(0, C.LOGICAL_W - 70), rng.uniform(0, TILE_H)
        ln = rng.uniform(26, 64)
        for yy in _ys(y, 2):
            _block(near, x, yy, ln, 2, (24, 50, 86))
        if rng.random() < 0.35:
            _block(near, x + ln - 9, y - 1, 9, 2, (58, 94, 140))
    for _ in range(22):
        _crest(near, rng.uniform(10, C.LOGICAL_W - 70),
               rng.uniform(0, TILE_H), rng.uniform(18, 40), (50, 82, 122), rng)
    # sandbars under the surface
    for _ in range(3):
        bx, by = rng.uniform(60, 700), rng.uniform(0, TILE_H)
        _blob(near, bx, by, rng.uniform(18, 34), (24, 44, 62), rng, 5)
    # harbor corner: pier + moored ship + oil platforms + cargo
    _pier(near, rng.uniform(60, 740), 0, rng.uniform(70, 130),
          (42, 34, 26), (24, 20, 16))
    sx0, sy0 = rng.uniform(120, 660), rng.uniform(80, TILE_H - 60)
    sln = rng.uniform(40, 60)
    _sh_ell(sh, sx0 + 4, sy0 + 5, sln * 0.55, 5, 36)
    _ship(near, sx0, sy0, sln, (28, 32, 40), (40, 62, 92))
    for _ in range(2):
        px2, py2 = rng.uniform(60, 720), rng.uniform(40, TILE_H - 80)
        ps = rng.uniform(22, 34)
        _sh_ell(sh, px2 + ps * 0.3, py2 + ps * 0.5, ps * 0.7, ps * 0.35, 40)
        _platform(near, px2, py2, ps, (36, 36, 42), (22, 24, 30))
        _wear(near, px2 - ps / 2, py2, ps, ps * 0.7, (30, 30, 36), rng, 4)
    # whitecap specks
    for _ in range(150):
        x, y = rng.uniform(0, C.LOGICAL_W - 2), rng.uniform(0, TILE_H - 2)
        _specks(near, x, y, 2, 2, (40, 66, 102), rng, 1, size=1.0)
    near.blit(sh, (0, 0))


def _paint_ruins(far: Any, near: Any, rng: random.Random) -> None:
    import pygame
    # broken towers with jagged crowns and fallen segments
    sh = _shadow_sheet()
    for _ in range(6):
        x = rng.uniform(20, C.LOGICAL_W - 60)
        w = rng.uniform(26, 52)
        h = rng.uniform(90, 200)
        y = rng.uniform(0, TILE_H - 60)
        _sh_rect(sh, x, y, w, h, w * 0.14, 6, 50)
        _block(far, x, y, w, h, (38, 32, 26))
        # lit left face / shaded right face
        _block(far, x, y, w * 0.3, h, (42, 36, 29))
        _block(far, x + w * 0.7, y, w * 0.3, h, (32, 27, 22))
        for j in range(3):                       # chipped crown
            pygame.draw.polygon(far, (28, 24, 20),
                                [(_scale2(x + j * w / 3), _scale2(y)),
                                 (_scale2(x + (j + 1) * w / 3), _scale2(y)),
                                 (_scale2(x + (j + 0.5) * w / 3),
                                  _scale2(y + 12))])
        # debris trail spilling from the broken side
        dx = x + (w if rng.random() < 0.5 else 0)
        for _ in range(10):
            bx = dx + rng.uniform(-14, 14)
            by = y + rng.uniform(h * 0.6, h + 40)
            _specks(near, bx, by, 6, 6, (40, 34, 27), rng, 3, size=1.6)
    # wall fragments with exposed floor slabs
    for _ in range(11):
        x = rng.uniform(0, C.LOGICAL_W - 120)
        y = rng.uniform(0, TILE_H - 40)
        w, h = rng.uniform(50, 120), rng.uniform(10, 22)
        _sh_rect(sh, x, y, w, h, 4, 5, 48)
        _block(near, x, y, w, h, (46, 40, 32), (34, 29, 23))
        _block(near, x + 6, y + 3, w - 12, h - 6,
               _blend((46, 40, 32), (0, 0, 0), 0.22))   # slab interior
        for _ in range(2):                       # cracks in the concrete
            _crack(near, x + rng.uniform(8, w - 12), y + 3,
                   rng.uniform(8, h - 4), (38, 33, 26), rng, wide=1)
    # collapsed road stub with guardrail
    rx = rng.uniform(100, 700)
    _block(near, rx, rng.uniform(100, 400), 30, rng.uniform(120, 220),
           (30, 27, 24))
    for yy in range(0, TILE_H, 26):
        for yy2 in _ys(yy, 2):
            _block(near, rx - 3, yy2, 2, 2, (52, 48, 42))
            _block(near, rx + 31, yy2, 2, 2, (52, 48, 42))
    # rubble scatter + scorch
    for _ in range(90):
        bx = rng.uniform(0, C.LOGICAL_W - 6)
        by = rng.uniform(0, TILE_H - 6)
        _specks(near, bx, by, 5, 5, (40, 34, 27), rng, 2)
    for _ in range(5):
        _blob(near, rng.uniform(60, 740), rng.uniform(0, TILE_H),
              rng.uniform(12, 26), (24, 20, 17), rng, 6)
    for _ in range(3):
        _crater(near, rng.uniform(50, C.LOGICAL_W - 50),
                rng.uniform(20, TILE_H - 20), rng.uniform(9, 15), rng,
                (15, 13, 11), (95, 42, 15))
    near.blit(sh, (0, 0))


def _paint_wasteland(far: Any, near: Any, rng: random.Random) -> None:
    import pygame
    sh = _shadow_sheet()
    # mesas: strata bands, sunlit/shaded faces, grounded shadow
    for _ in range(5):
        x = rng.uniform(60, C.LOGICAL_W - 140)
        w = rng.uniform(90, 200)
        h = rng.uniform(40, 90)
        y = rng.uniform(0, TILE_H - h)
        pts = [(x, y + h), (x + w * 0.18, y), (x + w * 0.82, y), (x + w, y + h)]
        for dy in _dy_offs(y, h):
            p2 = [(int(px * SS), int((py + dy / SS) * SS))
                  for px, py in pts]
            pygame.draw.polygon(far, (46, 26, 18), p2)
            shade = [(x + w * 0.62, y + h * 0.3), (x + w * 0.82, y),
                     (x + w, y + h), (x + w * 0.7, y + h)]
            p3 = [(int(px * SS), int((py + dy / SS) * SS))
                  for px, py in shade]
            pygame.draw.polygon(far, (38, 22, 15), p3)
        band = (52, 30, 20)
        for k in range(1, 4):
            yy = y + h * k / 4
            for dy in _dy_offs(y, h):
                pygame.draw.line(far, band,
                                 (_scale2(x + w * 0.2),
                                  _scale2(yy + dy / SS)),
                                 (_scale2(x + w * 0.8),
                                  _scale2(yy + dy / SS)), SS)
        _sh_ell(sh, x + w * 0.62, y + h * 1.05, w * 0.52, h * 0.2, 46)
    # dry riverbed meander (lighter dust band, tile-periodic)
    rx = rng.uniform(200, 600)
    amp = rng.uniform(40, 80)
    for step in range(0, TILE2, SS * 2):
        y1 = step / SS
        x = _river_x(y1, rx, amp)
        pygame.draw.circle(near, (48, 32, 22), (_scale2(x), step),
                           _scale2(7))
        pygame.draw.circle(near, (54, 38, 26), (_scale2(x), step),
                           _scale2(4))
    # scorched cracks (some faintly warm)
    for _ in range(12):
        warm = rng.random() < 0.3
        _crack(near, rng.uniform(20, C.LOGICAL_W - 20),
               rng.uniform(0, TILE_H - 120), rng.uniform(90, 170),
               (60, 26, 12) if warm else (20, 10, 8), rng)
    # wind-blown dust streaks across the flats
    for _ in range(9):
        dx0, dy0 = rng.uniform(0, C.LOGICAL_W - 130), rng.uniform(0, TILE_H)
        for k in range(3):
            _block(near, dx0, dy0 + k * 3.5, rng.uniform(60, 130), SS,
                   (49, 33, 23))
    # rock clusters + oil derricks
    for _ in range(26):
        x, y = rng.uniform(20, C.LOGICAL_W - 20), rng.uniform(0, TILE_H)
        br = rng.uniform(5, 12)
        _sh_ell(sh, x + br * 0.55, y + br * 0.45, br * 0.95, br * 0.5, 42)
        _blob(near, x, y, br, (56, 34, 22), rng, 4)
        if rng.random() < 0.4:
            _blob(near, x + 3, y + 2, rng.uniform(2, 4),
                  (62, 40, 26), rng, 3)
    for _ in range(3):
        ox, oy = rng.uniform(60, 720), rng.uniform(40, TILE_H - 60)
        s = rng.uniform(14, 22)
        _sh_ell(sh, ox + s * 0.3, oy + s * 1.1, s * 0.7, s * 0.25, 46)
        pygame.draw.polygon(near, (30, 18, 14),
                            [(_scale2(ox - s / 2), _scale2(oy + s)),
                             (_scale2(ox + s / 2), _scale2(oy + s)),
                             (_scale2(ox), _scale2(oy - s * 0.4))])
        pygame.draw.polygon(near, (38, 24, 17),
                            [(_scale2(ox - s / 2), _scale2(oy + s)),
                             (_scale2(ox), _scale2(oy + s)),
                             (_scale2(ox), _scale2(oy - s * 0.4))])
        pygame.draw.line(near, (30, 18, 14),
                         (_scale2(ox - s / 2), _scale2(oy + s)),
                         (_scale2(ox + s / 2), _scale2(oy + s)), SS * 2)
    for _ in range(4):
        _crater(near, rng.uniform(40, C.LOGICAL_W - 40),
                rng.uniform(20, TILE_H - 20), rng.uniform(9, 16), rng,
                (16, 12, 10), (105, 45, 15))
    near.blit(sh, (0, 0))


# ---------------------------------------------------------------------------
# shared Raiden motifs: craters, canopy, pines, buried hatches, dune ripples
# ---------------------------------------------------------------------------

def _crater(surf: Any, x: float, y: float, r: float, rng: random.Random,
            dark: RGB, warm: RGB) -> None:
    """Raiden's signature bomb-scar: rough dark bowl, speckled rim with a
    sunlit top-left lip, dim glowing cracks inside, ejecta specks."""
    import pygame
    _blob(surf, x, y, r * 0.9, dark, rng, 8)
    for _ in range(max(10, int(r * 1.8))):          # rim ring
        a = rng.uniform(0, math.tau)
        rr = r * rng.uniform(0.82, 1.05)
        bx, by = x + math.cos(a) * rr, y + math.sin(a) * rr * 0.95
        rimc = (_blend(dark, (255, 244, 214), 0.10) if math.pi < a < 2 * math.pi
                else _blend(dark, (255, 255, 255), 0.04))
        for yy in _ys(by, 2):
            pygame.draw.circle(surf, rimc, (_scale2(bx), _scale2(yy)),
                               max(SS, _scale2(rng.uniform(0.7, 1.5))))
    for _ in range(3):                              # inner glow cracks
        _crack(surf, x + rng.uniform(-r * 0.25, r * 0.25),
               y + rng.uniform(-r * 0.2, r * 0.2), r * rng.uniform(0.7, 1.4),
               warm, rng, wide=1)
    for _ in range(int(r)):                         # ejecta specks
        a = rng.uniform(0, math.tau)
        rr = r * rng.uniform(1.1, 1.6)
        _specks(surf, x + math.cos(a) * rr, y + math.sin(a) * rr, 2, 2,
                _blend(dark, (255, 255, 255), 0.07), rng, 1, size=1.2)


def _canopy(surf: Any, x: float, y: float, r: float, rng: random.Random,
            dark: RGB, mid: RGB, lite: RGB) -> None:
    """Lumpy treetop seen from above: mid blob, sunlit crown, dark skirt."""
    import pygame
    _blob(surf, x, y, r, mid, rng, 7)
    _blob(surf, x - r * 0.15, y - r * 0.18, r * 0.62, lite, rng, 5)
    _specks(surf, x - r * 0.9, y - r * 0.9, r * 1.3, r * 1.1, dark, rng,
            int(r * 0.8), size=1.4)
    k = max(6, int(r * 1.2))                        # leaf-edge dots
    for _ in range(k):
        a = rng.uniform(0, math.tau)
        rr = r * rng.uniform(0.85, 1.02)
        bx, by = x + math.cos(a) * rr, y + math.sin(a) * rr
        for yy in _ys(by, 2):
            pygame.draw.circle(surf, dark, (_scale2(bx), _scale2(yy)),
                               max(SS, _scale2(rng.uniform(0.6, 1.3))))


def _pine(surf: Any, x: float, y: float, r: float, rng: random.Random,
          col: RGB, dark: RGB) -> None:
    """Conifer star (top-down): 8 radial spikes around a dark core."""
    import pygame
    for k in range(8):
        a = k * math.tau / 8 + rng.uniform(-0.14, 0.14)
        x1, y1 = x + math.cos(a - 0.28) * r * 0.35, y + math.sin(a - 0.28) * r * 0.35
        x2, y2 = x + math.cos(a + 0.28) * r * 0.35, y + math.sin(a + 0.28) * r * 0.35
        for dy in _dy_offs(y, r * 2):
            p2 = [(int(px * SS), int((py + dy / SS) * SS)) for px, py in
                  [(x1, y1), (x + math.cos(a) * r, y + math.sin(a) * r), (x2, y2)]]
            pygame.draw.polygon(surf, col, p2)
    _blob(surf, x, y, r * 0.28, dark, rng, 3)


def _hatch_buried(surf: Any, x: float, y: float, r: float, rng: random.Random,
                  metal: RGB, sand: RGB) -> None:
    """Circular metal hatch half-buried in sand (Raiden stage-3/5 motif)."""
    import pygame
    for dy in _ys(y - r, r * 2):
        yy = dy
        pygame.draw.circle(surf, _blend(metal, (0, 0, 0), 0.35),
                           (_scale2(x), _scale2(yy + 1)), _scale2(r + 1))
        pygame.draw.circle(surf, metal, (_scale2(x), _scale2(yy)), _scale2(r))
        pygame.draw.circle(surf, _blend(metal, (0, 0, 0), 0.3),
                           (_scale2(x), _scale2(yy)), _scale2(r * 0.72), SS)
    for k in range(6):                              # bolts
        a = k * math.tau / 6
        bx, by = x + math.cos(a) * r * 0.85, y + math.sin(a) * r * 0.85
        for yy in _ys(by, 2):
            pygame.draw.circle(surf, _blend(metal, (255, 255, 255), 0.18),
                               (_scale2(bx), _scale2(yy)), SS)
    # sand creep over the lower-right lip
    _blob(surf, x + r * 0.6, y + r * 0.5, r * 0.5, sand, rng, 4)


def _ripple(surf: Any, x: float, y: float, ln: float, col: RGB) -> None:
    """Dune ripple: two stacked shallow arcs."""
    import pygame
    for dy in _dy_offs(y, 4):
        pts = [(x, y), (x + ln * 0.5, y - 2.5), (x + ln, y)]
        p2 = [(int(px * SS), int((py + dy / SS) * SS)) for px, py in pts]
        pygame.draw.lines(surf, col, False, p2, SS)


# ---------------------------------------------------------------------------
# new theme painters
# ---------------------------------------------------------------------------

def _paint_forest(far: Any, near: Any, rng: random.Random) -> None:
    import pygame
    sh = _shadow_sheet()
    # distant canopy bands on the far layer
    for _ in range(34):
        _blob(far, rng.uniform(0, C.LOGICAL_W), rng.uniform(0, TILE_H),
              rng.uniform(14, 34), rng.choice([(13, 24, 15), (16, 29, 18),
                                               (19, 34, 20)]), rng, 6)
    # mossy clearings (lighter glades with fern specks)
    for _ in range(4):
        gx, gy = rng.uniform(40, C.LOGICAL_W - 40), rng.uniform(0, TILE_H)
        gr = rng.uniform(26, 48)
        _blob(near, gx, gy, gr, (18, 34, 20), rng, 6)
        _specks(near, gx - gr, gy - gr, gr * 2, gr * 2, (24, 42, 24), rng,
                int(gr * 1.2), size=1.3)
    # winding creek with stone banks (no bridges: wilderness)
    rx = rng.uniform(160, 640)
    amp = rng.uniform(24, 52)
    _river(near, rx, amp, (20, 42, 58), 7)
    for _ in range(16):
        sy = rng.uniform(0, TILE_H)
        sx = _river_x(sy, rx, amp) + rng.uniform(-13, 13)
        _sh_ell(sh, sx + 2, sy + 2, 3, 2, 30)
        _blob(near, sx, sy, rng.uniform(1.6, 3.4), (40, 42, 44), rng, 3)
    # dirt trail (hunting road)
    tx = rng.uniform(80, 700)
    _river(near, tx, rng.uniform(30, 60), (42, 34, 24), 5)
    # fallen logs
    for _ in range(3):
        lx, ly = rng.uniform(30, C.LOGICAL_W - 90), rng.uniform(0, TILE_H)
        ll = rng.uniform(26, 56)
        _sh_rect(sh, lx, ly, ll, 4, 2, 3, 34)
        _block(near, lx, ly, ll, 4, (46, 34, 24), (30, 22, 16))
        _specks(near, lx, ly, ll, 4, (36, 27, 19), rng, 6, size=1.2)
    # dense canopy clusters + conifer stars, each shadowed
    for _ in range(24):
        tx2, ty = rng.uniform(10, C.LOGICAL_W - 10), rng.uniform(0, TILE_H)
        tr = rng.uniform(8, 18)
        _sh_ell(sh, tx2 + tr * 0.65, ty + tr * 0.5, tr * 0.95, tr * 0.55, 36)
        _canopy(near, tx2, ty, tr, rng, (10, 19, 12), (16, 31, 17),
                (24, 43, 23))
    for _ in range(16):
        px, py = rng.uniform(10, C.LOGICAL_W - 10), rng.uniform(0, TILE_H)
        pr = rng.uniform(5, 10)
        _sh_ell(sh, px + pr * 0.5, py + pr * 0.4, pr * 0.8, pr * 0.45, 30)
        _pine(near, px, py, pr, rng,
              rng.choice([(14, 27, 15), (18, 32, 18)]), (9, 17, 10))
    # crash-scar craters
    for _ in range(2):
        _crater(near, rng.uniform(60, C.LOGICAL_W - 60),
                rng.uniform(30, TILE_H - 30), rng.uniform(8, 13), rng,
                (12, 12, 10), (85, 36, 12))
    # fog ribbons
    for _ in range(6):
        fx, fy = rng.uniform(0, C.LOGICAL_W - 220), rng.uniform(0, TILE_H)
        for yy in _ys(fy, 7):
            pygame.draw.rect(near, (160, 190, 205, 7),
                             (_scale2(fx), _scale2(yy), _scale2(rng.uniform(120, 240)), _scale2(7)))
    near.blit(sh, (0, 0))


def _paint_canyon(far: Any, near: Any, rng: random.Random) -> None:
    import pygame
    sh = _shadow_sheet()
    # distant mesas on the far layer
    for _ in range(4):
        x = rng.uniform(40, C.LOGICAL_W - 160)
        w, h = rng.uniform(80, 170), rng.uniform(30, 60)
        y = rng.uniform(0, TILE_H - h)
        pts = [(x, y + h), (x + w * 0.12, y), (x + w * 0.88, y), (x + w, y + h)]
        for dy in _dy_offs(y, h):
            p2 = [(int(px * SS), int((py + dy / SS) * SS)) for px, py in pts]
            pygame.draw.polygon(far, (52, 36, 24), p2)
    # sinuous cliff seam with rubble along it (y-periodic: wrap-safe)
    sx0 = rng.uniform(160, 640)
    samp = []
    for step in range(0, TILE2, SS * 3):
        yy1 = step / SS
        x = sx0 + 50 * math.sin(2 * math.pi * 2 * yy1 / TILE_H)
        samp.append((x, yy1))
    for i in range(len(samp) - 1):
        x1, y1 = samp[i]
        x2, y2 = samp[i + 1]
        pygame.draw.line(near, (30, 20, 14), (_scale2(x1), y1),
                         (_scale2(x2), y2), 2 * SS)
        pygame.draw.line(near, (66, 48, 32), (_scale2(x1 + 2.5), y1),
                         (_scale2(x2 + 2.5), y2), SS)
    for _ in range(34):                             # seam rubble + shadows
        yy1 = rng.uniform(0, TILE_H)
        x = sx0 + 50 * math.sin(2 * math.pi * 2 * yy1 / TILE_H)
        bx = x + rng.uniform(-14, 14)
        br = rng.uniform(1.6, 3.6)
        _sh_ell(sh, bx + 1.5, yy1 + 1.5, br, br * 0.6, 34)
        _blob(near, bx, yy1, br, (60, 44, 30), rng, 3)
    # squat buttes with strata + chunky offset shadows (stage-4 slab feel)
    for _ in range(5):
        x = rng.uniform(30, C.LOGICAL_W - 140)
        w, h = rng.uniform(60, 140), rng.uniform(26, 60)
        y = rng.uniform(0, TILE_H - h)
        body = rng.choice([(58, 41, 27), (64, 46, 30), (52, 37, 25)])
        _sh_rect(sh, x, y, w, h, w * 0.16 + 4, h * 0.24 + 4, 58)
        _block(near, x, y, w, h, body)
        _block(near, x, y, w, SS, _blend(body, (255, 255, 255), 0.14))
        for k in (1, 2, 3):                         # strata bands
            _block(near, x + 2, y + h * k / 4, w - 4, SS,
                   _blend(body, (0, 0, 0), 0.22))
        _wear(near, x + 3, y + 3, w - 6, h - 6, _blend(body, (0, 0, 0), 0.12),
              rng, int(w * h / 900))
    # dry riverbed (pale dust band, tile-periodic)
    rx = rng.uniform(200, 600)
    amp = rng.uniform(40, 80)
    for step in range(0, TILE2, SS * 2):
        yy1 = step / SS
        x = _river_x(yy1, rx, amp)
        pygame.draw.circle(near, (62, 48, 32), (_scale2(x), step), _scale2(6))
        pygame.draw.circle(near, (70, 55, 38), (_scale2(x), step), _scale2(3))
    # dune ripples + dry cracks + boulders
    for _ in range(30):
        _ripple(near, rng.uniform(0, C.LOGICAL_W - 40),
                rng.uniform(0, TILE_H), rng.uniform(16, 34), (64, 47, 30))
    for _ in range(10):
        _crack(near, rng.uniform(20, C.LOGICAL_W - 20),
               rng.uniform(0, TILE_H - 100), rng.uniform(50, 110),
               (34, 23, 15), rng)
    for _ in range(20):
        x, y = rng.uniform(20, C.LOGICAL_W - 20), rng.uniform(0, TILE_H)
        br = rng.uniform(3, 8)
        _sh_ell(sh, x + br * 0.5, y + br * 0.4, br, br * 0.55, 38)
        _blob(near, x, y, br, (60, 46, 32), rng, 4)
        _blob(near, x - br * 0.2, y - br * 0.25, br * 0.55, (68, 53, 38),
              rng, 3)
    # buried metal hatches
    for _ in range(2):
        hx, hy = rng.uniform(80, C.LOGICAL_W - 80), rng.uniform(40, TILE_H - 40)
        hr = rng.uniform(12, 20)
        _sh_ell(sh, hx + 3, hy + 3, hr, hr * 0.8, 40)
        _hatch_buried(near, hx, hy, hr, rng, (56, 52, 44), (58, 46, 30))
    # fresh bomb-scar craters
    for _ in range(4):
        _crater(near, rng.uniform(40, C.LOGICAL_W - 40),
                rng.uniform(20, TILE_H - 20), rng.uniform(9, 16), rng,
                (18, 14, 11), (110, 48, 16))
    near.blit(sh, (0, 0))


# ---------------------------------------------------------------------------
# composite helpers for the farmland + airbase themes
# ---------------------------------------------------------------------------

def _paddy(surf: Any, x: float, y: float, w: float, h: float,
           water: RGB, levee: RGB, crop: RGB, rng: random.Random) -> None:
    """Flooded paddy: levee-framed water cell with bright meniscus + crop
    rows. Vertical seams are handled by `_ys` so plots wrap cleanly."""
    import pygame
    # levee (soil) frame, then the water inset inside it
    _block(surf, x, y, w, h, levee)
    for yy in _ys(y + 1.5, h - 3):
        pygame.draw.rect(surf, water,
                         (_scale2(x + 1.5), _scale2(yy),
                          _scale2(w - 3), _scale2(h - 3)))
    # standing-water glints: short horizontal streaks, low count
    for _ in range(int(w * h / 240)):
        sx2 = x + rng.uniform(2.5, w - 6)
        sy2 = y + rng.uniform(2.5, h - 5)
        for yy in _ys(sy2, 1):
            pygame.draw.line(surf, _blend(water, (255, 255, 255), 0.14),
                             (_scale2(sx2), _scale2(yy)),
                             (_scale2(sx2 + rng.uniform(2, 5)), _scale2(yy)),
                             SS)
    # rice rows: evenly spaced darker verticals (young shoots)
    for rx in range(int(x) + 2, int(x + w) - 1, 3):
        for yy in _ys(y + 2, h - 4):
            pygame.draw.line(surf, crop, (_scale2(rx), _scale2(yy)),
                             (_scale2(rx), _scale2(yy + h - 4)), SS)


def _crate_stack(surf: Any, x: float, y: float, rng: random.Random,
                 wood: RGB, wood2: RGB) -> None:
    """Supply crates in a tight stack — Raiden stage-1 props."""
    import pygame
    for k in range(3):
        cx2, cy2 = x + (k % 2) * 11, y + (k // 2) * 9
        col = wood if k % 2 == 0 else wood2
        for yy in _ys(cy2, 9):
            pygame.draw.rect(surf, col, (_scale2(cx2), _scale2(yy),
                                         _scale2(9), _scale2(9)))
            # plank seam + rim highlight for a hand-painted cube read
            pygame.draw.rect(surf, _blend(col, (0, 0, 0), 0.3),
                             (_scale2(cx2), _scale2(yy), _scale2(9),
                              _scale2(9)), SS)
            pygame.draw.line(surf, _blend(col, (255, 255, 255), 0.12),
                             (_scale2(cx2 + 4.5), _scale2(yy + 1)),
                             (_scale2(cx2 + 4.5), _scale2(yy + 8)), SS)


def _apron(surf: Any, x: float, y: float, w: float, h: float,
           concrete: RGB, rng: random.Random,
           joint: int = 26) -> None:
    """Concrete taxiway slab: expansion-joint grid + oil stains + tire marks."""
    import pygame
    _block(surf, x, y, w, h, concrete)
    # joint grid
    for gx in range(int(x), int(x + w) + 1, joint):
        for yy in _ys(y, h):
            pygame.draw.line(surf, _blend(concrete, (0, 0, 0), 0.3),
                             (_scale2(gx), _scale2(yy)),
                             (_scale2(gx), _scale2(yy + h)), SS)
    for gy in range(int(y), int(y + h) + 1, joint):
        for yy in _ys(gy, 1):
            pygame.draw.line(surf, _blend(concrete, (0, 0, 0), 0.26),
                             (_scale2(x), _scale2(yy)),
                             (_scale2(x + w), _scale2(yy)), SS)
    # sun-bleached patch + oil pooling
    _wear(surf, x + 4, y + 4, w - 8, h - 8,
          _blend(concrete, (255, 255, 255), 0.06), rng, int(w * h / 2600))
    _wear(surf, x + 4, y + 4, w - 8, h - 8,
          _blend(concrete, (0, 0, 0), 0.2), rng, int(w * h / 3200))
    # rubber skid streaks along the scrolling axis
    for _ in range(int(w / 22)):
        sx2 = x + rng.uniform(3, w - 3)
        for yy in _ys(y, h):
            pygame.draw.line(surf, _blend(concrete, (0, 0, 0), 0.16),
                             (_scale2(sx2), _scale2(yy + rng.uniform(0, h * 0.4))),
                             (_scale2(sx2 + rng.uniform(-2, 2)),
                              _scale2(yy + h * rng.uniform(0.6, 1.0))), SS)


def _hangar(surf: Any, x: float, y: float, w: float, h: float,
            body: RGB, roof: RGB) -> None:
    """Quonset hangar: rounded ridge roof with rib lines + end cap."""
    import pygame
    # roof as a rounded-top slab (arch via stacked narrowing bands)
    for k in range(int(h)):
        band = _scale2(y + h - k)
        inset = 0 if k < h * 0.55 else _scale2((k - h * 0.55) * 1.9)
        wpx = _scale2(w) - 2 * inset
        if wpx <= 0:
            break
        shade = _blend(roof, (255, 255, 255), 0.10) if k % 2 else roof
        pygame.draw.rect(surf, shade,
                         (_scale2(x) + inset, band, wpx, SS))
    _block(surf, x, y + h, w, 4, body, _blend(body, (0, 0, 0), 0.3))
    # roof ribs across the ridge
    for rx in range(int(x) + 5, int(x + w), 9):
        for yy in _ys(y + h * 0.2, h * 0.7):
            pygame.draw.line(surf, _blend(roof, (0, 0, 0), 0.22),
                             (_scale2(rx), _scale2(yy)),
                             (_scale2(rx), _scale2(yy + h * 0.7)), SS)


def _jet_static(surf: Any, x: float, y: float, s: float, hull: RGB,
                wing: RGB) -> None:
    """Parked fighter seen top-down: fuselage, swept wings, tail, nose."""
    import pygame
    # wings (swept back triangle pair)
    for yy in _ys(y - s * 0.1, s * 0.5):
        pygame.draw.polygon(surf, wing,
                            [(_scale2(x - s * 0.9), _scale2(yy + s * 0.4)),
                             (_scale2(x + s * 0.9), _scale2(yy + s * 0.4)),
                             (_scale2(x + s * 0.18), _scale2(yy - s * 0.35)),
                             (_scale2(x - s * 0.18), _scale2(yy - s * 0.35))])
    # fuselage
    for yy in _ys(y - s * 0.7, s * 1.5):
        pygame.draw.rect(surf, hull, (_scale2(x - s * 0.12), _scale2(yy),
                                      _scale2(s * 0.24), _scale2(s * 1.4)))
    # nose cone + tail fins
    for yy in _ys(y - s * 0.9, s * 0.3):
        pygame.draw.circle(surf, _blend(hull, (255, 255, 255), 0.15),
                           (_scale2(x), _scale2(yy)), max(SS, _scale2(s * 0.12)))
    pygame.draw.line(surf, wing, (_scale2(x - s * 0.4), _scale2(y + s * 0.55)),
                     (_scale2(x + s * 0.4), _scale2(y + s * 0.55)), SS)


def _fuel_tank(surf: Any, x: float, y: float, r: float, body: RGB) -> None:
    """Fuel-store tank: banded cylinder with round cap + shading crescent."""
    import pygame
    for yy in _ys(y - r, r * 2):
        pygame.draw.circle(surf, body, (_scale2(x), _scale2(yy)), _scale2(r))
    for b in (-r * 0.5, 0.0, r * 0.5):
        for yy in _ys(y + b, r):
            pygame.draw.line(surf, _blend(body, (0, 0, 0), 0.28),
                             (_scale2(x - r * 0.7), _scale2(yy)),
                             (_scale2(x + r * 0.7), _scale2(yy)), SS)
    # lit crescent top-left
    for yy in _ys(y - r * 0.7, r):
        pygame.draw.arc(surf, _blend(body, (255, 255, 255), 0.16),
                        (_scale2(x - r), _scale2(yy), _scale2(r * 2),
                         _scale2(r * 2)), math.pi * 0.5, math.pi, SS)


def _control_tower(surf: Any, x: float, y: float) -> None:
    """ATC tower from above: hex pad, glass cab ring, beacon dot."""
    import pygame
    pts = []
    for i in range(6):
        a = math.tau * i / 6 + 0.3
        pts.append((_scale2(x + math.cos(a) * 9), _scale2(y + math.sin(a) * 9)))
    pygame.draw.polygon(surf, (46, 48, 54), pts)
    pygame.draw.circle(surf, (28, 30, 36), (_scale2(x), _scale2(y)),
                       _scale2(6))
    pygame.draw.circle(surf, (60, 92, 96), (_scale2(x), _scale2(y)),
                       _scale2(4))
    pygame.draw.circle(surf, (150, 200, 210), (_scale2(x), _scale2(y)),
                       max(1, SS))


def _radar_dish(surf: Any, x: float, y: float, rng: random.Random) -> None:
    """Radar scope: dish ring, shadowed underside, strut."""
    import pygame
    r = 8.0
    for yy in _ys(y - r, r * 2):
        pygame.draw.circle(surf, (52, 56, 62), (_scale2(x), _scale2(yy)),
                           _scale2(r))
        pygame.draw.circle(surf, (36, 40, 46), (_scale2(x), _scale2(yy)),
                           _scale2(r), SS)
    # feed arm
    pygame.draw.line(surf, (30, 32, 38), (_scale2(x), _scale2(y)),
                     (_scale2(x + 6), _scale2(y - 6)), SS)
    pygame.draw.circle(surf, (120, 130, 140), (_scale2(x + 6), _scale2(y - 6)),
                       max(1, SS))


def _fence_line(surf: Any, x0: float, y0: float, x1: float, y1: float,
                post: RGB, rng: random.Random) -> None:
    """Perimeter fence: posts + a top wire between two points."""
    import pygame
    n = int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / 12)
    pygame.draw.line(surf, _blend(post, (255, 255, 255), 0.05),
                     (_scale2(x0), _scale2(y0 - 2)),
                     (_scale2(x1), _scale2(y1 - 2)), SS)
    for i in range(n + 1):
        t = i / max(1, n)
        px2, py2 = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        for yy in _ys(py2 - 1.5, 3):
            pygame.draw.rect(surf, post, (_scale2(px2 - 0.7), _scale2(yy),
                                          SS * 2, _scale2(3)))


def _paint_farmland(far: Any, near: Any, rng: random.Random) -> None:
    """Raiden II stage-1: flooded paddy grid, winding track, groves, ponds."""
    sh = _shadow_sheet()
    # distant hedgerow bands on the far parallax layer
    for _ in range(10):
        _tree_cluster(far, rng.uniform(15, C.LOGICAL_W - 15),
                      rng.uniform(0, TILE_H), rng.uniform(10, 22), rng,
                      (12, 23, 14), (16, 30, 18), (20, 37, 22))
    # paddy grid: near-regular fields with flooded cells + levees
    cell = rng.uniform(46, 62)
    for gy in range(-1, int(TILE_H / cell) + 1):
        for gx in range(-1, int(C.LOGICAL_W / cell) + 1):
            if rng.random() < 0.14:
                continue                      # fallow gaps between paddies
            x = gx * cell + rng.uniform(-4, 4)
            y = gy * cell + rng.uniform(-4, 4)
            w = cell - rng.uniform(4, 8)
            h = cell - rng.uniform(4, 8)
            water = rng.choice([(18, 34, 34), (16, 30, 36), (20, 38, 34)])
            _paddy(near, x, y, w, h, water, (30, 32, 22), (26, 48, 28), rng)
    # a winding dirt track threading between the fields
    tx = rng.uniform(160, 640)
    amp = rng.uniform(36, 78)
    _track(near, tx, amp, (58, 50, 36), (74, 64, 46), rng)
    for _ in range(2):
        _track_bridge(near, tx, amp, rng.uniform(60, TILE_H - 60),
                      (48, 42, 32), (26, 22, 18))
    # groves casting long soft shadows (stage-1 tree clumps)
    for _ in range(9):
        gx2, gy2 = rng.uniform(12, C.LOGICAL_W - 12), rng.uniform(0, TILE_H)
        gr = rng.uniform(8, 16)
        _sh_ell(sh, gx2 + gr * 0.7, gy2 + gr * 0.5, gr, gr * 0.6, 30)
        _tree_cluster(near, gx2, gy2, gr, rng,
                      (17, 35, 19), (25, 47, 25), (33, 59, 31))
    # farm ponds with reedy banks
    for _ in range(2):
        px, py = rng.uniform(90, 700), rng.uniform(70, TILE_H - 70)
        _sh_ell(sh, px, py, 20, 14, 22)
        _islet(near, px, py, rng.uniform(11, 18), rng,
               (26, 40, 48), (16, 30, 22), (20, 36, 24))
    # farm compound + supply crates casting shadows
    for _ in range(2):
        bx, by = rng.uniform(40, C.LOGICAL_W - 90), rng.uniform(0, TILE_H - 24)
        _sh_rect(sh, bx, by, 34, 14, 4, 5, 46)
        _farm(near, bx, by, rng, (40, 30, 24), (54, 38, 28))
    for _ in range(3):
        cx2, cy2 = rng.uniform(30, C.LOGICAL_W - 40), rng.uniform(0, TILE_H - 22)
        _sh_rect(sh, cx2, cy2, 20, 18, 4, 4, 44)
        _crate_stack(near, cx2, cy2, rng, (78, 58, 34), (64, 48, 30))
    # short levee fences along the track, then a few quiet bomb scars
    for _ in range(4):
        fx0 = rng.uniform(0, 620)
        fy = rng.uniform(0, TILE_H)
        _fence_line(near, fx0, fy, fx0 + rng.uniform(60, 130),
                    fy + rng.uniform(-8, 8), (34, 37, 30), rng)
    for _ in range(2):
        _crater(near, rng.uniform(50, C.LOGICAL_W - 50),
                rng.uniform(30, TILE_H - 30), rng.uniform(6, 10), rng,
                (14, 14, 11), (52, 24, 12))
    near.blit(sh, (0, 0))


def _track(surf: Any, tx: float, amp: float, dirt: RGB,
           ruts: RGB, rng: random.Random) -> None:
    """Winding dirt track (tile-periodic like _river) with wheel ruts."""
    import pygame
    edge = _blend(dirt, (0, 0, 0), 0.4)
    for step in range(0, TILE2, SS):
        y1 = step / SS
        x = _river_x(y1, tx, amp)
        pygame.draw.circle(surf, edge, (_scale2(x), step), _scale2(11) + SS)
        pygame.draw.circle(surf, dirt, (_scale2(x), step), _scale2(10))
    # twin wheel ruts a little brighter than the dirt
    for side in (-3.2, 3.2):
        for step in range(0, TILE2, SS):
            y1 = step / SS
            x = _river_x(y1, tx, amp) + side
            pygame.draw.circle(surf, ruts, (_scale2(x), step), SS)
    # grass tufts encroaching on the edges
    for _ in range(int(TILE_H / 5)):
        y1 = rng.uniform(0, TILE_H)
        x = _river_x(y1, tx, amp) + rng.uniform(-14, 14)
        _specks(surf, x - 1, y1, 2, 2, (26, 44, 24), rng, 1)


def _track_bridge(surf: Any, tx: float, amp: float, y: float,
                  deck: RGB, rail: RGB) -> None:
    _bridge(surf, tx, amp, y, 10, deck, rail)


def _paint_airbase(far: Any, near: Any, rng: random.Random) -> None:
    """Raiden airbase sector: concrete aprons, hangars, parked jets, fuel
    stores, ATC + radar, perimeter fence and runway lights."""
    sh = _shadow_sheet()
    # distant runway + treeline silhouette on the far layer
    for _ in range(3):
        y = rng.uniform(0, TILE_H)
        _block(far, 0, y, C.LOGICAL_W, rng.uniform(10, 22), (30, 33, 30))
    for _ in range(8):
        _tree_cluster(far, rng.uniform(15, C.LOGICAL_W - 15),
                      rng.uniform(0, TILE_H), rng.uniform(9, 18), rng,
                      (11, 21, 14), (15, 28, 18), (19, 34, 21))
    # grass apron base tone
    for _ in range(int(C.LOGICAL_W * TILE_H / 9000)):
        _wear(near, rng.uniform(0, C.LOGICAL_W - 40),
              rng.uniform(0, TILE_H - 40), 40, 40, (24, 34, 22), rng, 6)
    # main apron slabs (two big concrete pads) + taxiway links
    for _ in range(2):
        w, h = rng.uniform(220, 340), rng.uniform(150, 240)
        x = rng.uniform(-20, C.LOGICAL_W - w + 20)
        y = rng.uniform(0, TILE_H - h)
        _sh_rect(sh, x, y, w, h, 6, 8, 40)
        _apron(near, x, y, w, h, (58, 60, 62), rng)
    # connecting taxiway strip (vertical) with edge lights
    tx = rng.uniform(320, 520)
    _block(near, tx, 0, 44, TILE_H, (54, 56, 58))
    for yy in range(0, TILE_H, 34):
        for yy2 in _ys(yy, 2):
            _block(near, tx + 2, yy2, 2, 2, (70, 72, 74))
            _block(near, tx + 40, yy2, 2, 2, (70, 72, 74))
    # hangar row with shadows + a couple of revetments
    hx = rng.uniform(60, 260)
    for k in range(4):
        x = hx + k * 96
        y = rng.uniform(30, TILE_H - 90)
        _sh_rect(sh, x, y, 84, 34, 10, 8, 52)
        _hangar(near, x, y, 84, 34, (44, 46, 52), (60, 63, 66))
    # parked fighters: one alert scrape in hard rows + stragglers (dim so
    # bullets and enemies still read over them)
    jx0 = rng.uniform(140, 520)
    jy0 = rng.uniform(60, TILE_H - 140)
    for r in range(2):
        for c in range(3):
            jx, jy = jx0 + c * 46, jy0 + r * 40
            js = 13.0
            _sh_ell(sh, jx + js * 0.3, jy + js * 0.3, js * 0.9, js * 0.5, 30)
            _jet_static(near, jx, jy, js, (46, 52, 60), (54, 62, 70))
    for _ in range(3):
        jx, jy = rng.uniform(40, C.LOGICAL_W - 40), rng.uniform(0, TILE_H)
        js = rng.uniform(12, 17)
        _sh_ell(sh, jx + js * 0.3, jy + js * 0.3, js * 0.9, js * 0.5, 30)
        _jet_static(near, jx, jy, js, (46, 52, 60), (54, 62, 70))
    # fuel-storage tank cluster
    fx, fy = rng.uniform(120, 560), rng.uniform(60, TILE_H - 80)
    for k in range(3):
        _sh_ell(sh, fx + 4, fy + k * 26, 11, 8, 34)
        _fuel_tank(near, fx, fy + k * 26, 11, (70, 72, 66))
    # control tower + radar dish
    cx, cy = rng.uniform(120, C.LOGICAL_W - 120), rng.uniform(80, TILE_H - 80)
    _sh_rect(sh, cx - 9, cy - 9, 18, 18, 5, 6, 46)
    _control_tower(near, cx, cy)
    rdx, rdy = rng.uniform(80, C.LOGICAL_W - 80), rng.uniform(40, TILE_H - 40)
    _sh_ell(sh, rdx + 4, rdy + 4, 9, 8, 36)
    _radar_dish(near, rdx, rdy, rng)
    # perimeter fence lines
    for _ in range(3):
        fy = rng.uniform(0, TILE_H)
        _fence_line(near, rng.uniform(0, 200), fy, rng.uniform(400, 799),
                    fy + rng.uniform(-30, 30), (40, 44, 44), rng)
    # fresh bomb-scar craters on the apron (Raiden motif)
    for _ in range(3):
        _crater(near, rng.uniform(40, C.LOGICAL_W - 40),
                rng.uniform(20, TILE_H - 20), rng.uniform(8, 13), rng,
                (16, 15, 13), (64, 30, 14))
    near.blit(sh, (0, 0))


_PAINTERS = {
    C.StageTheme.COUNTRYSIDE: _paint_countryside,
    C.StageTheme.CITY: _paint_city,
    C.StageTheme.OCEAN: _paint_ocean,
    C.StageTheme.RUINS: _paint_ruins,
    C.StageTheme.WASTELAND: _paint_wasteland,
    C.StageTheme.FOREST: _paint_forest,
    C.StageTheme.CANYON: _paint_canyon,
    C.StageTheme.FARMLAND: _paint_farmland,
    C.StageTheme.AIRBASE: _paint_airbase,
    # Sectors 6-9 reuse the closest structural painter when no tileset is
    # shipped: water reads as swamp, ice as sea, obsidian as ash, decking as
    # apron.  The tileset path (compose.py) has bespoke recipes for all four.
    C.StageTheme.SWAMP: _paint_farmland,
    C.StageTheme.GLACIER: _paint_ocean,
    C.StageTheme.VOLCANIC: _paint_wasteland,
    C.StageTheme.INDUSTRIAL: _paint_airbase,
}
