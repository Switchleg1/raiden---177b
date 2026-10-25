"""Which builder lays which place."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .campground import build_campground
from .farmstead import build_farmstead
from .highway import build_highway
from .lake import build_lake
from .neighborhood import build_neighborhood
from .plains import build_plains
from .woodland import build_woodland

if TYPE_CHECKING:
    from .anchor import _Site
    from .place_spec import PlaceSpec

import random
from collections.abc import Callable

from ...plan.site_plan import SitePlan

BUILDERS: dict[str, Callable[[SitePlan, _Site, PlaceSpec, random.Random], int]] = {
    "neighborhood": build_neighborhood,
    "highway": build_highway,
    "lake": build_lake,
    "woodland": build_woodland,
    "campground": build_campground,
    "farmstead": build_farmstead,
    "plains": build_plains,
}
