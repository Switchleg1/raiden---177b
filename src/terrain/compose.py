"""Seeded, y-periodic tileset compositions (1600x1120 bake space)."""
from __future__ import annotations

import math
import random
from typing import Any

from .theme_table import FAR_PAIR, NEAR_MEAN, THEME_MEAN
from .tilekit import (
    CH,
    CW,
    GRID_C,
    GRID_R,
    TILE,
    TileKit,
    kit,
    kit_available,
)

# ---------------------------------------------------------------------------
# helpers (periodic in y over CH; x is canvas-wide, not wrapped)
# ---------------------------------------------------------------------------

def _wave_y(y: float, terms: list[tuple[int, float, float]]) -> float:
    """Periodic offset: INTEGER-frequency sine terms over the CH period."""
    f = y / CH
    return sum(a * CH * math.sin(2.0 * math.pi * k * f + p) for k, a, p in terms)


def _blit_wrap(c: Any, img: Any, x: float, y: float) -> None:
    """Blit with wrap copies so shapes crossing the y seam stay continuous."""
    xi, yi = int(round(x)), int(round(y % CH))
    c.blit(img, (xi, yi))
    if yi + img.get_height() > CH:
        c.blit(img, (xi, yi - CH))
    if yi - img.get_height() < 0:
        c.blit(img, (xi, yi + CH))


def _grid(canvas: Any, k: TileKit, mats: list[tuple[str, float]],
          rng: random.Random) -> None:
    """Base material + soft masked patches.  The dominant material fills
    every cell; alternates are radially feathered so cell boundaries read
    as natural patches, and the canvas stays wrap-continuous."""
    names, wts = zip(*mats, strict=True)
    base = names[0]
    for gy in range(GRID_R):
        for gx in range(GRID_C):
            # NO flips/rotations: seam matching only holds unflipped
            canvas.blit(k.material(base), (gx * TILE, gy * TILE))
    for gy in range(GRID_R):
        for gx in range(GRID_C):
            name = rng.choices(names, weights=wts)[0]
            if name != base:
                canvas.blit(k.patch(name), (gx * TILE, gy * TILE))


def _road_v(canvas: Any, k: TileKit, mat: str, center_x: float,
            terms: list[tuple[int, float, float]], rng: random.Random,
            edges: tuple[str, str] = ("splat_dirt", "splat_grass")) -> None:
    """Vertical road whose centre x(y) is periodic -> wraps at CH.

    ``edges`` picks the soiling splats stamped along the shoulders; themes
    without soil (ice, decking) pass their own so no grass grows on a
    glacier."""
    soft, hard = edges
    for y in range(-TILE, CH + TILE, TILE // 3):
        cx = center_x + _wave_y(y, terms)
        t = k.material(mat)
        _blit_wrap(canvas, t, cx - TILE // 2, y)
        for side in (-1, 1):
            if rng.random() < 0.8:
                _splat_on(canvas, k, soft,
                          cx + side * rng.uniform(58.0, 78.0),
                          y + rng.uniform(-20.0, 40.0),
                          rng.uniform(0.55, 0.85), rng)
            if rng.random() < 0.35:
                _splat_on(canvas, k, hard,
                          cx + side * rng.uniform(90.0, 118.0),
                          y + rng.uniform(-30.0, 50.0),
                          rng.uniform(0.5, 0.75), rng)


def _band_h(canvas: Any, k: TileKit, mat: str, center_y: float,
            half_w: float, amp: float, rng: random.Random,
            soft: bool = False) -> None:
    """Horizontal periodic band (river/paddy/wash).

    y(x) = center_y + amp*sin(2*pi*3*x/CW); constant in y so the canvas
    wrap period is preserved.  soft=True stamps radially feathered tiles
    (flooded water, sandbars) instead of full-coverage material."""
    src = k.patch(mat) if soft else k.material(mat)
    for x in range(-TILE, CW + TILE, TILE // 2):
        yc = center_y + amp * math.sin(2.0 * math.pi * 3.0 * x / CW)
        # stamp CENTRES within the band; coverage is band +/- half a tile
        y0 = int(yc - half_w)
        y1 = int(yc + half_w)
        for yy in range((y0 // (TILE // 2)) * (TILE // 2), y1 + TILE // 2,
                        TILE // 2):
            _blit_wrap(canvas, src, x - TILE // 2, yy - TILE // 2)


def _band_h_edges(canvas: Any, k: TileKit, center_y: float, half_w: float,
                  amp: float, count: int, splat: str,
                  rng: random.Random) -> None:
    for _ in range(count):
        x = rng.uniform(0, CW)
        yc = center_y + amp * math.sin(2.0 * math.pi * 3.0 * x / CW)
        side = 1.0 if rng.random() < 0.5 else -1.0
        _splat_on(canvas, k, splat, x, yc + side * half_w + rng.gauss(0, half_w * 0.25),
                  rng.uniform(0.5, 0.85), rng)


def _plaza(canvas: Any, k: TileKit, mat: str, cx: float, cy: float,
           gw: int, gh: int, rng: random.Random,
           edge: str = "splat_grass") -> None:
    for j in range(gh):
        for i in range(gw):
            _blit_wrap(canvas, k.material(mat), cx + i * TILE - gw * TILE / 2,
                       cy + j * TILE - gh * TILE / 2)
    for _ in range(gw * 4):
        _splat_on(canvas, k, edge,
                  cx - gw * TILE / 2 + rng.uniform(0, gw * TILE),
                  cy + (gh * TILE if rng.random() < 0.5 else -gh * TILE) / 2,
                  rng.uniform(0.45, 0.7), rng)


def _splat_on(canvas: Any, k: TileKit, name: str, x: float, y: float,
              s: float, rng: random.Random) -> None:
    import pygame
    p = pygame.transform.rotozoom(k.splats[name], rng.randint(0, 359), s)
    _blit_wrap(canvas, p, x - p.get_width() / 2, y - p.get_height() / 2)


def _prop_on(canvas: Any, k: TileKit, name: str, x: float, y: float,
             s: float, rng: random.Random, rot4: bool = True) -> None:
    import pygame
    p = k.props[name]
    ang = rng.choice((0, 90, 180, 270)) if rot4 else 0
    p = pygame.transform.rotozoom(p, ang, s)
    if rng.random() < 0.5:
        p = pygame.transform.flip(p, True, False)
    _blit_wrap(canvas, p, x - p.get_width() / 2, y - p.get_height() / 2)


def _scatter(canvas: Any, k: TileKit, name: str, count: int,
             smin: float, smax: float, rng: random.Random) -> None:
    for _ in range(count):
        _prop_on(canvas, k, name, rng.uniform(0, CW), rng.uniform(0, CH),
                 rng.uniform(smin, smax), rng)


def _patches(canvas: Any, k: TileKit, name: str, count: int,
             smin: float, smax: float, rng: random.Random) -> None:
    for _ in range(count):
        _splat_on(canvas, k, name, rng.uniform(0, CW), rng.uniform(0, CH),
                  rng.uniform(smin, smax), rng)


def _darken(surf: Any, target_mean: float) -> Any:
    """Return surf with RGB scaled to the arcade brightness target."""
    try:
        import numpy as np
    except ImportError:
        return surf
    import pygame
    w, h = surf.get_size()
    arr = np.asarray(pygame.surfarray.array3d(surf), dtype=np.float32)
    alpha = np.asarray(pygame.surfarray.pixels_alpha(surf))
    m = alpha > 200
    if not m.any():
        return surf
    cur = float(arr[m].mean())
    if cur < 1:
        return surf
    factor = max(0.35, min(2.5, target_mean / cur))
    arr = np.clip(arr * factor, 0, 255).astype(np.uint8)
    rgba = np.dstack([arr, alpha]).transpose(1, 0, 2)  # -> row-major (H,W,4)
    return pygame.image.fromstring(np.ascontiguousarray(rgba).tobytes(),
                                   (w, h), "RGBA")


# ---------------------------------------------------------------------------
# per-theme compositions
# ---------------------------------------------------------------------------

def _near_countryside(c: Any, k: TileKit, rng: random.Random) -> None:
    _grid(c, k, [("grass_lush", 0.72), ("grass_patchy", 0.28)], rng)
    _road_v(c, k, "road_dirt", 0.42 * CW, [(1, 0.11, 0.3), (2, 0.04, 1.1)], rng)
    _patches(c, k, "splat_dirt", 5, 0.6, 1.0, rng)
    _scatter(c, k, "tree_clump", 8, 0.55, 0.85, rng)
    _scatter(c, k, "pine_clump", 3, 0.55, 0.8, rng)
    _scatter(c, k, "rock_cluster", 4, 0.45, 0.7, rng)
    _scatter(c, k, "crate_stack", 2, 0.35, 0.5, rng)
    _prop_on(c, k, "barn_red", rng.uniform(0, CW), rng.uniform(0, CH),
             0.95, rng, rot4=False)
    for _ in range(2):
        _prop_on(c, k, "house_top", rng.uniform(0, CW), rng.uniform(0, CH),
                 0.75, rng)


def _near_farmland(c: Any, k: TileKit, rng: random.Random) -> None:
    _grid(c, k, [("grass_lush", 0.8), ("grass_patchy", 0.2)], rng)
    for cy, hw, amp in ((0.30 * CH, 0.035 * CH, 0.02 * CH),
                        (0.66 * CH, 0.028 * CH, 0.015 * CH)):
        # water_river reads as flooded furrow; water_paddy is mud-grey
        _band_h(c, k, "water_river", cy, hw, amp, rng, soft=True)
        _band_h_edges(c, k, cy, hw, amp, 14, "splat_dirt", rng)
    _road_v(c, k, "road_dirt", 0.80 * CW, [(1, 0.08, 2.2)], rng)
    _prop_on(c, k, "barn_red", rng.uniform(0, CW), rng.uniform(0, CH),
             0.9, rng, rot4=False)
    for _ in range(2):
        _prop_on(c, k, "house_top", rng.uniform(0, CW), rng.uniform(0, CH),
                 0.7, rng)
    _scatter(c, k, "tree_clump", 4, 0.5, 0.75, rng)
    _scatter(c, k, "crate_stack", 3, 0.35, 0.5, rng)


def _near_forest(c: Any, k: TileKit, rng: random.Random) -> None:
    _grid(c, k, [("forest_floor", 0.78), ("grass_patchy", 0.22)], rng)
    _road_v(c, k, "road_dirt", 0.5 * CW, [(1, 0.13, 0.8), (3, 0.03, 2.0)], rng)
    _scatter(c, k, "pine_clump", 12, 0.6, 0.95, rng)
    _scatter(c, k, "tree_clump", 7, 0.55, 0.9, rng)
    _scatter(c, k, "rock_cluster", 5, 0.45, 0.75, rng)
    _patches(c, k, "splat_dirt", 4, 0.6, 1.0, rng)
    _patches(c, k, "splat_grass", 4, 0.6, 1.0, rng)


def _near_city(c: Any, k: TileKit, rng: random.Random) -> None:
    _grid(c, k, [("road_asphalt", 0.72), ("concrete_apron", 0.28)], rng)
    _plaza(c, k, "cobble_moss", rng.uniform(0.3, 0.7) * CW,
           rng.uniform(0, CH), 2, 2, rng)
    _road_v(c, k, "road_dirt", 0.15 * CW, [(1, 0.05, 1.5)], rng)
    for _ in range(4):
        _prop_on(c, k, "house_top", rng.uniform(0, CW), rng.uniform(0, CH),
                 0.8, rng)
    _scatter(c, k, "crate_stack", 3, 0.35, 0.55, rng)
    _patches(c, k, "splat_grass", 4, 0.45, 0.7, rng)


def _near_ruins(c: Any, k: TileKit, rng: random.Random) -> None:
    _grid(c, k, [("cobble_moss", 0.6), ("gravel_rubble", 0.4)], rng)
    _patches(c, k, "splat_dirt", 6, 0.6, 1.0, rng)
    _patches(c, k, "splat_grass", 5, 0.5, 0.85, rng)
    _scatter(c, k, "rock_cluster", 8, 0.5, 0.8, rng)
    _scatter(c, k, "house_top", 3, 0.6, 0.75, rng)    # broken shells
    _scatter(c, k, "crate_stack", 2, 0.35, 0.5, rng)


def _near_ocean(c: Any, k: TileKit, rng: random.Random) -> None:
    _grid(c, k, [("ocean_surface", 1.0)], rng)
    cy, hw, amp = 0.5 * CH, 0.045 * CH, 0.03 * CH
    _band_h(c, k, "sand_canyon", cy, hw, amp, rng, soft=True)
    _band_h_edges(c, k, cy, hw, amp, 14, "splat_dirt", rng)
    _scatter(c, k, "rock_cluster", 4, 0.45, 0.7, rng)
    _scatter(c, k, "crate_stack", 3, 0.3, 0.45, rng)  # flotsam
    _scatter(c, k, "mast_lattice", 2, 0.5, 0.65, rng)


def _near_wasteland(c: Any, k: TileKit, rng: random.Random) -> None:
    _grid(c, k, [("gravel_rubble", 0.72), ("ash_ground", 0.28)], rng)
    _band_h(c, k, "earth_cracked", 0.5 * CH, 0.06 * CH, 0.03 * CH, rng)
    _patches(c, k, "splat_dirt", 6, 0.6, 1.0, rng)
    _scatter(c, k, "rock_cluster", 7, 0.5, 0.8, rng)
    _scatter(c, k, "crate_stack", 3, 0.35, 0.5, rng)
    _scatter(c, k, "mast_lattice", 1, 0.55, 0.7, rng)


def _near_canyon(c: Any, k: TileKit, rng: random.Random) -> None:
    _grid(c, k, [("sand_canyon", 0.74), ("earth_cracked", 0.26)], rng)
    cy, hw, amp = 0.5 * CH, 0.03 * CH, 0.04 * CH
    _band_h(c, k, "road_dirt", cy, hw, amp, rng)
    _band_h_edges(c, k, cy, hw, amp, 12, "splat_dirt", rng)
    _patches(c, k, "splat_dirt", 8, 0.55, 0.9, rng)
    _scatter(c, k, "rock_cluster", 9, 0.5, 0.85, rng)


def _near_airbase(c: Any, k: TileKit, rng: random.Random) -> None:
    _grid(c, k, [("concrete_apron", 0.8), ("gravel_rubble", 0.2)], rng)
    rx = 0.42 * CW                          # straight runway: x const
    for y in range(-TILE, CH + TILE, TILE // 2):
        for xo in (-TILE, 0, TILE):
            t = k.material("tarmac_runway")
            _blit_wrap(c, t, rx + xo - TILE // 2, y)
    for _ in range(10):
        _splat_on(c, k, "splat_dirt", rx + rng.uniform(-420.0, 420.0),
                  rng.uniform(0, CH), rng.uniform(0.45, 0.7), rng)
    _scatter(c, k, "mast_lattice", 3, 0.55, 0.7, rng)
    _scatter(c, k, "crate_stack", 4, 0.35, 0.55, rng)
    _scatter(c, k, "rock_cluster", 2, 0.4, 0.6, rng)


def _near_swamp(c: Any, k: TileKit, rng: random.Random) -> None:
    """Bayou: open dark water, reed banks, mud flats, a stilt hut."""
    _grid(c, k, [("water_marsh", 0.62), ("reed_marsh", 0.24),
                 ("mud_flat", 0.14)], rng)
    # Open water must be a DIFFERENT material from the base: stamping
    # water_marsh over a water_marsh base is a no-op and the bayou reads as
    # one flat green wash.  River water gives real channels; mud softens the
    # banks.
    # Widths near the validated farmland furrows; the amplitude is large so
    # the channel snakes and the per-tile stamping steps stay hidden.
    # Feathered (soft) so banks read natural; two passes because one feather
    # over an equally dark water base is too subtle to read as a channel.
    for cy, hw, amp in ((0.34 * CH, 0.045 * CH, 0.05 * CH),
                        (0.74 * CH, 0.034 * CH, 0.04 * CH)):
        _band_h(c, k, "water_river", cy, hw, amp, rng, soft=True)
        _band_h(c, k, "water_river", cy, hw * 0.7, amp, rng, soft=True)
        _band_h_edges(c, k, cy, hw, amp, 12, "splat_mud", rng)
    _patches(c, k, "splat_mud", 7, 0.55, 0.95, rng)
    _scatter(c, k, "cypress_clump", 9, 0.5, 0.85, rng)
    _scatter(c, k, "dead_tree", 7, 0.45, 0.8, rng)
    _scatter(c, k, "rock_cluster", 3, 0.4, 0.6, rng)
    _prop_on(c, k, "hut_stilt", rng.uniform(0, CW), rng.uniform(0, CH),
             0.8, rng, rot4=False)


def _near_glacier(c: Any, k: TileKit, rng: random.Random) -> None:
    """Ice sheet wound through snow fields and mossy nunataks."""
    _grid(c, k, [("snow_field", 0.7), ("ice_sheet", 0.2),
                 ("tundra_moss", 0.1)], rng)
    _road_v(c, k, "ice_sheet", 0.5 * CW, [(1, 0.1, 0.6), (2, 0.035, 1.7)], rng,
            edges=("splat_snow", "splat_snow"))
    _patches(c, k, "splat_snow", 7, 0.6, 1.0, rng)
    _scatter(c, k, "pine_snow", 10, 0.55, 0.9, rng)
    _scatter(c, k, "ice_boulder", 7, 0.45, 0.8, rng)


def _near_volcanic(c: Any, k: TileKit, rng: random.Random) -> None:
    """Obsidian plains with a molten river; spires and vents."""
    _grid(c, k, [("obsidian", 0.66), ("lava_crust", 0.2),
                 ("gravel_rubble", 0.14)], rng)
    cy, hw, amp = 0.5 * CH, 0.04 * CH, 0.03 * CH
    _band_h(c, k, "lava_crust", cy, hw, amp, rng, soft=True)
    _band_h_edges(c, k, cy, hw, amp, 10, "splat_scorch", rng)
    _patches(c, k, "splat_scorch", 8, 0.55, 0.95, rng)
    _scatter(c, k, "basalt_spire", 8, 0.45, 0.8, rng)
    _scatter(c, k, "lava_vent", 5, 0.4, 0.7, rng)
    _scatter(c, k, "rock_cluster", 3, 0.45, 0.7, rng)


def _near_industrial(c: Any, k: TileKit, rng: random.Random) -> None:
    """Enemy works: steel decking, rust plate, container yards.

    Soiling is oil, never dirt or scorch: pale earth reads as a field and the
    ember-flecked scorch splat reads as fire, which the player takes for a
    hazard.
    """
    _grid(c, k, [("steel_deck", 0.6), ("rust_plate", 0.26),
                 ("concrete_apron", 0.14)], rng)
    _road_v(c, k, "road_asphalt", 0.38 * CW, [(1, 0.06, 1.2)], rng,
            edges=("splat_oil", "splat_oil"))
    _plaza(c, k, "concrete_apron", rng.uniform(0.55, 0.8) * CW,
           rng.uniform(0, CH), 2, 2, rng, edge="splat_oil")
    _patches(c, k, "splat_oil", 5, 0.5, 0.8, rng)
    _scatter(c, k, "cargo_container", 9, 0.4, 0.7, rng)
    _scatter(c, k, "storage_tank", 4, 0.5, 0.75, rng)
    _scatter(c, k, "crate_stack", 4, 0.35, 0.55, rng)
    _scatter(c, k, "antenna_dish", 2, 0.5, 0.7, rng)
    _scatter(c, k, "mast_lattice", 2, 0.5, 0.65, rng)
    _prop_on(c, k, "warehouse_long", rng.uniform(0, CW), rng.uniform(0, CH),
             0.8, rng, rot4=False)


_NEAR = {
    "countryside": _near_countryside,
    "farmland": _near_farmland,
    "forest": _near_forest,
    "city": _near_city,
    "ruins": _near_ruins,
    "ocean": _near_ocean,
    "wasteland": _near_wasteland,
    "canyon": _near_canyon,
    "airbase": _near_airbase,
    "swamp": _near_swamp,
    "glacier": _near_glacier,
    "volcanic": _near_volcanic,
    "industrial": _near_industrial,
}


def _near_for(theme: str, k: TileKit, rng: random.Random) -> Any:
    import pygame
    c = pygame.Surface((CW, CH), pygame.SRCALPHA)
    _NEAR[theme](c, k, rng)
    return _darken(c, THEME_MEAN.get(theme, NEAR_MEAN))


def _far_for(theme: str, k: TileKit, rng: random.Random) -> Any:
    """Slow distant layer: big soft low-alpha material patches."""
    import pygame
    c = pygame.Surface((CW, CH), pygame.SRCALPHA)
    for name in FAR_PAIR[theme]:
        t = pygame.transform.smoothscale(k.patch(name), (280, 280))
        for _ in range(4):
            t.set_alpha(rng.randint(26, 44))
            _blit_wrap(c, t, rng.uniform(0, CW), rng.uniform(0, CH))
    return c


def build_layers(theme: str, rng: random.Random) -> Any:
    """(far, near) bake-space layers 1600x1120 SRCALPHA, y-periodic, or
    None when the tileset or theme is unavailable (vector fallback)."""
    if not kit_available():
        return None
    k = kit()
    if theme not in _NEAR:
        return None
    return _far_for(theme, k, rng), _near_for(theme, k, rng)
