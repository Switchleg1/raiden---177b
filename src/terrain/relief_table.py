"""How the ground is lit, and how rugged each theme's high ground is."""
from __future__ import annotations

import math

#: Toward the light: from the upper left and fairly high, the same sun every prop
#: and every roof in the art is lit by.
_L = (-0.55, -0.62, 0.56)
_N = math.sqrt(sum(c * c for c in _L))
HILL_LIGHT: tuple[float, float, float] = (_L[0] / _N, _L[1] / _N, _L[2] / _N)

#: Wavelengths of the erosion detail, world px, biggest first.
HILL_OCTAVES: tuple[float, ...] = (360.0, 170.0, 80.0, 38.0)

#: Per theme: (relief height in world px per unit of relief, height of the
#: erosion detail on the high ground in world px, how hard the shading bites 0..1).
#: A theme missing here is not hillshaded (ocean: there is no ground).
HILL: dict[str, tuple[float, float, float]] = {
    "countryside": (260.0, 70.0, 0.85),
    "farmland": (220.0, 50.0, 0.8),
    "forest": (320.0, 90.0, 0.9),
    "swamp": (120.0, 20.0, 0.6),
    "city": (140.0, 20.0, 0.6),
    "ruins": (260.0, 70.0, 0.85),
    "glacier": (380.0, 120.0, 1.0),
    "canyon": (420.0, 110.0, 1.0),
    "volcanic": (400.0, 120.0, 1.0),
    "wasteland": (280.0, 80.0, 0.9),
    "industrial": (160.0, 30.0, 0.7),
    "airbase": (140.0, 20.0, 0.6),
}

#: Per theme: how much of the relief COLOUR RAMP, bare ROCK and foot-of-slope RIM
#: line the relief painter lays (1 = as calibrated). Those three were how a mass
#: was made legible before the ground was hillshaded; on green country they now
#: fight the shading - a grey ramp over a grassy hill reads as a quarry, and a
#: dark contour round it reads as a drawn outline.
RELIEF_LOOK: dict[str, tuple[float, float, float]] = {
    "countryside": (0.18, 0.25, 0.0),
    "farmland": (0.15, 0.2, 0.0),
    "forest": (0.3, 0.5, 0.0),
    "swamp": (0.15, 0.2, 0.0),
    "city": (0.15, 0.2, 0.0),
    "ruins": (0.35, 0.5, 0.0),
    "industrial": (0.4, 0.5, 0.0),
    "airbase": (0.3, 0.4, 0.0),
    "glacier": (1.0, 1.0, 0.0),
    "canyon": (1.0, 1.0, 0.2),
    "volcanic": (1.0, 1.0, 0.2),
    "wasteland": (0.8, 0.8, 0.0),
}

__all__ = ["HILL", "HILL_LIGHT", "HILL_OCTAVES", "RELIEF_LOOK"]
