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
NEAR_MEAN = 48.0
#: Target mean luminance of the near layer, per theme. These are NOT taste:
#: measured on the planned maps, a canyon forced to mean 46 ended with its
#: ENTIRE value range compressed into lum 24-62 - every material in the theme,
#: from pale sand (121) to gravel (99), got scaled into the same brown band.
#: That is the "everything shares one dark value range" verdict, arithmetic.
#: A desert is allowed to be bright; glacier ice already was (86).
THEME_MEAN = {
    "countryside": 52.0, "farmland": 54.0, "forest": 46.0, "city": 52.0,
    "ruins": 48.0, "ocean": 50.0, "wasteland": 54.0, "canyon": 74.0,
    "airbase": 46.0,
    # Swamp sits with the other dark themes.  Snow is deliberately ~2x the
    # other sectors: dropping it to 66 was tried and measured, and the stage
    # stopped reading as ice while sprite contrast did not improve (the
    # problem is sprites over local bright drifts, i.e. a renderer/outline
    # concern, not a stage-brightness one).  Do not fix sprite contrast here.
    "swamp": 48.0,
    "glacier": 86.0,
    "volcanic": 52.0,
    "industrial": 52.0,
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

#: Near-layer materials per theme, as ``(material, weight)``: the first entry is
#: the open ground, the rest mix in as feathered patches. Split out of the
#: composition code so retuning a sector's ground never means editing paint
#: logic.
NEAR_MATS = {
    "countryside": (("grass_lush", 0.72), ("grass_patchy", 0.28)),
    "farmland": (("grass_lush", 0.8), ("grass_patchy", 0.2)),
    "forest": (("forest_floor", 0.78), ("grass_patchy", 0.22)),
    # A city base is BLOCKS, not pavement: the streets are painted on top by the
    # plan, and if the ground under them is already asphalt the grid vanishes.
    # Cobbles and gravel under the streets, paddock in between. Meant to sit
    # under a painted grid: if the base is itself brown earth, the whole map
    # reads as one brown surface with houses on it.
    "city": (("cobble_moss", 0.5), ("grass_patchy", 0.3),
             ("gravel_rubble", 0.2)),
    "ruins": (("cobble_moss", 0.6), ("gravel_rubble", 0.4)),
    "ocean": (("ocean_surface", 1.0),),
    "wasteland": (("gravel_rubble", 0.72), ("ash_ground", 0.28)),
    "canyon": (("sand_canyon", 0.74), ("earth_cracked", 0.26)),
    "airbase": (("concrete_apron", 0.8), ("gravel_rubble", 0.2)),
    "swamp": (("water_marsh", 0.62), ("reed_marsh", 0.24),
              ("mud_flat", 0.14)),
    "glacier": (("snow_field", 0.7), ("ice_sheet", 0.2),
                ("tundra_moss", 0.1)),
    "volcanic": (("obsidian", 0.66), ("lava_crust", 0.2),
                 ("gravel_rubble", 0.14)),
    "industrial": (("steel_deck", 0.6), ("rust_plate", 0.26),
                   ("concrete_apron", 0.14)),
}

#: What water and roads are paved with, per theme. A canyon "river" is a dry
#: wash of pale sand; a volcanic one is a lava channel; a glacier track is
#: compressed ice. Naming the surface per theme is what stops a dry landscape
#: getting water in it.
WATER_MAT = {
    "countryside": "water_river", "farmland": "water_river",
    "forest": "water_river", "ruins": "water_river",
    "glacier": "water_river", "city": "water_river",
    # water_marsh is the same green as the swamp floor: the channels vanish.
    "swamp": "water_river", "ocean": "ocean_surface",
    "canyon": "sand_canyon", "wasteland": "sand_canyon",
    "airbase": "sand_canyon", "industrial": "water_river",
    "volcanic": "lava_crust",
}

ROAD_MAT = {
    """Routes are GREY gravel in every green and tan theme. That choice is
    measured, not tasted: crop fields are brown earth (road_dirt, lum 105) and a
    grey route (gravel_rubble, lum 99) sits at the same brightness but a
    different hue, so "is that a field or a road?" - the single most repeated
    complaint from the art review - stops being a question. It also beats ice
    (an ice road on ice is invisible) and keeps a city's streets pale over dark
    cobbles."""
    "countryside": "gravel_rubble", "farmland": "gravel_rubble",
    "forest": "gravel_rubble", "ruins": "gravel_rubble",
    # a canyon route is a cut in the sand, so it is DARKER than the sand
    # (earth_cracked, lum 97 against sand_canyon 121). Pale grey gravel put the
    # road at the same value as a pale wash beside it and the review asked
    # "channel or track?" again
    "canyon": "earth_cracked", "wasteland": "earth_cracked",
    "glacier": "gravel_rubble", "volcanic": "gravel_rubble",
    "swamp": "gravel_rubble", "city": "gravel_rubble",
    "ocean": "road_dirt", "airbase": "concrete_apron",
    "industrial": "road_asphalt",
}

#: Rock colouring per theme: (valley/foot tone, crest tone, debris tone, and the
#: material a steep flank is made of). The relief painter ramps between the first
#: two by height and lights the result from the slope, so these three numbers are
#: what make a mesa look like sandstone and a nunatak look like ice.
ROCK = {
    "countryside": ((20, 30, 22), (96, 102, 82), (74, 74, 62),
                    "grass_patchy"),
    "farmland": ((22, 32, 22), (88, 96, 74), (70, 72, 58), "grass_patchy"),
    "forest": ((14, 26, 16), (56, 76, 54), (50, 58, 46), "forest_floor"),
    # canyon relief is shaded sand, not rubble: a rock-material plateau over a
    # sand plain paints a dark slab with a rectangular outline
    "canyon": ((52, 34, 22), (158, 118, 78), (112, 86, 58), "sand_canyon"),
    "glacier": ((58, 74, 92), (234, 242, 250), (150, 162, 176), "ice_sheet"),
    "volcanic": ((34, 20, 18), (126, 68, 42), (62, 42, 34), "obsidian"),
    "wasteland": ((40, 26, 20), (114, 84, 62), (82, 62, 48), "gravel_rubble"),
    "ruins": ((30, 28, 24), (102, 100, 88), (72, 70, 60), "cobble_moss"),
    "city": ((20, 22, 28), (90, 92, 98), (62, 62, 66), "concrete_apron"),
    "airbase": ((22, 25, 23), (92, 94, 90), (64, 64, 62), "gravel_rubble"),
    "industrial": ((24, 26, 30), (98, 98, 102), (66, 64, 62), "rust_plate"),
    "swamp": ((18, 30, 26), (66, 86, 66), (54, 66, 54), "reed_marsh"),
    "ocean": ((10, 26, 44), (74, 114, 144), (42, 62, 82), "sand_canyon"),
}


#: What a field is *surfaced* with, by parcel kind. A crop field is bare tilled
# earth, not grass with lines on it: the whole point of a field is that the
# ground has been changed there. Pasture stays grass and is bounded by its fence
# instead.
FIELD_MAT = {
    # a pasture has to differ from the ground it was cut out of: grass_lush on
    # a grass_lush base is an invisible field
    "crop": "road_dirt", "pasture": "grass_patchy", "paddy": "water_paddy",
    "orchard": "grass_patchy", "lot": "concrete_apron",
    "park": "grass_lush", "yard": "mud_flat",
}

#: ...except in a city, where a "lot" is a paved yard.
FIELD_MAT_CITY = {"lot": "concrete_apron"}

__all__ = ["FAR_PAIR", "NEAR_MEAN", "NEAR_MATS", "THEME_MEAN", "WATER_MAT",
           "ROAD_MAT", "ROCK", "FIELD_MAT", "FIELD_MAT_CITY"]
