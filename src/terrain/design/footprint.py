"""The one way a building enters the plan, and the ground it takes."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..plan.building import Building
from ..plan.geom import CELL
from .art import _face, _ink_rect
from .geometry import _in_poly, _near_path, _span

if TYPE_CHECKING:
    from ..plan.geom import Point
    from ..plan.site_plan import SitePlan

import math

from .field_table import LIFTABLE_FIELDS


def _shore_clear(plan: SitePlan, x: float, y: float, scale: float) -> bool:
    """Would this tree's crown hang over standing water?

    The shore band in the wet grid is a *building* margin (26 px): ground you will not
    put a house on. A tree is a different object - the art is a 256 px ink box and the
    crown is roughly 90 px of radius at scale 1 - so a lake ringed by trees planted
    just outside its wet band came out with pale blobs sitting on the water (measured:
    mask 1.0 water pixels reading 46-58 luminance because a crown was painted over
    them; the lake test calls it "dry ground with lines in it").

    Only CLOSED bodies are tested. A tree leaning over a narrow stream is what a
    stream bank looks like, and the riparian pass already keeps its own distance from
    the channel; the defect is foliage floating on a lake.
    """
    # The art's own half-width (a 256 px prop at scale 1), plus the error in the
    # distance test itself: `_near_path` measures to a path's SAMPLE POINTS, not to
    # its edges, and a shoreline sampled every ~48 px reads up to half that further
    # away than it is. Measured: trees 71-88 px from a lake's nearest vertex still
    # lightened water 30-100 px inside the shoreline; keeping them 150*scale clear of
    # it took the body from 14/22 dark samples to 21/22. The honest fix is segment
    # distance in `_near_path` itself, which changes every proximity rule in the plan
    # and is not tonight's change.
    reach = 150.0 * scale
    for w in plan.water:
        if not w.closed:
            continue
        if _in_poly(x, y, w.path) or _near_path(plan.geom, x, y, w.path, reach):
            return False
    return True


def _near_building(plan: SitePlan, x: float, y: float, dist: float) -> bool:
    """Foliage within arm's reach of a house reads as scrub swallowing the
    village, which is exactly what the old maps did."""
    return any(math.hypot(b.x - x, b.y - y) < dist for b in plan.buildings)


def lift_vegetation(plan: SitePlan,
                    rect: tuple[float, float, float, float],
                    margin: float = 18.0) -> None:
    """Clear the growth out of the ground a building is about to stand on.

    Trees claim no cells, so a footprint test cannot see them: a frontage barn was
    laid in ground a woodland had planted first, and the map got a tree crown sitting
    on a roof (`foliage_does_not_swallow_the_village`). The order of the plan makes it
    unavoidable in general - a woodland is a landmark laid before the small roadside
    buildings fill the gaps - and the answer real development uses is a clearing: the
    footprint, plus a margin for the crown that leans over the wall, is cleared.
    """
    x0, y0, x1, y1 = rect[0] - margin, rect[1] - margin, \
        rect[2] + margin, rect[3] + margin
    kept = []
    for wd in plan.woods:
        items = [(x, y, s) for (x, y, s) in wd.items
                 if not (x0 <= x <= x1 and y0 <= y <= y1)]
        if len(items) >= 2 or (items and wd.kind in ("riparian", "treeline")):
            wd.items = items
            kept.append(wd)
    plan.woods = kept


def _rect_free(plan: SitePlan, rect: tuple[float, float, float, float]) -> bool:
    """Is a footprint's ground free: inside the strip, unbuilt, dry, not on a slope,
    not in a channel.

    Checked against the PLANNING CELLS the rect covers, not against the rect's
    centre. A centre-only test is how two houses whose art is 160-220 px wide were
    allowed to stand 60 px apart: each centre sat on free ground while the two
    footprints were on top of one another.
    """
    x0, y0, x1, y1 = rect
    g = plan.geom
    if x0 < 10.0 or x1 > g.w - 10.0:
        return False
    # The footprint's own position, sampled the way the plan's own contract samples
    # it. The cell test below reads planning cells; a house can pass it (every cell
    # it covers under 0.42) and still stand where `relief_at` says 0.46 - which is
    # the number `no_building_on_ground_it_cannot_stand_on` measures, and what a
    # farmstead's barn on a farmland ridge tripped. A building is allowed on ground
    # a lane can climb to, not on a slope it has to sit into.
    if plan.relief_at((x0 + x1) / 2.0, (y0 + y1) / 2.0) > 0.40:
        return False
    # NOT `_in_strip`: that asks "does this y exist once the strip wraps", which is
    # always yes, so a footprint straddling the seam was tested against cells it does
    # not cover. A building whose rect leaves [0, h) has its own ground on one side of
    # the seam and its cell test on the other: a neighborhood house measured up at
    # y = 1233 in a 1120-tall sector, standing in a river it was never checked
    # against. Straddling the seam is not worth the bookkeeping; refuse it.
    if y0 < 0.0 or y1 > g.h:
        return False
    j0, j1 = _span(y0, y1, g.rows, g.cell)
    i0, i1 = _span(x0, x1, g.cols, g.cell)
    # `built` and slope get zero tolerance: another building's ground and a hillside
    # are not things a footprint may clip. WET gets a small share, because the cell
    # grid (64 px) is coarser than a house (170x134 px): a lot next to a river covers
    # one river cell with a corner and was refused for it, which is how three
    # countryside sectors ended up with no buildings at all. What decides whether the
    # house stands in water is the corner-and-centre test below, against the water's
    # own geometry - that stays exact.
    wet_cells = 0
    cells = (j1 - j0 + 1) * (i1 - i0 + 1)
    for j in range(j0, j1 + 1):
        row_rel, row_wet, row_built = plan.relief[j], plan.wet[j], plan.built[j]
        for i in range(i0, i1 + 1):
            if row_built[i] or row_rel[i] > 0.42:
                return False
            if row_wet[i]:
                wet_cells += 1
    if wet_cells > cells * 0.12:
        return False
    # a footprint must not straddle water either: the corners and the middle are
    # enough, because a channel wider than the spacing between those samples would
    # swallow the whole building anyway
    for px, py in ((x0, y0), (x1, y0), (x0, y1), (x1, y1),
                   # the middle is held further off the water than the corners: a
                   # building's centre is where its door and yard are, and the plan
                   # promises no building stands in a channel (measured against the
                   # water's own half-width + 38) - a 26 px corner test let a frontage
                   # house sit 30 px from a channel it was built across
                   ((x0 + x1) / 2.0, (y0 + y1) / 2.0)):
        centre = abs(px - (x0 + x1) / 2.0) < 1.0 and abs(py - (y0 + y1) / 2.0) < 1.0
        if plan.near_water(px, py, 42.0 if centre else 26.0):
            return False
    return True


def _claim_rect(plan: SitePlan, rect: tuple[float, float, float, float]) -> None:
    """Mark the ground a footprint covers as taken.

    This mark is what every later pass reads: fields refuse the cell (`_fields`),
    vegetation refuses it (`_cover`), the next building refuses it. Claiming a 26 px
    dot under a 160 px house is why a hedgerow used to run through a living room and
    a barn stood in the middle of a crop field.
    """
    g = plan.geom
    x0, y0, x1, y1 = rect
    j0, j1 = _span(max(0.0, y0), min(float(g.h), y1), g.rows, g.cell)
    i0, i1 = _span(max(0.0, x0), min(float(g.w), x1), g.cols, g.cell)
    for j in range(j0, j1 + 1):
        for i in range(i0, i1 + 1):
            plan.built[j][i] = True


def place_building(plan: SitePlan, kind: str, x: float, y: float,
                   face_to: Point, scale: float, group: str,
                   drive: list[Point] | None = None,
                   yard: tuple[float, float, float] | None = None,
                   air: float = 16.0, commit: bool = True) -> Building | None:
    """The one way a building enters the plan.

    Size comes from the art, not from a wish: the footprint is the prop's ink box at
    its painted scale, the candidate is rejected if any of that ground is taken, and
    on success the ground it covers is claimed - so nothing later plants a tree, a
    hedge or another house inside it.

    `air` is the gap kept between footprints, in bake px. It is a *painting* margin:
    shadows and the light dot at a house's near edge reach a few px past the ink.
    """
    angle = _face(x, y, face_to[0], face_to[1])
    rect = _ink_rect(kind, x, y, scale, angle, pad=air)
    if not _rect_free(plan, rect):
        return None
    # A road owns its corridor. Checked here, in the one gate every building
    # passes through, because a rule that lives in one blueprint is a rule the
    # others do not know: a frontage house set back from the lane it faces ended
    # up 23 px from the edge of a highway the lane happened to run beside.
    if plan.in_road_corridor(x, y):
        return None
    b = Building(kind=kind, x=x, y=y, angle=angle, scale=scale, group=group,
                 drive=drive, yard=yard)
    if not commit:
        # A probe, not a placement: a blueprint is allowed to ask "would a house
        # stand here" before it commits to the road that house hangs off. Without
        # this the probe built the house for real, the blueprint built it again, and
        # when the road was then refused the sector kept houses with no lane under
        # them - which is what `every_house_is_reached_by_a_road` caught.
        return b
    plan.buildings.append(b)
    lift_parcel_ground(plan, rect)
    lift_vegetation(plan, rect)
    _claim_rect(plan, rect)
    return b


def lift_parcel_ground(plan: SitePlan,
                       rect: tuple[float, float, float, float]) -> None:
    """Take the crop out of the ground a building is about to stand on.

    Field parcels claim their cells (`_mark_parcel`), which is what stops a hedgerow
    running through a living room and a barn standing in a crop. It also meant a
    neighborhood could not be built at all: the flat, drained, road-side ground a
    subdivision wants IS farmland, and one sector refused 161 estate house probes for
    standing in a field. Real development eats fields, so the plan says the same:
    the parcel a footprint covers is removed and its ground released, and the house
    goes there.

    Only the lifted parcel's own cells are cleared - a road or another building that
    claimed ground keeps its claim.
    """
    x0, y0, x1, y1 = rect
    g = plan.geom
    keep = []
    for f in plan.fields:
        fx = [q[0] for q in f.poly]
        fy = [q[1] for q in f.poly]
        # FARMLAND only. Every other parcel was laid by a place for the buildings
        # that stand on it - a camp's clearing, a rest stop's apron, a city block's
        # paving - and lifting those deleted each one the moment its first tent or
        # depot went down.
        if (f.kind not in LIFTABLE_FIELDS
                or max(fx) < x0 or min(fx) > x1 or max(fy) < y0 or min(fy) > y1):
            keep.append(f)
            continue
        jr = _span(max(y0, min(fy)), min(y1, max(fy)), g.rows, CELL)
        ic = _span(max(x0, min(fx)), min(x1, max(fx)), g.cols, CELL)
        for j in range(jr[0], jr[1] + 1):
            for i in range(ic[0], ic[1] + 1):
                px, py = i * CELL + CELL / 2.0, j * CELL + CELL / 2.0
                if plan.built[j][i] and _in_poly(px, py, f.poly):
                    plan.built[j][i] = False
    plan.fields = keep


def _mark_parcel(plan: SitePlan, poly: list[Point]) -> None:
    g = plan.geom
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    jr = _span(min(ys) - 4, max(ys) + 4, g.rows, CELL)
    ic = _span(min(xs) - 4, max(xs) + 4, g.cols, CELL)
    for j in range(jr[0], jr[1] + 1):
        for i in range(ic[0], ic[1] + 1):
            if _in_poly(i * CELL + CELL / 2, j * CELL + CELL / 2, poly):
                plan.built[j][i] = True      # parcels claim their ground
