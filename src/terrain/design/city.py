"""A city's blocks, built.

A city is read by its blocks, and a block is read by what stands on it: towers
over a plaza, apartment slabs facing the street, a row of shops with their car
park behind, houses with gardens toward the edge of town. The old pass enclosed
each block as one bare parcel - "lot", "yard" or "park" - and put nothing on it,
which is how a whole city sector came out with four buildings in it.

Run from `design.fields._fields` once the street grid, the places and the frontage
are down, so a block builds on whatever ground the river, the highway and the
places left it.
"""
from __future__ import annotations

import random

from ..plan.geom import Point
from ..plan.site_plan import SitePlan
from ..plan.wood import Wood
from .art import _face, ink_size
from .city_table import (
    APARTMENT,
    BLOCK_MIX,
    CARS,
    HOUSES,
    MAT_PARK,
    MAT_PARKING,
    MAT_PLAZA,
    MAT_SIDEWALK,
    MAT_YARD,
    OCCUPANCY,
    SHOPS,
    SIDE_FACING,
    SIDEWALK,
    TOWER,
)
from .footprint import place_building

Rect = tuple[float, float, float, float]


def _streets(plan: SitePlan) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """The grid's lines: (x, half-width) of the streets that run along the strip
    and (y, half-width) of the ones that cross it."""
    g = plan.geom
    xs: dict[int, float] = {}
    ys: dict[int, float] = {}
    for r in plan.roads:
        if len(r.path) < 4:
            continue
        dx = abs(r.path[0][0] - r.path[-1][0])
        dy = abs(r.path[0][1] - r.path[-1][1])
        span_x = max(p[0] for p in r.path) - min(p[0] for p in r.path)
        if r.kind == "highway" and dy > g.h * 0.5:
            # a highway divides the blocks it runs between, like any street - with
            # its shoulders and the wander of its line counted as carriageway, or
            # the block beside it spans it and is refused for standing on it
            x = round(sum(p[0] for p in r.path) / len(r.path))
            xs[x] = r.width * 0.5 + r.shoulder + span_x * 0.5 + 6.0
        elif dy > g.h * 0.5 and dx < 40.0:
            x = round(sum(p[0] for p in r.path) / len(r.path))
            xs[x] = max(xs.get(x, 0.0), r.width * 0.5)
        elif dx > g.w * 0.5 and dy < 40.0:
            y = round(sum(p[1] for p in r.path) / len(r.path))
            ys[y] = max(ys.get(y, 0.0), r.width * 0.5)
    return sorted(xs.items()), sorted(ys.items())


def _blocks(plan: SitePlan) -> list[tuple[Rect, frozenset[str]]]:
    """Every block's buildable rectangle - between two streets each way, set back
    from both by the carriageway and the pavement - and which of its sides
    ("n", "s", "w", "e") front a real street. The edge of the map is a block
    boundary but not a street, and a shop front facing it faces nothing."""
    g = plan.geom
    xs, ys = _streets(plan)
    edge = -1.0                                  # half-width marking "no street"
    xs = [(-SIDEWALK, edge)] + xs + [(g.w + SIDEWALK, edge)]
    ys = [(0.0, edge)] + ys + [(float(g.h), edge)]
    out: list[tuple[Rect, frozenset[str]]] = []
    for (xa, ha), (xb, hb) in zip(xs, xs[1:], strict=False):
        for (ya, va), (yb, vb) in zip(ys, ys[1:], strict=False):
            r = (xa + max(ha, 0.0) + SIDEWALK, ya + max(va, 0.0) + SIDEWALK,
                 xb - max(hb, 0.0) - SIDEWALK, yb - max(vb, 0.0) - SIDEWALK)
            if r[2] - r[0] < 90.0 or r[3] - r[1] < 90.0:
                continue
            sides = frozenset(name for name, half in
                              (("w", ha), ("e", hb), ("n", va), ("s", vb))
                              if half >= 0.0)
            out.append((r, sides))
    return out


def _usable(plan: SitePlan, r: Rect) -> bool:
    """A block standing in a river or across a highway is not a block.

    Tested on the block's INTERIOR and against carriageways only: the general
    corridor test pads every road by 30 px, and a block's edge is 12 px past the
    kerb of the streets that define it, so asking that test refused every block in
    the city - including for touching its own streets.
    """
    x0, y0, x1, y1 = _inset(r, 10.0)
    step = 30.0
    y = y0
    while y <= y1:
        x = x0
        while x <= x1:
            if plan.is_wet(x, y) or plan.in_road_corridor(x, y, margin=4.0):
                return False
            x += step
        y += step
    return True


def _rect_poly(r: Rect) -> list[Point]:
    x0, y0, x1, y1 = r
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _inset(r: Rect, d: float) -> Rect:
    return (r[0] + d, r[1] + d, r[2] - d, r[3] - d)


def _parcel(plan: SitePlan, r: Rect, mat: str, kind: str) -> None:
    from .places.ground import add_parcel
    add_parcel(plan, _rect_poly(r), mat, kind)


def _zone(plan: SitePlan, y: float, core: tuple[float, float]) -> str:
    return "core" if core[0] <= y <= core[1] else "edge"


def _pick(rng: random.Random, mix: tuple[tuple[str, int], ...]) -> str:
    names = [n for n, _w in mix]
    weights = [w for _n, w in mix]
    return rng.choices(names, weights=weights)[0]


def _fit(kind: str, room: float, lo: float, hi: float, along: bool = True) -> float:
    """The biggest scale in [lo, hi] whose ink fits `room` px (width if `along`)."""
    w, h = ink_size(kind, 1.0)
    return max(lo * 0.7, min(hi, room / (w if along else h)))


def _face_street(r: Rect, sides: frozenset[str], x: float, y: float) -> Point:
    """The nearest STREET edge to a point in a block: what a building there faces."""
    x0, y0, x1, y1 = r
    d = {"n": ((x, y0 - 40.0), y - y0), "s": ((x, y1 + 40.0), y1 - y),
         "w": ((x0 - 40.0, y), x - x0), "e": ((x1 + 40.0, y), x1 - x)}
    cand = [d[k] for k in d if k in sides] or list(d.values())
    return min(cand, key=lambda t: t[1])[0]


def _towers(plan: SitePlan, r: Rect, rng: random.Random,
            sides: frozenset[str]) -> int:
    x0, y0, x1, y1 = r
    kind, (lo, hi) = TOWER
    sc = _fit(kind, min(x1 - x0, y1 - y0) * 0.8, lo, hi)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    n = 0
    if (y1 - y0) > (x1 - x0) * 1.6:
        spots = [(cx, y0 + (y1 - y0) * 0.27), (cx, y0 + (y1 - y0) * 0.73)]
        sc = _fit(kind, min(x1 - x0, (y1 - y0) * 0.5) * 0.8, lo, hi)
    else:
        spots = [(cx, cy)]
    for x, y in spots:
        if place_building(plan, kind, x, y, _face_street(r, sides, x, y), sc,
                          "downtown", air=6.0):
            n += 1
    _parcel(plan, r, MAT_PLAZA, "lot")
    return n


def _row(plan: SitePlan, r: Rect, kind: str, scale: tuple[float, float],
         rng: random.Random, group: str, sides: tuple[str, ...] = ("n", "s"),
         air: float = 10.0) -> int:
    """Buildings shoulder to shoulder along a block's street edges, each facing
    the street it stands on."""
    x0, y0, x1, y1 = r
    n = 0
    kinds = kind if isinstance(kind, tuple) else (kind,)
    for side in sides:
        horizontal = side in ("n", "s")
        lo_a, hi_a = (x0, x1) if horizontal else (y0, y1)
        a = lo_a
        while True:
            k = kinds[rng.randrange(len(kinds))]
            sc = rng.uniform(*scale)
            face = SIDE_FACING[side]
            # ink as it will stand: facing the street on this side, by the same
            # rule `place_building` will apply (guessing the angle here stood every
            # slab sideways and walked the row by the wrong width)
            ang = _face(0.0, 0.0, face[0], face[1])
            w, h = ink_size(k, sc, ang)
            along, depth = (w, h) if horizontal else (h, w)
            if a + along > hi_a + 0.5:
                break
            mid = a + along / 2
            if horizontal:
                x, y = mid, (y0 + depth / 2) if side == "n" else (y1 - depth / 2)
            else:
                x, y = (x0 + depth / 2) if side == "w" else (x1 - depth / 2), mid
            if place_building(plan, k, x, y, (x + face[0] * 200.0,
                                              y + face[1] * 200.0),
                              sc, group, air=air):
                n += 1
            a += along + air
    return n


def _cars(plan: SitePlan, lot: Rect, rng: random.Random) -> int:
    """Parked cars in stalls across a lot, nose to the aisle."""
    kinds, sc = CARS
    cw, ch = ink_size(kinds[0], sc)            # a car is long in y as drawn
    x0, y0, x1, y1 = lot
    n = 0
    row_h = ch + 4.0
    aisle = ch * 0.9
    y = y0 + 2.0
    facing_up = True
    while y + row_h <= y1:
        x = x0 + 4.0
        while x + cw <= x1:
            cx, cy = x + cw / 2, y + ch / 2
            # a stall is only a stall if it can be driven to
            if rng.random() < OCCUPANCY and plan.near_road(cx, cy, 240.0):
                tgt = (cx, cy - 100.0) if facing_up else (cx, cy + 100.0)
                if place_building(plan, kinds[rng.randrange(len(kinds))], cx, cy,
                                  tgt, sc, "parking", air=2.0):
                    n += 1
            x += cw + 7.0
        y += row_h + (aisle if not facing_up else 0.0)
        facing_up = not facing_up
    return n


def _stalls(r: Rect) -> list[tuple[Point, Point]]:
    """The painted stall lines of a lot, as segments (drawn as its furrows)."""
    kinds, sc = CARS
    cw, ch = ink_size(kinds[0], sc)
    x0, y0, x1, y1 = r
    out = []
    y = y0 + 2.0
    up = True
    while y + ch + 4.0 <= y1:
        x = x0 + 4.0 - 3.5
        while x <= x1:
            out.append(((x, y), (x, y + ch + 2.0)))
            x += cw + 7.0
        y += ch + 4.0 + (ch * 0.9 if not up else 0.0)
        up = not up
    return out


def _parking(plan: SitePlan, r: Rect, rng: random.Random,
             sides: frozenset[str] = frozenset()) -> int:
    _ = sides
    n = _cars(plan, _inset(r, 8.0), rng)
    from .places.ground import add_parcel
    f = add_parcel(plan, _rect_poly(r), MAT_PARKING, "parking")
    if f is not None:
        f.furrows = _stalls(_inset(r, 8.0))
    return n


def _shops(plan: SitePlan, r: Rect, rng: random.Random,
           sides: frozenset[str]) -> int:
    """A row of shops on the block's street front, their car park behind."""
    kind, scale = SHOPS
    x0, y0, x1, y1 = r
    front = "n" if "n" in sides else "s" if "s" in sides else None
    if front is None:
        return _parking(plan, r, rng)
    n = _row(plan, r, kind, scale, rng, "downtown", sides=(front,), air=4.0)
    _w, h = ink_size(kind, scale[1])
    depth = h + 14.0
    if front == "n":
        lot, strip = (x0, y0 + depth, x1, y1), (x0, y0, x1, y0 + depth)
    else:
        lot, strip = (x0, y0, x1, y1 - depth), (x0, y1 - depth, x1, y1)
    if lot[3] - lot[1] > 60.0:
        n += _parking(plan, lot, rng)
    _parcel(plan, strip, MAT_SIDEWALK, "lot")
    return n


def _apartments(plan: SitePlan, r: Rect, rng: random.Random,
                sides: frozenset[str]) -> int:
    kind, scale = APARTMENT
    n = _row(plan, r, kind, scale, rng, "downtown",
             sides=tuple(k for k in ("n", "s") if k in sides), air=14.0)
    _parcel(plan, r, MAT_YARD, "yard")
    return n


def _park(plan: SitePlan, r: Rect, rng: random.Random,
          sides: frozenset[str] = frozenset()) -> int:
    _ = sides
    _parcel(plan, r, MAT_PARK, "park")
    x0, y0, x1, y1 = r
    # trees well inside the block: a crown at the kerb hangs over the street
    items = []
    for _ in range(rng.randint(5, 10)):
        x, y = rng.uniform(x0 + 45, x1 - 45), rng.uniform(y0 + 45, y1 - 45)
        items.append((x, y, rng.uniform(0.32, 0.48)))
    plan.woods.append(Wood(kind="copse", items=items))
    return 1


def _residential(plan: SitePlan, r: Rect, rng: random.Random,
                 sides: frozenset[str]) -> int:
    kinds, scale = HOUSES
    palette = tuple(rng.sample(kinds, 2))
    n = _row(plan, r, palette, scale, rng, "residential",
             sides=tuple(k for k in ("n", "s") if k in sides), air=18.0)
    _parcel(plan, r, MAT_YARD, "yard")
    # a couple of garden trees in the middle of the block, where the back
    # gardens meet - not between the houses, which is where the street is read
    x0, y0, x1, y1 = r
    cy = (y0 + y1) / 2
    items = [(rng.uniform(x0 + 20, x1 - 20), cy + rng.uniform(-12, 12),
              rng.uniform(0.3, 0.42)) for _ in range(rng.randint(1, 3))]
    items = [it for it in items if not plan.is_built(it[0], it[1])]
    if items:
        plan.woods.append(Wood(kind="copse", items=items))
    return n


BUILD = {"towers": _towers, "apartments": _apartments, "shops": _shops,
         "parking": _parking, "park": _park, "residential": _residential}


def build_city(plan: SitePlan, rng: random.Random) -> dict[str, int]:
    """Fill the grid's blocks. Returns how many blocks of each type were built."""
    g = plan.geom
    mid = rng.uniform(0.35, 0.65) * g.h
    half = g.h * rng.uniform(0.18, 0.28)
    core = (mid - half, mid + half)
    made: dict[str, int] = {}
    for r, sides in _blocks(plan):
        # a block no street touches is ground, not a block: nothing on it could be
        # reached (the plan's rule is that every building is)
        if not sides or not _usable(plan, r):
            continue
        cy = (r[1] + r[3]) / 2
        zone = _zone(plan, cy, core)
        kind = _pick(rng, BLOCK_MIX[zone])
        # a block too small for a tower holds something smaller
        if kind == "towers" and min(r[2] - r[0], r[3] - r[1]) < 150.0:
            kind = "apartments"
        at = len(plan.fields)
        BUILD[kind](plan, r, rng, sides)
        # the pavement: a paved base under the whole block, laid BEFORE the block's
        # own surfaces in paint order (fields paint in list order) and after its
        # buildings in plan order (a building lifts any parcel it stands on)
        from .places.ground import add_parcel
        base = add_parcel(plan, _rect_poly(_inset(r, -4.0)), MAT_SIDEWALK, "lot")
        if base is not None:
            plan.fields.remove(base)
            plan.fields.insert(at, base)
        made[kind] = made.get(kind, 0) + 1
    return made


__all__ = ["build_city"]
