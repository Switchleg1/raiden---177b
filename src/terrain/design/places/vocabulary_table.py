"""The places the planner knows how to build."""
from __future__ import annotations

from .place_spec import PlaceSpec

# How much air a place keeps between its own footprints, bake px. Slightly larger
# than the building-to-building margin in `siteplan`: a place should read as a
# pattern of objects, and objects touching each other read as one blob.
AIR = 22.0


# A place's claimed disc also keeps the later passes off its ground: `cover` will
# not grow a tree in a cul-de-sac, `fields` will not enclose a campsite.
CLAIM_PAD = 12.0


# how far a place will go to find a way in, bake px
ROAD_MAX = 430.0


#: The vocabulary. A theme picks a subset in `SPEC.places`; the blueprints live here.
VOCABULARY: dict[str, PlaceSpec] = {
    "neighborhood": PlaceSpec(
        name="neighborhood", per=(2.0, 3.0), reach=430.0, keep=210.0, order=0,
        against="road",
        against_max=260.0,
        kinds=("house_suburb", "house_suburb_tan", "house_suburb_brown",
               "house_suburb_slate")),
    "highway": PlaceSpec(
        # order -1: a highway forbids more ground than anything else in the
        # vocabulary, so it asks first. Laid after a neighborhood it drove through
        # the houses that were already standing there - the corridor test guards
        # NEW buildings, not old ones - and a building ended up 14 px inside the
        # carriageway.
        # one every twelve-plus screens: a highway is a through-route, and at one
        # per screen three of them criss-crossed a four-screen city and took most of
        # its blocks
        name="highway", per=(12.0, 16.0), reach=240.0, keep=150.0, order=-1,
        needs=("flat", "offroad"),
        kinds=("depot", "container", "pylon")),
    "lake": PlaceSpec(
        name="lake", per=(2.5, 4.0), reach=330.0, keep=210.0,
        needs=("flat", "offroad"),
        kinds=("shed",), shun=(("neighborhood", 520.0), ("downtown", 600.0))),
    "woodland": PlaceSpec(
        # reach 760 and keep 340: a forest has an EDGE, and the edge is what makes
        # it a forest rather than a density setting applied to the whole map
        name="woodland", per=(2.5, 4.0), reach=760.0, keep=340.0, order=2,
        needs=("offroad",), kinds=("deer_stand",),
        shun=(("neighborhood", 700.0), ("downtown", 800.0))),
    "campground": PlaceSpec(
        name="campground", per=(3.0, 4.5), reach=250.0, keep=140.0, order=3,
        needs=("flat", "dry", "offroad"), road_max=ROAD_MAX - 60.0,
        offroad=150.0,
        against="water", against_max=330.0,
        kinds=("tent_orange", "tent_green", "tent_green")),
    "plains": PlaceSpec(
        # laid after the settlements and the woods: open country is what is LEFT
        # open, and claiming it first would push every estate off the flat ground
        name="plains", per=(3.0, 4.5), reach=520.0, keep=380.0, order=4,
        needs=("flat", "dry", "offroad"), offroad=120.0),
    "farmstead": PlaceSpec(
        # against_max 220, not 300: the plan's own rule is that every building is
        # reached by a road (within 260 px), and a farmstead's second range is
        # laid a barn-length further along the yard - at 300 px of slack the barn
        # itself was already out of reach of the lane it served.
        name="farmstead", per=(2.0, 3.0), reach=300.0, keep=150.0, order=2,
        against="road",
        against_max=210.0, kinds=("barn", "house")),
}
