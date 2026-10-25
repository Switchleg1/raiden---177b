"""Vector fallbacks as data: enemy silhouettes and item glyphs.

These are what the renderer draws when there is no baked art, or in high-contrast
mode - so they have to identify the thing on their own.
"""
from __future__ import annotations

import math

# An enemy silhouette: points as (fx, fy, dx, dy), drawn at
# (x + fx * r + dx, y + fy * r + dy) for an enemy of radius r.
_TRIANGLE = ((0.0, 1.0, 0, 0), (-1.0, -1.0, 0, 0), (1.0, -1.0, 0, 0))
ENEMY_SHAPES: dict[str, tuple[tuple[float, float, int, int], ...]] = {
    "grunt": _TRIANGLE,
    "weaver": ((0.0, 1.0, 0, 0), (1.0, 0.0, 0, 0), (0.0, -1.0, 0, 0),
               (-1.0, 0.0, 0, 0)),
    "darter": ((0.0, 1.0, 0, 0), (0.0, -1.0, 4, 0), (0.0, -1.0, -4, 0)),
    "gunner": tuple((math.cos(a), math.sin(a), 0, 0)
                    for a in (i * math.tau / 6 for i in range(6))),
    "sentry": tuple((math.cos(a), math.sin(a), 0, 0)
                    for a in (i * math.tau / 8 + math.tau / 16 for i in range(8))),
    "heavy": ((-1.0, -1.0, 0, 0), (1.0, -1.0, 0, 0), (1.0, 1.0, 0, 0),
              (-1.0, 1.0, 0, 0)),
}
ENEMY_SHAPE_DEFAULT = _TRIANGLE

# An item glyph: drawing operations relative to the item's centre, in the edge
# colour. ("polygon", points, width) - width 0 fills; ("circle", centre, radius,
# width); ("line", a, b, width); ("arc", (left, top, w, h), start, end, width).
GLYPHS: dict[str, tuple[tuple, ...]] = {
    "up": (("polygon", ((0, -6), (6, 0), (2, 0), (2, 6), (-2, 6), (-2, 0), (-6, 0)),
            0),),
    "rocket": (("polygon", ((0, -7), (4, 3), (0, 1), (-4, 3)), 0),
               ("line", (-4, 5), (4, 5), 2)),
    "bomb": (("circle", (0, 1), 5, 0),
             ("line", (3, -3), (6, -6), 2)),
    "shield": (("polygon", ((0, -6), (6, -3), (6, 2), (0, 7), (-6, 2), (-6, -3)), 2),),
    "medal": (("circle", (0, 0), 6, 2),
              ("line", (0, -3), (0, 3), 2),
              ("line", (-3, 0), (3, 0), 2)),
    "life": (("circle", (-3, -1), 3, 0),
             ("circle", (3, -1), 3, 0),
             ("polygon", ((-5, 1), (5, 1), (0, 6)), 0)),
    # squashed S-lash with an energy bead at the tip
    "whip": (("arc", (-7, -8, 8, 9), math.pi * 0.9, math.pi * 2.1, 2),
             ("arc", (-1, -1, 8, 9), math.pi * 1.9, math.pi * 3.1, 2),
             ("circle", (5, 6), 2, 0)),
    # tongue of fire: point up, wide base, hot bead inside. Outline rather than
    # solid, because the "up" glyph beside it is solid.
    "flame": (("polygon", ((0, -7), (4, -1), (3, 4), (0, 6), (-3, 4), (-4, -1)), 2),
              ("circle", (0, 2), 2, 0)),
    "jam": (("line", (-5, -5), (5, 5), 2),
            ("line", (5, -5), (-5, 5), 2)),
    "mine": (("circle", (0, 0), 4, 2),) + tuple(
        ("line", (0, 0), (math.cos(math.radians(a)) * 7,
                          math.sin(math.radians(a)) * 7), 2)
        for a in range(0, 360, 45)),
}

__all__ = ["ENEMY_SHAPES", "ENEMY_SHAPE_DEFAULT", "GLYPHS"]
