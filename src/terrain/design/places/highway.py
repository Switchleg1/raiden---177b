"""A highway: a through-route with its corridor, pylons and rest stop."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .ground import _claim_cells, _road_ok, add_parcel, add_road
from .shapes import _quad
from .vocabulary_table import AIR

if TYPE_CHECKING:
    from .anchor import _Site
    from .place_spec import PlaceSpec

import math
import random

from ...plan.road import Road
from ...plan.site_plan import SitePlan
from ...plan.wood import Wood
from ..art import ink_size
from ..footprint import _near_building, place_building
from ..geometry import (
    _along,
    _vpath,
)


def build_highway(plan: SitePlan, site: _Site, ps: PlaceSpec,
                  rng: random.Random) -> int:
    """A straight run with shoulders, pylons and a rest stop.

    A highway is defined by what it does NOT allow: a corridor nothing builds in,
    which is the only reason it reads as a highway rather than as another road
    with houses on it.
    """
    g = plan.geom
    # a highway goes the way the ground goes: mostly along the strip's length
    # On a strip, always along it: a highway across a strip is a few hundred px of
    # road that starts and ends at the map edge, which is a bridge to nowhere.
    vert = (not g.cyclic) or rng.random() < 0.75
    y0 = max(40.0, site.y - rng.uniform(0.6, 1.3) * g.h * 0.5)
    y1 = min(g.h - 40.0, site.y + rng.uniform(0.6, 1.3) * g.h * 0.5)
    if not g.cyclic:
        # a through-route runs through: from one end of the sector to the other
        y0, y1 = -40.0, g.h + 40.0
    if y1 - y0 < 500.0:
        return 0
    terms = [(1, rng.uniform(0.005, 0.02), rng.uniform(0, 6.28))]
    path = _vpath(g, site.x, terms, step=60, y_lo=y0, y_hi=y1) if vert else \
        [(x, site.y + math.sin(x / 900.0) * 60.0)
         for x in range(int(max(40.0, site.x - 700.0)),
                        int(min(g.w - 40.0, site.x + 700.0)), 60)]
    width = rng.uniform(26.0, 34.0)
    hr = Road(kind="highway", path=path, width=width, shoulder=16.0)
    if _road_ok(hr) is None:
        return 0
    from ..circulation import _add_decks, _bridge_spans
    _add_decks(hr, _bridge_spans(plan.geom, path, plan.water))
    plan.roads.append(hr)
    # Shoulders are the road's own (`Road.shoulder`), painted by the road painter:
    # modelling them as parcels produced a highway of ~200 narrow polygons per
    # attempt, and the city rules then read every one of them as a block.
    arc = sum(math.hypot(path[i + 1][0] - path[i][0],
                         path[i + 1][1] - path[i][1])
              for i in range(len(path) - 1)) or 1.0
    # pylons along one side at a fixed pitch: tall thin markers are what let the
    # eye measure a road's speed, and a highway without them is a wide dirt band
    masts: list[tuple[float, float, float]] = []
    s = 90.0
    while s < arc - 90.0:
        (px, py), tang = _along(path, s / arc)
        nx_, ny_ = math.cos(tang - math.pi / 2), math.sin(tang - math.pi / 2)
        mx, my = px + nx_ * (width * 0.5 + 52.0), py + ny_ * (width * 0.5 + 52.0)
        if 12.0 < mx < g.w - 12.0 and not plan.is_wet(mx, my) \
                and not _near_building(plan, mx, my, 110.0):
            # a pylon is 254 px of steel lattice at the anchor and the row is
            # planted every 250 px along a road that runs THROUGH the country: it
            # has to step over the houses it would otherwise stand in
            masts.append((mx, my, rng.uniform(0.24, 0.32)))
        s += rng.uniform(210.0, 300.0)
    if len(masts) >= 3:
        plan.woods.append(Wood(kind="pylon_row", items=masts))
    # the rest stop: a depot with containers on an apron, reached by a short spur
    pad = None
    for _ in range(6):
        (px, py), tang = _along(path, rng.uniform(0.25, 0.75))
        side = 1.0 if rng.random() < 0.5 else -1.0
        nx_, ny_ = math.cos(tang + math.pi / 2 * side), \
            math.sin(tang + math.pi / 2 * side)
        cand = (px + nx_ * 92.0, py + ny_ * 92.0)
        if plan.is_wet(cand[0], cand[1]) or plan.relief_at(cand[0], cand[1]) > 0.42:
            continue
        pad = (cand[0], cand[1], tang, px, py)
        break
    # From here the highway EXISTS, so every return counts it. Returning the rest
    # stop's building count instead (0 when the stop did not fit) told `lay_places`
    # nothing had been built, and it laid another highway: four of them criss-
    # crossed one four-screen city.
    if pad is None:
        return 1
    px, py, tang = pad[3], pad[4], pad[2]
    apron = _quad(pad[0], pad[1], 210.0, 150.0, tang)
    if add_parcel(plan, apron, "concrete_apron", "lot") is None:
        return 1
    _claim_cells(plan, apron)
    add_road(plan, "track", [(px, py), (pad[0], pad[1])], 11.0)
    built = 0
    d = place_building(plan, "depot", pad[0] + math.cos(tang) * 40.0,
                       pad[1] + math.sin(tang) * 40.0, (px, py),
                       rng.uniform(0.42, 0.56), "highway", air=AIR)
    if d is not None:
        built += 1
        dw, dh = ink_size("depot", d.scale, d.angle)
        for i in range(rng.randint(2, 3)):
            cx = pad[0] - math.cos(tang) * (dw * 0.5 + 34.0 * (i + 1))
            cy = pad[1] - math.sin(tang) * (dw * 0.5 + 34.0 * (i + 1))
            if place_building(plan, "container", cx, cy, (px, py),
                              rng.uniform(0.16, 0.22), "highway", air=12.0):
                built += 1
    return 1 + built
