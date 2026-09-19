"""Bake animated enemy sheets from keyed artwork (sprites_src/).

Part of the ``sprites`` package.

scripts/bake_sprite_raws.py normalises each generation into
assets/textures/sprites_src/<stem>.png: straight alpha, defringed, trimmed,
centred.  This module turns one of those stills into the shipped animation
sheet by adding the motion a static render cannot have:

  * engine plumes that stretch, flicker and collapse,
  * pulsing light bloom on cores and nozzles, coloured by sampling the art,
  * spinning turbine highlights inside intake discs,
  * an optional hull bob and an optional wing-beat squeeze.

Every effect is anchored in ANCHORS in normalised *art* coordinates, so the
motion lands where the artwork actually has an engine, a rotor or a cockpit
instead of where a heuristic guessed.  frame() maps those anchors into the
tile, which is why reserving plume headroom cannot misalign them.

All of it is plain numpy on a deterministic schedule, so
scripts/bake_sprites.py stays byte-reversible (tests assert it).  This is
bake-time art: the game loads the baked sheets and never reads sprites_src, so a
shipped build and a stripped checkout have none -- build_sheet() then returns
None and the caller falls back to the vector painter.
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
import pygame

from .manifest import SPRITES, cols_for, raw_stem, tile_count

REPO = Path(__file__).resolve().parents[2]

DEFAULT_PROFILE: dict[str, Any] = {
    "glow": (),          # (x, y, r, amp) pulsing point lights
    "plume": (),         # (x, y, w, len_min, len_max) exhaust, points up
    "spin": (),          # (x, y, r, blades) rotating specular disc
    "flap": 0.0,         # horizontal squeeze amplitude (wing beat)
    "bob": 0.0,          # vertical bob in pixels
}


# ---------------------------------------------------------------------------
# keyed art I/O
# ---------------------------------------------------------------------------
def _src_root() -> Path:
    env = os.environ.get("RAIDEN_SPRITE_SRC_DIR")
    return Path(env) if env else REPO / "assets" / "textures" / "sprites_src"


def has_source(stem: str) -> bool:
    return (_src_root() / f"{stem}.png").is_file()


def _surf_to_array(surf: Any) -> np.ndarray:
    """Surface -> float RGBA in numpy order (row=y, col=x).

    Deliberately uses pygame.image rather than pygame.surfarray: surfarray
    hands back (W, H, ch) arrays whose channel order follows the blit format,
    which is how channel-swap bugs get baked into art.
    """
    w, h = surf.get_size()
    buf = pygame.image.tostring(surf, "RGBA")
    return np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4).astype(
        np.float32)


def _array_to_surf(rgba: np.ndarray) -> Any:
    """float RGBA (H, W, 4) -> RGBA Surface."""
    data = np.ascontiguousarray(np.clip(rgba, 0, 255).astype(
        np.uint8)).tobytes()
    return pygame.image.fromstring(data, (rgba.shape[1], rgba.shape[0]),
                                   "RGBA")


def source_size(stem: str) -> tuple:
    """Pixel size of a keyed source (PNG IHDR only), (0, 0) if absent."""
    path = _src_root() / f"{stem}.png"
    if not path.is_file():
        return (0, 0)
    head = path.read_bytes()[:24]
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return (0, 0)
    return (int.from_bytes(head[16:20], "big"),
            int.from_bytes(head[20:24], "big"))


def load_src(stem: str) -> np.ndarray | None:
    path = _src_root() / f"{stem}.png"
    if not path.is_file():
        return None
    surf = pygame.image.load(str(path))
    if not surf.get_flags() & pygame.SRCALPHA:
        surf = surf.convert_alpha()
    return _surf_to_array(surf)


def _auto_boss_anchors(stem: str) -> dict[str, Any]:
    """Read a boss's anchors back out of its own artwork.

    Hand-placing anchors pays off for the six recurring grunts; it does not for
    nine one-off sector bosses. They all follow the house convention (one hot
    core, engine cans along the top edge), so the core is found as the brightest
    saturated blob near the middle and the nozzles as the solid clusters hugging
    the top of the silhouette. Deterministic, and it never edits the art.
    """
    art = load_src(stem)
    if art is None:
        return {}
    h, w = art.shape[0], art.shape[1]
    rgb = art[..., :3] / 255.0
    a = art[..., 3] / 255.0
    val = rgb.max(axis=2)
    sat = val - rgb.min(axis=2)
    yy = np.linspace(-1.0, 1.0, h)[:, None]
    xx = np.linspace(-1.0, 1.0, w)[None, :]
    hot = (0.35 * val + 0.65 * sat) * np.exp(-2.0 * (xx * xx + yy * yy)) * a
    keep = hot >= 0.8 * hot.max()
    ys, xs = np.nonzero(keep)
    if len(xs) < 8:
        return {}
    gx = float(xs.mean()) / w
    gy = float(ys.mean()) / h

    # No exhaust plumes: a boss hovers, its art already paints the smoke, and
    # a flame drawn at cell scale on a hull this large just reads as a bright
    # nub.  The life comes from the core instead - pulse plus a slow swirl -
    # and a slight hull bob.
    return {
        "glow": ((gx, gy, 0.13, 0.5),),
        "spin": ((gx, gy, 0.085, 4),),
        "bob": 1.5,
    }


_AUTO: dict[str, dict[str, Any]] = {}


def anchors_for(stem: str) -> dict[str, Any]:
    """Hand-authored anchors, or derived ones for the sector bosses."""
    if stem in ANCHORS:
        return ANCHORS[stem]
    if re.fullmatch(r"e_boss\d+", stem):
        if stem not in _AUTO:
            _AUTO[stem] = _auto_boss_anchors(stem)
        return _AUTO[stem]
    return {}


def profile(stem: str) -> dict[str, Any]:
    prof = dict(DEFAULT_PROFILE)
    prof.update(anchors_for(stem))
    return prof


# ---------------------------------------------------------------------------
# frame construction
# ---------------------------------------------------------------------------
def _cyc(i: int, n: int, phase: float = 0.0) -> float:
    """Smooth 0..1..0 loop over n frames (frame n matches frame 0)."""
    return 0.5 - 0.5 * math.cos(2.0 * math.pi * (i / n + phase))


def _grid(h: int, w: int) -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    return xx, yy


def _unsharp(rgba: np.ndarray, amount: float) -> np.ndarray:
    """Recover the edge crispness that downscaling to cell size shaves off.

    Shrinking 384px art into a 48px cell softens exactly the panel lines that
    make a generated sprite read as detailed, so a mild high-boost is part of
    the look rather than an accident.
    """
    if amount <= 0.0:
        return rgba
    acc = np.zeros_like(rgba)
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        acc += np.roll(np.roll(rgba, dy, 0), dx, 1)
    return rgba + (rgba - acc / 4.0) * amount


def _trim(rgba: np.ndarray, pad: int = 1) -> tuple[np.ndarray, tuple[int, int]]:
    """Crop to the silhouette; return (crop, (x0, y0)) of the crop origin.

    The keyed source keeps a transparent margin; scaling it along with the
    art would silently shrink the hull by that margin twice over.  Callers
    need the origin back so anchors still land where the art has them.
    """
    ys, xs = np.nonzero(rgba[..., 3] > 8)
    if len(xs) == 0:
        return rgba, (0, 0)
    y0 = max(0, int(ys.min()) - pad)
    y1 = min(rgba.shape[0], int(ys.max()) + 1 + pad)
    x0 = max(0, int(xs.min()) - pad)
    x1 = min(rgba.shape[1], int(xs.max()) + 1 + pad)
    return rgba[y0:y1, x0:x1], (x0, y0)


def _fit(rgba: np.ndarray, cell: tuple[int, int],
         top: int = 0) -> tuple[np.ndarray, tuple[float, float, float]]:
    """Scale the source into the cell below `top`.

    Returns (tile, (scale, offset_x, offset_y)) where scale/offsets map art
    pixels onto the tile, so anchors survive the resize and the headroom.
    """
    cw, ch = cell
    src = _array_to_surf(rgba)
    s = min(cw / src.get_width(), max(ch - top, 4) / src.get_height())
    nw, nh = max(1, round(src.get_width() * s)), max(1, round(
        src.get_height() * s))
    big = pygame.transform.smoothscale(src, (nw, nh))
    ox, oy = (cw - nw) / 2.0, top + (ch - top - nh) / 2.0
    out = pygame.Surface((cw, ch), pygame.SRCALPHA)
    out.fill((0, 0, 0, 0))
    out.blit(big, (int(round(ox)), int(round(oy))))
    return _unsharp(_surf_to_array(out), 0.55), (s, ox, oy)


def _sample_color(rgba: np.ndarray, cx: float, cy: float,
                  rad: float) -> np.ndarray:
    """Colour of the brightest pixels near an anchor.

    Engines glow orange and cores glow cyan; sampling the art means the bloom
    matches without anyone hand-picking a colour per sprite.
    """
    h, w = rgba.shape[:2]
    r = max(rad, 1.0)
    x0, x1 = int(max(0.0, cx - r)), int(min(w, cx + r + 1))
    y0, y1 = int(max(0.0, cy - r)), int(min(h, cy + r + 1))
    box = rgba[y0:y1, x0:x1]
    if box.size == 0:
        return np.array([255.0, 180.0, 90.0], dtype=np.float32)
    lum = box[..., :3] @ np.array([0.3, 0.6, 0.1], dtype=np.float32)
    cut = max(170.0, float(lum.max()) * 0.74)
    sel = box[lum >= cut]
    if sel.size == 0:
        sel = box.reshape(-1, 4)
    return sel[:, :3].mean(axis=0).astype(np.float32)


def _add_light(rgba: np.ndarray, cx: float, cy: float, rad: float,
               color: np.ndarray, amp: float) -> None:
    """Additive bloom with coverage-aware alpha (in place)."""
    if amp <= 0.001 or rad <= 0.5:
        return
    h, w = rgba.shape[:2]
    xx, yy = _grid(h, w)
    d = np.sqrt(((xx - cx) / rad) ** 2 + ((yy - cy) / (rad * 1.15)) ** 2)
    f = np.clip(1.0 - d, 0.0, 1.0) ** 2.2 * amp
    if not f.any():
        return
    rgba[..., :3] += color[None, None, :] * f[..., None]
    rgba[..., 3] = np.clip(rgba[..., 3] + f * (255.0 - rgba[..., 3]), 0, 255)


def _add_plume(rgba: np.ndarray, cx: float, cy: float, wdt: float,
               length: float, color: np.ndarray, i: int, n: int) -> None:
    """Exhaust flame above the nozzle (enemy art is drawn nose-down)."""
    if length <= 1.0 or wdt <= 0.4:
        return
    h, w = rgba.shape[:2]
    xx, yy = _grid(h, w)
    dy = cy - yy                      # positive above the nozzle
    inband = (dy > -1.5) & (dy < length)
    span = wdt * (1.0 + 1.15 * np.clip(dy / max(length, 1e-3), 0.0, 1.0))
    fx = np.clip(1.0 - np.abs(xx - cx) / np.maximum(span, 1e-3), 0.0, 1.0)
    taper = 1.0 - np.clip(dy / length, 0.0, 1.0)
    # three flicker tongues so the flame is never a static teardrop
    flick = 0.70 + 0.30 * np.sin(2.0 * math.pi * (dy / max(length, 1e-3) * 3.0
                                                  + i / max(n, 1)))
    f = np.clip(np.where(inband, fx ** 1.15 * taper ** 0.9 * flick, 0.0),
                0.0, 1.0)
    if not f.any():
        return
    # white-hot root -> body in the nozzle colour -> ember tail.  Sampling is
    # only a hint here: the sampled nozzle colour is pale, and a pale flame
    # over bright terrain reads as grey smoke.
    body = 0.65 * np.clip(color, 0, 255) + 0.35 * np.array(
        [255.0, 140.0, 40.0], dtype=np.float32)
    hot = np.clip(1.0 - dy / max(length * 0.42, 1e-3), 0.0, 1.0)[..., None]
    cool = np.clip((dy / max(length, 1e-3) - 0.55) / 0.45, 0.0, 1.0)[..., None]
    tint = body[None, None, :] * (1.0 - hot) + np.array(
        [255.0, 248.0, 218.0], dtype=np.float32) * hot
    tint = tint * (1.0 - cool) + np.array([205.0, 60.0, 18.0],
                                          dtype=np.float32) * cool
    rgba[..., :3] += tint * f[..., None] * 1.25
    rgba[..., 3] = np.clip(rgba[..., 3] + f * (255.0 - rgba[..., 3]) * 0.95,
                           0, 255)


def _add_spin(rgba: np.ndarray, cx: float, cy: float, rad: float,
              blades: int, i: int, n: int) -> None:
    """Rotating specular streaks inside an intake disc (spinning turbine)."""
    if rad <= 1.0:
        return
    h, w = rgba.shape[:2]
    xx, yy = _grid(h, w)
    dx, dy = (xx - cx) / rad, (yy - cy) / rad
    d = np.sqrt(dx * dx + dy * dy)
    disc = np.clip(1.0 - (d - 0.55) / 0.45, 0.0, 1.0) * (d <= 1.0)
    hull = rgba[..., 3] > 170.0
    ang = np.arctan2(dy, dx)
    spokes = np.cos(blades * ang + (2.0 * math.pi * i / max(n, 1)) * blades)
    blade = np.clip((spokes - 0.25) / 0.75, 0.0, 1.0) ** 2.0
    f = disc * blade * hull * 0.42
    if not f.any():
        return
    rgba[..., :3] += np.array([215.0, 225.0, 240.0],
                              dtype=np.float32)[None, None, :] * f[..., None]


def frame(src: np.ndarray, cell: tuple[int, int], prof: dict[str, Any],
          i: int, n: int) -> np.ndarray:
    """One animation frame: hull + squeeze + bob + lights + plumes + spin."""
    base = src
    if prof["flap"] > 0.0:
        # squeeze about the middle, then paste back onto a full-size canvas:
        # scaling down and up again would cancel out and only blur the art.
        squeeze = 1.0 - prof["flap"] * _cyc(i, n, 0.5)
        w0, h0 = src.shape[1], src.shape[0]
        wdt = max(1, int(round(w0 * squeeze)))
        sq = pygame.transform.smoothscale(_array_to_surf(src), (wdt, h0))
        canvas = pygame.Surface((w0, h0), pygame.SRCALPHA)
        canvas.fill((0, 0, 0, 0))
        canvas.blit(sq, ((w0 - wdt) // 2, 0))
        base = _surf_to_array(canvas)

    # Reserve most of the longest plume above the hull.  Not all of it: the
    # flame's brightest palm is meant to sit on the nozzle housing, and every
    # reserved pixel is hull size the craft loses on screen.
    top = 0
    if prof["plume"]:
        top = int(math.ceil(0.6 * max(p[4] for p in prof["plume"]) * cell[1]))
    crop, (cx0, cy0) = _trim(base)
    out, (scale, ox, oy) = _fit(crop, cell, top)

    def px(ax: float, ay: float) -> tuple[float, float]:
        """Art-normalised anchor -> tile pixels (crop, scale and headroom)."""
        return ((ax * src.shape[1] - cx0) * scale + ox,
                (ay * src.shape[0] - cy0) * scale + oy)

    pulse = _cyc(i, n)
    for (ax, ay, ar, amp) in prof["glow"]:
        cx, cy = px(ax, ay)
        rad = ar * src.shape[1] * scale
        color = _sample_color(out, cx, cy, rad * 1.6)
        _add_light(out, cx, cy, rad, color, amp * (0.55 + 0.75 * pulse))
        _add_light(out, cx, cy, rad * 2.3, color,
                   amp * 0.26 * (0.35 + 0.65 * pulse))
    for (ax, ay, aw, lmin, lmax) in prof["plume"]:
        cx, cy = px(ax, ay)
        wdt = aw * src.shape[1] * scale
        color = _sample_color(out, cx, cy, max(wdt * 1.5, 1.5))
        length = (lmin + (lmax - lmin) * pulse) * cell[1]
        _add_plume(out, cx, cy, wdt, length, color, i, n)
    for (ax, ay, ar, blades) in prof["spin"]:
        cx, cy = px(ax, ay)
        _add_spin(out, cx, cy, ar * src.shape[1] * scale, int(blades), i, n)

    if prof["bob"]:
        dy = int(round(prof["bob"] * math.sin(2.0 * math.pi * i / max(n, 1))))
        if dy:
            # shift without wrapping: np.roll dragged the stinger tip back in
            # from the opposite edge and drew it as a stray dash.
            shifted = np.zeros_like(out)
            shifted[max(0, dy):min(out.shape[0], out.shape[0] + dy)] = \
                out[max(0, -dy):min(out.shape[0], out.shape[0] - dy)]
            out = shifted
    return np.clip(out, 0, 255)


# ---------------------------------------------------------------------------
# sheet assembly
# ---------------------------------------------------------------------------
# (plume power, bank level, sign) per tile, identical to the vector painter's
# recipe so the generated hero banks, squashes and idles exactly where the
# painted one did and no caller has to know the art changed.
_PLAYER_TILES: tuple[tuple[float, int, int], ...] = (
    (1.0, 0, 0), (0.55, 0, 0),
    (1.0, 1, +1), (1.0, 2, +1), (0.55, 1, +1), (0.55, 2, +1),
    (1.0, 1, -1), (1.0, 2, -1), (0.55, 1, -1), (0.55, 2, -1),
)


def build_player_sheet(name: str) -> pygame.Surface | None:
    """Hero sheet: one still, two burn states, four bank poses.

    Banking is a rotation plus horizontal foreshortening about the hull, which
    is what a top-down craft does when it rolls; the burn pair comes from the
    two ends of the glow pulse, so the idle frames breathe instead of freezing.
    """
    stem = raw_stem(name) or name
    src = load_src(stem)
    if src is None:
        return None
    prof = profile(stem)
    cw, ch = SPRITES[name]["cell"]
    cols, n = cols_for(name), tile_count(name)
    rows = (n + cols - 1) // cols
    sheet = pygame.Surface((cols * cw, rows * ch), pygame.SRCALPHA)
    sheet.fill((0, 0, 0, 0))
    masters = [_array_to_surf(frame(src, (cw, ch), prof, i, 2))
               for i in (0, 1)]
    for i, (power, level, sign) in enumerate(_PLAYER_TILES[:n]):
        surf = masters[1 if power > 0.9 else 0]
        if level:
            surf = pygame.transform.rotozoom(surf, -sign * level * 8.0, 1.0)
            wdt = max(1, int(surf.get_width() * (1.0 - 0.045 * level)))
            surf = pygame.transform.smoothscale(
                surf, (wdt, surf.get_height()))
        surf = pygame.transform.smoothscale(surf, (cw, ch))
        r, c = divmod(i, cols)
        sheet.blit(surf, (c * cw, r * ch))
    return sheet


def build_sheet(name: str) -> pygame.Surface | None:
    """Compose the shipped sheet for one sprite from its keyed still.

    Returns None when there is no keyed art, so the caller can fall back to
    the vector painter.  Sheet geometry follows the manifest rules exactly
    (cols_for/tile_count), which is what Bank.frame assumes when slicing.
    """
    stem = raw_stem(name) or name
    src = load_src(stem)
    if src is None:
        return None
    prof = profile(stem)
    if prof.get("player"):
        return build_player_sheet(name)
    cw, ch = SPRITES[name]["cell"]
    cols, n = cols_for(name), tile_count(name)
    rows = (n + cols - 1) // cols
    sheet = np.zeros((rows * ch, cols * cw, 4), dtype=np.float32)
    for fi in range(n):
        tile = frame(src, (cw, ch), prof, fi, n)
        r, c = divmod(fi, cols)
        sheet[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = tile
    return _array_to_surf(sheet)


def motion_report(name: str) -> str:
    """Human-readable summary of what animates on a raw-backed sheet."""
    stem = raw_stem(name) or name
    prof = profile(stem)
    bits = [f"{len(prof['glow'])} glow", f"{len(prof['plume'])} plume",
            f"{len(prof['spin'])} spin"]
    if prof["flap"]:
        bits.append(f"flap {prof['flap']:.2f}")
    if prof["bob"]:
        bits.append(f"bob {prof['bob']:.1f}")
    return ", ".join(bits)


# Normalised anchors per art stem: (x, y) with (0, 0) top-left and y running
# downward, because enemy art is drawn nose-down.  Radii and plume widths are
# fractions of art width; plume lengths are fractions of cell height.  Read
# off a 10x10 grid overlay of each generation.
ANCHORS: dict[str, dict[str, Any]] = {
    # Hero craft (art is drawn nose-UP, unlike every enemy).  No plume: the
    # generation already paints its own flames, so the burn state is read back
    # as two nozzle blooms breathing at the tail, plus a cool canopy glint.
    "p_ship": {
        "player": True,
        "glow": ((0.447, 0.845, 0.034, 0.95), (0.563, 0.845, 0.034, 0.95),
                 (0.499, 0.209, 0.030, 0.30)),
        "bob": 0.0,
    },
    # Bomber: the four engine cans burn along the top of the wide hull, and the
    # nose eye is the only thing that moves fast enough to read as aiming.
    "e_bomber": {
        "glow": ((0.406, 0.236, 0.034, 0.80), (0.592, 0.235, 0.034, 0.80),
                 (0.174, 0.337, 0.050, 0.45), (0.815, 0.335, 0.050, 0.45),
                 (0.495, 0.745, 0.026, 1.00)),
        "plume": ((0.406, 0.215, 0.044, 0.04, 0.15),
                  (0.592, 0.215, 0.044, 0.04, 0.15)),
        "bob": 0.3,
    },
    # Splitter: the fracture seams are the animation - they brighten until the
    # pod looks two seconds from bursting.
    "e_splitter": {
        "glow": ((0.500, 0.470, 0.048, 1.00), (0.420, 0.300, 0.028, 0.60),
                 (0.580, 0.300, 0.028, 0.60), (0.370, 0.560, 0.024, 0.50),
                 (0.630, 0.560, 0.024, 0.50)),
        "flap": 0.022,
        "bob": 0.5,
    },
    # Rammer: a needle, so almost all of its life is the afterburner flicker.
    "e_rammer": {
        "glow": ((0.424, 0.055, 0.028, 0.90), (0.576, 0.055, 0.028, 0.90),
                 (0.300, 0.235, 0.026, 0.45), (0.700, 0.235, 0.026, 0.45),
                 (0.500, 0.550, 0.022, 0.35)),
        "plume": ((0.424, 0.050, 0.030, 0.05, 0.20),
                  (0.576, 0.050, 0.030, 0.05, 0.20)),
        "bob": 0.4,
    },
    "e_grunt": {
        "glow": ((0.385, 0.055, 0.050, 0.80), (0.615, 0.055, 0.050, 0.80),
                 (0.500, 0.535, 0.030, 1.00)),
        "plume": ((0.385, 0.050, 0.062, 0.05, 0.15),
                  (0.615, 0.050, 0.062, 0.05, 0.15)),
        "spin": ((0.155, 0.385, 0.095, 6), (0.845, 0.385, 0.095, 6)),
        "bob": 0.6,
    },
    # Weaver: four swept wings with burning tips, twin stacked nozzles.
    "e_weaver": {
        "glow": ((0.500, 0.410, 0.050, 0.55),
                 (0.110, 0.140, 0.030, 0.35), (0.890, 0.130, 0.030, 0.35),
                 (0.110, 0.670, 0.030, 0.35), (0.890, 0.660, 0.030, 0.35)),
        "plume": ((0.420, 0.090, 0.050, 0.05, 0.22),
                  (0.580, 0.090, 0.050, 0.05, 0.22)),
        "flap": 0.02,
        "bob": 0.7,
    },
    # Darter: a needle. Barely any body, so the motion lives in the engines.
    "e_darter": {
        "glow": ((0.500, 0.300, 0.045, 0.60), (0.500, 0.620, 0.020, 0.30)),
        "plume": ((0.440, 0.020, 0.040, 0.04, 0.20),
                  (0.560, 0.020, 0.040, 0.04, 0.20)),
        "bob": 0.5,
    },
    "e_gunner": {
        "glow": ((0.500, 0.400, 0.060, 0.60), (0.500, 0.580, 0.025, 0.45),
                 (0.160, 0.450, 0.020, 0.30), (0.840, 0.450, 0.020, 0.30)),
        "plume": ((0.360, 0.150, 0.045, 0.04, 0.18),
                  (0.500, 0.120, 0.050, 0.05, 0.20),
                  (0.640, 0.150, 0.045, 0.04, 0.18)),
        "bob": 0.6,
    },
    # Sentry and heavy hold a visible rotating turbine in their core.
    "e_sentry": {
        "glow": ((0.500, 0.460, 0.075, 0.60), (0.340, 0.460, 0.020, 0.40),
                 (0.660, 0.460, 0.020, 0.40)),
        "plume": ((0.400, 0.070, 0.050, 0.05, 0.20),
                  (0.600, 0.070, 0.050, 0.05, 0.20)),
        "spin": ((0.500, 0.460, 0.105, 8),),
        "bob": 0.4,
    },
    "e_heavy": {
        "glow": ((0.500, 0.440, 0.080, 0.55), (0.130, 0.310, 0.025, 0.35),
                 (0.870, 0.310, 0.025, 0.35), (0.130, 0.700, 0.025, 0.35),
                 (0.870, 0.700, 0.025, 0.35)),
        "plume": ((0.360, 0.060, 0.060, 0.05, 0.22),
                  (0.620, 0.060, 0.060, 0.05, 0.22)),
        "spin": ((0.500, 0.440, 0.085, 5),),
        "bob": 0.35,
    },
}
