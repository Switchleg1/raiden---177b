"""Encounters placed by the ground, not by a timer.

The spawn director has always worked on a clock: every `spawn_interval` seconds
roll a kind and drop it over the top edge. That is why a sector stops feeling
like a place - the same grunt formation can arrive over a rice paddy, over a
car park and over a lava channel, because nothing about the ground was consulted
when it was placed.

This module asks the ground instead. A site plan already knows where the houses
are, where the water is, which flanks are steep and which fields are open. Those
are affordances, and an archetype has a home: a sentry belongs on a rooftop, a
heavy on a ridge flank, a splitter rising off a wet wash, a gunner at the end of
a road. Nothing here is random in the sense of unplaceable - every encounter is
anchored to a feature the player can see below it.

Coordinates are the plan's own space: bake pixels, x across the strip and y down
it from the sector's start (the same y the painted strips are indexed by). The
game converts to logical pixels when it releases an encounter, which is the only
place the two scales should meet.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

import config as C
from config.enemy_kind import EnemyKind
from terrain.common import NEAR_SPEED, SS
from terrain.plan.site_plan import SitePlan

__all__ = ["Encounter", "plan_encounters", "affordance_of"]

# What each archetype is looking for in the ground. The point is not realism for
# its own sake: a player who sees a hamlet below and then a turret climbing out
# of it understands the shot before it is fired.
AFFORDANCE = {
    EnemyKind.SENTRY: "roof",       # a turret on the highest thing in view
    EnemyKind.GUNNER: "roof",       # same: aimed from cover, not from empty sky
    EnemyKind.HEAVY: "ridge",       # slow, armoured: comes off high ground
    EnemyKind.RAMMER: "ridge",
    EnemyKind.SPLITTER: "wet",      # rises off a wash, and scatters over water
    EnemyKind.BOMBER: "wet",
    EnemyKind.GRUNT: "open",        # the filler: any clear ground will do
    EnemyKind.WEAVER: "open",
    EnemyKind.DARTER: "open",
}

LEAD_IN = 3.0       # seconds of clear ground before the first encounter
LEAD_OUT = 2.0      # seconds at the end, so a wave does not die mid-screen
SEARCH = 420.0      # bake px of ground searched around a beat for a site
PAD = 24.0          # bake px kept clear of the strip's side walls
DEFAULT_ROSTER = (("grunt", 60), ("weaver", 26), ("darter", 14))


def affordance_of(kind: EnemyKind) -> str:
    return AFFORDANCE.get(kind, "open")


@dataclass(frozen=True)
class Encounter:
    """A group the ground produces, at the place the ground produces it.

    `y` is where in the sector it lives, which is also when: an encounter is
    released as that stretch of ground reaches the screen. `form` and `count`
    carry the formation so the game does not have to invent one afterwards and
    lose the reason the group was standing there in the first place.
    """

    y: float
    x: float
    kind: EnemyKind
    count: int = 1
    form: str = "single"


def _pick(spec: Any, rng: random.Random) -> EnemyKind:
    """A kind from the sector's roster, at its sector's weights.

    The roster still comes from the level table - this chooses *which* thing the
    ground should produce, not what the sector is allowed to produce. A spec
    without one (a stub, a work in progress) gets the opening sector's mix
    rather than an AttributeError: the planner is asked for places, not for
    table validation.
    """
    roster = list(getattr(spec, "spawns", None) or DEFAULT_ROSTER)
    kinds = [str(k) for k, _w in roster]
    weights = [float(w) for _k, w in roster]
    return EnemyKind(rng.choices(kinds, weights=weights, k=1)[0])


def _formation(kind: EnemyKind, rng: random.Random) -> tuple[int, str]:
    """How many, and in what shape.

    A turret is one thing; infantry come in files. Keeping the shape here means
    the group that arrives matches the place it came out of - a hamlet puts up a
    pair of guns, not a parade.
    """
    if kind in (EnemyKind.SENTRY, EnemyKind.HEAVY, EnemyKind.BOMBER,
                EnemyKind.RAMMER):
        return (1, "single")
    if kind is EnemyKind.GUNNER:
        n = rng.choice((1, 2))
        return (n, "single" if n == 1 else "pair")
    roll = rng.random()
    if roll < 0.34:
        return (rng.choice((2, 3)), "line")
    if roll < 0.67:
        return (rng.choice((3, 5)), "v")
    return (1, "single")


def _clamp_x(g: Any, x: float) -> float:
    """Keep an encounter inside the playfield, not under the side walls."""
    lo, hi = C.FIELD_LEFT * SS + PAD, C.FIELD_RIGHT * SS - PAD
    return max(lo, min(hi, x))


def _roof(plan: SitePlan, y: float, rng: random.Random) -> tuple[float, float] | None:
    """A building near this stretch of ground. A gun rises out of the hamlet."""
    idxs = plan.band("buildings", y - SEARCH, y + SEARCH)
    if not idxs:
        return None
    b = plan.buildings[rng.choice(idxs)]
    return (_clamp_x(plan.geom, b.x), b.y)


def _ridge(plan: SitePlan, y: float, rng: random.Random) -> tuple[float, float] | None:
    """The flank of a ridge: high, exposed, and slow to reach.

    The offset is perpendicular to the spine, not sideways in x: a ridge that
    winds runs north-south as often as east-west, and an x offset would drop the
    group into the valley on the far side of a crest and call it a flank.
    """
    idxs = [i for i in plan.band("ridges", y - SEARCH, y + SEARCH)
            if len(plan.ridges[i].spine) >= 2]
    if not idxs:
        return None
    r = plan.ridges[rng.choice(idxs)]
    k = min(range(len(r.spine)), key=lambda i: abs(r.spine[i][1] - y))
    px, py = r.spine[k]
    q = r.spine[k + 1] if k + 1 < len(r.spine) else r.spine[k - 1]
    dx, dy = q[0] - px, q[1] - py
    ln = math.hypot(dx, dy) or 1.0
    side = 1.0 if rng.random() < 0.5 else -1.0
    off = r.width * 0.55 * side
    return (_clamp_x(plan.geom, px - dy / ln * off), py + dx / ln * off)


def _wet(plan: SitePlan, y: float, rng: random.Random) -> tuple[float, float] | None:
    """A channel or wash: things that scatter rise off water."""
    idxs = [i for i in plan.band("water", y - SEARCH, y + SEARCH)
            if plan.water[i].path]
    if not idxs:
        return None
    w = plan.water[rng.choice(idxs)]
    x, yy = min(w.path, key=lambda p: abs(p[1] - y))
    return (_clamp_x(plan.geom, x), yy)


def _open(plan: SitePlan, y: float, rng: random.Random) -> tuple[float, float] | None:
    """Clear ground: not built, not wet, and not on a crest.

    The fallback for the filler kinds, and the honest answer when the sector has
    nothing else here: over open fields anything may be standing.
    """
    for _ in range(10):
        x = rng.uniform(C.FIELD_LEFT * SS, C.FIELD_RIGHT * SS)
        if (not plan.is_built(x, y) and not plan.is_wet(x, y)
                and plan.relief_at(x, y) < 0.72):
            return (x, y)
    return None


_SITES = {"roof": _roof, "ridge": _ridge, "wet": _wet, "open": _open}


def _seed_of(plan: SitePlan, spec: Any) -> int:
    """Arithmetic, never hash(): the same sector must place the same encounters
    in a replay, and hash() moves between runs."""
    name_key = sum((i + 1) * ord(ch)
                   for i, ch in enumerate(str(getattr(spec, "name", ""))))
    return plan.seed * 1_000_003 + name_key


def plan_encounters(plan: SitePlan, spec: Any,
                    tail: float = 0.0) -> list[Encounter]:
    """The sector's encounters, in the order the player will fly into them.

    Spacing follows the sector's own pacing (`spawn_interval`, the same number
    the timer used) converted into ground: a beat every `spawn_interval` seconds
    of scroll, so the density of a sector is still a level-design number and has
    simply stopped being a clock. `tail` is seconds of ground past the wave that
    belong to the boss fight, and gets none of these: the boss fight is a fight,
    not a walk past more of the same.
    """
    g = plan.geom
    rng = random.Random(_seed_of(plan, spec))
    beat = max(60.0, float(getattr(spec, "spawn_interval", 1.0))
               * NEAR_SPEED * SS)
    y0 = LEAD_IN * NEAR_SPEED * SS
    y1 = g.h - (LEAD_OUT + tail) * NEAR_SPEED * SS
    out: list[Encounter] = []
    y = y0
    while y < y1:
        kind = _pick(spec, rng)
        site = _SITES[affordance_of(kind)](plan, y, rng)
        if site is not None and not (y0 <= site[1] <= y1):
            # the search window reaches past the sector's encounter band at both
            # ends; an anchor outside it is not this sector's to use
            site = None
        if site is None and affordance_of(kind) != "open":
            # nothing here for that archetype: the sector simply does not have
            # a rooftop, and inventing one in mid-air is the old behaviour
            site = _open(plan, y, rng)
        if site is not None:
            n, form = _formation(kind, rng)
            out.append(Encounter(y=site[1], x=site[0], kind=kind,
                                 count=n, form=form))
        y += beat
    out.sort(key=lambda e: e.y)
    return out
