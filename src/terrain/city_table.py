"""What a city block can be, and what it is built with."""
from __future__ import annotations

#: Block types by zone, as (type, weight). The CORE is downtown - towers,
#: apartments, shops with their parking; the EDGE is where people live.
BLOCK_MIX: dict[str, tuple[tuple[str, int], ...]] = {
    "core": (("towers", 4), ("apartments", 3), ("shops", 3), ("parking", 1),
             ("park", 1)),
    "edge": (("residential", 7), ("apartments", 1), ("shops", 1), ("park", 1)),
}

#: Building kinds per role, and the scale range each is drawn at.
TOWER = ("office_tower", (0.56, 0.72))
APARTMENT = ("apartment_block", (0.58, 0.74))
SHOPS = ("shop_row", (0.58, 0.72))
HOUSES = (("house_suburb", "house_suburb_tan", "house_suburb_brown",
           "house_suburb_slate", "house"), (0.34, 0.4))
CARS = (("car_red", "car_white", "car_blue", "car_grey", "car_grey", "car_white"),
        0.15)

#: Surfaces, by role.
MAT_SIDEWALK = "concrete_apron"
MAT_PLAZA = "concrete_apron"
MAT_PARKING = "gravel_rubble"
MAT_PARK = "grass_lush"
MAT_YARD = "grass_lush"

#: How far a block's buildable ground sits back from a street's centreline,
#: beyond half the carriageway: the kerb and the pavement.
SIDEWALK = 12.0

#: Share of a parking lot's stalls that hold a car.
OCCUPANCY = 0.7

__all__ = ["APARTMENT", "BLOCK_MIX", "CARS", "HOUSES", "MAT_PARK", "MAT_PARKING",
           "MAT_PLAZA", "MAT_SIDEWALK", "MAT_YARD", "OCCUPANCY", "SHOPS",
           "SIDEWALK", "TOWER"]
