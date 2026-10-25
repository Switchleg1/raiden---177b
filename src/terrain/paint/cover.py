"""Craters under the buildings; trees and debris over them."""
from __future__ import annotations

import random
from typing import Any

from ..plan.site_plan import SitePlan
from ..tilekit import TileKit
from .cover_table import COVER_PROPS
from .ink import _prop
from .sampling import _band, _frand


def _cover_props(theme: str, kind: str) -> tuple[str, ...]:
    from ..design.spec_table import _DEFAULT, SPEC
    spec = SPEC.get(theme, _DEFAULT)
    if kind in ("outcrop", "scree"):
        return (spec.ridge_prop,)
    if kind in COVER_PROPS:
        return COVER_PROPS[kind]
    if kind == "pylon_row":
        # a highway's pylons are a ROW of one prop, not vegetation: this is how a
        # place lays something the tree vocabulary cannot express
        return ("mast_lattice",)
    return spec.tree_props or ("tree_clump",)


def paint_scars(canvas: Any, kit: TileKit, plan: SitePlan,
                rng: random.Random) -> None:
    """Craters: over the ground, the roads and the fields, under the buildings
    and the trees - a crater is a hole IN the ground, and a road through a bombed
    field is a broken road."""
    for wdi in _band(canvas, plan, "woods"):
        wd = plan.woods[wdi]
        if wd.kind != "crater":
            continue
        for x, y, s in wd.items:
            _prop(kit, canvas, "crater", x, y, s, rng, rot4=True)


def paint_cover(canvas: Any, kit: TileKit, plan: SitePlan,
                rng: random.Random) -> None:
    for wdi in _band(canvas, plan, "woods"):
        wd = plan.woods[wdi]
        frng = _frand(plan, wdi, 37)
        if wd.kind == "crater":
            continue                  # laid under the buildings by `paint_scars`
        if wd.kind in ("scree", "outcrop"):
            # rock DEBRIS is not a landform. Stamping cluster sprites along a
            # crest gave "boulder fences" - a row of individually drawn rocks
            # instead of one mass of rock. The relief painter shades the ridge
            # itself; debris is only speckled into it
            continue
        names = _cover_props(plan.theme, wd.kind)
        for x, y, s in wd.items:
            name = names[frng.randrange(len(names))]
            _prop(kit, canvas, name, x, y, s, rng,
                  rot4=wd.kind not in ("riparian", "orchard"),
                  shadow=6.0 * s)
