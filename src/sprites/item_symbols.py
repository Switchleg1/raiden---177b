"""The icon inside each pickup's window, one function per item kind.

Each draws its symbol on frame `i` of the pickup's loop (`ph` is that frame as
a phase, 0..tau); `key` and `dark` are the accent lifted and sunk, the two
tones a 20 px symbol is drawn in.
"""
from __future__ import annotations

import math

from .fxkit import RGB, WHITE, Tile, mix, spike


def symbol_weapon(t: Tile, c: float, accent: RGB, key: RGB, dark: RGB,
                 ph: float, i: int) -> None:
    """Up arrow, rising on the beat."""
    # One unmistakable arrow. Two stacked triangles read as a tree at 20 px;
    # head + shaft is the glyph for "weapon up" in every shmup ever made.
    bob = -0.9 * math.sin(ph)
    y0 = c - 1.4 + bob
    for shade, grow in ((dark, 1.5), (key, 0.0)):
        t.tri((c, y0 - 5.6 - grow), (c - 5.4 - grow, y0 - 0.4 + grow),
              (c + 5.4 + grow, y0 - 0.4 + grow), shade, edge=0.6)
        t.box(c, y0 + 2.9, 3.6 + grow, 5.4 + grow, shade, edge=0.6)
    t.box(c - 0.7, y0 + 2.4, 1.2, 4.2, WHITE, edge=0.4, alpha=0.45)
    t.bloom(c, c, 7.8, accent, power=2.2, peak=0.22 + 0.12 * math.sin(ph))


def symbol_missile(t: Tile, c: float, accent: RGB, key: RGB, dark: RGB,
                  ph: float, i: int) -> None:
    """Dart with a flickering motor."""
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
    t.capsule(c - 0.6, c - 1.8, 2.7, 0.75, WHITE, edge=0.4, alpha=0.55)
    t.tri((c, c - 7.0), (c - 2.1, c - 3.2), (c + 2.1, c - 3.2), key,
          edge=0.45)
    t.disc(c, c - 2.1, 1.15, mix(accent, WHITE, 0.6), edge=0.4)


def symbol_bomb(t: Tile, c: float, accent: RGB, key: RGB, dark: RGB,
               ph: float, i: int) -> None:
    """Steel shell, live fuse."""
    # Dark steel with a hard specular, not a warm ball: the medal is
    # already the bright round thing on this sheet.
    spark = 0.35 + 0.65 * (1.0 if i % 2 == 0 else 0.2)
    t.box(c + 2.4, c - 4.4, 2.2, 3.0, (96, 102, 116), edge=0.5)
    t.capsule(c + 3.0, c - 6.2, 1.0, 0.7, (150, 128, 96), edge=0.45)
    t.disc(c - 0.4, c + 1.4, 5.1, (24, 27, 34), edge=0.6)
    t.disc(c - 0.4, c + 1.4, 4.4, (74, 80, 92), edge=0.5)
    t.disc(c - 0.4, c + 2.2, 3.4, (48, 53, 64), edge=0.6, alpha=0.75)
    t.disc(c - 2.2, c - 0.6, 1.7, mix(WHITE, (190, 200, 220), 0.2),
           edge=0.5, alpha=0.8)
    t.bloom(c + 3.0, c - 7.2, 5.0, (255, 190, 90), power=2.0, peak=spark)
    t.disc(c + 3.0, c - 7.2, 1.4 + 0.6 * (i % 2),
           mix((255, 248, 215), accent, 0.3), edge=0.4,
           alpha=0.5 + 0.5 * spark)


def symbol_shield(t: Tile, c: float, accent: RGB, key: RGB, dark: RGB,
                 ph: float, i: int) -> None:
    """Heraldic plate, rim surging."""
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
    t.disc(c - 2.2, c - 3.0, 1.5, WHITE, edge=0.55, alpha=0.45)
    t.disc(c, c + 2.6, 1.4, key, edge=0.5, alpha=0.4 + 0.35 * pulse)


def symbol_medal(t: Tile, c: float, accent: RGB, key: RGB, dark: RGB,
                ph: float, i: int) -> None:
    """Struck coin with a spinning star."""
    t.disc(c, c, 6.7, mix(accent, (60, 44, 14), 0.4), edge=0.6)
    t.disc(c, c, 5.6, mix(accent, (128, 92, 22), 0.3), edge=0.55)
    t.annulus(c, c, 5.9, 1.1, mix(accent, WHITE, 0.45), edge=0.5,
              alpha=0.75)
    # struck star: dark relief first, bright star on top, or the whole coin
    # blooms into one bright blob at 20 px
    for shade, grow, alpha in ((dark, 1.5, 0.9), (mix(WHITE, accent, 0.3),
                                                   0.0, 0.95)):
        for k in range(5):
            a = -math.tau / 4.0 + k * math.tau / 5.0 + ph * 0.25
            t.tri(*spike(c, c, a, 1.6, 4.4 + grow, 1.15 + grow * 0.4),
                  shade, edge=0.45, alpha=alpha)
    t.disc(c, c, 1.2, WHITE, edge=0.4, alpha=0.85)
    t.disc(c - 2.4, c - 2.6, 1.1, WHITE, edge=0.45, alpha=0.35)


def symbol_extra_life(t: Tile, c: float, accent: RGB, key: RGB, dark: RGB,
                     ph: float, i: int) -> None:
    """Heart that beats."""
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
          mix(body, WHITE, 0.18), edge=0.45)
    t.disc(c - 2.4, c - 2.8, 1.25, mix(WHITE, body, 0.3), edge=0.45,
           alpha=0.75)


def symbol_whip(t: Tile, c: float, accent: RGB, key: RGB, dark: RGB,
               ph: float, i: int) -> None:
    """Coiled lash, bead runs the coil."""
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
    t.disc(bx, by, 2.1, mix(WHITE, accent, 0.35), edge=0.45)
    t.disc(bx, by, 0.9, WHITE, edge=0.35)


def symbol_moon(t: Tile, c: float, accent: RGB, key: RGB, dark: RGB,
               ph: float, i: int) -> None:
    """Crescent blade, slow turn."""
    # The same silhouette the craft throws, so a pickup says what it is
    # before the pod is read: one tapered arc, horns up, turning a quarter
    # of a turn over the four frames. Cold steel on a near-white accent -
    # missile and shield already own the saturated blues.
    a = math.tau * 0.25 + ph * 0.25
    # Same construction as the fired blade, at pod scale: widest arc is the
    # cut edge, inner arcs span less so the crescent ends in points.
    #
    # A crescent's mass sits on the far side of its arc centre, so the centre
    # is pulled back along the spin axis by that offset. Without it the glyph
    # orbits the recess - hanging low in frame 0 and against the left wall in
    # frame 4 - and reads as a smudge that will not stay put; with it the
    # blade turns inside the window about its own middle.
    gx, gy = math.cos(a) * 3.2, math.sin(a) * 3.2
    mx, my = c - gx, c - gy
    t.bloom(c, c, 9.0, accent, power=2.0,
            peak=0.26 + 0.12 * math.sin(ph))
    t.arc(mx, my, 6.5, 2.2, a, 1.42, key, edge=0.45, taper=0.16)
    t.arc(mx, my, 5.0, 3.4, a, 1.18, mix(accent, dark, 0.22), edge=0.5,
          taper=0.4)
    t.arc(mx, my, 3.7, 2.2, a, 0.92, dark, edge=0.6, taper=0.35,
          alpha=0.85)


def symbol_flame(t: Tile, c: float, accent: RGB, key: RGB, dark: RGB,
                ph: float, i: int) -> None:
    """Tongue of fire, licking taller."""
    # A flame is a teardrop with the point up. The only thing that changes
    # across the four frames is how far the tip licks and how far the
    # shoulder leans: a fire glyph that changes shape reads as flickering,
    # one that only changes colour reads as a lamp.
    lick = 5.6 + 1.6 * math.sin(ph)
    lean = 1.15 * math.sin(ph * 0.5)
    t.bloom(c, c + 0.8, 9.4, accent, power=2.0,
            peak=0.28 + 0.12 * math.sin(ph))
    base = c + 4.2
    for dx, half, col, al in ((lean, 4.7, mix(accent, (255, 58, 18), 0.4),
                               0.95),
                              (lean * 0.45, 2.6, mix(accent, WHITE, 0.3),
                               0.9)):
        # Triangle plus a base disc, not cone(): a cone keeps its base
        # width past its base line, so a flame drawn with it runs a bar of
        # fire off the bottom of the pod and out of the tile.
        t.tri((c + dx, c - lick), (c + dx - half, base),
              (c + dx + half, base), col, edge=0.5, alpha=al)
        t.disc(c + dx, base, half, col, edge=0.5, alpha=al)
    t.disc(c, c + 2.6, 1.9, mix(WHITE, accent, 0.3), edge=0.45)
    # one ember peeling off the top, on an offset beat from the lick
    ey = c - lick - 1.4 - 1.1 * math.sin(ph * 1.5)
    t.disc(c + lean * 1.6, ey, 1.0, mix(accent, WHITE, 0.4), edge=0.4,
           alpha=0.55 + 0.35 * math.sin(ph))


def symbol_jammer(t: Tile, c: float, accent: RGB, key: RGB, dark: RGB,
                 ph: float, i: int) -> None:
    """Broadcasting antenna, pulsing."""
    # No "prohibited" slash through it: ring + mast + slash is three shapes
    # of mush at 20 px. The octagon plate and the red already say hazard,
    # so the glyph can spend all its pixels on the transmitter itself.
    t.tri((c - 3.0, c + 6.0), (c + 3.0, c + 6.0), (c + 1.0, c + 1.8),
          (116, 126, 144), edge=0.5)
    t.box(c, c + 0.6, 2.1, 8.0, (196, 206, 220), edge=0.5)
    t.disc(c, c - 3.9, 2.1, mix(accent, WHITE, 0.4), edge=0.45)
    t.bloom(c, c - 3.9, 6.0, accent, power=2.0, peak=0.3 + 0.2 * math.sin(ph))
    for k, rr in enumerate((3.6, 6.3)):
        g = 0.5 + 0.5 * math.sin(ph - k * 1.2)
        for side in (-math.tau * 0.25, -math.tau * 0.75):
            t.arc(c, c - 3.9, rr + 0.8 * g, 2.6, side, 1.05, key,
                  edge=0.6, taper=0.7, alpha=0.5 + 0.4 * g)


def symbol_mine(t: Tile, c: float, accent: RGB, key: RGB, dark: RGB,
               ph: float, i: int) -> None:
    """Bright thing in the middle".."""
    # Steel spikes on a dark body: a dark shell on a red hazard plate is
    # invisible, so the spikes have to carry the silhouette in bright metal.
    # Long radial spikes to the plate edge: the mine has to read as a burr
    # at a glance, because the jammer beside it is also "red hazard plate +
    # bright thing in the middle".
    for k in range(8):
        a = k * math.tau / 8.0 + ph * 0.12
        t.tri(*spike(c, c, a, 3.6, 9.0, 2.1), (40, 44, 54), edge=0.5)
        t.tri(*spike(c, c, a, 3.6, 8.2, 0.95), (162, 172, 190), edge=0.4,
              alpha=0.92)
    t.disc(c, c, 5.2, (24, 26, 32), edge=0.6)
    t.disc(c, c, 4.4, (74, 78, 90), edge=0.5)
    t.disc(c - 1.7, c - 1.8, 1.6, mix(WHITE, (190, 200, 220), 0.2),
           edge=0.5, alpha=0.65)
    lamp = 1.0 if i % 4 < 2 else 0.2
    t.bloom(c, c, 6.4, accent, power=1.9, peak=0.62 * lamp)
    t.disc(c, c, 1.9, mix(accent, WHITE, 0.6 * lamp), edge=0.4,
           alpha=0.4 + 0.6 * lamp)
