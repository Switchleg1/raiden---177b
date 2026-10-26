"""A woodland: a forest with a lake in it."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .ground import _claim_cells, add_water
from .shapes import _ellipse, _shore

if TYPE_CHECKING:
    from .anchor import _Site
    from .place_spec import PlaceSpec

import math
import random

from ...plan.site_plan import SitePlan
from ...plan.water import Water
from ...plan.wood import Wood
from ..footprint import _shore_clear, tree_clear_of_buildings
from ..geometry import (
    _in_strip,
)


def build_woodland(plan: SitePlan, site: _Site, ps: PlaceSpec,
                   rng: random.Random) -> int:
    """A forest with a lake in it: ground where the trees ARE the point.

    Two things this replaces. The first is the sector-wide scatter: vegetation used
    to be sprinkled over every unclaimed cell, which is what "there tends to be too
    many trees in general" measures - a 4-screen sector was holding 350-530 trees,
    most of them thinnings between houses and along every drain. Forest is not a
    density setting, it is a PLACE with an edge: inside it the ground is mostly
    trees, outside it the ground is fields, lanes and houses with a few trees.
    The second is the lake, which had no reason to be big: a forest lake is a mere
    or a lake, and the water and the trees arrive together because that is how the
    ground works - water collects where the land dips, and the trees keep it in.
    """
    made = 0
    # the water first: the trees are laid around it, not through it
    cls = rng.choices(("mere", "lake"), weights=(4, 6))[0]
    rx = {"mere": rng.uniform(260.0, 430.0),
          "lake": rng.uniform(500.0, 780.0)}[cls]
    ry = rx * rng.uniform(0.58, 0.9)
    for _ in range(6):
        # the forest asks for a big lake and takes what the sector can spare: the
        # water budget in `add_water` refuses a body that would drown too much of the
        # ground, and a woodland around a mere is still a woodland
        poly = _shore(site.x, site.y, rx, ry, rng)
        body = Water(kind="lake", path=poly, half=ry * 0.95, flood=rx * 0.2,
                     closed=True, inside=(site.x, site.y))
        if add_water(plan, body):
            made += 1
            break
        rx *= 0.72
        ry *= 0.72
    if not made:
        return 0
    # the woods: dense, clustered, with glades - and stopped by the shore
    g = plan.geom
    reach = rx * 2.1
    trees = 0
    tries = 0
    while trees < rng.randint(120, 240) and tries < 900:
        tries += 1
        a = rng.uniform(0, math.tau)
        d = rng.uniform(ry * 1.15, reach)
        cx = site.x + math.cos(a) * d
        cy = site.y + math.sin(a) * d * 0.8
        if not (16.0 < cx < g.w - 16.0) or not _in_strip(g, cy):
            continue
        # a glade: gaps are what make a wood read as a wood rather than as texture
        if rng.random() < 0.16:
            continue
        items = []
        for _ in range(rng.randint(5, 11)):
            ba = rng.uniform(0, math.tau)
            br = abs(rng.gauss(0, 52.0))
            x, y = cx + math.cos(ba) * br, cy + math.sin(ba) * br * 0.85
            sc = tree_clear_of_buildings(plan, x, y, rng.uniform(0.55, 1.15),
                                         20.0)
            if sc is None or not (14.0 < x < g.w - 14.0) \
                    or not _in_strip(g, y):
                continue
            if plan.is_wet(x, y) or plan.is_built(x, y) or plan.is_place(x, y):
                continue
            if not _shore_clear(plan, x, y, sc):
                continue
            if plan.relief_at(x, y) > 0.72:
                continue
            if plan.near_road(x, y, 30.0):
                continue
            items.append((x, y, sc))
        if len(items) >= 4:
            plan.woods.append(Wood(kind="wood", items=items))
            trees += len(items)
    # The forest's OWN ground is the shore band, not the whole reach. Reserving the
    # reach claimed a disc wider than the map in a big-lake forest (rx 780 -> a
    # 3200 px ring in a 1600 px-wide sector), and every other blueprint - camp,
    # farmstead, neighborhood - found the sector already taken and built nothing at
    # all. The trees spread to the reach; the reservation is where the water and its
    # shore are, which is the part another pass would actually contradict.
    shore = _ellipse(site.x, site.y, rx * 1.22, ry * 1.22, n=14, wob=0.1, rng=rng)
    _claim_cells(plan, shore)
    return made + trees
