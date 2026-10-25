"""A subdivision: collector, loop, culs-de-sac, houses facing streets."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .ground import _mark_corridor
from .siting import _nearest_road
from .streets import _build_street, _estate_trees, _lane_grow, _ring_fit, _row_candidates
from .vocabulary_table import AIR

if TYPE_CHECKING:
    from .anchor import _Site
    from .place_spec import PlaceSpec

import math
import random

from ...plan.geom import Point
from ...plan.site_plan import SitePlan
from ..footprint import place_building
from ..geometry import (
    _along,
)


def build_neighborhood(plan: SitePlan, site: _Site, ps: PlaceSpec,
                       rng: random.Random) -> int:
    """A subdivision: a collector off the road, a loop, culs-de-sac, and houses
    facing the street they stand on.

    The old version was one dead-end lane with houses alternating down it, which is
    a lane with houses, not a neighborhood. A real one (the photographs the user
    supplied) has a HIERARCHY - a collector entering from the main road, a loop that
    brings traffic back, culs-de-sac off both - a consistent setback along each
    street, houses on both sides facing it, a green or pond somewhere in the middle,
    and few trees between the houses because the trees belong in the woodland.
    """
    hit = _nearest_road(plan, site.x, site.y)
    if hit is None:
        return 0
    road, (ax0, ay0), tang0, dist = hit
    group = "neighborhood"
    lots = "grass_lush" if plan.theme != "city" else "concrete_apron"
    # One builder, one estate: a subdivision is a handful of house types in one or
    # two roof colours, not one of every house in the catalogue. Two colours drawn
    # from the vocabulary, alternated down each street.
    pool = list(ps.kinds or ("house",))
    rng.shuffle(pool)
    kinds = tuple(pool[:2]) if len(pool) > 1 else tuple(pool)

    def score_street(lane: list[Point], kinds: tuple[str, ...],
                     scale: tuple[float, float], front: float) -> int:
        """How many houses this lane would hold, without committing to anything.

        The estate used to take the first anchor that cleared a bar. The anchors are
        drawn at random along a road that is already there, so the first one that
        works is usually ground that merely works: a collector that fits two houses
        where one 300 px along the same road fits six. Score the ground, build on the
        best of it."""
        if len(lane) < 4:
            return 0
        marked = _mark_corridor(plan, lane, 13.0 * 0.5 + 6.0)
        try:
            n = 0
            for c in _row_candidates(plan, rng, lane, kinds, scale, front):
                if place_building(plan, c["kind"], c["x"], c["y"],
                                  (c["px"], c["py"]), c["scale"], "score",
                                  air=AIR, commit=False) is not None:
                    n += 1
            return n
        finally:
            for (j, i) in marked:
                plan.built[j][i] = False

    for _ in range(7):
        best: tuple[int, list[Point], float] = (0, [], 0.0)
        for _scan in range(9):
            (ax, ay), tang = _along(road.path, rng.uniform(0.1, 0.9))
            side = 1.0 if rng.random() < 0.5 else -1.0
            front = rng.uniform(24.0, 34.0)
            # a collector is the long street of the estate: 420-700 px held two
            # houses per side at the art's frontage, which is a lane, not the
            # "bunch of houses facing a street" being asked for
            lane = _lane_grow(plan, (ax, ay), tang + side * math.pi / 2,
                              rng.uniform(560.0, 980.0), rng,
                              wind=rng.uniform(0.0, 40.0))
            sc = score_street(lane, kinds,
                              (rng.uniform(0.40, 0.46), rng.uniform(0.49, 0.55)),
                              front)
            if sc > best[0]:
                best = (sc, lane, front)
        _, collector, front = best
        if not collector:
            continue
        # One scale band for the whole estate, and a smaller house than the plan used
        # to place. At scale 0.55 a house is ~120 px across and a 300 px lane holds
        # two of them, so every "street" the estate tried produced one house and was
        # thrown away - measured: 30 street attempts, zero houses, on two seeds. At
        # 0.40-0.50 the row is ~95 px of house and a real street length holds a real
        # row, which is also what the reference photographs show: many similar small
        # houses, not a few big ones.
        scale = (rng.uniform(0.40, 0.46), rng.uniform(0.49, 0.55))
        jx, jy = collector[-1]
        # The loop and the culs-de-sac are grown when they are BUILT, not all up
        # front. Growing them first meant they were routed through ground the
        # collector's houses had already taken: the lots were claimed after the
        # streets were chosen, and a cul-de-sac laid across a neighbour's garden is
        # exactly the slop the user is asking the designer to stop making
        # (`fields_do_not_swallow_the_road` caught a lot parcel sitting on a road).

        def grow_spine(from_streets: list[list[Point]]) -> list[Point]:
            base = from_streets[rng.randrange(len(from_streets))]
            (bx, by), btang = _along(base, rng.uniform(0.3, 0.9))
            for sgn in (1.0, -1.0):
                cul = _lane_grow(plan, (bx, by), btang + sgn * math.pi / 2,
                                 rng.uniform(300.0, 520.0), rng,
                                 wind=rng.uniform(0.0, 30.0))
                if len(cul) >= 5:
                    return cul
            return []

        # Pave the collector first, so its frontage is claimed ground before any
        # other street is routed.
        total = 0
        built: list[list[Point]] = []
        # "spur", not "main": in this plan `main` is the sector's through-route (the
        # road that carries the encounters and the widest carriageway). A
        # subdivision's collector hangs off it, and a house's drive has to reach a
        # lane of the estate it belongs to.
        n = _build_street(plan, rng, collector, kinds, scale, front, group, lots,
                          "spur", head=False, fits_min=3)
        if n < 2:
            continue
        total += n
        built.append(collector)
        loop = _ring_fit(plan, (jx, jy), rng.uniform(380.0, 620.0), rng)
        if len(loop) >= 12:
            loop = [(jx, jy)] + loop
            m = _build_street(plan, rng, loop, kinds, scale, front, group, lots,
                              "spur", head=False, fits_min=3, both_sides=False)
            if m:
                total += m
                built.append(loop)
        for _cul in range(3):
            cul = grow_spine(built)
            if not cul:
                continue
            m = _build_street(plan, rng, cul, kinds, scale, front, group, lots,
                              "spur", head=True)
            if m:
                total += m
                built.append(cul)
        # Five houses is an estate; eight was a gate that mostly rejected the good
        # ground because a loop plus culs-de-sac needs room, and the sectors that
        # could not fit it came out with no neighborhood at all.
        if total >= 4:
            # No pond. Still water inside the loop was a feature of the first estate
            # design, and the user's word on it is the rule: lakes don't belong in a
            # neighbourhood. The middle of a loop is back gardens.
            _estate_trees(plan, built, rng, budget=rng.randint(4, 7))
            return total
    return 0
