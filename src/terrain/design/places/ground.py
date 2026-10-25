"""Adding water, parcels and roads to a plan, through the rules."""
from __future__ import annotations

import math

from ...plan.field import Field
from ...plan.geom import Point
from ...plan.road import Road
from ...plan.site_plan import SitePlan
from ..drainage import _water_mark_body
from ..geometry import (
    _clip_poly,
    _in_poly,
    _in_strip,
    _near_path,
    _span,
)
from .shapes import _poly_area, _segs_cross


def add_water(plan: SitePlan, w) -> bool:
    """Put a water body on the ground, and mark the ground it makes wet NOW.

    The orogeny pass rasterised `wet` before any blueprint existed, so water laid
    later was invisible to every later check until this existed: a blueprint lake
    did not make its own shore wet, a lane could be grown through it, a house could
    stand in it, and the fields pass ploughed its middle. A body that would stand in
    another place's reservation or drown a building is refused here, once, rather
    than contradicted downstream.
    """
    if len(w.path) < 3:
        return False
    if w.inside is not None and plan.is_place(w.inside[0], w.inside[1]):
        return False
    for b in plan.buildings:
        if (w.closed and _in_poly(b.x, b.y, w.path)) or _near_path(
                plan.geom, b.x, b.y, w.path, w.half + 14.0):
            return False
    if w.closed:
        # Standing water keeps clear of standing water. Two lakes laid over each
        # other paint as two overlapping circles - a figure of eight with a seam
        # through it - and nothing about real ground makes that shape.
        for o in plan.water:
            if not o.closed:
                continue
            if any(_in_poly(x, y, o.path) for x, y in w.path[::2]) or any(
                    _in_poly(x, y, w.path) for x, y in o.path[::2]):
                return False
            if _near_path(plan.geom, w.inside[0] if w.inside else w.path[0][0],
                          w.inside[1] if w.inside else w.path[0][1], o.path,
                          w.half + 60.0):
                return False
    # A road may CROSS water - that is what a bridge is - but it may not run along
    # it. A big blueprint lake laid beside an existing carriageway puts the road and
    # the water side by side for hundreds of pixels, which is the "road runs with the
    # river" contradiction the plan already forbids for orogeny-laid water. Counting
    # the samples that sit in the corridor tells the two apart: a crossing is one or
    # two, a chase along the shore is many.
    for r in plan.roads:
        along = 0
        for (px, py) in r.path[::2]:
            if _near_path(plan.geom, px, py, w.path, w.half + 34.0):
                along += 1
        if along >= 4:
            return False
    # ...and no road in it at all. A short chord is a bridge over the head of an
    # inlet, which is a real thing roads do over RIVERS - but across a standing body
    # it reads as the causeway bisecting a lake, which is the "roadway across the
    # water" the user objected to. Point tests miss it: a road can sail across the
    # outline between two of its own samples. The segments have to be tested.
    if w.closed:
        for r in plan.roads:
            if any(_in_poly(sx, sy, w.path) for (sx, sy) in r.path):
                return False
            cut = 0
            for (ax, ay), (bx, by) in zip(r.path, r.path[1:],
                                       strict=False):
                for i in range(len(w.path) - 1):
                    if _segs_cross(ax, ay, bx, by,
                                   w.path[i][0], w.path[i][1],
                                   w.path[i + 1][0], w.path[i + 1][1]):
                        cut += 1
                        break
            if cut:
                return False
    # A sector is not all water. Big lakes are the point - a forest lake should be a
    # landmark, not a puddle - but three of them in one sector measured 60% of the
    # ground as wet, and a map that is mostly lake has nowhere for a lane, a field or
    # a house. One body gets an eighth of the sector, all of them together get a
    # fifth.
    if w.closed:
        area = plan.geom.w * plan.geom.h
        mine = _poly_area(w.path)
        if mine > area * 0.12:
            return False
        laid = sum(_poly_area(x.path) for x in plan.water if x.closed)
        if laid + mine > area * 0.20:
            return False
    plan.water.append(w)
    _water_mark_body(plan, w)
    return True


def add_parcel(plan: SitePlan, poly: list[Point], mat: str, kind: str,
               hedge: bool = False) -> Field | None:
    """Register a parcel a place is laying, if it is a parcel at all.

    Two rules every pass already obeys and a blueprint must not skip: the parcel
    is inside the ground being planned, and it does not stand in wet ground. A
    neighborhood lot or a rest-stop apron placed by offset arithmetic breaks both
    without being asked.
    """
    poly = _clip_poly(plan.geom, poly)
    if len(poly) < 3:
        return None
    xs = [q[0] for q in poly]
    ys = [q[1] for q in poly]
    if max(xs) - min(xs) < 24.0 or max(ys) - min(ys) < 24.0:
        return None
    # inside the ground being planned: `_clip_poly` follows y (that is where the
    # wrapping happens) and leaves x alone, so a lot hung off a lane near the edge
    # kept a vertex at x = -41 and the plan shipped it
    if min(xs) < 0.0 or max(xs) > plan.geom.w:
        return None
    if any(plan.is_wet(qx, qy) for qx, qy in poly):
        return None
    # and clear of the carriageways: a parcel that grows over a road hides it,
    # which is what "field swallows the road" measured. A highway's own shoulder
    # starts outside that band, so this does not forbid shoulders - it forbids
    # paving over the carriageway. Corners alone are not enough: a parcel can
    # cover a road between vertices, so the interior is sampled too.
    from ..geometry import _in_poly, _near_path
    x0, y0 = min(xs), min(ys)
    probe = list(poly)
    gx = int((max(xs) - x0) // 40) + 1
    gy = int((max(ys) - y0) // 40) + 1
    probe += [(x0 + (i + 0.5) * 40.0, y0 + (j + 0.5) * 40.0)
              for i in range(gx)
              for j in range(gy)
              if _in_poly(x0 + (i + 0.5) * 40.0, y0 + (j + 0.5) * 40.0, poly)]
    for qx, qy in probe:
        for r in plan.roads:
            lo = min(pt[1] for pt in r.path)
            hi = max(pt[1] for pt in r.path)
            if not (lo - 30.0 <= qy <= hi + 30.0):
                continue
            if _near_path(plan.geom, qx, qy, r.path, r.width * 0.5 + 6.0):
                return None
    f = Field(poly=poly, mat=mat, kind=kind, hedge=hedge)
    plan.fields.append(f)
    return f


def _inside(plan: SitePlan, x: float, y: float, pad: float = 14.0) -> bool:
    """Is a point inside the strip the plan covers?

    A campground's parked block, a lake's dock or a cul-de-sac head placed by
    offset arithmetic can end up outside the ground being designed. Measured: a
    car park at x = -41, which the painter then tried to draw - and a test that
    asks whether every planned point is inside the strip caught it.
    """
    g = plan.geom
    return (pad <= x <= g.w - pad) and _in_strip(g, y)


def _claim_cells(plan: SitePlan, poly: list[Point]) -> None:
    """Reserve the cells a parcel polygon covers (see `SitePlan.place`)."""
    g = plan.geom
    if plan.place is None:
        plan.place = [[False] * g.cols for _ in range(g.rows)]
    xs = [q[0] for q in poly]
    ys = [q[1] for q in poly]
    j0, j1 = _span(min(ys), max(ys), g.rows, g.cell)
    i0, i1 = _span(min(xs), max(xs), g.cols, g.cell)
    for j in range(j0, j1 + 1):
        cy = j * g.cell + g.cell / 2
        for i in range(i0, i1 + 1):
            cx = i * g.cell + g.cell / 2
            if _in_poly(cx, cy, poly):
                plan.place[j][i] = True


def _road_ok(r: Road) -> Road | None:
    """Decline a road that is not a route (see :func:`add_road`)."""
    if len(r.path) < 2:
        return None
    if sum(math.hypot(r.path[i + 1][0] - r.path[i][0],
                      r.path[i + 1][1] - r.path[i][1])
           for i in range(len(r.path) - 1)) < 8.0:
        return None
    return r


def _mark_corridor(plan: SitePlan, path: list[Point], half: float) -> list[tuple[int, int]]:
    """Claim the cells a carriageway covers, and hand back the ones that were newly
    claimed so a caller can put them back.

    This exists so a street can be ASKED the right question. `_build_street` counted
    how many houses fit before the road was laid, then laid the road, which claimed
    its own corridor and made those houses overlap it: a probe that found six fits
    committed one or two, and the sector ended with lanes and a house or two on each
    instead of a street. The probe has to see the street.
    """
    g = plan.geom
    set_cells: list[tuple[int, int]] = []
    for (px, py) in path:
        j0, j1 = _span(py - half, py + half, g.rows, g.cell)
        i0, i1 = _span(px - half, px + half, g.cols, g.cell)
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                cx, cy = i * g.cell + g.cell / 2, j * g.cell + g.cell / 2
                if _near_path(g, cx, cy, path, half) and not plan.built[j][i]:
                    plan.built[j][i] = True
                    set_cells.append((j, i))
    return set_cells


def add_road(plan: SitePlan, kind: str, path: list[Point],
             width: float) -> Road | None:
    """Register a road the place is laying, if it is a road at all.

    A route needs two distinct points to be a route. A horizontal highway next to
    the strip's edge has nowhere to run and produced a one-point path, which the
    painter then rejected with "points argument must contain 2 or more points" -
    a crash coming out of the paint workers, in a band, at runtime. The blueprint
    that cannot draw its road should decline, and say so by returning nothing.
    """
    if len(path) < 2:
        return None
    if sum(math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
           for i in range(len(path) - 1)) < 8.0:
        return None
    r = Road(kind=kind, path=path, width=width)
    # A blueprint's road consults the water it is drawn next to. `build_campground`'s
    # entry track and `build_lake`'s shed track are placed by offset arithmetic AFTER
    # the water exists, and a track drawn into a lake paints a causeway across it -
    # the "road down the middle of the water" again, through a gate the water rules
    # never saw. A crossing is a short run of wet samples (the bridge pass puts decks
    # on it afterwards); a run through the body is long.
    run = worst = 0
    for (px, py) in path:
        if plan.is_wet(px, py):
            run += 1
            worst = max(worst, run)
        else:
            run = 0
    if worst > 3:
        return None
    # a lane that crosses a channel needs a deck, exactly like the routed roads:
    # this was the "road fords the river" artifact, and a blueprint that adds a
    # road without asking the water about it puts it straight back
    from ..circulation import _add_decks, _bridge_spans
    _add_decks(r, _bridge_spans(plan.geom, path, plan.water))
    plan.roads.append(r)
    # The carriageway is ground something else already needs. The lot behind one
    # house reached across the street next door and sat on it
    # (`fields_do_not_swallow_the_road`: "lot parcel covers the road"), because a
    # road reserved nothing. Marked in `built`, not in `place`: a building may not
    # stand on a road, but a lane must still be able to CROSS another lane - the
    # `place` grid would forbid the T-junctions that make a neighborhood a network
    # instead of a set of dead ends.
    half = width * 0.5 + 6.0
    _mark_corridor(plan, path, half)
    return r
