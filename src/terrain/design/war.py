"""Battle damage: craters, and ground a fire has been through.

Laid LAST, over a sector that has already been designed as if nothing had
happened to it, because that is what war damage is: the same roads, fields and
houses, broken. A crater lands on a road or a field as readily as on waste
ground; it does not land in a river or inside a standing building. A burn
blackens the ground, strips the trees to charred trunks and leaves houses as
shells.

Drawn from its own random stream, keyed by the plan's seed: a sector with no
scars is exactly the sector it was before this module existed.
"""
from __future__ import annotations

import math
import random

from ..plan.field import Field
from ..plan.geom import Point
from ..plan.site_plan import SitePlan
from ..plan.wood import Wood
from .geometry import _in_poly, _in_strip
from .war_table import (
    BURN_RADIUS,
    BURNABLE_WOODS,
    BURNS_PER_SCREEN,
    BURNS_TO,
    CRATER_SCALE,
    RUN_LENGTH,
    RUN_STEP,
    RUNS_PER_SCREEN,
    SINGLES_PER_SCREEN,
)


def _count(rate: float, screens: int, scars: float, rng: random.Random) -> int:
    """A count with the right mean: `rate * screens * scars`, rounded at random."""
    mean = rate * screens * scars
    n = int(mean)
    return n + (1 if rng.random() < mean - n else 0)


def _crater_ok(plan: SitePlan, x: float, y: float, r: float) -> bool:
    g = plan.geom
    if not (r < x < g.w - r) or not _in_strip(g, y):
        return False
    if plan.is_wet(x, y):
        return False
    for b in plan.buildings:
        if abs(b.x - x) < r + 40.0 and abs(b.y - y) < r + 40.0:
            return False
    return True


def _craters(plan: SitePlan, scars: float, rng: random.Random) -> list[tuple]:
    g = plan.geom
    items: list[tuple[float, float, float]] = []
    lo, hi = CRATER_SCALE
    for _ in range(_count(RUNS_PER_SCREEN, g.screens, scars, rng)):
        # a stick of bombs: one heading, evenly-ish spaced, a little scatter
        x, y = rng.uniform(80.0, g.w - 80.0), rng.uniform(0.0, g.h)
        a = rng.uniform(0.0, math.tau)
        sc = rng.uniform(lo, hi * 0.8)
        for _k in range(rng.randint(*RUN_LENGTH)):
            cx = x + rng.gauss(0.0, 10.0)
            cy = y + rng.gauss(0.0, 10.0)
            s = sc * rng.uniform(0.8, 1.2)
            if _crater_ok(plan, cx, cy, 125.0 * s):
                items.append((cx, cy, s))
            step = rng.uniform(*RUN_STEP)
            x += math.cos(a) * step
            y += math.sin(a) * step
    for _ in range(_count(SINGLES_PER_SCREEN, g.screens, scars, rng)):
        x, y = rng.uniform(40.0, g.w - 40.0), rng.uniform(0.0, g.h)
        s = rng.uniform(lo, hi)
        if _crater_ok(plan, x, y, 125.0 * s):
            items.append((x, y, s))
    return items


def _blob(x: float, y: float, r: float, rng: random.Random) -> list[Point]:
    """An irregular burn outline: fire runs with the wind and stops at gaps."""
    harm = [(k, rng.uniform(0.04, 0.16) / k ** 0.5, rng.uniform(0, math.tau))
            for k in (2, 3, 5, 7)]
    pts = []
    for i in range(36):
        a = i / 36 * math.tau
        k = 1.0 + sum(amp * math.sin(f * a + ph) for f, amp, ph in harm)
        pts.append((x + math.cos(a) * r * k, y + math.sin(a) * r * k * 0.8))
    return pts


def _burn(plan: SitePlan, poly: list[Point]) -> None:
    """Everything inside a burn: shells for houses, charred trunks for trees."""
    for b in plan.buildings:
        if b.kind in BURNS_TO and _in_poly(b.x, b.y, poly):
            b.kind = BURNS_TO[b.kind]
            b.yard = None
    charred: list[tuple[float, float, float]] = []
    for wd in plan.woods:
        if wd.kind not in BURNABLE_WOODS:
            continue
        keep = []
        for it in wd.items:
            (charred if _in_poly(it[0], it[1], poly) else keep).append(it)
        wd.items = keep
    plan.woods[:] = [wd for wd in plan.woods if wd.items]
    if charred:
        # a burned tree keeps its place and loses most of its crown
        plan.woods.append(Wood(kind="charred",
                               items=[(x, y, s * 0.8) for x, y, s in charred]))


def _burns(plan: SitePlan, scars: float, rng: random.Random) -> list[list[Point]]:
    g = plan.geom
    out = []
    for _ in range(_count(BURNS_PER_SCREEN, g.screens, scars, rng)):
        x, y = rng.uniform(0.2, 0.8) * g.w, rng.uniform(0.0, g.h)
        poly = _blob(x, y, rng.uniform(*BURN_RADIUS), rng)
        poly = [(min(g.w, max(0.0, px)), py) for px, py in poly]
        out.append(poly)
        _burn(plan, poly)
        # The scorched ground itself. Painted as a soft field (see paint_fields),
        # and laid FIRST among the fields so a farm's parcel that survived is
        # drawn over it rather than buried under ash.
        plan.fields.insert(0, Field(poly=poly, mat="ash_ground", kind="scorch",
                                    hedge=False))
    return out


def scar(plan: SitePlan, scars: float) -> None:
    """Lay battle damage over a finished plan. `scars` 0 leaves it untouched."""
    if scars <= 0.0:
        return
    rng = random.Random(plan.seed * 7_919 + 104_729)
    _burns(plan, scars, rng)
    items = _craters(plan, scars, rng)
    if items:
        plan.woods.append(Wood(kind="crater", items=items))
    plan.scars = scars
    plan._bands = None            # the feature index is stale now


__all__ = ["scar"]
