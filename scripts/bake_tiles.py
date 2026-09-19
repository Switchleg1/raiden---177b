"""Tile/prop prep: enforce seamlessness, chroma-key props, ship to data/.

Reads generation scratch from assets/textures/{tiles,tiles_raw}/, writes
game-ready data to data/textures/tiles/{materials,props,splats}/ plus
manifest.json (kind, px, seam/coverage metrics, sha1 per entry).
Then renders a pilot scene from the tileset (periodic roads, paddy bands,
village props) into screenshots/ for visual review.

Run after (re)generating source textures; the game (src/tiles.py) loads
whatever data/textures/tiles/manifest.json lists and terrain.py falls back
to its vector painters when the tileset is absent. Re-run
scripts/bake_terrain.py after changing tiles.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import zlib

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame

RAW_MAT = "assets/textures/tiles"          # seamless material requests
RAW_PROP = "assets/textures/tiles_raw"     # magenta-background props
OUT = "data/textures/tiles"
SHOTS = "screenshots"

# Sectors 1-5 (countryside / wasteland / city / forest / canyon).
MATERIALS = [
    "grass_lush", "grass_patchy", "road_dirt", "cobble_moss",
    "water_river", "water_paddy", "concrete_apron", "earth_cracked",
    "ash_ground", "sand_canyon", "forest_floor", "gravel_rubble",
    "ocean_surface", "tarmac_runway", "road_asphalt",
]
# Sectors 6-9: farmland + airbase reuse the set above; the four new sectors
# bring their own materials (swamp / glacier / volcanic / industrial).
MATERIALS += [
    "water_marsh", "reed_marsh", "mud_flat",
    "snow_field", "ice_sheet", "tundra_moss",
    "lava_crust", "obsidian",
    "steel_deck", "rust_plate",
]
SPLATS = ["splat_dirt", "splat_grass", "splat_mud", "splat_scorch", "splat_snow",
          "splat_oil"]
PROPS = [
    "tree_clump", "pine_clump", "rock_cluster", "crate_stack",
    "barn_red", "house_top", "mast_lattice",
    # swamp
    "dead_tree", "cypress_clump", "hut_stilt",
    # glacier
    "pine_snow", "ice_boulder",
    # volcanic
    "basalt_spire", "lava_vent",
    # industrial
    "storage_tank", "warehouse_long", "cargo_container", "antenna_dish",
]

MAT_SIZE = 256
PROP_SIZE = 256


def _disp() -> None:
    pygame.display.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((8, 8))


def seam_error(a: np.ndarray) -> float:
    a = a.astype(np.float64)
    lr = np.abs(a[:, 0] - a[:, -1]).mean() / (np.abs(a[:, 1:] - a[:, :-1]).mean() + 1e-9)
    tb = np.abs(a[0] - a[-1]).mean() / (np.abs(a[1:] - a[:-1]).mean() + 1e-9)
    return max(lr, tb)


def seamless_axis(a: np.ndarray, axis: int, frac: float = 0.25) -> np.ndarray:
    n = a.shape[axis]
    band = max(8, int(n * frac))
    rolled = np.roll(a, n // 2, axis=axis).astype(np.float32)
    ramp = np.linspace(1.0, 0.0, band, dtype=np.float32)
    a = a.astype(np.float32)
    shape = [1, 1, 1]
    shape[axis] = band
    for start, rev in ((0, False), (n - band, True)):
        w = (ramp[::-1] if rev else ramp).reshape(shape)
        sl = [slice(None), slice(None)]
        sl[axis] = slice(start, start + band)
        a[tuple(sl)] = a[tuple(sl)] * (1.0 - w) + rolled[tuple(sl)] * w
    return np.clip(a, 0, 255).astype(np.uint8)


def seamless2d(a: np.ndarray) -> np.ndarray:
    return seamless_axis(seamless_axis(a, axis=1), axis=0)


def load_any(path: str) -> pygame.Surface:
    _disp()
    s = pygame.image.load(path)
    if s.get_alpha() is not None or s.get_bitsize() == 32:
        return s.convert_alpha()
    return s.convert()


def to_surf(a: np.ndarray, alpha: bool = False) -> pygame.Surface:
    raw = np.ascontiguousarray(a.transpose(1, 0, 2)).tobytes()
    size = (a.shape[1], a.shape[0])
    if alpha:
        return pygame.image.fromstring(raw, size, "RGBA")
    return pygame.image.fromstring(raw, size, "RGB")


def chroma_key(img: pygame.Surface) -> pygame.Surface:
    """Distance-from-magenta key with despill and 1px alpha erosion.

    Alpha = how far the pixel is from the chroma color (pure #FF00FF -> 0,
    opaque subjects survive), despill removes magenta cast from translucent
    edge pixels, erosion eats the remaining 1-2px halo ring.
    """
    pygame.surfarray.use_arraytype("numpy")
    a = pygame.surfarray.array3d(img).astype(np.float32)
    orig_a = np.asarray(pygame.surfarray.pixels_alpha(img), dtype=np.float32) / 255.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    # Hue-based: magenta-ness = how far BOTH r and b sit above g. Luminance
    # independent, so shadowed/dark magenta still keys out (distance-from-
    # pure-magenta fails there).
    mmag = np.minimum(r, b) - g
    alpha = orig_a * (1.0 - np.clip((mmag - 8.0) / 48.0, 0.0, 1.0))
    # despill: pull r/b toward g where magenta dominates the channel mix
    spill = np.clip((np.minimum(r, b) - g) / 90.0, 0.0, 1.0)
    r = r - spill * (r - g) * 0.85
    b = b - spill * (b - g) * 0.85
    rgba = np.dstack([r, g, b, alpha * 255.0])
    srf = pygame.image.fromstring(np.ascontiguousarray(
        rgba.transpose(1, 0, 2).clip(0, 255).astype(np.uint8)).tobytes(),
        (a.shape[0], a.shape[1]), "RGBA").convert_alpha()
    # 1px erosion of the alpha channel kills the halo ring around edges
    m = pygame.surfarray.pixels_alpha(srf)
    er = m.copy()
    er[1:, :] = np.minimum(er[1:, :], m[:-1, :])
    er[:-1, :] = np.minimum(er[:-1, :], m[1:, :])
    er[:, 1:] = np.minimum(er[:, 1:], m[:, :-1])
    er[:, :-1] = np.minimum(er[:, :-1], m[:, 1:])
    m[:] = er
    del m
    return srf


def trim_center(surf: pygame.Surface, size: int) -> pygame.Surface:
    m = pygame.mask.from_surface(surf, threshold=8)
    bb = m.get_bounding_rects()
    if bb:
        x, y, w, h = bb[0].unionall(bb)
        pad = 6
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(surf.get_width(), x + w + pad), min(surf.get_height(), y + h + pad)
        surf = surf.subsurface((x0, y0, x1 - x0, y1 - y0))
    s = max(surf.get_width(), surf.get_height())
    surf = pygame.transform.smoothscale(surf, (int(surf.get_width() * size / s),
                                               int(surf.get_height() * size / s)))
    out = pygame.Surface((size, size), pygame.SRCALPHA)
    out.blit(surf, ((size - surf.get_width()) // 2, (size - surf.get_height()) // 2))
    return out


def prep_materials() -> dict:
    os.makedirs(f"{OUT}/materials", exist_ok=True)
    info = {}
    for name in MATERIALS:
        surf = load_any(f"{RAW_MAT}/{name}.png")
        arr = pygame.surfarray.array3d(surf).transpose(1, 0, 2)
        before = seam_error(arr)
        if before > 1.6:  # already-seamless sharp tiles must not be blurred
            arr = seamless2d(arr)
        surf = to_surf(arr)
        surf = pygame.transform.smoothscale(surf, (MAT_SIZE, MAT_SIZE))
        after = seam_error(pygame.surfarray.array3d(surf).transpose(1, 0, 2))
        pygame.image.save(surf, f"{OUT}/materials/{name}.png")
        info[name] = {"kind": "material", "px": MAT_SIZE,
                      "seam_before": round(before, 2), "seam_after": round(after, 2),
                      "mean": round(float(pygame.surfarray.array3d(surf).mean()), 1)}
        print(f"material {name:<16} seam {before:5.2f} -> {after:5.2f}")
    return info


def prep_props() -> dict:
    os.makedirs(f"{OUT}/props", exist_ok=True)
    info = {}
    for name in PROPS:
        surf = load_any(f"{RAW_PROP}/{name}.png").convert_alpha()
        keyed = chroma_key(surf)
        final = trim_center(keyed, PROP_SIZE)
        pygame.image.save(final, f"{OUT}/props/{name}.png")
        a = pygame.surfarray.pixels_alpha(final)
        cov = float((a > 128).mean())
        del a
        info[name] = {"kind": "prop", "px": PROP_SIZE, "coverage": round(cov, 3)}
        print(f"prop     {name:<16} coverage {cov:.2f}")
    return info


def prep_splats() -> dict:
    os.makedirs(f"{OUT}/splats", exist_ok=True)
    info = {}
    for name in SPLATS:
        surf = load_any(f"{RAW_PROP}/{name}.png").convert_alpha()
        keyed = chroma_key(surf)
        final = trim_center(keyed, PROP_SIZE)
        pygame.image.save(final, f"{OUT}/splats/{name}.png")
        a = pygame.surfarray.pixels_alpha(final)
        cov = float((a > 128).mean())
        del a
        info[name] = {"kind": "splat", "px": PROP_SIZE, "coverage": round(cov, 3)}
        print(f"splat    {name:<16} coverage {cov:.2f}")
    return info


def render_pilot(info: dict) -> None:
    rng = random.Random(zlib.crc32(b"pilot2"))
    TILE, COLS, ROWS = 128, 16, 11  # 2048x1408 -> crop 1600x1112 (in-game view)
    mats = {n: pygame.image.load(f"{OUT}/materials/{n}.png").convert() for n in MATERIALS}
    props = {n: pygame.image.load(f"{OUT}/props/{n}.png").convert_alpha() for n in PROPS}
    splats = {n: pygame.image.load(f"{OUT}/splats/{n}.png").convert_alpha() for n in SPLATS}

    def splat(name: str, x: float, y: float, s: float) -> None:
        p = pygame.transform.rotozoom(splats[name], rng.randint(0, 359), s)
        canvas.blit(p, (x - p.get_width() / 2, y - p.get_height() / 2))

    def stamp_mat(name: str, gx: int, gy: int) -> tuple:
        t = mats[name]
        if rng.random() < 0.5:
            t = pygame.transform.flip(t, True, False)
        if rng.random() < 0.5:
            t = pygame.transform.flip(t, False, True)
        return t, (gx * TILE, gy * TILE)

    canvas = pygame.Surface((COLS * TILE, ROWS * TILE))
    for gy in range(ROWS):
        for gx in range(COLS):
            t, pos = stamp_mat("grass_patchy" if rng.random() < 0.3 else "grass_lush", gx, gy)
            canvas.blit(t, pos)

    # Periodic paddy bands (2 cycles over canvas height).
    H = ROWS * TILE
    for band_c, band_a in ((0.34, 0.05), (0.72, 0.04)):
        for yy in range(0, H, 16):
            w = int(band_a * H * (0.7 + 0.3 * np.sin(4 * np.pi * yy / H)))
            cx = int(band_c * H + 0.04 * H * np.sin(2 * np.pi * yy / H))
            if abs(yy - cx) < w:
                gx = 0
                while gx < COLS:
                    t, pos = stamp_mat("water_paddy", gx, yy // TILE)
                    canvas.blit(t, (gx * TILE, yy))
                    gx += 1
    for band_c, band_a in ((0.34, 0.05), (0.72, 0.04)):
        cx_b = band_c * H
        for k in range(18):
            y_e = cx_b + (1 if k % 2 else -1) * band_a * H + rng.gauss(0, 14)
            splat("splat_dirt", rng.uniform(0, COLS * TILE), y_e,
                  rng.uniform(0.4, 0.75))
    # Periodic dirt road: integer-frequency sine sum -> road wraps at H.
    for yy in range(0, H, 48):
        f = yy / H
        cx = int(0.5 * COLS * TILE + 0.16 * COLS * TILE * np.sin(2 * np.pi * f)
                 + 0.06 * COLS * TILE * np.sin(4 * np.pi * f + 1.3))
        t, _ = stamp_mat("road_dirt", 0, 0)
        canvas.blit(t, (cx - TILE // 2, yy))
        for side in (-1, 1):
            if rng.random() < 0.75:
                splat("splat_dirt", cx + side * rng.uniform(52, 72),
                      yy + rng.uniform(-10, 40), rng.uniform(0.35, 0.55))
            if rng.random() < 0.30:
                splat("splat_grass", cx + side * rng.uniform(78, 100),
                      yy + rng.uniform(-16, 48), rng.uniform(0.30, 0.5))
    # Ocean band (periodic) with muddy shore splats.
    oy_c = 0.74 * H
    for yy in range(int(oy_c - 140), int(oy_c + 140), 16):
        gx = 0
        while gx < COLS:
            canvas.blit(mats["ocean_surface"], (gx * TILE, yy))
            gx += 1
    for _ in range(34):
        splat("splat_dirt", rng.uniform(0, COLS * TILE),
              oy_c - 140 + rng.gauss(0, 30), rng.uniform(0.45, 0.85))
    # Horizontal asphalt road with grass edging near the top.
    ay = 176
    canvas.fill((0, 0, 0)) if False else None
    for gx in range(0, COLS * TILE, 128):
        canvas.blit(mats["road_asphalt"], (gx, ay), (0, 0, 128, 112))
        if rng.random() < 0.6:
            splat("splat_grass", gx + rng.uniform(0, 128), ay + rng.uniform(-18, 2),
                  rng.uniform(0.32, 0.55))
        if rng.random() < 0.6:
            splat("splat_grass", gx + rng.uniform(0, 128), ay + 112 + rng.uniform(-4, 18),
                  rng.uniform(0.32, 0.55))
    # Cobble plaza with grass encroaching its seams.
    for gy in range(3, 6):
        for gx in range(1, 4):
            t, pos = stamp_mat("cobble_moss", gx, gy)
            canvas.blit(t, pos)
    for _ in range(22):
        edge = rng.randint(0, 3)
        x0, y0 = 128, 3 * 128
        w, h = 3 * 128, 3 * 128
        if edge == 0:
            splat("splat_grass", rng.uniform(x0, x0 + w), y0 - 6, 0.4)
        elif edge == 1:
            splat("splat_grass", rng.uniform(x0, x0 + w), y0 + h + 6, 0.4)
        elif edge == 2:
            splat("splat_grass", x0 - 6, rng.uniform(y0, y0 + h), 0.4)
        else:
            splat("splat_grass", x0 + w + 6, rng.uniform(y0, y0 + h), 0.4)

    # Props: village + farm + forest dressing.
    def stamp_prop(name: str, x: float, y: float, s: float) -> None:
        p = props[name]
        p = pygame.transform.rotozoom(p, rng.choice((0, 90, 180, 270)) if name !=
                                      "mast_lattice" else 0, s)
        if rng.random() < 0.5:
            p = pygame.transform.flip(p, True, False)
        canvas.blit(p, (x - p.get_width() / 2, y - p.get_height() / 2))

    stamp_prop("barn_red", 1180, 320, 0.55)
    stamp_prop("crate_stack", 1260, 400, 0.30)
    for i in range(3):
        stamp_prop("house_top", 1160 + i * 90, 700 + rng.randint(-25, 25), 0.40)
    stamp_prop("mast_lattice", 1450, 220, 0.42)
    for _ in range(26):
        stamp_prop(rng.choice(["tree_clump", "pine_clump"]),
                   rng.uniform(0, COLS * TILE), rng.uniform(0, H), rng.uniform(0.30, 0.55))
    for _ in range(8):
        stamp_prop("rock_cluster", rng.uniform(0, COLS * TILE),
                   rng.uniform(0, H), rng.uniform(0.25, 0.40))
    for _ in range(5):
        stamp_prop("crate_stack", rng.uniform(0, COLS * TILE),
                   rng.uniform(0, H), rng.uniform(0.22, 0.30))

        field = pygame.transform.smoothscale(canvas.subsurface(0, 0, 1600, 1112), (800, 556))
    pygame.image.save(field, f"{SHOTS}/_prev_tile_pilot2.png")

    tall = pygame.Surface((COLS * TILE, H * 2))
    for i in (0, H):
        tall.blit(canvas, (0, i))
    strip = pygame.Surface((800, 556 * 2 + 8))
    strip.fill((0, 0, 0))
    for i, off in enumerate((0, 500)):
        crop = pygame.transform.smoothscale(
            tall.subsurface(0, 2 * off, 1600, 1112), (800, 556))
        strip.blit(crop, (0, i * (556 + 8)))
    pygame.image.save(strip, f"{SHOTS}/_prev_tile_scroll2.png")


def main() -> None:
    os.makedirs(SHOTS, exist_ok=True)
    info = {}
    info.update(prep_materials())
    info.update(prep_props())
    info.update(prep_splats())
    for name, meta in info.items():
        p = f"{OUT}/{meta['kind']}s/{name}.png"
        meta["sha1"] = hashlib.sha1(open(p, "rb").read()).hexdigest()[:12]
    meta = {"generator": "gpt-image-2 via pi-imagegen, seamless2d + chroma-key post",
            "note": "assets/ holds raw generations (scratch); data/ is shipped",
            "tiles": info}
    with open(f"{OUT}/manifest.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1, sort_keys=True)
    print(f"manifest: {len(info)} entries -> {OUT}/manifest.json")
    render_pilot(info)
    print("wrote screenshots/_prev_tile_pilot2.png, _prev_tile_scroll2.png")


if __name__ == "__main__":
    main()
