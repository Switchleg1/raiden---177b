"""Paint terrain props from geometry, into the raw-art folder the bake reads.

Most props in `assets/textures/tiles_raw/` were generated images. The generator is
not always available, and some things are better DRAWN than generated: a roof is a
height field, so its lighting, its ridge and hip lines and the run of its shingles
all fall out of the geometry instead of being hoped for. Everything here is
deterministic from the prop's name, so re-running reproduces the same art.

    python scripts/paint_props.py                 # every prop
    python scripts/paint_props.py house_suburb    # one (or several) by name
    python scripts/paint_props.py --sheet         # also write a contact sheet

Output is RGBA at 512 px on a transparent background; `scripts/bake_tiles.py`
then keys, trims and ships it like any other raw prop (an RGBA source with no
magenta passes through the chroma key untouched).

Conventions shared with the generated art: seen from straight above, lit from the
upper left, a soft contact shadow down and to the right, muted and weathered.
"""
from __future__ import annotations

import math
import sys
import zlib
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "textures" / "tiles_raw"
S = 512                                  # art box, px
LIGHT = np.array([-0.55, -0.62, 0.56])   # toward the light: upper left, fairly high
LIGHT = LIGHT / np.linalg.norm(LIGHT)

Rect = tuple[float, float, float, float]


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------

def _rng(name: str) -> np.random.Generator:
    return np.random.default_rng(zlib.crc32(name.encode()))


def _grid() -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    return xx, yy


def vnoise(rng: np.random.Generator, cell: float) -> np.ndarray:
    """Smooth value noise in 0..1 with features about `cell` px across."""
    n = max(2, int(S / cell) + 2)
    small = Image.fromarray((rng.random((n, n)) * 255).astype(np.uint8))
    big = small.resize((int(n * cell), int(n * cell)), Image.BICUBIC)
    return np.asarray(big, dtype=np.float32)[:S, :S] / 255.0


def fbm(rng: np.random.Generator, cell: float = 96.0, octaves: int = 4
        ) -> np.ndarray:
    out = np.zeros((S, S), np.float32)
    amp, tot = 1.0, 0.0
    for _ in range(octaves):
        out += vnoise(rng, cell) * amp
        tot += amp
        amp *= 0.5
        cell = max(2.0, cell / 2.0)
    return out / tot


def shade(height: np.ndarray, gain: float = 1.0) -> np.ndarray:
    """Lambert term of a height field lit from LIGHT (1 = facing the light)."""
    gy, gx = np.gradient(height * gain)
    nz = np.ones_like(gx)
    inv = 1.0 / np.sqrt(gx * gx + gy * gy + nz * nz)
    return np.clip((-gx * LIGHT[0] - gy * LIGHT[1] + nz * LIGHT[2]) * inv, 0, 1)


def blur(a: np.ndarray, r: float) -> np.ndarray:
    im = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(r)),
                      dtype=np.float32) / 255.0


def poly_mask(pts: list[tuple[float, float]], ss: int = 4) -> np.ndarray:
    """Antialiased polygon coverage (supersampled)."""
    im = Image.new("L", (S * ss, S * ss), 0)
    ImageDraw.Draw(im).polygon([(x * ss, y * ss) for x, y in pts], fill=255)
    return np.asarray(im.resize((S, S), Image.LANCZOS), dtype=np.float32) / 255.0


def line_mask(segs: list[tuple[tuple[float, float], tuple[float, float], float]],
              ss: int = 4) -> np.ndarray:
    im = Image.new("L", (S * ss, S * ss), 0)
    d = ImageDraw.Draw(im)
    for (ax, ay), (bx, by), w in segs:
        d.line([(ax * ss, ay * ss), (bx * ss, by * ss)], fill=255,
               width=max(1, int(w * ss)))
        r = w * ss / 2
        for x, y in ((ax, ay), (bx, by)):
            d.ellipse([x * ss - r, y * ss - r, x * ss + r, y * ss + r], fill=255)
    return np.asarray(im.resize((S, S), Image.LANCZOS), dtype=np.float32) / 255.0


def ellipse_mask(cx: float, cy: float, rx: float, ry: float) -> np.ndarray:
    xx, yy = _grid()
    d = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
    edge = 1.2 / max(1.0, min(rx, ry))
    return np.clip((1.0 - d) / edge + 0.5, 0, 1)


def rect_mask(r: Rect) -> np.ndarray:
    x0, y0, x1, y1 = r
    return poly_mask([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


class Layer:
    """Premultiplied-free RGBA accumulator: paint colour through coverage."""

    def __init__(self) -> None:
        self.rgb = np.zeros((S, S, 3), np.float32)
        self.a = np.zeros((S, S), np.float32)

    def paint(self, cov: np.ndarray, col: np.ndarray | tuple, alpha: float = 1.0
              ) -> None:
        c = np.asarray(col, np.float32)
        if c.ndim == 1:
            c = np.broadcast_to(c, (S, S, 3))
        k = np.clip(cov * alpha, 0, 1)
        out_a = k + self.a * (1 - k)
        safe = np.where(out_a > 1e-6, out_a, 1.0)
        self.rgb = (c * k[..., None] + self.rgb * (self.a * (1 - k))[..., None]
                    ) / safe[..., None]
        self.a = out_a

    def shadow(self, cov: np.ndarray, dx: float = 9, dy: float = 12,
               soft: float = 7, strength: float = 0.55) -> None:
        """A contact shadow for `cov`, cast down and to the right."""
        sh = np.roll(np.roll(cov, int(dy), axis=0), int(dx), axis=1)
        sh = blur(sh, soft) * strength
        self.paint(sh, (12, 14, 10))

    def image(self) -> Image.Image:
        rgba = np.dstack([np.clip(self.rgb, 0, 255),
                          np.clip(self.a * 255, 0, 255)]).astype(np.uint8)
        return Image.fromarray(rgba, "RGBA")


def tone(col: tuple[float, float, float], k: np.ndarray) -> np.ndarray:
    """A base colour modulated per pixel by `k` (1 = as given)."""
    return np.asarray(col, np.float32)[None, None, :] * k[..., None]


# ---------------------------------------------------------------------------
# roofs
# ---------------------------------------------------------------------------

def hip_field(rects: list[Rect]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Height, footprint and eave-distance of a hip roof over a union of rects.

    A hip roof over a rectangle IS the distance to its nearest edge: every face
    rises at the same pitch from its own eave, so ridges and hips are where two
    faces meet. Over a union of rectangles the roof is the max of the parts,
    which is what makes an L-shaped house come out with a valley in the corner.
    """
    xx, yy = _grid()
    h = np.full((S, S), -1.0, np.float32)
    for x0, y0, x1, y1 in rects:
        d = np.minimum(np.minimum(xx - x0, x1 - xx), np.minimum(yy - y0, y1 - yy))
        h = np.maximum(h, d)
    foot = np.clip(h + 0.5, 0, 1)
    return np.maximum(h, 0), foot, h


def shingles(h: np.ndarray, rng: np.random.Generator, period: float = 7.0
             ) -> np.ndarray:
    """Course lines parallel to each face's eave, with staggered tab breaks."""
    gy, gx = np.gradient(h)
    xx, yy = _grid()
    along = np.where(np.abs(gx) > np.abs(gy), yy, xx)
    course = np.floor(h / period)
    frac = h / period - course
    line = np.clip(1.0 - frac / 0.16, 0, 1)                  # dark course line
    stagger = (course % 2) * period * 0.9
    tab = np.clip(1.0 - np.abs(((along + stagger) % (period * 1.8)) - 0.5)
                  / 0.9, 0, 1)
    jitter = vnoise(rng, 5.0)
    return 1.0 - 0.32 * line - 0.18 * tab * (frac > 0.16) + 0.10 * (jitter - 0.5)


def ridge_lines(hraw: np.ndarray) -> np.ndarray:
    """Where faces meet: the gradient direction flips across a ridge or hip."""
    gy, gx = np.gradient(hraw)
    gyy, _ = np.gradient(gy)
    _, gxx = np.gradient(gx)
    curv = -(gxx + gyy)
    return np.clip(curv * 1.6, 0, 1) * (hraw > 2)


def house(name: str, rects: list[Rect], roof: tuple[int, int, int],
          extras: Callable[[Layer, np.random.Generator], None] | None = None
          ) -> Image.Image:
    rng = _rng(name)
    lay = Layer()
    h, foot, hraw = hip_field(rects)
    lay.shadow(foot, 10, 13, 8, 0.6)
    pitch = 0.55
    lit = shade(h, pitch)
    weather = 0.86 + 0.28 * fbm(rng, 80, 4)
    stains = 1.0 - 0.18 * np.clip(fbm(rng, 30, 3) * 2.2 - 1.2, 0, 1)
    k = (0.42 + 0.78 * lit) * weather * stains * shingles(h, rng)
    k = k + 0.35 * ridge_lines(hraw)                         # ridge caps catch light
    eave = np.clip(1.0 - hraw / 2.2, 0, 1) * foot            # dark drip edge
    k = k * (1.0 - 0.45 * eave)
    lay.paint(foot, tone(roof, k))
    if extras:
        extras(lay, rng)
    return lay.image()


def box(lay: Layer, r: Rect, top: tuple[int, int, int], height: float,
        rng: np.random.Generator, grille: bool = False) -> None:
    """A rooftop object: a lit top face, a darker skirt and its cast shadow."""
    x0, y0, x1, y1 = r
    m = rect_mask(r)
    lay.shadow(m, height * 0.7, height * 0.9, 2.5, 0.6)
    side = rect_mask((x0 + 1, y0 + 1, x1 + height * 0.18, y1 + height * 0.22))
    lay.paint(side, tone(top, np.full((S, S), 0.55)))
    tex = 0.9 + 0.2 * vnoise(rng, 6.0)
    edge = rect_mask((x0, y0, x1, y1)) - rect_mask((x0 + 2, y0 + 2, x1 - 2, y1 - 2))
    lay.paint(m, tone(top, tex))
    lay.paint(np.clip(edge, 0, 1), tone(top, np.full((S, S), 1.25)), 0.7)
    if grille:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rr = min(x1 - x0, y1 - y0) * 0.36
        lay.paint(ellipse_mask(cx, cy, rr, rr), (38, 40, 42))
        xx, yy = _grid()
        ang = np.arctan2(yy - cy, xx - cx)
        blades = (np.sin(ang * 5) > 0.2) * ellipse_mask(cx, cy, rr * 0.85, rr * 0.85)
        lay.paint(blades, (92, 96, 98), 0.8)
        lay.paint(ellipse_mask(cx, cy, rr * 0.22, rr * 0.22), (70, 72, 74))


def chimney(lay: Layer, x: float, y: float, w: float, rng: np.random.Generator,
            col: tuple[int, int, int] = (112, 84, 70)) -> None:
    box(lay, (x, y, x + w, y + w * 0.8), col, 9.0, rng)
    lay.paint(rect_mask((x + w * 0.25, y + w * 0.2, x + w * 0.75, y + w * 0.6)),
              (24, 22, 22))


def flat_roof(name: str, rect: Rect, membrane: tuple[int, int, int],
              objects: Callable[[Layer, np.random.Generator, Rect], None],
              parapet: tuple[int, int, int] = (150, 148, 140),
              gravel: bool = True) -> Image.Image:
    """A flat roof: membrane or gravel, a parapet with its inner shadow, plant."""
    rng = _rng(name)
    lay = Layer()
    m = rect_mask(rect)
    lay.shadow(m, 14, 18, 10, 0.65)
    x0, y0, x1, y1 = rect
    tex = 0.84 + 0.3 * fbm(rng, 70, 4)
    if gravel:
        tex = tex * (0.86 + 0.28 * (rng.random((S, S)) ** 2))
    ponding = np.clip(fbm(rng, 48, 3) * 2.4 - 1.35, 0, 1)    # old water stains
    tex = tex * (1.0 - 0.22 * ponding)
    lay.paint(m, tone(membrane, tex))
    # the parapet: a raised lip, lit on its upper-left run, with its own shadow
    # falling inward on the roof below it
    p = 7.0
    inner = rect_mask((x0 + p, y0 + p, x1 - p, y1 - p))
    lip = np.clip(m - inner, 0, 1)
    xx, yy = _grid()
    lit_side = ((xx - x0) < (x1 - xx)) * 0.0 + 1.0
    lay.paint(lip, tone(parapet, (0.95 + 0.1 * vnoise(rng, 4.0)) * lit_side))
    inshadow = np.clip(rect_mask((x0 + p, y0 + p, x1 - p, y0 + p + 7))
                       + rect_mask((x0 + p, y0 + p, x0 + p + 7, y1 - p)), 0, 1)
    lay.paint(inshadow * inner, (10, 10, 10), 0.35)
    lay.paint(np.clip(rect_mask((x0 + p - 1, y1 - p - 1, x1 - p + 1, y1 - p + 1))
                      , 0, 1), (230, 228, 220), 0.25)
    objects(lay, rng, (x0 + p, y0 + p, x1 - p, y1 - p))
    return lay.image()


# ---------------------------------------------------------------------------
# the props
# ---------------------------------------------------------------------------

def _suburb(name: str, roof: tuple[int, int, int], flip: bool) -> Image.Image:
    """A suburban house: a long main block whose hip roof has a real ridge, and a
    garage wing joined to it at right angles, so the roofs meet in a valley.

    Near-square blocks gave two pyramids side by side, which reads as two sheds;
    the ridge running the length of the house is what says "one building".
    """
    main = (112.0, 170.0, 400.0, 300.0)
    wing = (112.0, 236.0, 222.0, 410.0) if not flip else (290.0, 236.0, 400.0, 410.0)

    def extras(lay: Layer, rng: np.random.Generator) -> None:
        chimney(lay, 330.0 if not flip else 160.0, 186.0, 20.0, rng)
        # a deck on the garden side, tight to the back wall
        dx0 = 240.0 if not flip else 150.0
        deck = (dx0, 132.0, dx0 + 110.0, 170.0)
        xx, _yy = _grid()
        boards = 0.82 + 0.16 * ((xx % 7.0) > 1.2) + 0.1 * vnoise(rng, 10.0)
        lay.shadow(rect_mask(deck), 3, 4, 2, 0.4)
        lay.paint(rect_mask(deck), tone((106, 82, 60), boards))
        # skylights on the sunny (upper) face of the main roof
        for sx in ((176.0, 214.0) if not flip else (298.0, 336.0)):
            lay.paint(rect_mask((sx, 186.0, sx + 16.0, 208.0)), (50, 64, 78))
            lay.paint(rect_mask((sx + 2, 188.0, sx + 8.0, 198.0)), (150, 170, 182),
                      0.45)
    return house(name, [main, wing], roof, extras)


def house_suburb() -> Image.Image:
    return _suburb("house_suburb", (78, 80, 84), False)


def house_suburb_tan() -> Image.Image:
    return _suburb("house_suburb_tan", (150, 128, 98), True)


def house_suburb_brown() -> Image.Image:
    return _suburb("house_suburb_brown", (104, 72, 56), False)


def house_suburb_slate() -> Image.Image:
    return _suburb("house_suburb_slate", (70, 86, 100), True)


def apartment_block() -> Image.Image:
    rect = (40.0, 136.0, 472.0, 376.0)

    def objects(lay: Layer, rng: np.random.Generator, r: Rect) -> None:
        x0, y0, x1, y1 = r
        box(lay, (x0 + 40, y0 + 34, x0 + 104, y0 + 92), (138, 134, 126), 16, rng)
        box(lay, (x1 - 110, y1 - 96, x1 - 46, y1 - 38), (138, 134, 126), 16, rng)
        for i in range(5):
            ax = x0 + 150 + i * 46
            box(lay, (ax, y0 + 40, ax + 30, y0 + 70), (160, 162, 164), 7, rng,
                grille=True)
        for i in range(7):
            vx = x0 + 60 + i * 52 + (rng.random() * 10)
            lay.paint(ellipse_mask(vx, y1 - 30, 5, 5), (60, 60, 62))
        # a lift overrun and a run of conduit between the units
        box(lay, (x0 + 200, y1 - 92, x0 + 252, y1 - 44), (120, 118, 112), 20, rng)
        lay.paint(line_mask([((x0 + 150, y0 + 82), (x1 - 80, y0 + 82), 3)]),
                  (90, 90, 92))
    return flat_roof("apartment_block", rect, (118, 116, 110), objects)


def office_tower() -> Image.Image:
    rect = (72.0, 72.0, 440.0, 440.0)

    def objects(lay: Layer, rng: np.random.Generator, r: Rect) -> None:
        x0, y0, x1, y1 = r
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        # the mechanical penthouse in the middle, cooling towers on it
        box(lay, (cx - 92, cy - 70, cx + 92, cy + 70), (96, 100, 104), 26, rng)
        for ox in (-46, 46):
            box(lay, (cx + ox - 34, cy - 34, cx + ox + 34, cy + 34),
                (130, 136, 140), 8, rng, grille=True)
        # window-washing rail around the edge and a few antennas
        lay.paint(rect_mask((x0 + 10, y0 + 10, x1 - 10, y1 - 10))
                  - rect_mask((x0 + 13, y0 + 13, x1 - 13, y1 - 13)), (70, 72, 74),
                  0.8)
        for ax, ay in ((x0 + 40, y0 + 40), (x1 - 46, y0 + 44), (x0 + 50, y1 - 52)):
            lay.shadow(ellipse_mask(ax, ay, 4, 4), 16, 20, 2, 0.7)
            lay.paint(ellipse_mask(ax, ay, 4, 4), (180, 180, 176))
    return flat_roof("office_tower", rect, (64, 68, 74), objects,
                     parapet=(120, 126, 132), gravel=False)


def shop_row() -> Image.Image:
    rng = _rng("shop_row")
    lay = Layer()
    units = []
    x = 36.0
    tones = [(128, 120, 108), (98, 96, 92), (140, 132, 116), (110, 104, 98),
             (124, 112, 100)]
    i = 0
    while x < 470.0:
        w = float(rng.integers(70, 104))
        units.append(((x, 180.0 + rng.integers(-8, 8), min(476.0, x + w),
                       330.0 + rng.integers(-6, 10)), tones[i % len(tones)]))
        x += w
        i += 1
    whole = np.zeros((S, S), np.float32)
    for r, _c in units:
        whole = np.maximum(whole, rect_mask(r))
    lay.shadow(whole, 12, 16, 9, 0.6)
    for r, col in units:
        x0, y0, x1, y1 = r
        m = rect_mask(r)
        lay.paint(m, tone(col, 0.86 + 0.28 * fbm(rng, 40, 3)))
        lay.paint(np.clip(m - rect_mask((x0 + 3, y0 + 3, x1 - 3, y1 - 3)), 0, 1),
                  (60, 58, 56), 0.8)
        box(lay, (x0 + 14, y0 + 20, x0 + 44, y0 + 50), (156, 158, 160), 6, rng,
            grille=True)
        lay.paint(ellipse_mask(x1 - 22, y1 - 26, 5, 5), (54, 54, 56))
    # an awning strip along the street front
    for r, _c in units:
        x0, _y0, x1, y1 = r
        lay.paint(rect_mask((x0 + 4, y1, x1 - 4, y1 + 12)),
                  (int(rng.integers(90, 170)), 60, 52))
    return lay.image()


def tent(name: str, fly: tuple[int, int, int]) -> Image.Image:
    """A two-pole dome tent: a rounded oblong crowned in the middle, the poles
    crossing over it, a short porch over the door, guy lines out to pegs."""
    rng = _rng(name)
    lay = Layer()
    xx, yy = _grid()
    cx, cy, hw, hh = 256.0, 240.0, 120.0, 150.0
    # superellipse footprint: tents are boxier than a circle
    q = (np.abs((xx - cx) / hw) ** 3 + np.abs((yy - cy) / hh) ** 3)
    foot = np.clip((1 - q) * 18, 0, 1)
    dome = np.sqrt(np.clip(1 - q, 0, 1)) * 80.0
    porch = poly_mask([(cx - 64, cy + hh - 16), (cx + 64, cy + hh - 16),
                       (cx + 40, cy + hh + 36), (cx - 40, cy + hh + 36)])
    ph = np.clip((cy + hh + 36 - yy) / 52, 0, 1) * 22.0 * porch
    hgt = np.maximum(dome, ph)
    foot = np.maximum(foot, porch)
    lay.shadow(foot, 12, 16, 9, 0.6)
    poles = line_mask([((cx - hw * 0.8, cy - hh * 0.8), (cx + hw * 0.8, cy + hh * 0.8),
                        4), ((cx + hw * 0.8, cy - hh * 0.8),
                             (cx - hw * 0.8, cy + hh * 0.8), 4)]) * foot
    seams = line_mask([((cx, cy - hh), (cx, cy + hh), 2)]) * foot
    k = (0.36 + 0.82 * shade(hgt, 1.0)) * (0.94 + 0.12 * fbm(rng, 30, 3))
    k = k * (1 - 0.22 * poles - 0.12 * seams)
    lay.paint(foot, tone(fly, k))
    lay.paint(poles, (226, 222, 206), 0.3)
    for a in (0.75, 2.4, 3.9, 5.5):
        ex, ey = cx + math.cos(a) * hw * 0.9, cy + math.sin(a) * hh * 0.9
        px, py = cx + math.cos(a) * hw * 1.3, cy + math.sin(a) * hh * 1.25
        lay.paint(line_mask([((ex, ey), (px, py), 1.2)]), (196, 192, 176), 0.6)
        lay.paint(ellipse_mask(px, py, 3, 3), (60, 56, 50))
    return lay.image()


def tent_orange() -> Image.Image:
    return tent("tent_orange", (186, 104, 46))


def tent_green() -> Image.Image:
    return tent("tent_green", (84, 108, 66))


def campfire() -> Image.Image:
    rng = _rng("campfire")
    lay = Layer()
    cx = cy = 256.0
    lay.paint(ellipse_mask(cx, cy, 150, 150), (40, 34, 30),
              0.0)                                              # nothing outside
    ash = ellipse_mask(cx, cy, 96, 96)
    lay.paint(ash, tone((70, 64, 58), 0.8 + 0.4 * fbm(rng, 18, 3)))
    # stones around the ring, each a lit lump with a shadow
    n = 13
    for i in range(n):
        a = i / n * math.tau + rng.random() * 0.2
        sx, sy = cx + math.cos(a) * 112, cy + math.sin(a) * 112
        r = 20 + rng.random() * 8
        m = ellipse_mask(sx, sy, r, r * 0.85)
        lay.shadow(m, 5, 6, 3, 0.6)
        xx, yy = _grid()
        hgt = np.sqrt(np.clip(1 - ((xx - sx) / r) ** 2 - ((yy - sy) / (r * .85)) ** 2,
                              0, 1)) * r
        lay.paint(m, tone((128, 124, 116), 0.45 + 0.75 * shade(hgt)))
    # logs, charred, crossed over the embers
    for a in (0.3, 1.4, 2.5):
        ax, ay = cx + math.cos(a) * 70, cy + math.sin(a) * 70
        bx, by = cx - math.cos(a) * 54, cy - math.sin(a) * 54
        lay.paint(line_mask([((ax, ay), (bx, by), 18)]), (54, 38, 28))
        lay.paint(line_mask([((ax, ay), (bx, by), 7)]), (88, 64, 44), 0.6)
    glow = ellipse_mask(cx, cy, 52, 52) * (0.5 + 0.5 * fbm(rng, 10, 2))
    lay.paint(glow, (236, 118, 40), 0.85)
    lay.paint(ellipse_mask(cx, cy, 22, 22), (255, 212, 120), 0.8)
    return lay.image()


def crater() -> Image.Image:
    """A shell crater: a dark bowl, a raised lit rim, ejecta thrown outward."""
    rng = _rng("crater")
    lay = Layer()
    xx, yy = _grid()
    cx = cy = 256.0
    ang = np.arctan2(yy - cy, xx - cx)
    wob = 1.0 + 0.10 * np.sin(ang * 3 + 1.3) + 0.06 * np.sin(ang * 7 + 0.4)
    r = np.hypot(xx - cx, yy - cy) / (118.0 * wob)
    n = fbm(rng, 24, 4)
    # profile: bowl below grade inside r<1, rim just outside it, then grade
    bowl = -np.clip(1 - r, 0, 1) ** 1.6 * 70
    rim = np.exp(-((r - 1.05) / 0.16) ** 2) * 26
    hgt = bowl + rim + (n - 0.5) * 14
    lit = shade(hgt, 1.0)
    ejecta = np.clip(1.0 - (r - 1.0) / (0.9 + 0.5 * n), 0, 1)
    rays = 0.6 + 0.4 * np.clip(np.sin(ang * 11 + n * 6), 0, 1)
    cov = np.clip(np.where(r < 1.15, 1.0, ejecta * rays), 0, 1)
    soil = np.where(r < 1.0, 0.0, 1.0)
    base = (np.asarray((62, 52, 42), np.float32) * (1 - soil[..., None])
            + np.asarray((104, 90, 72), np.float32) * soil[..., None])
    k = (0.35 + 0.95 * lit) * (0.85 + 0.3 * n)
    char = np.clip(1.0 - r * 1.1, 0, 1)                         # scorched floor
    col = base * k[..., None] * (1 - 0.55 * char[..., None])
    lay.paint(cov, col)
    # clods thrown out past the rim
    for _ in range(60):
        a = rng.random() * math.tau
        d = 140 + rng.random() * 100
        x, y = cx + math.cos(a) * d, cy + math.sin(a) * d
        s = 3 + rng.random() * 6
        lay.paint(ellipse_mask(x, y, s, s * 0.8), (80, 68, 54), 0.9)
    return lay.image()


def wreck_burnt() -> Image.Image:
    """A house after a fire: walls standing as broken stubs, the inside black."""
    rng = _rng("wreck_burnt")
    lay = Layer()
    x0, y0, x1, y1 = 120.0, 130.0, 392.0, 380.0
    soot = blur(rect_mask((x0 - 30, y0 - 30, x1 + 40, y1 + 40)), 22)
    soot = soot * (0.4 + 0.6 * fbm(rng, 40, 3))
    lay.paint(soot, (22, 20, 18), 0.75)
    floor = rect_mask((x0, y0, x1, y1))
    lay.shadow(floor, 8, 10, 6, 0.5)
    ash = 0.5 + 0.7 * fbm(rng, 16, 4)
    lay.paint(floor, tone((46, 42, 38), ash))
    # embers still in the debris
    hot = np.clip(fbm(rng, 22, 3) * 2.6 - 1.75, 0, 1) * floor
    lay.paint(hot, (196, 84, 34), 0.8)
    # fallen roof timbers
    for _ in range(9):
        ax, ay = x0 + rng.random() * (x1 - x0), y0 + rng.random() * (y1 - y0)
        a = rng.random() * math.pi
        L = 60 + rng.random() * 90
        bx, by = ax + math.cos(a) * L, ay + math.sin(a) * L
        lay.paint(line_mask([((ax, ay), (bx, by), 9)]) * floor, (20, 16, 14))
        lay.paint(line_mask([((ax - 2, ay - 2), (bx - 2, by - 2), 3)]) * floor,
                  (70, 58, 50), 0.6)
    # the walls: a masonry outline, broken into stubs of varying height
    wall = 14.0
    runs = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)),
            ((x0, y1), (x0, y0)), ((x0, (y0 + y1) / 2), ((x0 + x1) / 2,
                                                          (y0 + y1) / 2))]
    for (ax, ay), (bx, by) in runs:
        t = 0.0
        while t < 1.0:
            seg = 0.08 + rng.random() * 0.22
            if rng.random() < 0.72:
                pa = (ax + (bx - ax) * t, ay + (by - ay) * t)
                t2 = min(1.0, t + seg)
                pb = (ax + (bx - ax) * t2, ay + (by - ay) * t2)
                m = line_mask([(pa, pb, wall)])
                lay.shadow(m, 7, 9, 3, 0.7)
                lay.paint(m, tone((120, 110, 98), 0.8 + 0.35 * vnoise(rng, 6)))
                lay.paint(line_mask([(pa, pb, wall * 0.35)]), (150, 140, 126), 0.5)
            t += seg + rng.random() * 0.08
    # a chimney stack survives - they usually do
    box(lay, (x1 - 70, y0 + 20, x1 - 40, y0 + 46), (112, 84, 70), 18, rng)
    return lay.image()


def tree_charred() -> Image.Image:
    """A burned tree from above: a black crown of bare branches over ash."""
    rng = _rng("tree_charred")
    lay = Layer()
    cx = cy = 256.0
    lay.paint(blur(ellipse_mask(cx, cy, 120, 112), 12) * (0.5 + 0.5 * fbm(rng, 30)),
              (40, 38, 36), 0.7)
    segs: list[tuple[tuple[float, float], tuple[float, float], float]] = []

    def grow(x: float, y: float, a: float, length: float, w: float, depth: int
             ) -> None:
        if depth == 0 or length < 8:
            return
        bx, by = x + math.cos(a) * length, y + math.sin(a) * length
        segs.append(((x, y), (bx, by), w))
        for _ in range(2 if depth > 1 else 1):
            grow(bx, by, a + (rng.random() - 0.5) * 1.3, length * 0.68,
                 max(1.2, w * 0.62), depth - 1)

    for i in range(7):
        grow(cx, cy, i / 7 * math.tau + rng.random() * 0.5, 62 + rng.random() * 24,
             13, 5)
    m = line_mask(segs)
    lay.shadow(m, 10, 13, 4, 0.55)
    lay.paint(m, (26, 22, 20))
    lay.paint(line_mask([(a, b, w * 0.35) for a, b, w in segs]), (64, 56, 50), 0.6)
    lay.paint(ellipse_mask(cx, cy, 20, 20), (30, 26, 22))
    return lay.image()


def car(name: str, body: tuple[int, int, int]) -> Image.Image:
    """A saloon from above, nose up: body, glass, roof panel, lights."""
    rng = _rng(name)
    lay = Layer()
    cx, cy = 256.0, 256.0
    L, W = 400.0, 168.0
    xx, yy = _grid()
    # a rounded-rectangle body whose height field crowns along the centre line
    dx = np.clip(np.abs(xx - cx) - (W / 2 - 40), 0, None)
    dy = np.clip(np.abs(yy - cy) - (L / 2 - 50), 0, None)
    rr = np.hypot(dx / 40, dy / 50)
    foot = np.clip((1 - rr) * 30, 0, 1)
    crown = np.clip(1 - ((xx - cx) / (W / 2)) ** 2, 0, 1) * 30
    lay.shadow(foot, 14, 16, 8, 0.6)
    k = (0.45 + 0.75 * shade(crown + foot * 8, 1.0)) * (0.96 + 0.08 * vnoise(rng, 20))
    lay.paint(foot, tone(body, k))
    glass = (52, 62, 72)
    lay.paint(poly_mask([(cx - 66, cy - 92), (cx + 66, cy - 92), (cx + 58, cy - 40),
                         (cx - 58, cy - 40)]), glass)              # windscreen
    lay.paint(poly_mask([(cx - 58, cy + 60), (cx + 58, cy + 60), (cx + 62, cy + 98),
                         (cx - 62, cy + 98)]), glass)              # rear window
    lay.paint(rect_mask((cx - 58, cy - 40, cx + 58, cy + 60)),
              tone(body, np.full((S, S), 1.08)))                   # roof panel
    lay.paint(poly_mask([(cx - 60, cy - 88), (cx - 30, cy - 88), (cx - 52, cy - 50)]),
              (190, 200, 210), 0.35)                               # glint
    for sx in (-1, 1):
        lay.paint(rect_mask((cx + sx * 62 - 9, cy - 196, cx + sx * 62 + 9,
                             cy - 186)), (236, 230, 200))
        lay.paint(rect_mask((cx + sx * 62 - 9, cy + 186, cx + sx * 62 + 9,
                             cy + 196)), (170, 40, 36))
    return lay.image()


def car_red() -> Image.Image:
    return car("car_red", (150, 44, 40))


def car_white() -> Image.Image:
    return car("car_white", (196, 196, 190))


def car_blue() -> Image.Image:
    return car("car_blue", (52, 72, 110))


def car_grey() -> Image.Image:
    return car("car_grey", (104, 106, 110))


def truck_semi() -> Image.Image:
    rng = _rng("truck_semi")
    lay = Layer()
    cab = (206.0, 18.0, 306.0, 120.0)
    trailer = (196.0, 130.0, 316.0, 494.0)
    whole = np.maximum(rect_mask(cab), rect_mask(trailer))
    lay.shadow(whole, 14, 16, 8, 0.6)
    lay.paint(rect_mask(trailer), tone((186, 186, 180), 0.9 + 0.15 * fbm(rng, 30)))
    xx, _yy = _grid()
    ribs = 1.0 - 0.12 * ((_yy % 22) < 2)
    lay.paint(rect_mask(trailer), tone((186, 186, 180), ribs), 0.5)
    lay.paint(rect_mask(cab), (128, 40, 34))
    lay.paint(rect_mask((214.0, 30.0, 298.0, 62.0)), (50, 60, 70))
    lay.paint(rect_mask((222.0, 74.0, 290.0, 112.0)), (150, 52, 44))
    return lay.image()


PAINTERS: dict[str, Callable[[], Image.Image]] = {
    "house_suburb": house_suburb,
    "house_suburb_tan": house_suburb_tan,
    "house_suburb_brown": house_suburb_brown,
    "house_suburb_slate": house_suburb_slate,
    "apartment_block": apartment_block,
    "office_tower": office_tower,
    "shop_row": shop_row,
    "tent_orange": tent_orange,
    "tent_green": tent_green,
    "campfire": campfire,
    "crater": crater,
    "wreck_burnt": wreck_burnt,
    "tree_charred": tree_charred,
    "car_red": car_red,
    "car_white": car_white,
    "car_blue": car_blue,
    "car_grey": car_grey,
    "truck_semi": truck_semi,
}


def main(argv: list[str]) -> int:
    names = [a for a in argv if not a.startswith("--")] or list(PAINTERS)
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for n in names:
        img = PAINTERS[n]()
        img.save(OUT / f"{n}.png")
        made.append(img)
        print(f"painted {n}")
    if "--sheet" in argv:
        cols = 6
        rows = (len(made) + cols - 1) // cols
        sheet = Image.new("RGBA", (256 * cols, 256 * rows), (66, 92, 52, 255))
        for i, im in enumerate(made):
            sheet.alpha_composite(im.resize((256, 256), Image.LANCZOS),
                                  ((i % cols) * 256, (i // cols) * 256))
        import time
        path = ROOT / "screenshots" / "terrain" / f"_painted_props_{int(time.time())}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(path)
        print(f"sheet -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
