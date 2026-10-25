"""How much water a sector's ground carries, and how wide it is."""
from __future__ import annotations

#: Half-width ranges of each kind of channel, bake px.
WATER_HALF: dict[str, tuple[float, float]] = {
    "wash": (30.0, 44.0),
    "arroyo": (26.0, 40.0),
    "channel": (22.0, 34.0),
    "fjord": (40.0, 70.0),
    "river": (30.0, 46.0),
}

#: (screens per main river, screens per tributary), keyed by a theme's
#: `water_kinds`. A swamp is MADE of channels; a desert has a wash now and then.
#: A river valley has ONE river: at 14 screens a river every sector of 21+ screens
#: (all of them) carried two full-length rivers side by side, which read as a
#: canal pair, not a valley. 60 rounds to one for any sector length we fly.
WATER_RATE: dict[tuple[str, ...], tuple[float, float]] = {
    (): (60.0, 5.0),
    ("river",): (60.0, 5.0),
    ("channel", "river"): (60.0, 3.5),
    ("channel", "channel", "river"): (8.0, 1.8),
    # A desert has one main wash through it and the side washes join it; at 16
    # screens a 40-screen wasteland got two or three full-length washes running
    # parallel, and the sector read as corduroy rather than as a desert.
    ("wash",): (60.0, 6.0),
    ("channel",): (60.0, 5.0),
}

__all__ = ["WATER_HALF", "WATER_RATE"]
