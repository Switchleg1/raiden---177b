"""Ridge cross-sections: crest height along a spine, one function per landform.

Each returns N heights in 0..1. They are real landform profiles, not random
ones - the shape is what tells a canyon mesa from a volcanic cone.
"""
from __future__ import annotations

import math
import random


def _crest_sawback(n: int, rng: random.Random) -> list[float]:
    """Jagged thrust belt: sharp teeth, uneven."""
    h = [0.0] * n
    teeth = rng.randint(3, 6)
    for i in range(n):
        t = (i / n) * teeth
        h[i] = 0.45 + 0.55 * abs(t - math.floor(t) - 0.5) * 2.0
    h = [min(1.0, v * rng.uniform(0.75, 1.2)) for v in h]
    return h


def _crest_domefield(n: int, rng: random.Random) -> list[float]:
    """Domed uplift: broad rounded swells."""
    h = [0.0] * n
    bumps = [(rng.uniform(0.1, 0.9), rng.uniform(0.06, 0.18),
              rng.uniform(0.5, 1.0)) for _ in range(rng.randint(2, 4))]
    for i in range(n):
        u = i / n
        h[i] = max(a * math.exp(-((u - c) / w) ** 2) for c, w, a in bumps)
    return h


def _crest_mesa(n: int, rng: random.Random) -> list[float]:
    """Table mountain: long flats, cliff edges."""
    h = [0.0] * n
    lo = rng.uniform(0.15, 0.35)
    hi = lo + rng.uniform(0.25, 0.45)
    # the cliff is a cosine shoulder over 16% of the run, not a step: a step
    # in the height field shades as a hard-edged black rectangle, which is
    # how the first canyon renders looked like a rendering bug
    for i in range(n):
        u = i / n
        if u < lo or u > hi:
            h[i] = 0.12
        else:
            e = min(u - lo, hi - u, 0.16)
            h[i] = 0.12 + 0.88 * (0.5 - 0.5 * math.cos(math.pi * (e / 0.16)))
    return h


def _crest_cone(n: int, rng: random.Random) -> list[float]:
    """Stratovolcano: one narrow tall peak."""
    h = [0.0] * n
    c, w = rng.uniform(0.35, 0.65), rng.uniform(0.08, 0.14)
    for i in range(n):
        u = i / n
        h[i] = math.exp(-((u - c) / w) ** 2)
    return h


def _crest_hogback(n: int, rng: random.Random) -> list[float]:
    """Asymmetric dipping strata: steep scarp, gentle dip slope."""
    h = [0.0] * n
    c = rng.uniform(0.3, 0.7)
    for i in range(n):
        u = i / n
        h[i] = (1.0 - abs(u - c) / max(1e-6, c if u < c else 1.0 - c))
        h[i] = max(0.05, min(1.0, h[i]))
    return h


def _crest_massif(n: int, rng: random.Random) -> list[float]:
    """Eroded massif: lumpy core, radiating arms."""
    h = [0.0] * n
    bumps = [(rng.uniform(0.15, 0.85), rng.uniform(0.1, 0.22),
              rng.uniform(0.55, 1.0)) for _ in range(rng.randint(3, 5))]
    for i in range(n):
        u = i / n
        h[i] = 0.35 * max(a * math.exp(-((u - c) / w) ** 2)
                          for c, w, a in bumps) + 0.45
    return h


def _crest_ridge(n: int, rng: random.Random) -> list[float]:
    """A single gentle arc - the default ridge."""
    h = [0.0] * n
    c, w = 0.5, rng.uniform(0.22, 0.35)
    for i in range(n):
        h[i] = math.exp(-((i / n - c) / w) ** 2)
    return h
