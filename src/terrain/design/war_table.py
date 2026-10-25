"""What a war leaves on the ground, and how much of it.

`LevelSpec.scars` (0..1) says how fought-over a sector is. Sector 1 is the
approach - nothing has happened there yet - and the ground gets more broken the
deeper the campaign goes.
"""
from __future__ import annotations

#: Bombing runs per screen of strip at scars = 1: a stick of craters laid along
#: one line, the way bombs actually fall.
RUNS_PER_SCREEN = 1.4
#: Craters in one run, and the spacing along it (bake px).
RUN_LENGTH = (4, 9)
RUN_STEP = (46.0, 92.0)
#: Lone craters per screen at scars = 1 (shellfire, not bombing).
SINGLES_PER_SCREEN = 5.0
#: Crater art scale: a 250 px picture, so 0.2-0.48 is a 50-120 px hole (bake px;
#: half that on screen, where anything smaller reads as a pothole).
CRATER_SCALE = (0.2, 0.48)

#: Burned ground: zones per screen at scars = 1, and their radius (bake px).
BURNS_PER_SCREEN = 0.45
BURN_RADIUS = (200.0, 460.0)

#: What a fire turns a building into. Anything not listed survives (a tower's
#: concrete frame does not read as a burnt-out house, and is left standing).
BURNS_TO: dict[str, str] = {
    "house": "wreck", "house_suburb": "wreck", "house_suburb_tan": "wreck",
    "house_suburb_brown": "wreck", "house_suburb_slate": "wreck",
    "barn": "wreck", "hut": "wreck", "cabin": "wreck", "shack": "wreck",
    "tent_orange": "wreck", "tent_green": "wreck",
}

#: Wood kinds whose trees burn (orchards and hedges burn as well as woods).
BURNABLE_WOODS = frozenset({"wood", "copse", "riparian", "treeline", "orchard"})

__all__ = ["BURNABLE_WOODS", "BURNS_PER_SCREEN", "BURNS_TO", "BURN_RADIUS",
           "CRATER_SCALE", "RUNS_PER_SCREEN", "RUN_LENGTH", "RUN_STEP",
           "SINGLES_PER_SCREEN"]
