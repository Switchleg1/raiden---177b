"""The prop art: what each plan kind is drawn with, how big it is, which way
its front faces."""
from __future__ import annotations

#: Which prop art a plan kind is drawn with. ``paint_buildings`` falls back to
#: ``house_top`` for any name it does not recognise, which is why every "barn"
#: the game has ever placed has been a house.
PROP_OF: dict[str, str] = {"house": "house_top", "barn": "barn_red", "hut": "hut_stilt",
           "shack": "hut_stilt", "cabin": "hut_stilt", "shed": "crate_stack",
           "silo": "storage_tank", "tank": "storage_tank",
           "depot": "warehouse_long", "warehouse": "warehouse_long",
           "pylon": "mast_lattice", "tower": "antenna_dish",
           "container": "cargo_container", "crate": "crate_stack",
           "tree": "tree_clump", "pine": "pine_clump", "rock": "rock_cluster",
           "wreck": "wreck_burnt", "campfire": "campfire"}

#: Opaque ink extents of each prop, in ART px at scale 1 - the bounding box of the
#: non-transparent pixels inside the 256 px art box, not the art box itself.
#
#: Every spacing rule in this module derives from these numbers, because a house
#: set beside another one used to mean 56-100 bake px of arc along a road while the
#: art is 221 px wide: frontage rows were GUARANTEED to overlap, which is the
#: "houses piled on top of each other randomly" report. The rule being replaced was
#: centre-to-centre (`house_gap` 78-95 px) against an object ~160 px wide.
#:
#: `tests/test_terrain_siteplan.py` measures the art and fails if a number here goes
#: stale, so a redrawn sprite cannot silently invalidate the spacing underneath it.
INK: dict[str, tuple[float, float]] = {
    "antenna_dish": (222.0, 253.0), "barn_red": (182.0, 254.0),
    "basalt_spire": (207.0, 254.0), "cargo_container": (254.0, 245.0),
    "crate_stack": (252.0, 226.0), "cypress_clump": (252.0, 251.0),
    "dead_tree": (249.0, 250.0), "house_top": (221.0, 254.0),
    "hut_stilt": (250.0, 195.0), "ice_boulder": (253.0, 254.0),
    "lava_vent": (249.0, 252.0), "mast_lattice": (254.0, 234.0),
    "pine_clump": (252.0, 253.0), "pine_snow": (249.0, 252.0),
    "rock_cluster": (254.0, 251.0), "storage_tank": (254.0, 247.0),
    "tree_clump": (254.0, 235.0), "warehouse_long": (255.0, 76.0),
    # drawn by scripts/paint_props.py
    "apartment_block": (248.0, 146.0), "campfire": (245.0, 238.0),
    "car_blue": (112.0, 249.0), "car_grey": (112.0, 249.0),
    "car_red": (112.0, 249.0), "car_white": (112.0, 249.0),
    "crater": (251.0, 256.0), "house_suburb": (246.0, 239.0),
    "house_suburb_brown": (246.0, 239.0), "house_suburb_slate": (246.0, 239.0),
    "house_suburb_tan": (246.0, 239.0), "office_tower": (245.0, 249.0),
    "shop_row": (252.0, 102.0), "tent_green": (178.0, 247.0),
    "tent_orange": (178.0, 247.0), "tree_charred": (239.0, 249.0),
    "truck_semi": (74.0, 253.0), "wreck_burnt": (247.0, 233.0),
}

INK_DEFAULT: tuple[float, float] = (256.0, 256.0)

#: Which way the FRONT of each picture points, as drawn (plan degrees, y down:
#: 0 right, 90 down, 180 left, 270 up). Most of the art shows its door, garage,
#: awning or barn doors at the bottom; a car is drawn nose up.
ART_FRONT_DEFAULT = 90
ART_FRONT: dict[str, int] = {
    "car_red": 270, "car_white": 270, "car_blue": 270, "car_grey": 270,
    "truck_semi": 270,
}

__all__ = ["ART_FRONT", "ART_FRONT_DEFAULT", "INK", "INK_DEFAULT", "PROP_OF"]
