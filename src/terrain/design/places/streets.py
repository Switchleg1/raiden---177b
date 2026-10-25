"""Streets: lanes, rows of houses, loops and estate trees."""
from __future__ import annotations

import math
import random

from ...plan.geom import Point
from ...plan.green import Green
from ...plan.road import Road
from ...plan.site_plan import SitePlan
from ...plan.wood import Wood
from ..art import _face, ink_size
from ..footprint import _shore_clear, place_building
from ..geometry import (
    _along,
    _clip_poly,
    _in_strip,
    _near_path,
)
from .ground import _claim_cells, _mark_corridor, add_parcel, add_road
from .shapes import _quad
from .vocabulary_table import AIR


def _lane_grow(plan: SitePlan, at: Point, ang: float, max_len: float,
               rng: random.Random, wind: float = 0.0) -> list[Point]:
    """Draw a lane by walking off the road until the ground stops.

    The alternative - pick a length, draw it, then reject the whole lane if anything
    in it is unsuitable - is why four of five seeds had no neighborhoods at all: the
    lane was a wish, the sector was already carved up by water corridors and roads,
    and the corridor test said no to thirty-six attempts in a row. A lane is whatever
    buildable ground runs off this point on this road, so it is generated to fit and
    the length is an upper bound, not a demand. 200 px is the floor: shorter than
    that and there is no row of houses to put on it.
    """
    g = plan.geom
    pts = [at]
    bend = rng.uniform(-0.5, 0.5)
    step = 40.0
    n = max(2, int(max_len / step))
    wet_run = 0
    for i in range(1, n + 1):
        t = i / n
        a = ang + bend * t
        d = step * i
        sway = wind * math.sin(t * math.pi * 1.1)
        x = at[0] + math.cos(a) * d + math.cos(a + math.pi / 2) * sway
        y = at[1] + math.sin(a) * d + math.sin(a + math.pi / 2) * sway
        if not (14.0 < x < g.w - 14.0) or not _in_strip(g, y):
            break
        if plan.is_place(x, y) or plan.relief_at(x, y) > 0.55:
            break
        if plan.is_wet(x, y):
            # a lane crosses a stream (the bridge pass gives it decks afterwards);
            # a lane that chases a floodplain is a track through a bog
            wet_run += 1
            if wet_run > 4:
                break
        else:
            wet_run = 0
        pts.append((x, y))
    return pts if len(pts) >= 5 else []


def _row_candidates(plan: SitePlan, rng: random.Random, lane: list[Point],
                    kinds: tuple[str, ...], scale: tuple[float, float],
                    front: float) -> list[dict]:
    """Where the houses on a lane would stand, before any of it is committed.

    Generated separately from the act of building so a lane can be ASKED whether it
    holds a street before it is laid. Laying a road and then failing to place a
    single house beside it is what produced thirty-odd empty lanes in one sector:
    the road got drawn because the ground was walkable, and the houses were refused
    afterwards because the ground beside it was wet or claimed.

    Two rows, one per side of the lane, each walked by arc and stepped by `what this
    house occupies along the lane + AIR` - the one rule that keeps a row from merging
    into one roof (it used to be a fixed arc fraction, which put a centre every
    56-100 px against a 150-220 px house). It used to be ONE walker alternating
    sides, which is why neighborhoods read as "single houses here and there": the
    step was spent whether or not the alternating side produced a house, so a 450 px
    lane against 190 px houses held two steps total.
    """
    arc = sum(math.hypot(lane[i + 1][0] - lane[i][0], lane[i + 1][1] - lane[i][1])
              for i in range(len(lane) - 1))
    out: list[dict] = []
    for side in (1.0, -1.0):
        # the two rows are not required to line up: a house opposite a gap is a
        # street, a house opposite a house is a hedge
        s = rng.uniform(18.0, 70.0)
        while s < arc - 24.0:
            (px, py), tang = _along(lane, s / arc)
            sc = rng.uniform(*scale)
            kind = kinds[len(out) % len(kinds)]
            ang_face = _face(px, py, px + math.cos(tang + math.pi / 2 * side),
                             py + math.sin(tang + math.pi / 2 * side))
            w, h = ink_size(kind, sc, ang_face)
            along = w * abs(math.cos(tang)) + h * abs(math.sin(tang))
            depth = h * abs(math.sin(tang)) + w * abs(math.cos(tang))
            nx_, ny_ = math.cos(tang + math.pi / 2 * side), \
                math.sin(tang + math.pi / 2 * side)
            # the house stands where the lane plus its setback puts it, and that can
            # fall off the end of the ground even when the lane point itself is inside
            hx = px + nx_ * (front + depth * 0.5)
            hy = py + ny_ * (front + depth * 0.5)
            if not (14.0 < hx < plan.geom.w - 14.0) or not (0.0 <= hy < plan.geom.h):
                s += along + AIR
                continue
            out.append({
                "kind": kind, "scale": sc, "angle": ang_face,
                "x": px + nx_ * (front + depth * 0.5),
                "y": py + ny_ * (front + depth * 0.5),
                "px": px, "py": py,
                "w": w, "h": h, "along": along, "depth": depth,
                "nx": nx_, "ny": ny_, "tang": tang, "side": side,
            })
            s += along + AIR + rng.uniform(6.0, 26.0)
    return out


def _near_other_road(plan: SitePlan, x: float, y: float, lane: list[Point]) -> bool:
    """Is this house on (or at the edge of) a road other than its own lane?

    A lane hanging off a highway must not put a front door on the carriageway:
    a neighborhood house once stood 14 px inside a 29 px highway, which a corridor
    test that only ever looked at the lane being built could not see. Asked at
    PROBE time as well as at build time, so what a street is scored on is what
    gets built on it.
    """
    return any(_near_path(plan.geom, x, y, other.path, other.width * 0.5 + 30.0)
               for other in plan.roads if other.path is not lane)


def _row_place(plan: SitePlan, rng: random.Random, sp: Road, lane: list[Point],
               cands: list[dict], group: str, lots: str | None) -> int:
    """Build the row. `place_building` is the only thing that says no here - it owns
    the footprint rules (wet, steep, claimed, off the carriageway), and every refusal
    is that rule rather than an extra filter invented on the spot."""
    built = 0
    for c in cands:
        hx, hy = c["x"], c["y"]
        # clear of every OTHER road: a lane hanging off a highway must not put a
        # front door on the carriageway. Measured: a neighborhood house stood 14 px
        # inside a 29 px highway, which the corridor test could not see because it
        # only ever looked at the lane being built.
        if _near_other_road(plan, hx, hy, lane):
            continue
        b = place_building(plan, c["kind"], hx, hy, (c["px"], c["py"]),
                           c["scale"], group,
                           drive=[(hx, hy), (c["px"], c["py"])], air=AIR)
        if b is None:
            continue
        built += 1
        if lots:
            # the lot is the ground BEHIND the house: a hedge row along its front
            # edge is what makes a lane read as owned parcels rather than houses
            # dropped in grass
            lw = max(c["w"], c["h"]) + 46.0
            lot = _clip_poly(plan.geom,
                             _quad(hx + c["nx"] * (c["depth"] * 0.5 + 26.0),
                                   hy + c["ny"] * (c["depth"] * 0.5 + 26.0),
                                   c["along"] + 40.0, lw, c["tang"]))
            # own the lot's ground whether or not the parcel survives its own rules,
            # or the next pass plants a tree in the garden
            _claim_cells(plan, lot)
            if len(lot) >= 3:
                add_parcel(plan, lot, lots, "lot", hedge=True)
            tx = hx + c["nx"] * (c["depth"] * 0.5 + lw * 0.5) + \
                math.cos(c["tang"]) * (c["along"] * 0.5 + 14.0)
            ty = hy + c["ny"] * (c["depth"] * 0.5 + lw * 0.5) + \
                math.sin(c["tang"]) * (c["along"] * 0.5 + 14.0)
            # inside the ground being planned: the tree sits at the far corner of
            # the lot, and a lot whose house is near the strip's edge puts that
            # corner off the map (`a_strip_is_designed_not_stretched` measured one
            # at x = -53). A tree that is not on the map is not on the map.
            if (12.0 < tx < plan.geom.w - 12.0 and _in_strip(plan.geom, ty)
                    and not plan.is_wet(tx, ty)
                    and _shore_clear(plan, tx, ty, 0.5)):
                plan.woods.append(Wood(kind="wood",
                                       items=[(tx, ty, rng.uniform(0.34, 0.5))]))
    return built


def _build_street(plan: SitePlan, rng: random.Random, lane: list[Point],
                  kinds: tuple[str, ...], scale: tuple[float, float],
                  front: float, group: str, lots: str | None,
                  road_kind: str, head: bool, fits_min: int = 2,
                  both_sides: bool = True) -> int:
    """One street: pave it if it holds a street, and put houses on both sides.

    `front` (the setback) and `scale` are chosen ONCE for the whole neighborhood,
    not per house. That is what makes a row read as built by one builder rather than
    as a scatter that happens to be nearby: the reference neighbourhoods in the
    screenshots are organised because the frontage line is consistent along a
    street, and every house in a row is roughly the same size.
    """
    cands = _row_candidates(plan, rng, lane, kinds, scale, front)
    # Ask with the street in place. `add_road` claims the carriageway's cells, and a
    # house may not stand on a road - so counting fits before the road existed counted
    # houses the road would later evict. Measured on one estate: six candidates probed
    # as fitting, one or two committed, and the sector shipped lanes with a house or
    # two on them instead of rows.
    CORRIDOR = 13.0 * 0.5 + 6.0
    marked = _mark_corridor(plan, lane, CORRIDOR)
    fits = [c for c in cands
            if not _near_other_road(plan, c["x"], c["y"], lane)
            and place_building(plan, c["kind"], c["x"], c["y"],
                               (c["px"], c["py"]), c["scale"], group,
                               drive=[(c["x"], c["y"]), (c["px"], c["py"])],
                               air=AIR, commit=False) is not None]
    for (j, i) in marked:
        plan.built[j][i] = False        # `add_road` below re-claims them for real
    if len(fits) < fits_min:
        return 0
    # A street has houses on BOTH sides. Three or more on one side and none on the
    # other is a frontage strip along a river or a road the estate happened to
    # brush - the opposite of "houses facing each other across a street". A loop is
    # exempt (its houses face the middle of it, which is why a loop is built).
    if both_sides and len(fits) >= 3 and len({c["side"] for c in fits}) < 2:
        return 0
    sp = add_road(plan, road_kind, lane, 13.0)
    if sp is None:
        return 0
    if head:
        # a cul-de-sac ends in a head the houses turn around: an asphalt disc with
        # a grass island in it, which is also where the neighborhood's trees go
        ex, ey = lane[-1]
        plan.greens.append(Green(x=ex, y=ey, radius=24.0, mat="road_asphalt"))
        plan.greens.append(Green(x=ex, y=ey, radius=9.0, mat="grass_lush"))
    n = _row_place(plan, rng, sp, lane, fits, group, lots)
    if n == 0:
        # The probe asks about each house alone, so two candidates can each fit and
        # not fit together; a street can end up paved with nobody on it. A street to
        # nowhere is the tell of generated ground: take it back out.
        plan.roads.remove(sp)
        if head:
            del plan.greens[-2:]
    return n


def _ring_fit(plan: SitePlan, at: Point, radius: float, rng: random.Random,
              sweep: float = math.tau) -> list[Point]:
    """A loop road: a ring of ground around a centre, kept only where the ground
    allows, and only as one continuous arc.

    The loop is the shape a real subdivision makes - traffic comes back to where it
    started instead of dead-ending into a field - and it is also what makes a
    neighborhood read as designed from the air. A ring that survives in fragments
    would be slop, so the longest unbroken stretch is kept and the rest is dropped.
    """
    g = plan.geom
    cx = at[0] + math.cos(rng.uniform(0, math.tau)) * radius * 0.55
    cy = at[1] + math.sin(rng.uniform(0, math.tau)) * radius * 0.55
    n = 26
    wob = rng.uniform(0.86, 1.14)
    phase = rng.uniform(0, math.tau)
    run: list[Point] = []
    best: list[Point] = []
    for i in range(n + 1):
        a = phase + sweep * i / n
        r = radius * wob * (1.0 + 0.08 * math.sin(3 * a + phase))
        x, y = cx + math.cos(a) * r, cy + math.sin(a) * r * 0.85
        ok = (16.0 < x < g.w - 16.0 and _in_strip(g, y)
              and not plan.is_place(x, y) and not plan.is_wet(x, y)
              and plan.relief_at(x, y) <= 0.55)
        if ok:
            run.append((x, y))
        else:
            if len(run) > len(best):
                best = run
            run = []
    if len(run) > len(best):
        best = run
    return best if len(best) >= 12 else []


def _estate_trees(plan: SitePlan, streets: list[list[Point]], rng: random.Random,
                  budget: int) -> int:
    """A HANDFUL of trees, on the streets, not a wood between the houses.

    The complaint was that the neighborhoods were slop in a field of trees: every
    lot had its own garden tree, every lane was hedged in, and the whole sector
    read as scrub with roofs in it. A real subdivision has street trees and a few
    in the parkland, and the density that belongs in the trees is put in the
    woodland instead, where it is the point.
    """
    made = 0
    spots: list[Point] = []
    for lane in streets:
        # the head of a cul-de-sac, and the middle of a street's outer side
        ex, ey = lane[-1]
        spots.append((ex, ey))
        mid = lane[len(lane) // 2]
        spots.append(mid)
    for (sx, sy) in spots:
        if made >= budget:
            break
        for _ in range(6):
            a = rng.uniform(0, math.tau)
            d = rng.uniform(26.0, 44.0)
            x, y = sx + math.cos(a) * d, sy + math.sin(a) * d
            if not (14.0 < x < plan.geom.w - 14.0) or not _in_strip(plan.geom, y):
                continue
            sc = rng.uniform(0.42, 0.62)
            if plan.is_built(x, y) or plan.is_wet(x, y):
                continue
            if not _shore_clear(plan, x, y, sc):
                continue
            if _near_path(plan.geom, x, y, [p for lane in streets for p in lane],
                          16.0):
                continue
            plan.woods.append(Wood(kind="yard", items=[(x, y, sc)]))
            made += 1
            break
    return made
