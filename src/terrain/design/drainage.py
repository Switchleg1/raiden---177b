"""Water: where it runs, and the ground it makes wet."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..plan.geom import CELL
from ..plan.water import Water
from .geometry import (
    _cell_box,
    _crossings,
    _dist_path,
    _hpath,
    _in_poly,
    _near_path,
    _paths_close,
    _vpath,
)
from .orogeny import _path_max, _path_relief

if TYPE_CHECKING:
    from ..plan.geom import Geom
    from ..plan.site_plan import SitePlan
    from ..plan.site_spec import SiteSpec

import random

from .water_table import WATER_HALF, WATER_RATE


def _drainage(g: Geom, spec: SiteSpec, relief: list[list[float]],
              rng: random.Random) -> list[Water]:
    """Water goes where the ground falls away. Candidates are scored on how
    much ridge they would have to cut through, so the river is in the valley it
    belongs to rather than across a mountain."""
    if not spec.water_kinds:
        return []
    if g.cyclic:
        out = _drainage_screen(g, spec, relief, rng)
    else:
        out = _drainage_strip(g, spec, relief, rng)
    _carve(g, relief, out)
    return out


def _water_half(kind: str, rng: random.Random) -> float:
    """A channel's half-width, bake px. It has to read at playfield scale, where
    these numbers are halved: a 12 px half-width is a scratch, not a watercourse."""
    lo, hi = WATER_HALF.get(kind, WATER_HALF["river"])
    return rng.uniform(lo, hi)


def _drainage_screen(g: Geom, spec: SiteSpec, relief: list[list[float]],
                     rng: random.Random) -> list[Water]:
    """One screen that wraps: a body per kind, the best of sixteen candidates."""
    out: list[Water] = []
    for kind in spec.water_kinds:
        best: Water | None = None
        best_score = float("inf")
        for _ in range(16):
            vertical = rng.random() < (0.4 if kind == "wash" else 0.7)
            amp_a = (0.02, 0.06) if kind == "wash" else (0.04, 0.14)
            amp_b = (0.0, 0.02) if kind == "wash" else (0.01, 0.05)
            if vertical:
                path = _vpath(
                    g, rng.uniform(0.1, 0.9) * g.w,
                    [(1, rng.uniform(*amp_a), rng.uniform(0, 6.28)),
                     (2, rng.uniform(*amp_b), rng.uniform(0, 6.28))],
                    step=32)
            else:
                path = _hpath(g, rng.uniform(0.15, 0.85) * g.h,
                              [(1, rng.uniform(0.02, 0.05),
                                rng.uniform(0, 6.28))], step=32)
            score = (_path_relief(g, relief, path)
                     + 0.6 * _path_max(g, relief, path))
            for prev in out:
                if _paths_close(g, path, prev.path, 130.0):
                    score += 2.0
            if score < best_score:
                best_score = score
                best = Water(kind=kind, path=path, half=_water_half(kind, rng),
                             flood=rng.uniform(60.0, 130.0))
        if best is not None:
            out.append(best)
    return out


def _drainage_strip(g: Geom, spec: SiteSpec, relief: list[list[float]],
                    rng: random.Random) -> list[Water]:
    """A sector's water as one SYSTEM: a main river down the length of the strip
    and tributaries that run in from one edge and end where they meet it.

    The old rule asked for `round(screens * 0.7)` bodies PER KIND, every one of them
    either a full-length river or a full-width crossing: a four-screen strip got three
    near-identical parallel rivers a screen apart, and a real 33-screen sector asked
    for twenty-three. Water does not do that. It collects: small streams join bigger
    ones, and a valley has one river in it.
    """
    out: list[Water] = []
    kinds = list(spec.water_kinds)
    main_kind = kinds[-1]                 # the theme lists its biggest water last
    rate = WATER_RATE.get(spec.water_kinds, WATER_RATE[()])
    mains = max(1, int(round(g.screens / rate[0])))
    for _ in range(mains):
        best: Water | None = None
        best_score = float("inf")
        for _ in range(16):
            m = spec.meander
            path = _vpath(g, rng.uniform(0.15, 0.85) * g.w,
                          [(1, rng.uniform(0.05, 0.11) * m, rng.uniform(0, 6.28)),
                           (2, rng.uniform(0.015, 0.04) * m, rng.uniform(0, 6.28)),
                           (3, rng.uniform(0.0, 0.015) * m, rng.uniform(0, 6.28))],
                          step=32)
            score = (_path_relief(g, relief, path)
                     + 0.6 * _path_max(g, relief, path))
            for prev in out:
                if _paths_close(g, path, prev.path, 260.0):
                    score += 4.0
            if score < best_score:
                best_score = score
                best = Water(kind=main_kind, path=path,
                             half=_water_half(main_kind, rng),
                             flood=rng.uniform(80.0, 140.0))
        if best is not None:
            out.append(best)
    # tributaries: from one edge of the strip to the main river, and no further
    streams = int(round(g.screens / rate[1]))
    ys = sorted(rng.uniform(0.04, 0.96) * g.h for _ in range(streams))
    for y0 in ys:
        kind = kinds[0]
        path = _hpath(g, y0, [(1, rng.uniform(0.02, 0.05), rng.uniform(0, 6.28)),
                              (2, rng.uniform(0.01, 0.025), rng.uniform(0, 6.28)),
                              (3, rng.uniform(0.0, 0.012), rng.uniform(0, 6.28))],
                      step=32)
        if out:
            main = out[0]
            hits = _crossings(path, main.path)
            if hits:
                hx = hits[0][0]
                # run in from whichever edge is further from the confluence, so
                # the stream has a length worth drawing
                if hx > g.w * 0.5:
                    path = [pt for pt in path if pt[0] <= hx + 8.0]
                else:
                    path = [pt for pt in path if pt[0] >= hx - 8.0]
        if len(path) < 6:
            continue
        # a stream should not drop into the same reach as the last one
        if any(_paths_close(g, path, w.path, 220.0) for w in out[1:]):
            continue
        half = _water_half(kind, rng) * (0.62 if kind == main_kind else 1.0)
        out.append(Water(kind=kind, path=path, half=half,
                         flood=rng.uniform(50.0, 90.0)))
    return out


def _carve(g: Geom, relief: list[list[float]], out: list[Water]) -> None:
    # carve the valley: a river lowers the ground it runs in, and everything
    # beside it reads as its floodplain
    for w in out:
        # a river cuts; a dry wash only sweeps sand off the surface. Carving a
        # wash as deep as a river leaves a hollow that shades into "a brown
        # stain", which is what the canyon review kept calling an unexplained pit
        depth = 0.35 if w.kind in ("wash", "arroyo") else 0.85
        # bound the cell scan to the corridor the channel can actually reach:
        # on a twenty-screen strip an unbounded scan is 20x the work for cells
        # that are nowhere near the water
        lo_j, hi_j, lo_i, hi_i = _cell_box(g, w.path, w.flood)
        for j in range(lo_j, hi_j + 1):
            cy = j * CELL + CELL / 2
            for i in range(lo_i, hi_i + 1):
                cx = i * CELL + CELL / 2
                d = _dist_path(g, cx, cy, w.path)
                if d < w.flood:
                    t = 1.0 - d / w.flood
                    relief[j][i] = max(0.0, relief[j][i] - depth * t * t)


def _water_mark(plan: SitePlan) -> None:
    for w in plan.water:
        _water_mark_body(plan, w)


def _water_mark_body(plan: SitePlan, w) -> None:
    """Mark the cells this water body makes wet.

    Called as the body is laid, not only during orogeny: a lake a blueprint digs
    arrives after the orogeny pass, and until its cells are marked the rest of the
    planner believes the middle of that lake is dry ground.
    """
    g = plan.geom
    lo_j, hi_j, lo_i, hi_i = _cell_box(g, w.path,
                                       w.half + (26.0 if w.closed else 14.0))
    for j in range(lo_j, hi_j + 1):
        for i in range(lo_i, hi_i + 1):
            cx, cy = i * CELL + CELL / 2, j * CELL + CELL / 2
            # A closed body is wet INSIDE it. Marking wet by distance to the outline
            # alone left a dry core in the middle of every lake: the shoreline is
            # `ry` away from the centre while the stroke reaches 0.95*ry, so the very
            # middle of the water read as buildable ground - and a later pass put
            # something there. That dry core, ringed by the inner bank line and the
            # flow glints of a channel stroke, is what made a lake look like "a
            # roadway made in a circle, with the centre lines still inside it".
            #
            # And the shore band is a BAND. The channel radius (`half + 14`, where
            # `half` is a channel's own half-width) made no sense for a body whose
            # `half` is its minor radius: a lake 446 px across marked everything
            # within ~460 px of its shoreline wet, and measured 37-50% of two
            # countryside sectors became unbuildable shore - no house, lane, field or
            # camp anywhere near water, and 0 buildings in those sectors. A lake's
            # ground is water, its shore is marsh for a short way, and beyond that it
            # is the ground everybody else uses.
            if w.closed:
                if _in_poly(cx, cy, w.path) or _near_path(g, cx, cy, w.path,
                                                          26.0):
                    plan.wet[j][i] = True
            elif _near_path(g, cx, cy, w.path, w.half + 14.0):
                plan.wet[j][i] = True
