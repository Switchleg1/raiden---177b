"""Frontage: the houses along a road between the places."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..plan.green import Green
from .art import _face, ink_size
from .footprint import place_building
from .geometry import _along

if TYPE_CHECKING:
    from ..plan.site_plan import SitePlan
    from ..plan.site_spec import SiteSpec

import math
import random


def _along_extent(kind: str, scale: float, angle: float, tang: float) -> float:
    """How much ROOM a building takes along a road running at `tang`.

    Footprints are axis-aligned (buildings face the cardinal directions), so a
    building on a north-south road occupies its height along the road and one on an
    east-west road its width. Interpolating between the two by the road's own
    direction is exact enough for choosing a step, and the footprint test catches
    anything this under-estimates.
    """
    w, h = ink_size(kind, scale, angle)
    c = abs(math.cos(tang))
    s = abs(math.sin(tang))
    return w * c + h * s


def _settlement(spec: SiteSpec, plan: SitePlan, rng: random.Random) -> None:
    """Houses with frontage: on the road, facing it, set back from it, with a
    drive to it - and a hamlet where the road meets the water.

    Spacing here is sized from the ART, because that is what was missing. The frontage
    step used to be a fraction of the lane's arc (`0.05-0.09 * SCREEN_H / lane`), which
    on a multi-screen strip puts a centre every 56-100 bake px while a house at the
    scale being stamped is 150-220 px of ink wide: every frontage row overlapped the
    next one by half a house, at a random tilt, which is the report this module exists
    to fix. Now a house is placed where its own footprint fits, and the next one
    starts after that footprint ends.
    """
    if not spec.build or not plan.roads:
        return
    # the theme's own route, not the longest road in the sector: a six-screen
    # highway is longer than the lane a village fronts, and `max(len)` made the
    # village front the traffic
    main = max([r for r in plan.roads if r.kind in ("main", "ring")]
               or plan.roads, key=lambda r: len(r.path))
    # the green: where a bridge lands, or where the spur leaves the main road.
    # That is where a village actually forms.
    if spec.hamlet:
        at = plan.roads[0].bridges[0] if plan.roads[0].bridges else None
        if at is None:
            (_gx, _gy), _ = _along(main.path, rng.uniform(0.3, 0.7))
            at = (_gx, _gy)
        gx, gy = at
        radius = rng.uniform(34.0, 58.0)
        green = Green(x=gx, y=gy, radius=radius,
                      mat="cobble_moss" if plan.theme in ("countryside",
                                                          "ruins",
                                                          "farmland")
                      else "concrete_apron")
        # Houses around a green are spaced by their own size, not by a fixed count:
        # six houses on a small green were six roofs merged into one roof.
        room = 2.0 * math.pi * (radius + 52.0)
        n = max(0, min(6, int(room // (max(ink_size(spec.build[0], 0.85)) + 26.0))))
        for i in range(n):
            a = (i / float(n)) * math.tau + rng.uniform(-0.14, 0.14)
            d = radius + rng.uniform(46.0, 66.0)
            hx, hy = gx + math.cos(a) * d, gy + math.sin(a) * d
            b = place_building(plan, rng.choice(spec.build), hx, hy, (gx, gy),
                               rng.uniform(0.6, 0.78), "hamlet")
            if b is None:
                continue
            green.lanes.append([(hx, hy), (gx + math.cos(a) * radius,
                                           gy + math.sin(a) * radius)])
        plan.greens.append(green)
    # frontage: the row of houses along the road the player reads as a lane
    lane = sum(math.hypot(main.path[i + 1][0] - main.path[i][0],
                          main.path[i + 1][1] - main.path[i][1])
               for i in range(len(main.path) - 1)) or 1.0
    s = 0.04 * lane
    side = 1.0
    while s < 0.96 * lane:
        (bx, by), tang = _along(main.path, s / lane)
        kind = rng.choice(spec.build)
        scale = rng.uniform(0.58, 0.8)
        # Set the front EDGE back from the carriageway, then stand the centre far
        # enough in for the footprint to clear it: setting the CENTRE 40 px off a
        # 22 px road put half the house on the road.
        nx_, ny_ = math.cos(tang + math.pi / 2 * side), math.sin(tang + math.pi / 2 * side)
        front = rng.uniform(34.0, 64.0) + main.width * 0.5
        w, h = ink_size(kind, scale, _face(bx, by, bx + nx_, by + ny_))
        depth = h if abs(math.sin(tang)) > abs(math.cos(tang)) else w
        nx = bx + nx_ * (front + depth * 0.5)
        ny = by + ny_ * (front + depth * 0.5)
        b = place_building(plan, kind, nx, ny, (bx, by), scale, "frontage",
                           drive=[(nx, ny), (bx, by)],
                           yard=(nx + nx_ * 30.0, ny + ny_ * 30.0,
                                 rng.uniform(14.0, 22.0)))
        # Advance by whatever this house actually occupies, plus a gap - and when
        # the ground refused the house, advance by the house's own width anyway, so
        # a rejected site does not become the same candidate retried forever.
        step = _along_extent(kind, scale, _face(nx, ny, bx, by), tang)
        s += step + rng.uniform(26.0, 90.0) if b is not None else step
        side = -side
    # farmyards: set back off the road, at the edge of the fields. A farm is a
    # COMPOUND: a barn and a house with a yard between them, sized apart so their
    # roofs do not merge. The old code jittered both inside a 80x60 px box guarded
    # only by a centre distance smaller than either roof.
    for _ in range(rng.randint(1, 2) * plan.geom.screens):
        (bx, by), tang = _along(main.path, rng.uniform(0.1, 0.9))
        nx_, ny_ = math.cos(tang + math.pi / 2), math.sin(tang + math.pi / 2)
        off = rng.uniform(90.0, 150.0)
        fx, fy = bx + nx_ * off, by + ny_ * off
        barn = place_building(plan, "barn" if "barn" in spec.build else
                              spec.build[0], fx, fy, (bx, by),
                              rng.uniform(0.62, 0.78), "farm",
                              drive=[(fx, fy), (bx, by)])
        if barn is None:
            continue
        # the second building stands beside the first, clear of its footprint
        bw, bh = ink_size(barn.kind, barn.scale, barn.angle)
        span = max(bw, bh) + 34.0
        for k in range(rng.randint(1, 2)):
            hx = fx + math.cos(tang) * span * (k + 1)
            hy = fy + math.sin(tang) * span * (k + 1)
            place_building(plan, spec.build[0], hx, hy, (bx, by),
                           rng.uniform(0.58, 0.72), "farm",
                           drive=[(hx, hy), (bx, by)])
