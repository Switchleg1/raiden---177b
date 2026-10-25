"""Cover: woods, treelines, scree and the trees between things."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..plan.wood import Wood
from .footprint import _near_building, _shore_clear
from .geometry import _in_strip

if TYPE_CHECKING:
    from ..plan.site_plan import SitePlan
    from ..plan.site_spec import SiteSpec

import math
import random


def _cover(spec: SiteSpec, plan: SitePlan, rng: random.Random) -> None:
    """Vegetation and debris follow the ground: woods on ground nothing else
    claims, a treeline where the hillside turns, trees along the water, scree at
    the ridge foot and outcrops on its crest. Trees come in clusters with gaps,
    because a uniform scatter of foliage is the single loudest tell of generated
    ground."""
    g = plan.geom
    props = spec.tree_props
    if props:
        lo, hi = spec.woods
        for _ in range(rng.randint(lo, hi) * g.screens):
            cx, cy = rng.uniform(40, g.w - 40), rng.uniform(20, g.h - 20)
            if plan.relief_at(cx, cy) > 0.7 or plan.is_wet(cx, cy) \
                    or plan.is_built(cx, cy) or plan.is_place(cx, cy) \
                    or plan.near_road(cx, cy, 34.0):
                continue
            n = rng.randint(3, 7)              # clustered, never uniform
            items = []
            for _ in range(n):
                a = rng.uniform(0, math.tau)
                r = abs(rng.gauss(0, 46.0))
                x, y = cx + math.cos(a) * r, cy + math.sin(a) * r * 0.8
                sc = rng.uniform(0.45, 1.05)
                if 12 < x < g.w - 12 and _in_strip(g, y) \
                        and plan.relief_at(x, y) < 0.72 \
                        and not plan.is_built(x, y) \
                        and not plan.is_place(x, y) \
                        and not plan.is_wet(x, y) \
                        and _shore_clear(plan, x, y, sc) \
                        and not _near_building(plan, x, y, 60.0):
                    items.append((x, y, sc))
            if len(items) >= 3:
                plan.woods.append(Wood(kind="wood", items=items))
        # riparian corridor: trees follow the water, with gaps
        for w in plan.water:
            step = 0.0
            for i in range(len(w.path) - 1):
                a, b = w.path[i], w.path[i + 1]
                ln = math.hypot(b[0] - a[0], b[1] - a[1])
                step += ln
                # One tree per ~110 px of bank, at 20%: the corridor used to plant a
                # tree every 62 px at 42%, which is a wall of foliage along every
                # drain in the sector, and the sector read as scrub with roofs in it
                # (measured: 347-529 trees in a 4-screen countryside sector).
                if step > 110.0:
                    step = 0.0
                    if rng.random() < 0.20:      # the corridor is not a wall
                        side = 1.0 if rng.random() < 0.5 else -1.0
                        ang = math.atan2(b[1] - a[1], b[0] - a[0]) + \
                            side * math.pi / 2
                        # a crown over the channel hides the bank, and "its
                        # banks disappear under foliage" was the single most
                        # repeated note: the corridor has to stay a corridor
                        d = w.half + rng.uniform(42.0, 76.0)
                        x = a[0] + math.cos(ang) * d
                        y = a[1] + math.sin(ang) * d
                        sc = rng.uniform(0.5, 0.8)
                        if 12 < x < g.w - 12 and _in_strip(g, y) \
                                and not plan.is_built(x, y) \
                                and not plan.is_place(x, y) \
                                and not plan.is_wet(x, y) \
                                and _shore_clear(plan, x, y, sc) \
                                and not _near_building(plan, x, y, 50.0):
                            plan.woods.append(Wood(
                                kind="riparian", items=[(x, y, sc)]))
        # treeline where the hillside turns: contour-following, so it reads as
        # the top of the trees rather than a random band of them
        if spec.treeline:
            for ridge in plan.ridges:
                items = []
                for i in range(len(ridge.spine) - 1):
                    (ax, ay), (bx, by) = ridge.spine[i], ridge.spine[i + 1]
                    if rng.random() < 0.55:
                        continue
                    ang = math.atan2(by - ay, bx - ax) + math.pi / 2
                    d = ridge.width * rng.uniform(0.55, 0.8)
                    x = ax + math.cos(ang) * d
                    sc = rng.uniform(0.6, 1.0)
                    if 12 < x < g.w - 12:
                        y = ay + math.sin(ang) * d
                        # a treeline follows the hillside, and the hillside goes on
                        # underneath a lake: relief was laid before the water and has
                        # no idea the water exists. Measured, this planted a lattice of
                        # crowns at ~40 px spacing straight across three lakes, which
                        # is what "dry ground with lines through the middle" looked
                        # like after the fill itself was fixed.
                        if (_in_strip(g, y) and not plan.is_wet(x, y)
                                and _shore_clear(plan, x, y, sc)
                                and not _near_building(plan, x, y, 50.0)):
                            items.append((x, y, sc))
                if len(items) >= 6:
                    plan.woods.append(Wood(kind="treeline", items=items))
        # orchard rows inside one field
        for f in plan.fields:
            if f.kind == "orchard":
                items = []
                for a, b in f.furrows[::2]:
                    n = 3
                    for k in range(n):
                        t = (k + 0.5) / n
                        ox = a[0] + (b[0] - a[0]) * t
                        oy = a[1] + (b[1] - a[1]) * t
                        if _near_building(plan, ox, oy, 46.0):
                            continue     # an orchard is not a hedge on a house
                        items.append((ox, oy, rng.uniform(0.4, 0.55)))
                if items:
                    plan.woods.append(Wood(kind="orchard", items=items))
    # debris: scree fans at the ridge foot, outcrops on the crest. Both are
    # LINEAR: a line of rock reads as a ridge, a scatter of rock reads as a
    # level-design mistake.
    if spec.scree:
        for ridge in plan.ridges:
            fan: list[tuple[float, float, float]] = []
            crest: list[tuple[float, float, float]] = []
            for i in range(len(ridge.spine) - 1):
                (ax, ay), (bx, by) = ridge.spine[i], ridge.spine[i + 1]
                idx = min(len(ridge.crest) - 1,
                          int(i / max(1, len(ridge.spine) - 1)
                              * len(ridge.crest)))
                hgt = ridge.crest[idx]
                ang = math.atan2(by - ay, bx - ax) + math.pi / 2
                if rng.random() < 0.22 and hgt > 0.25 \
                        and not _near_building(plan, ax, ay, 90.0):
                    d = ridge.width * rng.uniform(0.75, 1.15)
                    fx = ax + math.cos(ang) * d
                    fy = ay + math.sin(ang) * d
                    # a scree fan does not sit in a river, and not next to a
                    # barn either: nothing stands where the slope lets go
                    if not plan.near_water(fx, fy, 70.0) \
                            and not _near_building(plan, fx, fy, 70.0) \
                            and 12.0 < fx < plan.geom.w - 12.0:
                        fan.append((fx, fy, 0.3 + 0.5 * hgt))
                if hgt > 0.68 and not plan.near_water(ax, ay, 60.0):
                    # a rocky crest is CONTINUOUS: outcrops every few spine
                    # points, overlapping, so the eye reads one mass of rock
                    # along the top of the ridge. Scattered at 6% they read as
                    # "individual boulders, not a coherent ridge" - the most
                    # common complaint about the planned maps
                    crest.append((ax, ay, 0.3 + 0.3 * hgt))
                elif rng.random() < 0.05:
                    cx2 = ax
                    cy2 = ay
                    if not plan.near_water(cx2, cy2, 60.0):
                        crest.append((cx2, cy2, 0.35 + 0.45 * hgt))
            if len(fan) >= 3:
                plan.woods.append(Wood(kind="scree", items=fan))
            if len(crest) >= 2:
                plan.woods.append(Wood(kind="outcrop", items=crest))
