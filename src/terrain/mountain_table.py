"""Mountain ranges, per kind of country: how often, how broad, how high."""
from __future__ import annotations

#: kind -> (screens of strip per range, (min, max) half-width of the range in
#: bake px, (min, max) crest height in relief units 0..1). Relief is normalised
#: per theme after the orogeny, so heights are relative to the theme's own hills.
RANGES: dict[str, tuple[float, tuple[float, float], tuple[float, float]]] = {
    "alpine": (5.0, (300.0, 460.0), (0.9, 1.0)),
    "volcanic": (6.0, (260.0, 400.0), (0.85, 1.0)),
    "foothills": (9.0, (240.0, 360.0), (0.55, 0.75)),
    "badlands": (7.0, (220.0, 340.0), (0.7, 0.9)),
}

#: Where snow lies, per theme: relief above this is snow-capped. A theme not
#: listed has no snow at any height.
SNOWLINE: dict[str, float] = {
    "glacier": 0.55,
    "forest": 0.82,
}

__all__ = ["RANGES", "SNOWLINE"]
