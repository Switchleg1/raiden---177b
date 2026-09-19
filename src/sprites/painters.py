"""Procedural sprite painters used OFFLINE to bake the sheets
(scripts/bake_sprites.py). Runtime code loads PNGs only.
"""
from __future__ import annotations

import math
import random
from functools import partial
from pathlib import Path
from typing import Any

import config as C  # only for art that must match a hitbox radius

from .fxkit import RGB, Tile, mix
from .manifest import SPRITES, cols_for, sheet_path

# ---------------------------------------------------------------------------
# Bake engine (offline; pygame imported inside). Paints each sheet into a
# tiled image at 2x supersample then downscales once — original art only.
# ---------------------------------------------------------------------------
SS = 1   # baked directly at logical resolution (sprites are chunky by design)


def _rng_for(sheet: str) -> random.Random:
    # crc32, not hash(): Python's string hash is per-process randomised and
    # would make bake vs stale-detector disagree.
    import zlib
    return random.Random(zlib.crc32(sheet.encode("utf-8")))


def tile_xy(name: str, i: int) -> tuple[int, int]:
    """Pixel offset of tile ``i`` inside the sheet (row-major, ``cols_for``)."""
    cw, ch = SPRITES[name]["cell"]
    n = cols_for(name)
    return (i % n) * cw, (i // n) * ch


def _shade(col, d):
    return tuple(max(0, min(255, c + d)) for c in col)


# ---- family painters: draw all tiles of one sheet -------------------------
# Painters work in LOGICAL units; every tile starts at tile_xy(name, i).
def _paint_shot_vulcan(sheet: Any) -> None:
    """Tracer bolt: white-hot tip, amber core, warm bloom.

    Length and tip flare phase along the four frames so a stream of them reads
    as one continuous burn instead of four identical dashes.  The bloom radius
    is deliberately bounded by the cell so no square halo ever lands on the
    terrain behind the bullet.
    """
    cw, ch = SPRITES["shot_vulcan"]["cell"]
    for i in range(4):
        ox, oy = tile_xy("shot_vulcan", i)
        t = Tile(cw, ch)
        cx, cy = cw / 2.0, ch / 2.0
        half = [4.4, 6.0, 7.2, 6.0][i]
        t.bloom(cx, cy, 8.0, (255, 132, 36), power=2.6, peak=0.42)
        t.capsule(cx, cy, half, 3.0, (255, 166, 50))
        t.capsule(cx, cy, max(half - 0.7, 0.4), 1.7, (255, 226, 132))
        t.capsule(cx, cy - 0.5, max(half - 2.0, 0.2), 0.85, (255, 255, 248))
        t.disc(cx, cy - half - 0.5, 1.7 + 0.45 * (i % 2), (255, 252, 240))
        t.disc(cx, cy + half + 0.4, 1.3, (255, 150, 60), alpha=0.75)
        t.blit(sheet, ox, oy)


def _paint_shot_plasma(sheet: Any) -> None:
    """Purple beaded plasma (Raiden II max-Vulcan homage): stacked
    white-core / violet-mantle beads whose bulge phases along the stream,
    each with a lit upper edge so the beads read as spheres not discs."""
    cw, ch = SPRITES["shot_plasma"]["cell"]
    for i in range(4):
        ox, oy = tile_xy("shot_plasma", i)
        t = Tile(cw, ch)
        cx, cy = cw / 2.0, ch / 2.0
        for bi, by in enumerate((cy - 7.6, cy, cy + 7.6)):
            r = [5.5, 6.5, 6.0, 6.5][(i + bi) % 4]
            t.bloom(cx, by, r + 1.8, (118, 36, 208), power=2.2, peak=0.5)
            t.disc(cx, by, r, (104, 26, 186))
            t.disc(cx, by, r * 0.74, (172, 88, 246))
            t.disc(cx, by, r * 0.42, (236, 204, 255))
            t.disc(cx, by, max(r * 0.18, 0.6), (255, 255, 255))
            t.disc(cx - r * 0.3, by - r * 0.34, r * 0.26, (255, 255, 255),
                   alpha=0.55)
        t.blit(sheet, ox, oy)


def _paint_shot_missile(sheet: Any) -> None:
    """Air-to-air missile: lit and shadowed flanks, red nose, darted fins and
    a two-tone exhaust with a spent smoke collar that grows each frame."""
    cw, ch = SPRITES["shot_missile"]["cell"]
    for i in range(4):
        ox, oy = tile_xy("shot_missile", i)
        t = Tile(cw, ch, ss=6)
        cx, cy = cw / 2.0, ch / 2.0 - 0.6
        flame = [3.6, 5.2, 4.2, 5.6][i]
        # exhaust first so the airframe sits on top of it
        t.cone(cx, cy + 4.6, cy + 4.6 + flame, 2.5, (255, 150, 44),
               bulb=0.6, alpha=0.9)
        t.cone(cx, cy + 4.6, cy + 4.6 + flame * 0.55, 1.2, (255, 246, 208),
               bulb=0.5)
        t.disc(cx, cy + 5.4 + flame * 0.8, 1.9, (126, 120, 118),
               alpha=0.28 - 0.05 * i)
        t.tri((cx - 1.8, cy + 2.2), (cx - 5.2, cy + 6.6), (cx - 1.8, cy + 6.4),
              (196, 72, 58))
        t.tri((cx + 1.8, cy + 2.2), (cx + 5.2, cy + 6.6), (cx + 1.8, cy + 6.4),
              (150, 52, 44))
        t.capsule(cx, cy - 0.6, 4.6, 2.6, (188, 198, 214))
        t.box(cx - 1.4, cy - 0.6, 2.1, 10.2, (238, 244, 252), alpha=0.85)
        t.box(cx + 1.7, cy - 0.6, 1.9, 10.2, (138, 150, 176), alpha=0.8)
        t.cone(cx, cy - 9.4, cy - 4.4, 2.6, (226, 82, 64), bulb=0.3)
        t.disc(cx, cy - 7.0, 1.0, (255, 236, 214), alpha=0.8)
        t.box(cx, cy + 2.4, 5.2, 1.5, (74, 82, 100))
        t.blit(sheet, ox, oy)


def _paint_shot_enemy(sheet: Any) -> None:
    """Enemy orb: hot core in a cooling shell, rippling rim so the four frames
    counter-rotate, warm bloom so it never disappears on snow or sand."""
    cw, ch = SPRITES["shot_enemy"]["cell"]
    for i in range(4):
        ox, oy = tile_xy("shot_enemy", i)
        t = Tile(cw, ch)
        cx, cy = cw / 2.0, ch / 2.0
        r = [4.0, 4.6, 4.9, 4.6][i]
        wob = (4, i * math.tau / 8.0, 0.16)
        t.bloom(cx, cy, r + 2.6, (255, 84, 36), power=2.4, peak=0.5)
        t.disc(cx, cy, r, (226, 62, 40), wobble=wob)
        t.disc(cx, cy, r * 0.72, (255, 138, 62), wobble=wob)
        t.disc(cx, cy, r * 0.4, (255, 230, 150))
        t.disc(cx, cy, max(r * 0.18, 0.6), (255, 255, 255))
        t.blit(sheet, ox, oy)


def _paint_fx_whip(sheet: Any) -> None:
    """Whip link: a magenta plasma bead wrapped in a bright shell, with two
    charge sparks orbiting the rim so the chain reads as current flowing."""
    cw, ch = SPRITES["fx_whip"]["cell"]
    reach = C.WHIP_BEAD_R           # the radius that actually grabs enemies
    for i in range(4):
        ox, oy = tile_xy("fx_whip", i)
        t = Tile(cw, ch, ss=4)
        cx, cy = cw / 2.0, ch / 2.0
        r = [6.0, 6.8, 7.2, 6.6][i]
        t.bloom(cx, cy, min(cw, ch) / 2.0 - 0.5, (224, 48, 236), power=2.1,
                peak=0.6)
        # Faint shell at the true contact radius, so the grab range is legible
        # from the art instead of learned by getting hit.
        t.annulus(cx, cy, reach - 0.8 + 0.4 * math.sin(i * math.tau / 4.0),
                  3.0, (186, 40, 214), alpha=0.32)
        t.disc(cx, cy, r, (142, 22, 186))
        t.disc(cx, cy, r * 0.72, (212, 72, 244))
        t.disc(cx, cy, r * 0.4, (252, 198, 255))
        t.disc(cx, cy, max(r * 0.18, 0.8), (255, 255, 255))
        t.annulus(cx, cy, r * 0.94, 1.2, (255, 196, 255), alpha=0.45)
        for k in range(2):
            a = i * math.tau / 4.0 + k * math.pi
            t.disc(cx + math.cos(a) * reach, cy + math.sin(a) * reach,
                   1.7, (255, 214, 255), alpha=0.9)
        t.blit(sheet, ox, oy)


# Explosion stages, in order of appearance through every tier's frames.
_EXPLOD_HOT = (255, 255, 252)
_EXPLOD_FIRE = (255, 176, 58)
_EXPLOD_EMBER = (198, 78, 34)
_EXPLOD_SMOKE = (104, 96, 92)


def _explosion_lobes(tier: str, count: int) -> list[tuple[float, float, float]]:
    """Seeded (angle, distance factor, size factor) per fireball lobe.

    The same lobes are reused for every frame of the tier, which is what makes
    the burst read as one object expanding rather than noise re-rolled 16 times.
    """
    rr = _rng_for(f"{tier}:lobes")
    out = []
    for k in range(count):
        out.append((k / count * math.tau + rr.uniform(-0.42, 0.42),
                    rr.uniform(0.45, 1.0), rr.uniform(0.40, 0.78)))
    return out


def _wedge(t: Tile, cx: float, cy: float, ang: float, length: float,
           half_deg: float, colour: RGB, alpha: float) -> None:
    """Radiating spike that is hottest at its root and thins to nothing.

    Drawn as three stacked wedges because a flat-alpha triangle reads as a
    grey paddle over terrain; a hot root with a fading tip reads as light.
    """
    for frac, mul in ((1.0, 0.45), (0.62, 0.72), (0.3, 1.0)):
        a1 = ang - math.radians(half_deg * frac)
        a2 = ang + math.radians(half_deg * frac)
        ln = length * frac
        t.tri((cx, cy),
              (cx + math.cos(a1) * ln, cy + math.sin(a1) * ln),
              (cx + math.cos(a2) * ln, cy + math.sin(a2) * ln),
              colour, alpha=alpha * mul)


def _paint_explosion(sheet: Any, tier: str) -> None:
    """Four-stage burst: flash, fireball, breakup, smoke and embers.

    Same recipe at three sizes; each stage has to read differently at a
    glance, because at arcade speed the player only ever sees one or two
    frames of any single explosion.
    """
    cw, ch = SPRITES[tier]["cell"]
    n = len(SPRITES[tier]["anims"]["boom"]["frames"])
    lobes = _explosion_lobes(tier, 7)
    sparks = _explosion_lobes(tier + ":sparks", 9)
    ss = 4 if cw <= 48 else 2
    rmax = min(cw, ch) / 2.0 - 0.6
    for i in range(n):
        ox, oy = tile_xy(tier, i)
        t = Tile(cw, ch, ss=ss)
        cx, cy = cw / 2.0, ch / 2.0
        p = i / (n - 1)
        if p < 0.2:                                  # 1. flash
            q = p / 0.2
            # Spikes, not blobs: at 160px a fat disc reads as a flower, while
            # thin wedges read as light tearing outward at any tier size.
            for k in range(6):
                a = k * math.tau / 6.0 + 0.3
                reach = rmax * (0.62 + 0.9 * q) * (1.0 if k % 2 else 0.66)
                _wedge(t, cx, cy, a, min(reach, rmax), 6.5, _EXPLOD_HOT,
                       0.5 - 0.15 * q)
            t.bloom(cx, cy, rmax * (0.45 + 1.0 * q), _EXPLOD_FIRE, power=1.9,
                    peak=0.85 - 0.3 * q)
            t.disc(cx, cy, rmax * (0.14 + 0.5 * q),
                   mix(_EXPLOD_HOT, (255, 226, 132), q))
        elif p < 0.55:                               # 2. fireball
            q = (p - 0.2) / 0.35
            body = rmax * (0.55 + 0.38 * q)
            t.bloom(cx, cy, body * 1.5, _EXPLOD_FIRE, power=2.1,
                    peak=0.55 - 0.2 * q)
            # Cool irregular rim behind the hot body.  An annulus here reads as
            # a drawn ring, especially on the 160px tier; a wobbling darker disc
            # behind a wobbling brighter one reads as burning metal.
            t.disc(cx, cy, body * 1.06, mix(_EXPLOD_FIRE, _EXPLOD_EMBER,
                                            0.35 + 0.4 * q),
                   wobble=(5, q * 1.7, 0.13))
            t.disc(cx, cy, body * 0.94,
                   mix((255, 222, 132), _EXPLOD_FIRE, 0.25 + 0.5 * q),
                   wobble=(4, q * 1.7 + 1.0, 0.11))
            for li, (ang, dfac, sfac) in enumerate(lobes):
                churn = ang + 0.12 * q * (1.0 if li % 2 else -1.0)
                dist = body * (0.6 + 0.42 * q) * dfac
                lr = body * sfac * (0.62 - 0.14 * q)
                t.disc(cx + math.cos(churn) * dist,
                       cy + math.sin(churn) * dist, lr,
                       mix(_EXPLOD_FIRE, (255, 236, 168), 0.35 * (1 - q)),
                       wobble=(3, ang + q, 0.18), alpha=0.88)
            for ang, dfac, sfac in sparks[:4]:
                dist = body * (0.22 + 0.5 * q) * dfac
                t.disc(cx + math.cos(ang) * dist, cy + math.sin(ang) * dist,
                       body * 0.34 * sfac,
                       mix(_EXPLOD_FIRE, _EXPLOD_EMBER, 0.5 + 0.3 * q),
                       wobble=(3, ang, 0.22), alpha=0.45)
            if q < 0.85:                             # lingering white core
                cr = rmax * (0.42 - 0.46 * q)
                t.bloom(cx, cy, cr * 1.7, _EXPLOD_HOT, power=2.0, peak=0.55)
                t.disc(cx, cy, cr, _EXPLOD_HOT, edge=2.2,
                       wobble=(3, q * 3.0, 0.15), alpha=0.92)
        elif p < 0.8:                                # 3. breakup
            q = (p - 0.55) / 0.25
            body = rmax * (0.9 + 0.16 * q)
            # Ash core: cooling fire still fills the middle until smoke does.
            t.disc(cx, cy, body * (0.86 - 0.14 * q),
                   mix(_EXPLOD_FIRE, _EXPLOD_SMOKE, 0.15 + 0.45 * q),
                   wobble=(4, q * 2.0, 0.14), alpha=0.88 - 0.22 * q)
            for li, (ang, dfac, sfac) in enumerate(lobes):
                lr = body * sfac * (0.6 - 0.2 * q)
                dist = min(body * (0.7 + 0.3 * q) * dfac, rmax - lr)
                ang = ang + 0.14 * (1.0 if li % 2 else -1.0)
                t.disc(cx + math.cos(ang) * dist, cy + math.sin(ang) * dist,
                       lr, mix(_EXPLOD_FIRE, _EXPLOD_EMBER, 0.4 + 0.45 * q),
                       wobble=(4, ang, 0.2), alpha=0.85 - 0.28 * q)
        else:                                        # 4. smoke and embers
            q = (p - 0.8) / 0.2
            for ang, dfac, sfac in lobes:
                lr = rmax * sfac * (0.5 + 0.2 * q)
                dist = min(rmax * (0.78 + 0.2 * q) * dfac, rmax - lr)
                t.disc(cx + math.cos(ang) * dist, cy + math.sin(ang) * dist,
                       lr, _EXPLOD_SMOKE, wobble=(5, ang, 0.3),
                       alpha=0.46 * (1 - 0.85 * q))
            for si, (ang, dfac, _sfac) in enumerate(sparks):
                if si % 3:
                    continue
                dist = min(rmax * (0.42 + 0.6 * q) * dfac, rmax - 1.5)
                t.disc(cx + math.cos(ang) * dist, cy + math.sin(ang) * dist,
                       max(rmax * 0.07, 1.1),
                       mix(_EXPLOD_FIRE, _EXPLOD_EMBER, q),
                       alpha=0.95 - 0.8 * q)
        t.window(rmax, edge=max(1.6, rmax * 0.14))
        t.blit(sheet, ox, oy)


def _rotor_blades(sheet, cx: float, cy: float, r: float, n: int,
                  angle_deg: float, col) -> None:
    import pygame
    for k in range(n):
        a = math.radians(angle_deg + k * 360 / n)
        pygame.draw.line(sheet, col,
                         (cx + math.cos(a) * r, cy + math.sin(a) * r),
                         (cx + math.cos(a) * r * 0.25,
                          cy + math.sin(a) * r * 0.25), 3)


def _paint_e_grunt(sheet: Any) -> None:
    """Red wasp-pod: teardrop hull (nose down) with spinning rotor pods."""
    import pygame
    cw, ch = SPRITES["e_grunt"]["cell"]
    col = (205, 65, 75)
    for i in range(4):
        ox, oy = tile_xy("e_grunt", i)
        cx, cy = ox + cw // 2, oy + ch // 2
        for sx in (-10, 10):
            pygame.draw.circle(sheet, _shade(col, -70), (cx + sx, cy - 2), 5)
            _rotor_blades(sheet, cx + sx, cy - 2, 10, 2, i * 45 + sx,
                          (180, 185, 195))
        hull = [(cx, cy + 13), (cx - 8, cy - 6), (cx - 4, cy - 12),
                (cx + 4, cy - 12), (cx + 8, cy - 6)]
        pygame.draw.polygon(sheet, col, hull)
        pygame.draw.polygon(sheet, _shade(col, -60), hull, 2)
        pygame.draw.circle(sheet, (255, 200, 90), (cx, cy - 4), 3)  # eye


def _paint_e_weaver(sheet: Any) -> None:
    """Orange chevron dart with shimmering swept wings."""
    import pygame
    cw, ch = SPRITES["e_weaver"]["cell"]
    col = (225, 145, 55)
    for i in range(4):
        ox, oy = tile_xy("e_weaver", i)
        cx, cy = ox + cw // 2, oy + ch // 2
        flap = [0, 2, 3, 1][i]
        pts = [(cx, cy + 12), (cx + 12, cy + flap), (cx + 4, cy - 4),
               (cx, cy - 10), (cx - 4, cy - 4), (cx - 12, cy + flap)]
        pygame.draw.polygon(sheet, col, pts)
        pygame.draw.polygon(sheet, _shade(col, -55), pts, 2)
        pygame.draw.line(sheet, (255, 235, 180), (cx, cy - 6), (cx, cy + 8), 2)


def _paint_e_darter(sheet: Any) -> None:
    """Yellow needle, engine streak flicker."""
    import pygame
    cw, ch = SPRITES["e_darter"]["cell"]
    col = (240, 205, 85)
    for i in range(4):
        ox, oy = tile_xy("e_darter", i)
        cx, cy = ox + cw // 2, oy + ch // 2
        pts = [(cx, cy + 12), (cx - 4, cy - 8), (cx + 4, cy - 8)]
        pygame.draw.polygon(sheet, col, pts)
        pygame.draw.polygon(sheet, _shade(col, -60), pts, 2)
        streak = [3, 6, 4, 7][i]
        pygame.draw.line(sheet, (255, 170, 60), (cx, cy - 8),
                         (cx, cy - 8 - streak), 2)


def _paint_e_gunner(sheet: Any) -> None:
    """Purple hoverpod: glowing orb caged in metal claws (core pulses)."""
    import pygame
    cw, ch = SPRITES["e_gunner"]["cell"]
    for i in range(6):
        ox, oy = tile_xy("e_gunner", i)
        cx, cy = ox + cw // 2, oy + ch // 2
        pulse = [5, 6, 7, 8, 7, 6][i]
        for k in range(4):
            a = math.radians(45 + k * 90 + i)
            pygame.draw.line(sheet, (150, 90, 165),
                             (cx + math.cos(a) * 8, cy + math.sin(a) * 8),
                             (cx + math.cos(a) * 17, cy + math.sin(a) * 17), 4)
            pygame.draw.circle(sheet, (110, 60, 125),
                               (cx + math.cos(a) * 17,
                                cy + math.sin(a) * 17), 3)
        pygame.draw.circle(sheet, (170, 70, 195), (cx, cy), 10)
        pygame.draw.circle(sheet, (230, 140, 255), (cx, cy), pulse)
        pygame.draw.circle(sheet, (255, 235, 255), (cx, cy), max(2, pulse - 3))


def _paint_e_sentry(sheet: Any) -> None:
    """Blue octagon turret with a rotating barrel (8-frame spin)."""
    import pygame
    cw, ch = SPRITES["e_sentry"]["cell"]
    col = (95, 150, 220)
    for i in range(8):
        ox, oy = tile_xy("e_sentry", i)
        cx, cy = ox + cw // 2, oy + ch // 2
        pts = [(cx + 14 * math.cos(math.tau * k / 8 + math.tau / 16),
                cy + 14 * math.sin(math.tau * k / 8 + math.tau / 16))
               for k in range(8)]
        pygame.draw.polygon(sheet, col, pts)
        pygame.draw.polygon(sheet, _shade(col, -60), pts, 2)
        a = math.tau * i / 8
        pygame.draw.line(sheet, (60, 70, 85), (cx, cy),
                         (cx + math.cos(a) * 17, cy + math.sin(a) * 17), 6)
        pygame.draw.line(sheet, (200, 215, 235), (cx, cy),
                         (cx + math.cos(a) * 16, cy + math.sin(a) * 16), 4)
        pygame.draw.circle(sheet, (255, 240, 140), (cx, cy), 3)


def _paint_e_heavy(sheet: Any) -> None:
    """Dark-red armour tank: scrolling treads + recoiling cannon."""
    import pygame
    cw, ch = SPRITES["e_heavy"]["cell"]
    col = (150, 65, 65)
    for i in range(6):
        ox, oy = tile_xy("e_heavy", i)
        cx, cy = ox + cw // 2, oy + ch // 2
        for tx in range(5):
            seg = (tx + i % 3) % 5
            shade = _shade(col, -95 if seg % 2 else -65)
            pygame.draw.rect(sheet, shade, (cx - 24 + tx * 10, cy + 10, 9, 10))
            pygame.draw.rect(sheet, shade, (cx - 24 + tx * 10, cy - 20, 9, 10))
        hull = [(cx - 20, cy + 8), (cx + 20, cy + 8), (cx + 16, cy - 12),
                (cx - 16, cy - 12)]
        pygame.draw.polygon(sheet, col, hull)
        pygame.draw.polygon(sheet, _shade(col, -55), hull, 2)
        recoil = [0, -3, -1, 0, -3, -1][i]
        pygame.draw.circle(sheet, (90, 95, 105), (cx, cy - 2), 9)
        pygame.draw.rect(sheet, (70, 75, 85), (cx - 3, cy + 2 + recoil, 6, 16))
        pygame.draw.circle(sheet, (255, 210, 120), (cx, cy - 2), 3)


def _paint_e_bomber(sheet: Any) -> None:
    """Mustard munitions carrier: twin bomb drums, belly racks, red eye."""
    import pygame
    cw, ch = SPRITES["e_bomber"]["cell"]
    col = (206, 172, 62)
    for i in range(6):
        ox, oy = tile_xy("e_bomber", i)
        cx, cy = ox + cw // 2, oy + ch // 2
        for sx in (-26, 26):                     # bomb-bay drums
            pygame.draw.rect(sheet, _shade(col, -60),
                             (cx + sx - 12, cy - 20, 24, 40), border_radius=8)
            pygame.draw.rect(sheet, _shade(col, -95),
                             (cx + sx - 12, cy - 20, 24, 40), 2,
                             border_radius=8)
            for sy in (-11, 1, 11):              # shells stacked inside
                pygame.draw.circle(sheet, (150, 156, 120), (cx + sx, cy + sy),
                                   4)
        hull = [(cx - 16, cy - 22), (cx + 16, cy - 22), (cx + 13, cy + 14),
                (cx, cy + 26), (cx - 13, cy + 14)]
        pygame.draw.polygon(sheet, col, hull)
        pygame.draw.polygon(sheet, _shade(col, -70), hull, 2)
        for sx in (-7, 7):                       # release racks
            pygame.draw.rect(sheet, (58, 54, 48), (cx + sx - 3, cy + 16, 6, 9))
        eye = 4 + (i % 3)                        # targeting eye breathes
        pygame.draw.circle(sheet, (240, 70, 60), (cx, cy + 18), eye)
        pygame.draw.circle(sheet, (255, 220, 190), (cx, cy + 18), 2)


def _paint_e_splitter(sheet: Any) -> None:
    """Crystalline pod: bone plates over a hot seam, green core."""
    import pygame
    cw, ch = SPRITES["e_splitter"]["cell"]
    shell = (226, 218, 214)
    for i in range(6):
        ox, oy = tile_xy("e_splitter", i)
        cx, cy = ox + cw // 2, oy + ch // 2
        pulse = (i % 6) / 5.0
        for sx in (-1, 1):                       # carapace halves
            pts = [(cx, cy - 20), (cx + sx * 15, cy - 6),
                   (cx + sx * 12, cy + 14), (cx, cy + 20)]
            pts = [(x if sx > 0 else 2 * cx - x, y) for x, y in pts]
            pygame.draw.polygon(sheet, shell, pts)
            pygame.draw.polygon(sheet, (126, 78, 168), pts, 2)
        hot = int(120 + 120 * pulse)             # the fracture seam glows
        pygame.draw.line(sheet, (250, hot, 40), (cx, cy - 19), (cx, cy + 19),
                         2)
        for sy in (-10, 6):                      # circuit veins
            pygame.draw.line(sheet, (110, 220, 210), (cx - 12, cy + sy),
                             (cx + 12, cy + sy), 1)
        pygame.draw.circle(sheet, (90, 235, 130), (cx, cy), 4 + int(2 * pulse))
        for sx, sy in ((-18, -12), (18, -12), (-16, 14), (16, 14)):
            pygame.draw.circle(sheet, (140, 92, 186), (cx + sx, cy + sy), 4)


def _paint_e_rammer(sheet: Any) -> None:
    """Chrome suicide dart: needle nose down, razor fins, engine streak."""
    import pygame
    cw, ch = SPRITES["e_rammer"]["cell"]
    for i in range(4):
        ox, oy = tile_xy("e_rammer", i)
        cx, cy = ox + cw // 2, oy + ch // 2
        fins = [(cx, cy + 24), (cx + 5, cy + 4), (cx + 20, cy - 10),
                (cx + 4, cy - 12), (cx - 4, cy - 12), (cx - 20, cy - 10),
                (cx - 5, cy + 4)]
        pygame.draw.polygon(sheet, (196, 200, 208), fins)
        pygame.draw.polygon(sheet, (52, 50, 58), fins, 2)
        body = [(cx, cy + 26), (cx - 5, cy - 4), (cx - 3, cy - 20),
                (cx + 3, cy - 20), (cx + 5, cy - 4)]
        pygame.draw.polygon(sheet, (226, 228, 234), body)
        for sx in (-1, 1):                       # crimson stripes
            pygame.draw.line(sheet, (210, 46, 46),
                             (cx + sx * 3, cy - 14), (cx + sx * 4, cy + 8), 2)
        pygame.draw.circle(sheet, (240, 240, 250), (cx, cy + 24), 2)  # tip
        streak = (6, 12, 8, 15)[i]               # afterburner flicker
        pygame.draw.line(sheet, (255, 168, 70), (cx - 3, cy - 20),
                         (cx - 3, cy - 20 - streak), 2)
        pygame.draw.line(sheet, (255, 168, 70), (cx + 3, cy - 20),
                         (cx + 3, cy - 20 - streak), 2)


def _paint_e_shard(sheet: Any) -> None:
    """Splitter fragment: a hot splinter of carapace."""
    import pygame
    cw, ch = SPRITES["e_shard"]["cell"]
    for i in range(4):
        ox, oy = tile_xy("e_shard", i)
        cx, cy = ox + cw // 2, oy + ch // 2
        lean = (-2, 0, 2, 0)[i]
        pts = [(cx + lean, cy + 11), (cx - 7, cy - 2), (cx - 2, cy - 10),
               (cx + 5, cy - 6)]
        pygame.draw.polygon(sheet, (214, 202, 214), pts)
        pygame.draw.polygon(sheet, (138, 84, 182), pts, 2)
        ember = 150 + 22 * i                     # the broken edge stays hot
        pygame.draw.line(sheet, (252, ember, 60),
                         (cx - 4, cy - 2), (cx + lean, cy + 9), 2)


def _paint_e_boss(sheet: Any, name: str = "e_boss1") -> None:
    """Sector boss: winged command hull, side gun pods, pulsing red core.

    The silhouette is authored for the 112 px classic cell and scaled to the
    sheet's own cell, so the wide per-sector boss sheets still fall back to
    painted art when the baked sources are absent.
    """
    import pygame
    cw, ch = SPRITES[name]["cell"]
    s = min(cw, ch) / 112.0

    def d(v: float) -> int:
        return int(round(v * s))

    col = (200, 60, 120)
    for i in range(6):
        ox, oy = tile_xy(name, i)
        cx, cy = ox + cw // 2, oy + ch // 2
        for sx in (-1, 1):
            wing = [(cx + d(sx * 18), cy + d(-8)), (cx + d(sx * 54), cy + d(-20)),
                    (cx + d(sx * 52), cy + d(6)), (cx + d(sx * 22), cy + d(10))]
            pygame.draw.polygon(sheet, _shade(col, -30), wing)
            pygame.draw.polygon(sheet, _shade(col, -75), wing, 2)
            pygame.draw.rect(sheet, (120, 125, 135),
                             (cx + d(sx * 36) - d(5), cy + d(-2), d(10), d(18)))
        hull = [(cx + d(-26), cy + d(-26)), (cx + d(26), cy + d(-26)),
                (cx + d(34), cy + d(8)), (cx + d(12), cy + d(26)),
                (cx + d(-12), cy + d(26)), (cx + d(-34), cy + d(8))]
        pygame.draw.polygon(sheet, col, hull)
        pygame.draw.polygon(sheet, _shade(col, -60), hull, max(1, d(3)))
        pygame.draw.rect(sheet, _shade(col, 40),
                         (cx + d(-10), cy + d(-22), d(20), d(8)))
        pulse = [10, 12, 14, 16, 14, 12][i]
        pygame.draw.circle(sheet, (255, 90, 60), (cx, cy), d(pulse))
        pygame.draw.circle(sheet, (255, 220, 120), (cx, cy), max(3, d(pulse - 5)))
        pygame.draw.circle(sheet, (255, 255, 255), (cx, cy), max(2, d(pulse - 9)))


def _paint_p_ship(sheet: Any) -> None:
    """Player fighter, original design inspired by arcade shmup silhouettes:
    white nose cone, red armor with engraved lines, amber canopy, outboard
    cream flaps, twin engine cans with exhaust plumes. Painted once at 3x
    supersample; bank frames are rotated/compressed copies (classic 2D
    bank-canvas trick), left bank mirrors right."""
    import pygame
    from pygame.transform import rotozoom, smoothscale
    CW, CH = SPRITES["p_ship"]["cell"]
    SS = 3
    MW, MH = CW * SS, CH * SS           # 192 x 216 master
    CX = MW // 2
    RED = (198, 46, 58)
    RED_D = (142, 28, 40)
    RED_DD = (102, 18, 28)
    RED_L = (236, 120, 110)
    CREAM = (226, 214, 198)
    CREAM_D = (168, 152, 140)
    SILV = (210, 214, 222)
    SILV_D = (134, 140, 150)
    OUT = (40, 18, 26)
    GRN = (62, 122, 84)

    # all shape coordinates below are MASTER pixels (MW x MH)
    def poly(s, pts, col, w=0):
        pygame.draw.polygon(s, col, pts)
        if w:
            pygame.draw.polygon(s, OUT, pts, w)

    def line(s, a, b, col, w):
        pygame.draw.line(s, col, a, b, w)

    def ell(s, cx, cy, rx, ry, col, w=0):
        r = pygame.Rect(int(cx - rx), int(cy - ry), int(2 * rx), int(2 * ry))
        pygame.draw.ellipse(s, col, r, w)

    def mpx(pts):
        """Right-half polygon points + mirrored copy (closed symmetric poly)."""
        return pts + [(2 * CX - px, py) for px, py in reversed(pts)]

    def paint_master(plume: float) -> Any:
        """plume: 1.0 = long frame A, 0.55 = short frame B (engine pulse)."""
        s = pygame.Surface((MW, MH), pygame.SRCALPHA)
        s.fill((0, 0, 0, 0))
        # --- exhaust plumes (drawn under the airframe) --------------------
        for ex in (CX - 42, CX + 42):
            for col, ln, wid in (((255, 110, 40, 190), 44 * plume, 13),
                                 ((255, 190, 90, 220), 30 * plume, 8),
                                 ((255, 250, 230, 240), 16 * plume, 4)):
                poly(s, [(ex - wid, 168), (ex + wid, 168),
                         (ex + wid * 0.35, 168 + ln), (ex - wid * 0.35, 168 + ln)],
                     col)
        poly(s, [(CX - 5, 176), (CX + 5, 176),
                 (CX + 2, 176 + 28 * plume), (CX - 2, 176 + 28 * plume)],
             (255, 170, 70, 200))
        # --- tail spike ----------------------------------------------------
        poly(s, [(CX + 3, 148), (CX + 8, 150), (CX + 3, 212),
                 (CX - 3, 212), (CX - 8, 150), (CX - 3, 148)], SILV_D, 2)
        # --- main wings (delta, swept back) --------------------------------
        wing = [(CX + 13, 56), (CX + 66, 122), (CX + 80, 146), (CX + 72, 162),
                (CX + 26, 146), (CX + 15, 120)]
        poly(s, mpx(wing), RED, 2)
        # leading-edge highlight + engraved sweep lines
        line(s, (CX + 15, 60), (CX + 66, 124), RED_L, SS)
        line(s, (CX + 22, 92), (CX + 58, 140), RED_D, SS)
        for bx, by in ((CX + 44, 128), (CX + 56, 138)):
            poly(s, [(bx - 4, by), (bx + 4, by + 4), (bx + 4, by + 10),
                     (bx - 4, by + 6)], RED_DD)
        # circuit-flecked intakes inboard of the wing roots
        rng = _rng_for("p_ship_circuits")
        for _ in range(26):
            gx = rng.uniform(CX + 20, CX + 40)
            gy = rng.uniform(96, 136)
            if gy > 56 + (gx - CX) * 1.05:            # inside wing sweep
                poly(s, [(gx, gy), (gx + 3.5, gy), (gx + 3.5, gy + 3.5),
                         (gx, gy + 3.5)], GRN)
        # --- outboard cream flaps ------------------------------------------
        flap = [(CX + 66, 134), (CX + 86, 144), (CX + 82, 170), (CX + 60, 162)]
        poly(s, mpx(flap), CREAM, 2)
        line(s, (CX + 70, 142), (CX + 80, 162), CREAM_D, SS)
        # --- gun pods ahead of the wing roots ------------------------------
        for gx in (CX + 20, CX - 20):
            poly(s, [(gx - 3.5, 44), (gx + 3.5, 44), (gx + 3.5, 88),
                     (gx - 3.5, 88)], SILV, 2)
            poly(s, [(gx - 2, 36), (gx + 2, 36), (gx + 2, 46),
                     (gx - 2, 46)], SILV_D)
        # --- engine cans ----------------------------------------------------
        for ex in (CX - 42, CX + 42):
            ell(s, ex, 148, 15, 25, SILV, 2)
            ell(s, ex, 138, 15, 10, RED)               # red band
            ell(s, ex, 158, 13, 9, SILV_D)             # nozzle housing
            ell(s, ex, 166, 9, 6, (60, 56, 62))        # nozzle mouth
            ell(s, ex, 167, 4, 3, (255, 170, 80))      # burning bleed
        # --- fuselage -------------------------------------------------------
        body = [(CX, 4), (CX + 8, 26), (CX + 14, 60), (CX + 16, 120),
                (CX + 12, 168), (CX - 12, 168), (CX - 16, 120),
                (CX - 14, 60), (CX - 8, 26)]
        poly(s, body, RED, 2)
        nose = [(CX, 4), (CX + 7, 24), (CX + 5, 34), (CX - 5, 34), (CX - 7, 24)]
        poly(s, nose, (240, 238, 240), 2)              # white nose cone
        # engraved side lines (the reference's armour seams)
        line(s, (CX + 11, 66), (CX + 13, 116), RED_DD, SS)
        line(s, (CX - 11, 66), (CX - 13, 116), RED_DD, SS)
        # --- canopy (black shroud, amber glass, hot highlight) -------------
        ell(s, CX, 62, 10, 22, (24, 20, 26))
        ell(s, CX, 62, 8, 19, (208, 122, 34))
        ell(s, CX, 58, 6, 12, (255, 190, 86))
        ell(s, CX - 2, 52, 2.5, 5, (255, 244, 214))
        line(s, (CX - 7, 62), (CX + 7, 62), (120, 66, 26), SS)
        # --- rear armour block + intakes -----------------------------------
        poly(s, [(CX - 10, 128), (CX + 10, 128), (CX + 12, 152),
                 (CX - 12, 152)], RED_D, 2)
        ell(s, CX - 9, 118, 4, 7, (30, 26, 32))
        ell(s, CX + 9, 118, 4, 7, (30, 26, 32))
        return s

    def bake_frame(s_master: Any, level: int, sign: int, ox: int, oy: int) -> None:
        """Blit one bank frame into the sheet at logical cell (ox, oy)."""
        angle = -sign * level * 8.0                    # right bank = clockwise
        xs = 1.0 - 0.045 * level                       # foreshortening
        surf = s_master
        if level:
            surf = rotozoom(surf, angle, 1.0)
            surf = smoothscale(surf, (max(1, int(surf.get_width() * xs)),
                                      surf.get_height()))
        final = smoothscale(surf, (CW, CH))
        sheet.blit(final, (ox, oy))

    # (variant, level, sign) for tiles 0..9 — left mirrors right
    recipe = [(1.0, 0, 0), (0.55, 0, 0),
              (1.0, 1, +1), (1.0, 2, +1), (0.55, 1, +1), (0.55, 2, +1),
              (1.0, 1, -1), (1.0, 2, -1), (0.55, 1, -1), (0.55, 2, -1)]
    masters = {True: paint_master(1.0), False: paint_master(0.55)}
    for i, (plume, level, sign) in enumerate(recipe):
        ox, oy = tile_xy("p_ship", i)
        bake_frame(masters[plume > 0.9], level, sign, ox, oy)


# ---- falling power-ups ----------------------------------------------------
# One pod recipe for the whole family: casing, top-lit bevel, recessed window,
# rivets, then a kind-specific symbol that animates on its own frames (fuse
# spark, blinking mine lamp, whip bead running along the coil). Hazards get an
# octagonal plate, so "do not touch" is a shape and not only a colour.
_POD_EDGE = (14, 17, 24)
_POD_FRAME_LO = (44, 50, 64)
_POD_FRAME_HI = (198, 210, 228)
_POD_RIVET = (166, 178, 196)
_WHITE = (255, 255, 255)
_ITEM_FRAMES = len(SPRITES["items"]["anims"]["weapon"]["frames"])


def _spike(
        cx: float, cy: float, ang: float, r0: float, r1: float, half_w: float,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    # Fixed-arity on purpose: ``t.tri(*_spike(...), colour)`` only typechecks
    # when mypy can see the unpacked count is exactly three vertices.
    """Tip-outward triangle: mine spikes, star points, exhaust tongues."""
    ca, sa = math.cos(ang), math.sin(ang)
    px, py = -sa, ca
    return ((cx + ca * r1, cy + sa * r1),
            (cx + ca * r0 + px * half_w, cy + sa * r0 + py * half_w),
            (cx + ca * r0 - px * half_w, cy + sa * r0 - py * half_w))


def _plate(t: Tile, cx: float, cy: float, size: float, colour: RGB,
           edge: float, hazard: bool, alpha: float = 1.0) -> None:
    """The item's silhouette: bevelled square plate, or cut octagon for a
    hazard. One function so every layer of a pod agrees on the outline."""
    if hazard:
        # cut octagon: a *slightly* clipped octagon, not a flower. Past about
        # 0.05 wobble the plate turns organic and swamps the symbol inside it.
        t.disc(cx, cy, size / 2.0, colour, edge=edge,
               wobble=(8, math.tau / 16.0, 0.048), alpha=alpha)
    else:
        t.rrect(cx, cy, size, size, size * 0.27, colour, edge=edge, alpha=alpha)


def _pod_shell(t: Tile, c: float, hull: RGB, accent: RGB,
               hazard: bool) -> None:
    """Hardware: thickness, casing, lit rim, recessed window, rivets.

    The stack is deliberately 6 plates deep (silhouette, dark casing, glowing
    rim, hull, lit upper face, window recess): at 20 px that is what replaces
    texture, and the rim — one plate of accent-bright metal between two dark
    ones — is what keeps the pod separable from a dark terrain tile.
    """
    _plate(t, c, c + 1.9, 22.6, _POD_EDGE, 0.9, hazard, 0.55)
    _plate(t, c, c, 22.2, _POD_FRAME_LO, 0.9, hazard)
    _plate(t, c, c, 21.0, mix(accent, _WHITE, 0.12), 0.8, hazard, 0.95)
    _plate(t, c, c - 0.4, 19.6, hull, 0.8, hazard)
    _plate(t, c, c - 1.3, 17.6, mix(hull, _POD_FRAME_HI, 0.42), 0.85, hazard)
    _plate(t, c, c, 16.6, mix(hull, (4, 6, 10), 0.55), 0.8, hazard)
    t.bloom(c, c - 0.4, 8.6, accent, power=2.0, peak=0.52)
    # glass edge inside the recess: lifts the symbol off the dark window so it
    # survives being drawn 20 px across a busy screen
    t.annulus(c, c, 8.1, 1.5, mix(accent, _WHITE, 0.25), edge=0.7, alpha=0.3)
    # bevel: bright sliver where the top edge catches the light, shadow below
    t.box(c, c - 9.6, 11.0, 1.5, mix(_POD_FRAME_HI, accent, 0.35),
          edge=0.6, alpha=0.5)
    t.box(c, c + 9.8, 10.4, 1.4, (10, 12, 18), edge=0.6, alpha=0.45)
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            rx, ry = c + sx * 9.4, c + sy * 9.4
            t.disc(rx, ry, 1.1, (26, 30, 40), edge=0.45)
            t.disc(rx - 0.25, ry - 0.3, 0.6, _POD_RIVET, edge=0.35)


def _item_symbol(t: Tile, c: float, kind: str, accent: RGB, i: int) -> None:
    """The icon inside the window, and whatever it does on frame ``i``."""
    key = mix(accent, _WHITE, 0.45)
    dark = mix(accent, (6, 8, 12), 0.78)
    ph = math.tau * i / _ITEM_FRAMES

    if kind == "weapon":                       # up arrow, rising on the beat
        # One unmistakable arrow. Two stacked triangles read as a tree at 20 px;
        # head + shaft is the glyph for "weapon up" in every shmup ever made.
        bob = -0.9 * math.sin(ph)
        y0 = c - 1.4 + bob
        for shade, grow in ((dark, 1.5), (key, 0.0)):
            t.tri((c, y0 - 5.6 - grow), (c - 5.4 - grow, y0 - 0.4 + grow),
                  (c + 5.4 + grow, y0 - 0.4 + grow), shade, edge=0.6)
            t.box(c, y0 + 2.9, 3.6 + grow, 5.4 + grow, shade, edge=0.6)
        t.box(c - 0.7, y0 + 2.4, 1.2, 4.2, _WHITE, edge=0.4, alpha=0.45)
        t.bloom(c, c, 7.8, accent, power=2.2, peak=0.22 + 0.12 * math.sin(ph))
    elif kind == "missile":                    # dart with a flickering motor
        # Plume stays inside the window and flares from the nozzle: a long even
        # cone below the airframe reads as a stick, not as thrust.
        flame = 4.0 + 1.1 * (0.5 + 0.5 * math.sin(ph * 2.0))
        t.cone(c, c + 2.9, c + flame, 2.3, (255, 140, 44), edge=0.8, bulb=0.9,
               alpha=0.9)
        t.cone(c, c + 3.0, c + flame - 1.0, 1.0, (255, 244, 200), edge=0.5,
               alpha=0.9)
        for sx in (-1.0, 1.0):
            t.tri((c + sx * 1.7, c - 0.6), (c + sx * 4.6, c + 3.6),
                  (c + sx * 1.7, c + 2.9), mix(accent, dark, 0.25), edge=0.5)
        t.capsule(c, c - 1.4, 3.2, 2.05, (200, 208, 222), edge=0.45)
        t.capsule(c - 0.6, c - 1.8, 2.7, 0.75, _WHITE, edge=0.4, alpha=0.55)
        t.tri((c, c - 7.0), (c - 2.1, c - 3.2), (c + 2.1, c - 3.2), key,
              edge=0.45)
        t.disc(c, c - 2.1, 1.15, mix(accent, _WHITE, 0.6), edge=0.4)
    elif kind == "bomb":                       # steel shell, live fuse
        # Dark steel with a hard specular, not a warm ball: the medal is
        # already the bright round thing on this sheet.
        spark = 0.35 + 0.65 * (1.0 if i % 2 == 0 else 0.2)
        t.box(c + 2.4, c - 4.4, 2.2, 3.0, (96, 102, 116), edge=0.5)
        t.capsule(c + 3.0, c - 6.2, 1.0, 0.7, (150, 128, 96), edge=0.45)
        t.disc(c - 0.4, c + 1.4, 5.1, (24, 27, 34), edge=0.6)
        t.disc(c - 0.4, c + 1.4, 4.4, (74, 80, 92), edge=0.5)
        t.disc(c - 0.4, c + 2.2, 3.4, (48, 53, 64), edge=0.6, alpha=0.75)
        t.disc(c - 2.2, c - 0.6, 1.7, mix(_WHITE, (190, 200, 220), 0.2),
               edge=0.5, alpha=0.8)
        t.bloom(c + 3.0, c - 7.2, 5.0, (255, 190, 90), power=2.0, peak=spark)
        t.disc(c + 3.0, c - 7.2, 1.4 + 0.6 * (i % 2),
               mix((255, 248, 215), accent, 0.3), edge=0.4,
               alpha=0.5 + 0.5 * spark)
    elif kind == "shield":                     # heraldic plate, rim surging
        # Round top + point at the bottom is the shield silhouette; a hexagon
        # with bars in it reads as a speaker grille.
        pulse = 0.45 + 0.4 * math.sin(ph)

        def plate(scale: float, colour: RGB, alpha: float) -> None:
            t.disc(c, c - 1.5 * scale, 5.5 * scale, colour, edge=0.6,
                   alpha=alpha)
            t.tri((c - 5.5 * scale, c - 0.9 * scale),
                  (c + 5.5 * scale, c - 0.9 * scale),
                  (c, c + 6.6 * scale), colour, edge=0.6, alpha=alpha)

        plate(1.22, (12, 18, 32), 0.95)     # dark relief behind: the outline
        plate(1.06, mix(accent, (18, 32, 60), 0.42), 1.0)
        t.disc(c, c - 2.6, 3.4, key, edge=0.7, alpha=0.3 + 0.25 * pulse)
        t.box(c, c - 1.2, 1.6, 5.0, key, edge=0.5, alpha=0.5 + 0.4 * pulse)
        t.disc(c - 2.2, c - 3.0, 1.5, _WHITE, edge=0.55, alpha=0.45)
        t.disc(c, c + 2.6, 1.4, key, edge=0.5, alpha=0.4 + 0.35 * pulse)
    elif kind == "medal":                      # struck coin with a spinning star
        t.disc(c, c, 6.7, mix(accent, (60, 44, 14), 0.4), edge=0.6)
        t.disc(c, c, 5.6, mix(accent, (128, 92, 22), 0.3), edge=0.55)
        t.annulus(c, c, 5.9, 1.1, mix(accent, _WHITE, 0.45), edge=0.5,
                  alpha=0.75)
        # struck star: dark relief first, bright star on top, or the whole coin
        # blooms into one bright blob at 20 px
        for shade, grow, alpha in ((dark, 1.5, 0.9), (mix(_WHITE, accent, 0.3),
                                                       0.0, 0.95)):
            for k in range(5):
                a = -math.tau / 4.0 + k * math.tau / 5.0 + ph * 0.25
                t.tri(*_spike(c, c, a, 1.6, 4.4 + grow, 1.15 + grow * 0.4),
                      shade, edge=0.45, alpha=alpha)
        t.disc(c, c, 1.2, _WHITE, edge=0.4, alpha=0.85)
        t.disc(c - 2.4, c - 2.6, 1.1, _WHITE, edge=0.45, alpha=0.35)
    elif kind == "extra_life":                 # heart that beats
        beat = 1.0 + 0.06 * math.sin(ph)
        body = mix((250, 96, 128), accent, 0.45)
        for sx in (-1.0, 1.0):
            t.disc(c + sx * 2.5, c - 2.0, 2.9 * beat, mix(body, (60, 10, 24),
                                                          0.25), edge=0.55)
        t.tri((c - 5.3, c - 0.6), (c + 5.3, c - 0.6), (c, c + 6.2 * beat),
              mix(body, (60, 10, 24), 0.25), edge=0.55)
        for sx in (-1.0, 1.0):
            t.disc(c + sx * 2.5, c - 2.3, 2.1 * beat, body, edge=0.5)
        t.tri((c - 4.1, c - 0.7), (c + 4.1, c - 0.7), (c, c + 5.0 * beat), body,
              edge=0.5)
        t.tri((c - 3.2, c - 1.2), (c + 3.2, c - 1.2), (c, c + 3.9 * beat),
              mix(body, _WHITE, 0.18), edge=0.45)
        t.disc(c - 2.4, c - 2.8, 1.25, mix(_WHITE, body, 0.3), edge=0.45,
               alpha=0.75)
    elif kind == "whip":                       # coiled lash, bead runs the coil
        t.arc(c, c - 1.4, 4.6, 2.5, -math.tau * 0.05, 1.5, dark, edge=0.6,
              taper=0.5, alpha=0.95)
        t.arc(c, c + 1.6, 4.4, 2.4, math.tau * 0.45, 1.5, dark, edge=0.6,
              taper=0.5, alpha=0.95)
        t.arc(c, c - 1.4, 4.6, 1.3, -math.tau * 0.05, 1.4, key, edge=0.5,
              taper=0.4, alpha=0.8)
        t.arc(c, c + 1.6, 4.4, 1.3, math.tau * 0.45, 1.4, key, edge=0.5,
              taper=0.4, alpha=0.8)
        ba = -math.tau * 0.05 + ph
        bx, by = c + math.cos(ba) * 4.6, c - 1.4 + math.sin(ba) * 4.6
        t.bloom(bx, by, 5.4, accent, power=2.0, peak=0.6)
        t.disc(bx, by, 2.1, mix(_WHITE, accent, 0.35), edge=0.45)
        t.disc(bx, by, 0.9, _WHITE, edge=0.35)
    elif kind == "jammer":                     # broadcasting antenna, pulsing
        # No "prohibited" slash through it: ring + mast + slash is three shapes
        # of mush at 20 px. The octagon plate and the red already say hazard,
        # so the glyph can spend all its pixels on the transmitter itself.
        t.tri((c - 3.0, c + 6.0), (c + 3.0, c + 6.0), (c + 1.0, c + 1.8),
              (116, 126, 144), edge=0.5)
        t.box(c, c + 0.6, 2.1, 8.0, (196, 206, 220), edge=0.5)
        t.disc(c, c - 3.9, 2.1, mix(accent, _WHITE, 0.4), edge=0.45)
        t.bloom(c, c - 3.9, 6.0, accent, power=2.0, peak=0.3 + 0.2 * math.sin(ph))
        for k, rr in enumerate((3.6, 6.3)):
            g = 0.5 + 0.5 * math.sin(ph - k * 1.2)
            for side in (-math.tau * 0.25, -math.tau * 0.75):
                t.arc(c, c - 3.9, rr + 0.8 * g, 2.6, side, 1.05, key,
                      edge=0.6, taper=0.7, alpha=0.5 + 0.4 * g)
    else:                                      # mine: spiked shell, blink lamp
        # Steel spikes on a dark body: a dark shell on a red hazard plate is
        # invisible, so the spikes have to carry the silhouette in bright metal.
        # Long radial spikes to the plate edge: the mine has to read as a burr
        # at a glance, because the jammer beside it is also "red hazard plate +
        # bright thing in the middle".
        for k in range(8):
            a = k * math.tau / 8.0 + ph * 0.12
            t.tri(*_spike(c, c, a, 3.6, 9.0, 2.1), (40, 44, 54), edge=0.5)
            t.tri(*_spike(c, c, a, 3.6, 8.2, 0.95), (162, 172, 190), edge=0.4,
                  alpha=0.92)
        t.disc(c, c, 5.2, (24, 26, 32), edge=0.6)
        t.disc(c, c, 4.4, (74, 78, 90), edge=0.5)
        t.disc(c - 1.7, c - 1.8, 1.6, mix(_WHITE, (190, 200, 220), 0.2),
               edge=0.5, alpha=0.65)
        lamp = 1.0 if i % 4 < 2 else 0.2
        t.bloom(c, c, 6.4, accent, power=1.9, peak=0.62 * lamp)
        t.disc(c, c, 1.9, mix(accent, _WHITE, 0.6 * lamp), edge=0.4,
               alpha=0.4 + 0.6 * lamp)


def _paint_items(sheet: Any) -> None:
    """Every falling pickup, painted from one pod recipe.

    Items are the smallest thing the player has to read in a hurry, so the
    detail is structural (bevel, recess, rivets, a lit edge) rather than tiny
    texture that would smear at 20 px. Each kind then animates something that
    belongs to it, so a stack of pickups is never a wall of identical tiles.
    """
    cw, ch = SPRITES["items"]["cell"]
    for i, kind in enumerate(C.ItemKind):
        hull, accent = C.ITEM_COLORS.get(str(kind.value),
                                         C.ITEM_STYLE_DEFAULT_COLOR)
        hazard = str(kind.value) in {str(k.value) for k in C.HAZARDS}
        for f in range(_ITEM_FRAMES):
            ox, oy = tile_xy("items", i * _ITEM_FRAMES + f)
            t = Tile(cw, ch, ss=4)
            c = cw / 2.0
            _pod_shell(t, c, hull, accent, hazard)
            _item_symbol(t, c, str(kind.value), accent, f)
            # specular sweep travelling across the window: ties the four frames
            # together so the pod reads as glass, not as a flat sticker
            g = f / (_ITEM_FRAMES - 1.0)
            gx, gy = c - 4.6 + g * 9.2, c + 4.6 - g * 9.2
            t.disc(gx, gy, 3.4, _WHITE, edge=1.4, alpha=0.14)
            t.disc(gx, gy, 1.3, _WHITE, edge=0.6, alpha=0.26)
            # No radial window() here: the pod is a *plate*, and clipping it to
            # the cell's inscribed circle would shave its corners off.
            t.blit(sheet, ox, oy)


def _paint_fx_item_aura(sheet: Any) -> None:
    """The shared pickup marker: one translucent sprite that rings every item.

    Nothing here is kind-specific — the renderer tints it with the kind's
    accent — so what sells "this is a collectable" has to be motion and
    silhouette: three blades orbiting counter-clockwise with hot heads and
    faded tails, a counter-rotating tick ring so the shape never sits still, a
    halo that breathes once per orbit, and four twinkles on offset beats.
    The middle is punched transparent, so the marker frames the pod instead of
    veiling it.
    """
    cw, ch = SPRITES["fx_item_aura"]["cell"]
    n = len(SPRITES["fx_item_aura"]["anims"]["orbit"]["frames"])
    for i in range(n):
        ox, oy = tile_xy("fx_item_aura", i)
        t = Tile(cw, ch, ss=4)
        c = cw / 2.0
        ph = math.tau * i / n
        t.bloom(c, c, 16.6, (202, 222, 255), power=1.9,
                peak=0.24 + 0.12 * math.cos(ph))
        # Faint full ring = the marker's silhouette in a still frame; the three
        # fat blades over it are what make it spin.
        t.arc(c, c, 15.6, 1.6, 0.0, math.pi, (226, 238, 255), edge=0.9,
              alpha=0.2)
        t.arc(c, c, 15.6, 1.6, math.pi, math.pi, (226, 238, 255), edge=0.9,
              alpha=0.2)
        for k in range(3):
            a = ph + k * math.tau / 3.0
            # Blade = a *solid* swept triangle (crisp at any scale) with a soft
            # tail behind it. An all-soft arc fades into the halo and reads as
            # a static ring; the hard leading edge is what says "orbiting".
            # Tail: a wide arc fading backwards. Head: a short arc with a hard
            # edge at the same band width, so the blade has a real leading edge
            # instead of dissolving into the halo. A straight triangle here
            # ignores the curvature and comes out looking like a dashed ring.
            # ~115 deg total per blade: three of them must not overlap, or the
            # orbit turns into a solid ring and the spin disappears.
            t.arc(c, c, 13.0, 6.0, a - 0.5, 0.7, (250, 252, 255), edge=0.9,
                  taper=2.2, alpha=0.42)
            t.arc(c, c, 13.0, 6.8, a + 0.42, 0.42, _WHITE, edge=0.45,
                  alpha=0.95)
            hx, hy = c + math.cos(a + 0.6) * 13.0, c + math.sin(a + 0.6) * 13.0
            t.bloom(hx, hy, 6.2, (236, 246, 255), power=2.0, peak=0.4)
        # Two gauge ticks across the band, orbiting the other way: a second,
        # opposite motion is what stops the ring looking like a static decal.
        for k in range(2):
            t.arc(c, c, 15.0, 4.4, -1.7 * ph + k * math.pi, 0.11, (244, 250, 255),
                  edge=0.5, alpha=0.34)
        t.hole(c, c, 10.6, edge=2.2)
        t.window(17.9, edge=1.1)
        t.blit(sheet, ox, oy)


def _shield_shell(t: Tile, c: float, r: float, spin: float,
                  build: float) -> None:
    """One frame of the shield bubble: a six-plate dome turning on its axis.

    ``build`` is how far through *materialising* the shield is (0..1). The
    middle stays almost clear and the structure lives at the rim: the bubble is
    blitted behind the craft, but a wash across the whole disc would still read
    as varnish over the player model, and a shield that hides what it protects
    is a bad shield.

    The six gaps are the whole trick. A continuous ring gives the eye nothing to
    track, so the spin is invisible; a plate with a bright leading edge and a
    gap after it turns even in a still frame.
    """
    step = math.tau / 6.0
    # Interior wash, rim-weighted: a hint of colour, not a veil.
    t.bloom(c, c, r, (98, 178, 248), power=1.55, peak=0.09 + 0.05 * build)
    t.annulus(c, c, r - 2.4, 4.2, (150, 214, 255), edge=1.4,
              alpha=0.30 * build)
    for i in range(6):
        a0 = spin + i * step
        # A sphere is brightest at its silhouette: plates facing the camera are
        # glass, plates crossing the limb are edges. Weighting the lattice by
        # longitude is what turns six arcs into a ball that turns.
        limb = 0.60 + 0.40 * abs(math.sin(math.radians(a0)))
        # Plate: a broad arc of energy glass. Faint enough that the craft shows
        # through, opaque enough that six of them and six gaps are legible as a
        # lattice, which is the only reason the spin reads at all.
        t.arc(c, c, r - 6.4, 11.0, a0, step * 0.31, (116, 198, 252), edge=1.2,
              taper=1.3, alpha=0.50 * build * limb)
        # Inner face, slightly recessed, so the plate has a thickness.
        t.arc(c, c, r - 12.0, 3.6, a0, step * 0.27, (96, 174, 236), edge=1.2,
              taper=1.5, alpha=0.17 * build)
        # Bright leading edge, so each plate has a front.
        t.arc(c, c, r - 4.2, 2.8, a0 + step * 0.31, 0.075, (230, 248, 255),
              edge=0.5, alpha=0.92 * build)
        # Node glint sitting in the gap behind the plate.
        gap = a0 + step * 0.5
        t.disc(c + math.cos(gap) * (r - 1.6), c + math.sin(gap) * (r - 1.6),
               2.1, (242, 251, 255), alpha=0.62 * build)
    # Structural rim plus a soft outer halo.
    t.annulus(c, c, r, 2.3, (206, 238, 255), edge=0.8,
              alpha=0.55 + 0.4 * build)
    t.annulus(c, c, r + 3.2, 5.0, (120, 190, 250), edge=1.6,
              alpha=0.15 * build)
    # Two specular sweeps turning against the lattice, so the silhouette never
    # sits still even where the plates come back around.
    for k in range(9):
        al = (0.62 - k * 0.066) * build
        if al <= 0.0:
            continue
        a = -spin * 0.6 + 2.26 + k * 0.058
        t.arc(c, c, r - 1.2, 2.6, a, 0.03, _WHITE, edge=0.5, alpha=al)
        t.arc(c, c, r - 1.2, 2.6, a - math.pi, 0.024, _WHITE, edge=0.5,
              alpha=al * 0.55)


def _paint_fx_shield(sheet: Any) -> None:
    """The shield bubble: a spinning plated dome plus a one-pass deploy pop.

    Sized to wrap the craft with room to spare - the radius here is what the
    renderer's ``SHIELD_FX_RADIUS`` has to agree with, and both are larger than
    the ship's own half-diagonal, which is the whole point of the sheet.
    """
    spec = SPRITES["fx_shield"]
    cw, ch = spec["cell"]
    spin = spec["anims"]["spin"]["frames"]
    deploy = spec["anims"]["deploy"]["frames"]
    r = float(spec["radius"])
    for i, idx in enumerate(spin):
        ox, oy = tile_xy("fx_shield", idx)
        t = Tile(cw, ch, ss=4)
        _shield_shell(t, cw / 2.0, r, i * (math.tau / len(spin)), 1.0)
        t.blit(sheet, ox, oy)
    for j, idx in enumerate(deploy):
        ox, oy = tile_xy("fx_shield", idx)
        t = Tile(cw, ch, ss=4)
        p = j / max(1, len(deploy) - 1)
        _shield_shell(t, cw / 2.0, r, 0.0, p ** 0.65)
        # A leading edge races outward while the plates are condensing, and the
        # flash is hottest before there is any shell to see.
        front = 12.0 + (r - 12.0) * p
        t.annulus(cw / 2.0, cw / 2.0, front, 3.4, (228, 246, 255), edge=1.0,
                  alpha=0.9 * (1.0 - p) ** 0.75)
        t.annulus(cw / 2.0, cw / 2.0, front + 4.0, 5.6, (120, 196, 255),
                  edge=1.8, alpha=0.34 * (1.0 - p))
        if p < 0.45:
            t.bloom(cw / 2.0, cw / 2.0, 14.0 + 22.0 * p, (214, 240, 255),
                    power=2.0, peak=0.72 * (1.0 - p / 0.45))
        t.blit(sheet, ox, oy)


_BAKE = {
    "p_ship": _paint_p_ship,
    "shot_vulcan": _paint_shot_vulcan,
    "shot_plasma": _paint_shot_plasma,
    "shot_missile": _paint_shot_missile,
    "shot_enemy": _paint_shot_enemy,
    "fx_whip": _paint_fx_whip,
    "items": _paint_items,
    "fx_item_aura": _paint_fx_item_aura,
    "fx_shield": _paint_fx_shield,
    "explosion_small": lambda s: _paint_explosion(s, "explosion_small"),
    "explosion_mid": lambda s: _paint_explosion(s, "explosion_mid"),
    "explosion_big": lambda s: _paint_explosion(s, "explosion_big"),
    "e_grunt": _paint_e_grunt,
    "e_weaver": _paint_e_weaver,
    "e_darter": _paint_e_darter,
    "e_gunner": _paint_e_gunner,
    "e_sentry": _paint_e_sentry,
    "e_heavy": _paint_e_heavy,
    "e_bomber": _paint_e_bomber,
    "e_splitter": _paint_e_splitter,
    "e_rammer": _paint_e_rammer,
    "e_shard": _paint_e_shard,
}

# One boss per sector; until a sector's generated art lands they fall back to
# the classic painted silhouette, scaled into the wide boss cell.
for _i in range(1, 10):
    _BAKE[f"e_boss{_i}"] = partial(_paint_e_boss, name=f"e_boss{_i}")


def build_procedural(name: str) -> Any:
    """Paint one sheet as a tiled texture (offline / tests only — gameplay
    loads the baked PNG through Bank).

    Sheets with keyed artwork in assets/textures/sprites_src are animated from
    that art by sprites.rawkit; everything else (and any stripped checkout)
    falls back to the vector painter registered in _BAKE.
    """
    import pygame

    from . import rawkit
    sheet = rawkit.build_sheet(name)
    if sheet is not None:
        return sheet
    meta = SPRITES[name]
    cw, ch = meta["cell"]
    cols = cols_for(name)
    n_frames = len(meta["anims"][next(iter(meta["anims"]))]["frames"])
    rows = (n_frames + cols - 1) // cols
    surf = pygame.Surface((cols * cw, rows * ch), pygame.SRCALPHA)
    surf.fill((0, 0, 0, 0))
    _BAKE[name](surf)
    return surf


def bake(name: str) -> Path:
    surf = build_procedural(name)
    path = sheet_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    import pygame
    pygame.image.save(surf, str(path))
    return path
