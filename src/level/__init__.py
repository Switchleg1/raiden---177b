"""Streaming sector ground: the ground as a tall strip, painted off-thread.

A sector used to be one screen of baked ground (1120 bake px, ~3.4 s of scroll)
repeated for the length of the wave, with two of them cross-faded in the middle
of the level. This package replaces that with one designed strip per sector: the
whole sector is planned once, and the picture of it is painted slice by slice on
worker threads while the player is already flying the sector. Painting is not on
the frame path, and the sector's ground never runs out, so there is no repeat to
hide and no zone boundary to dissolve through.

See ``docs/terrain.md`` ("Streaming a sector") for the geometry and the measured
painting rate against the scroll rate.
"""
from __future__ import annotations

from .design import plan_sector, shutdown_pool
from .encounters import Encounter, plan_encounters
from .level import Level, strip_length
from .strip import STRIP_MARGIN, STRIP_SLICE, TerrainStrip

__all__ = ["Encounter", "Level", "TerrainStrip", "STRIP_MARGIN",
           "STRIP_SLICE", "plan_encounters", "plan_sector",
           "shutdown_pool", "strip_length"]
