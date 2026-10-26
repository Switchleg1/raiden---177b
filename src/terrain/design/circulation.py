"""Roads: the through-route, spurs, a city's grid, bridges."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..plan.road import Road
from .geometry import _along, _crossings, _hpath, _near_path, _vpath
from .orogeny import _path_max, _path_relief

if TYPE_CHECKING:
    from ..plan.geom import Geom, Point
    from ..plan.site_spec import SiteSpec
    from ..plan.water import Water

import math
import random


def _decks(run: list[Point]) -> list[Point]:
    """Decks along a wet run: a short one is a crossing (one deck), a long one
    is a causeway - a road running along a flooded edge needs decks close enough
    that no stretch of it stands over water unsupported.

    The decks are placed at even *arc length* and interpolated between vertices,
    not snapped to the nearest vertex: vertex spacing is around 30 px, and
    snapping lets a gap grow past the span the painter has to cover, which is
    how a causeway ends up with one wet stretch left unsupported.
    """
    if not run:
        return []
    cum = [0.0]
    for i in range(1, len(run)):
        cum.append(cum[-1] + math.hypot(run[i][0] - run[i - 1][0],
                                        run[i][1] - run[i - 1][1]))
    arc = cum[-1]
    n = max(1, int(arc / 90.0) + 1)
    out: list[Point] = []
    seg = 0
    for k in range(n):
        want = arc * (k + 0.5) / n
        while seg + 1 < len(run) and cum[seg + 1] < want:
            seg += 1
        span = cum[seg + 1] - cum[seg] if seg + 1 < len(run) else 0.0
        t = 0.0 if span <= 0.0 else (want - cum[seg]) / span
        out.append((run[seg][0] + t * (run[seg + 1][0] - run[seg][0]),
                    run[seg][1] + t * (run[seg + 1][1] - run[seg][1]))
                   if seg + 1 < len(run) else run[seg])
    return out


def _bridge_spans(g: Geom, path: list[Point],
                water: list[Water]) -> list[Point]:
    """Where a route needs a deck.

    ``_crossings`` only finds a route that passes clean through a channel. A spur
    that runs *to* the water, or a road that grazes a wide channel without ever
    reaching the far bank, gets nothing from it - and then the carriageway is
    painted through the channel with no bridge, which is the "road fords the
    river" artefact. So: any contiguous run of the route standing inside the
    channel band earns one deck at its middle.
    """
    from .geometry import _in_poly
    out: list[Point] = []
    for w in water:
        run: list[Point] = []
        for pt in path:
            # A lake is a region: on it means INSIDE its outline. Its `half` is the
            # minor radius, and "within half of the outline" took a road running
            # along the shore - outside the water - for one crossing it, which gave
            # bridges on dry land (13 across nine sectors, one of them the bridge a
            # hamlet then put its green on).
            on = (_in_poly(pt[0], pt[1], w.path) if w.closed
                  else _near_path(g, pt[0], pt[1], w.path, w.half + 14.0))
            if on:
                run.append(pt)
            elif run:
                out.extend(_decks(run))
                run = []
        out.extend(_decks(run))
    return out


def _dry_ends(g: Geom, road: Road, water: list[Water],
              roads: list[Road] = ()) -> None:
    """A road ends on land: trim an end that stops in the water back to the bank.

    A spur aimed at a farm across a river, or a lane to a lake, could stop with its
    last point in the channel; the crossing pass then gave it a deck, and the map
    had a bridge running out into the river and ending there.

    IN the water, measured at the centreline: a cul-de-sac that ends AT a lake
    shore is a road end like any other (a slipway, a turning circle), and
    trimming it orphaned the drives of the houses along it.
    """
    def wet(x: float, y: float) -> bool:
        from .geometry import _in_poly
        return any((w.closed and _in_poly(x, y, w.path))
                   or _near_path(g, x, y, w.path, w.half)
                   for w in water)

    def joined(pt: Point) -> bool:
        # an end on another road is a junction, not a dead end: a spur leaves the
        # main road where it bridges the river, and cutting that end back to the
        # bank left the whole estate on it unconnected
        return any(o is not road and _near_path(g, pt[0], pt[1], o.path,
                                                (o.width + road.width) * 0.5 + 4.0)
                   for o in roads)

    def loose(pt: Point) -> bool:
        # an end past the strip's edge is not an end: the road runs on into the
        # next sector, and a river crossing there is a crossing
        return ((g.cyclic or 0.0 < pt[1] < g.h) and wet(*pt)
                and not joined(pt))

    # a NEW list, never the old one shortened: `_near_path` indexes a route by
    # the list it was given, and an index over a list that has since lost its
    # tail reads past the end of it
    def to_shore(path: list[Point]) -> list[Point]:
        # back along the route from its last point to the first dry ground, cut
        # THERE - not at a vertex: a two-point track has no vertex to drop, and
        # one that started in a lake kept its whole length in it
        if not loose(path[-1]):
            return path
        for i in range(len(path) - 1, 0, -1):
            (ax, ay), (bx, by) = path[i - 1], path[i]
            n = max(1, int(math.hypot(bx - ax, by - ay) / 4.0))
            for k in range(1, n + 1):
                t = k / n
                px, py = bx + (ax - bx) * t, by + (ay - by) * t
                if not wet(px, py):
                    return path[:i] + [(px, py)]
        return path                   # all of it is water: not this pass's to fix

    path = to_shore(to_shore(list(road.path))[::-1])[::-1]
    if path != road.path:
        road.path = path
        road.bridges[:] = [(x, y) for x, y in road.bridges
                           if _near_path(g, x, y, road.path, road.width + 8.0)]


def _true_decks(g: Geom, road: Road, water: list[Water]) -> None:
    """Keep the decks that stand where the road is OVER water.

    A deck is where the road's centreline crosses a channel. The planner's own
    band (half + 14 px) also caught a road that only grazed a bank - its kerb in
    the shore band, its line on land - and a bridge recorded there is one the
    painter has no water to draw it over: a deck on a field, and a hamlet's green
    sited by it. The test is the painter's (`paint.roads._deck_run`).
    """
    from .geometry import _in_poly

    def over(x: float, y: float) -> bool:
        return any((w.closed and _in_poly(x, y, w.path))
                   or (not w.closed and _near_path(g, x, y, w.path, w.half))
                   for w in water)

    def on_water(bx: float, by: float) -> bool:
        # the road's own points around the deck, stepped finely: a deck point is
        # interpolated between route vertices ~30 px apart
        path = road.path
        for i in range(len(path) - 1):
            (ax, ay), (cx, cy) = path[i], path[i + 1]
            n = max(1, int(math.hypot(cx - ax, cy - ay) / 4.0))
            for k in range(n + 1):
                x, y = ax + (cx - ax) * k / n, ay + (cy - ay) * k / n
                if math.hypot(x - bx, y - by) <= road.width + 40.0 and over(x, y):
                    return True
        return False

    road.bridges[:] = [(x, y) for x, y in road.bridges if on_water(x, y)]


def _add_decks(road: Road, spans: list[Point]) -> None:
    """Append bridge decks, ignoring only ones landing on top of a deck that is
    already there.

    A causeway is a *run* of decks, and they are deliberately close - close
    enough that no stretch of road stands over water unsupported. Suppressing a
    deck because another deck sits a channel-width away is how a causeway ends
    up with a hole in it, so the only thing dropped here is a true duplicate.
    """
    for x, y in spans:
        if any(math.hypot(x - bx, y - by) < 24.0
               for bx, by in road.bridges):
            continue
        road.bridges.append((x, y))


def _circulation(g: Geom, spec: SiteSpec, relief: list[list[float]],
                 water: list[Water], rng: random.Random) -> list[Road]:
    """Route the road: it follows the low ground, crosses water on a bridge,
    and reaches a col rather than fighting a ridge."""
    if spec.road == "none":
        return []
    if spec.road == "grid":
        return _city_grid(g, water, rng)
    best: Road | None = None
    best_score = float("inf")
    for _ in range(22):
        # on a strip the main road IS the through-route, so it runs along it: a
        # horizontal main road on a long strip is a lane across one screen, and the
        # rest of the sector has no road at all
        vertical = (not g.cyclic) or rng.random() < 0.72
        if vertical:
            path = _vpath(g, rng.uniform(0.12, 0.88) * g.w,
                          [(1, rng.uniform(0.02, 0.1), rng.uniform(0, 6.28)),
                           (2, rng.uniform(0.0, 0.04), rng.uniform(0, 6.28))],
                          step=32)
        else:
            path = _hpath(g, rng.uniform(0.2, 0.8) * g.h,
                          [(1, rng.uniform(0.02, 0.05), rng.uniform(0, 6.28))],
                          step=32)
        score = (3.0 * _path_relief(g, relief, path)
                 + 2.0 * _path_max(g, relief, path))
        # A route that crosses water is worth a lot - a bridge is the most legible
        # human-made object in a scrolling map - and crossing several different
        # channels is fine. Crossing the SAME river again and again is a road that
        # was never planned: rewarding every crossing made the main road weave over
        # a sector's one long river five times in four screens.
        per_body = [len(_crossings(path, w.path)) for w in water]
        bodies = sum(1 for c in per_body if c)
        repeats = sum(max(0, c - 1) for c in per_body)
        score -= 5.0 * min(1, bodies) + 1.2 * max(0, bodies - 1)
        score += 3.0 * repeats
        for w in water:
            # ...but a road that runs *with* the river is the "channel or track?"
            # ambiguity the reviewers kept reporting, and it is what the old
            # cost function produced: low ground is the valley floor, and the
            # valley floor is where the river already lives. Measure the share
            # of the route that hugs the water and make that expensive.
            hug = sum(1 for (x, y) in path
                      if _near_path(g, x, y, w.path, w.half + 80.0)) \
                / max(1, len(path))
            score += 13.0 * hug
        if score < best_score:
            best_score = score
            # widths are bake-space: the bake space is stretched 2:1 to the
            # playfield, so a 30 px lane here is a 15 px lane on screen. Anything
            # thinner than that stops reading as a road while scrolling.
            best = Road(kind="main", path=path,
                        width=rng.uniform(15.0, 21.0))
    if best is None:
        return []
    # rivers by where the route crosses their line; a lake (closed) by the run
    # of the route inside it, in `_bridge_spans` - its outline is its SHORE, and
    # crossing that is where a bridge would start, not where it stands
    decks: list[Point] = [pt for w in water if not w.closed
                          for pt in _crossings(best.path, w.path)]
    decks.extend(_bridge_spans(g, best.path, water))
    _add_decks(best, decks)
    roads = [best]
    # a spur: it leaves the main road and goes somewhere - the bridge end, a
    # col through the ridge, or out to a farm. A road that goes nowhere is the
    # tell of generated art.
    for _ in range(rng.randint(1, 2)):
        s = (rng.uniform(0.15, 0.85) if not best.bridges
             else _bridge_end(g, best, water))
        (bx, by), tang = _along(best.path, s)
        ang = tang + (1.0 if rng.random() < 0.5 else -1.0) * rng.uniform(0.5, 1.1)
        ln = rng.uniform(160.0, 340.0)
        pts = [(bx, by)]
        for i in range(1, 7):
            t = i / 6.0
            px = bx + math.cos(ang) * ln * t
            py = by + math.sin(ang) * ln * t
            # a spur that runs off along a bank is the "is that a road or the
            # river?" ambiguity again: it may reach the water, it may not follow
            # it, so the run stops at the near bank
            if any(_near_path(g, px, py, w.path, w.half + 26.0)
                       for w in water) \
                    and len(pts) > 2:
                break
            pts.append((px, py))
        spur = Road(kind="spur", path=pts, width=rng.uniform(10.0, 13.0))
        decks = [pt for w in water if not w.closed
                 for pt in _crossings(spur.path, w.path)]
        _add_decks(spur, decks + _bridge_spans(g, spur.path, water))
        roads.append(spur)
    return roads


def _bridge_end(g: Geom, road: Road, water: list[Water]) -> float:
    """Fraction along the road where its first bridge LANDS: the nearer bank,
    the first point on it clear of the water.

    The spur used to leave from the bridge itself, which is the middle of the
    river: two decks forked over the channel and the spur's first stretch ran
    along the water inside the river's own banks. (No random draw here: the
    nearer bank is the answer, and a draw would re-roll every plan after it.)
    """
    s0 = _near_hit(road)
    step = 1.0 / max(200, len(road.path) * 4)
    best: float | None = None
    for direction in (1.0, -1.0):
        s = s0
        while 0.0 <= s + direction * step <= 1.0:
            s += direction * step
            (px, py), _ = _along(road.path, s)
            if not any(_near_path(g, px, py, w.path,
                                  w.half + road.width + 30.0) for w in water):
                if best is None or abs(s - s0) < abs(best - s0):
                    best = s
                break
    return s0 if best is None else best


def _near_hit(road: Road) -> float:
    """Fraction along the road closest to its bridge."""
    if not road.bridges:
        return 0.5
    hit = road.bridges[0]
    best, best_s = float("inf"), 0.5
    for i in range(0, 100):
        s = i / 99.0
        (px, py), _ = _along(road.path, s)
        d = math.hypot(px - hit[0], py - hit[1])
        if d < best:
            best, best_s = d, s
    return best_s


def _city_grid(g: Geom, water: list[Water], rng: random.Random) -> list[Road]:
    """City: a street grid, because that is what a city is. Two main streets and
    their cross streets, with a bridge if the grid meets water."""
    roads: list[Road] = []
    # the two main streets have to be far enough apart to enclose a block: two

    # mains 40 px apart make a sliver, and a city is nothing but its blocks
    xs: list[float] = []
    ys: list[float] = []
    for _ in range(40):
        xs = sorted(rng.uniform(0.12, 0.88) * g.w for _ in range(2))
        if xs[1] - xs[0] > 320.0:
            break
    if g.cyclic:
        for _ in range(40):
            ys = sorted(rng.uniform(0.2, 0.8) * g.h for _ in range(2))
            if ys[1] - ys[0] > 280.0:
                break
    else:
        # a city down a long strip is a grid, not two streets: the streets
        # repeat at block spacing over the whole length, so the player keeps
        # flying through the same plan rather than a single giant block
        # from one end of the sector to the other: starting the streets 12% in and
        # stopping 10% short left the city's first and last stretches as blocks
        # a screen tall, which hold nothing
        ys = list(range(200, int(g.h) - 100, 460))
    for x in xs:
        r = Road("main", _vpath(g, x, [(1, 0.0, 0.0)], step=40), 18.0)
        roads.append(r)
    for y in ys:
        roads.append(Road("main", _hpath(g, float(y), [(1, 0.0, 0.0)],
                                         step=40), 18.0))
    # cross streets fill the block between the mains
    # block spacing is the city's real scale: at 150 px a block is 40 px on the
    # playfield, too small to read as anything, and a city is nothing but blocks.
    # A cross street also has to leave room for the block it borders - one 8 px
    # from a main makes a sliver instead of a yard
    x0, x1 = xs
    for x in range(int(x0) + 240, int(x1) - 180, 240):
        roads.append(Road("track", _vpath(g, float(x), [(1, 0.0, 0.0)],
                                         step=40), 12.0))
    y0, y1 = ys[0], ys[-1]
    step_y = 220 if g.cyclic else 240
    for y in range(int(y0) + step_y, int(y1) - 170, step_y):
        # a cross street 20 px from a main street is a doubled line, not a block:
        # keep cross streets a block's depth clear of every main
        if any(abs(y - m) < 110 for m in ys):
            continue
        roads.append(Road("track", _hpath(g, float(y), [(1, 0.0, 0.0)],
                                         step=40), 12.0))
    # a street that runs WITH the river for most of its length is the same
    # ambiguity the serpentine routes had; nudge it off the channel instead
    if water:
        for r in roads:
            for _ in range(6):
                wet = sum(1 for x, y in r.path
                          if any(_near_path(g, x, y, w.path, w.half + 26.0)
                                 for w in water))
                if wet <= max(2, len(r.path) // 8):
                    break
                off = 60.0 * (1.0 if _ % 2 == 0 else -1.0) * (1 + _ // 2)
                if abs(r.path[0][0] - r.path[-1][0]) > g.w * 0.5:
                    r.path = [(x, y + off) for x, y in r.path]
                else:
                    r.path = [(x + off, y) for x, y in r.path]
    for r in roads:
        decks = [pt for w in water if not w.closed
                 for pt in _crossings(r.path, w.path)]
        _add_decks(r, decks + _bridge_spans(g, r.path, water))
    return roads
