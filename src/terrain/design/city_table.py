"""What a city block can be, and what it is built with."""
from __future__ import annotations

#: Block types by zone, as (type, weight). The CORE is downtown - towers,
#: apartments, shops with their parking; the EDGE is where people live.
BLOCK_MIX: dict[str, tuple[tuple[str, int], ...]] = {
    "core": (("towers", 4), ("apartments", 3), ("shops", 3), ("parking", 2),
             ("park", 1)),
    "edge": (("residential", 7), ("apartments", 1), ("shops", 1), ("park", 1)),
}

#: What a block holds instead when it is too small for what it drew: the next
#: building down, ending at houses (which fit any block the grid makes).
STEP_DOWN: dict[str, str] = {"towers": "apartments", "apartments": "shops",
                             "shops": "residential"}

#: Building kinds per role, and the scale range each is drawn at.
TOWER = ("office_tower", (0.56, 0.72))
APARTMENT = ("apartment_block", (0.58, 0.74))
SHOPS = ("shop_row", (0.58, 0.72))
HOUSES = (("house_suburb", "house_suburb_tan", "house_suburb_brown",
           "house_suburb_slate", "house"), (0.30, 0.35))
CARS = (("car_red", "car_white", "car_blue", "car_grey", "car_grey", "car_white"),
        0.15)

#: Surfaces, by role.
MAT_SIDEWALK = "concrete_apron"
MAT_PLAZA = "concrete_apron"
MAT_PARKING = "gravel_rubble"
MAT_PARK = "grass_lush"
#: the ground between a city's buildings: NOT the park grass. `grass_lush` is the
#: countryside's turf and every city block was laid out on a field of it - half
#: the sector read as a suburb with offices in it. `cobble_moss` is the city's own
#: ground (a duller, darker version of it), so a yard reads as open city ground.
#: `grass_patchy` was tried and is a tan (mean 88 against the city's 50): the
#: whole sector went the colour of a playing field.
MAT_YARD = "cobble_moss"

#: How far a block's buildable ground sits back from a street's centreline,
#: beyond half the carriageway: the kerb and the pavement.
SIDEWALK = 12.0

#: The gap a row keeps between neighbours, by block type (bake px, padded on
#: every side of each footprint and rounded out to planning cells - so the gap
#: actually kept is about twice this plus a cell). At 18 px a house claimed
#: 124x127 px of a 200 px block and every block front held ONE house; a city
#: street is a terrace, not a row of detached villas.
ROW_AIR: dict[str, float] = {"residential": 6.0, "apartments": 8.0, "shops": 4.0}

#: How far a row of buildings slides along its street to try again when a
#: footprint is refused: one planning cell, the resolution the refusal was made at.
ROW_SLIDE = 20.0

#: Share of a parking lot's stalls that hold a car.
OCCUPANCY = 0.7

#: which way a building on each side of a block faces: out, toward its street
SIDE_FACING: dict[str, tuple[float, float]] = {
    "n": (0.0, -1.0), "s": (0.0, 1.0), "w": (-1.0, 0.0), "e": (1.0, 0.0),
}

__all__ = ["SIDE_FACING", "APARTMENT", "BLOCK_MIX", "CARS",
           "HOUSES",
           "MAT_PARK", "MAT_PARKING",
           "MAT_PLAZA", "MAT_SIDEWALK", "MAT_YARD", "OCCUPANCY", "ROW_AIR", "ROW_SLIDE", "SHOPS",
           "SIDEWALK", "STEP_DOWN", "TOWER"]
