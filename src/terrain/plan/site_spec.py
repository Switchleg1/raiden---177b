"""What a theme's ground is made of, in planning terms."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SiteSpec:
    """What a theme's ground is made of, in planning terms."""

    ridge_shapes: tuple[str, ...] = ("massif", "ridge")
    ridge_weight: float = 0.7        # chance a candidate ridge is kept
    relief_gain: float = 1.0         # peak height the theme's ground hits
    ridge_count: tuple[int, int] = (1, 2)
    ridge_prop: str = "rock_cluster"
    water_kinds: tuple[str, ...] = ("river",)
    road: str = "main"               # main | ring | none
    build: tuple[str, ...] = ("house",)
    # NOTE: there is deliberately no house_gap. Spacing between buildings is
    # the size of the buildings (see INK / ink_size), which is the only rule
    # that can hold across kinds as different as a hut and a 255 px warehouse.
    hamlet: bool = True
    field_kinds: tuple[str, ...] = ()
    field_count: tuple[int, int] = (0, 0)
    tree_props: tuple[str, ...] = ("tree_clump",)
    #: which places this theme knows how to build (see terrain.places.VOCABULARY).
    #: This is the theme's SETTLEMENT character: countryside knows neighborhoods
    #: and campgrounds by the water, a city knows neighborhoods and a highway, a
    #: forest knows campgrounds and lakes, a canyon knows neither.
    places: tuple[str, ...] = ()
    woods: tuple[int, int] = (2, 4)
    #: how hard the main river swings: 1 is a lowland river, a city's is a
    #: straightened, embanked channel
    meander: float = 1.0
    #: which kind of mountain range this ground grows (see `mountain_table`);
    #: "" for none
    ranges: str = ""
    treeline: bool = True
    scree: bool = True
    hedge: str = "hedge"
