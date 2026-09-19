"""Terrain themes for the nine sectors."""
from __future__ import annotations

from enum import StrEnum


class StageTheme(StrEnum):
    """Terrain theme. Value string is the theme key used by terrain/procedural."""
    COUNTRYSIDE = "countryside"
    WASTELAND = "wasteland"
    CITY = "city"
    FOREST = "forest"
    CANYON = "canyon"
    OCEAN = "ocean"
    RUINS = "ruins"
    FARMLAND = "farmland"
    AIRBASE = "airbase"
    SWAMP = "swamp"
    GLACIER = "glacier"
    VOLCANIC = "volcanic"
    INDUSTRIAL = "industrial"
