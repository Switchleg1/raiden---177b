"""Terrain maps for the scrolling backdrop (view layer).

Each sector gets a hand-painted-style map from a fixed seed; maps
are BAKED offline by scripts/bake_terrain.py and loaded at level
start. build_procedural() composes from the generated tileset, or
from vector primitives when the tileset is absent. Maps wrap
vertically and scroll at two parallax speeds. Imports pygame lazily.
"""
from __future__ import annotations

from .common import FAR_SPEED, NEAR_SPEED, SS, TILE_H
from .handoff import HANDOFF_SECONDS, SectorHandoff
from .layer import Layer
from .procedural import build_procedural
from .terrain_map import Terrain, bake, baked_paths
from .track import PHASE_FADE, PHASE_PLAN, TerrainTrack, plan_span, sector_key, sector_phases

__all__ = [
    "FAR_SPEED",
    "HANDOFF_SECONDS",
    "Layer",
    "SectorHandoff",
    "NEAR_SPEED",
    "PHASE_FADE",
    "PHASE_PLAN",
    "SS",
    "TILE_H",
    "Terrain",
    "TerrainTrack",
    "bake",
    "baked_paths",
    "plan_span",
    "sector_key",
    "sector_phases",
    "build_procedural",
]
