"""Per-theme ground data: which materials a sector's backdrop uses and how
dark it should read.

Keyed by theme name (the same strings ``config.StageTheme`` spells out). Edit
this file to retune a sector's ground; the painters in :mod:`terrain.compose`
and the material kit in :mod:`terrain.tilekit` read it, they do not decide.

``THEME_MEAN`` is the target mean luminance of a composed strip: below it the
strip is darkened so bright sprites keep their silhouette. It is *not* a
brightness dial for taste - see the glacier note below.
"""
from __future__ import annotations

#: Fallback mean luminance for a theme not listed below.
NEAR_MEAN = 40.0

#: Target mean luminance per theme.
THEME_MEAN = {
    "countryside": 40.0, "farmland": 42.0, "forest": 38.0, "city": 42.0,
    "ruins": 40.0, "ocean": 48.0, "wasteland": 40.0, "canyon": 46.0,
    "airbase": 44.0,
    # Swamp sits with the other dark themes.  Snow is deliberately ~2x the
    # other sectors: dropping it to 66 was tried and measured, and the stage
    # stopped reading as ice while sprite contrast did not improve (the
    # problem is sprites over local bright drifts, i.e. a renderer/outline
    # concern, not a stage-brightness one).  Do not fix sprite contrast here.
    "swamp": 38.0,
    "glacier": 86.0,
    "volcanic": 46.0,
    "industrial": 46.0,
}

#: Background materials per theme, in draw order: the first tiles the open
#: ground, the second is the secondary surface mixed in (river beds, rubble,
#: ice sheets...).  Both names must exist in the baked material kit.
FAR_PAIR = {
    "countryside": ("grass_patchy", "grass_lush"),
    "farmland": ("grass_patchy", "water_river"),
    "forest": ("forest_floor", "grass_patchy"),
    "city": ("concrete_apron", "cobble_moss"),
    "ruins": ("gravel_rubble", "cobble_moss"),
    "ocean": ("ocean_surface", "sand_canyon"),
    "wasteland": ("ash_ground", "gravel_rubble"),
    "canyon": ("sand_canyon", "earth_cracked"),
    "airbase": ("concrete_apron", "gravel_rubble"),
    "swamp": ("water_marsh", "reed_marsh"),
    "glacier": ("snow_field", "ice_sheet"),
    "volcanic": ("obsidian", "ash_ground"),
    "industrial": ("concrete_apron", "rust_plate"),
}

__all__ = ["FAR_PAIR", "NEAR_MEAN", "THEME_MEAN"]
