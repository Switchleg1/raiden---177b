"""The placement engine must know how big a thing is, and how to build a place.

Two properties, both easy to state and both previously violated:

* nothing draws on top of anything else - a house, a barn or a cabin covers the
  ground its ART covers, and two of them may not cover the same ground;
* a place is a composition, not a cluster: a neighborhood's houses face its lane
  and reach it by a drive, a campground's cabins face the fire, a highway keeps
  its corridor clear.

These are the properties the "houses piled on top of each other randomly" report
was about. They are checked on multi-screen strips because that is what the game
streams, and on several seeds because a single seed is a anecdote.
"""
from __future__ import annotations

import math

import pygame

import config as C
from terrain.design.art import _ink_rect, ink_size, prop_art
from terrain.design.art_table import INK
from terrain.design.site import plan_site
from terrain.design.spec_table import SPEC
from terrain.plan.geom import Geom

STRIP = Geom(h=C.STRIP_ROWS, cyclic=False) if hasattr(C, "STRIP_ROWS") \
    else Geom(h=1120 * 6, cyclic=False)


def _strip(theme: str, seed: int) -> list[tuple[float, float, float, float]]:
    """Every building footprint in a six-screen sector, as (x0, y0, x1, y1)."""
    plan = plan_site(theme, seed, Geom(h=1120 * 6, cyclic=False))
    return [(_ink_rect(b.kind, b.x, b.y, b.scale, b.angle), b)
            for b in plan.buildings], plan


def test_no_two_buildings_draw_on_the_same_ground():
    """The headline property: footprints, not centres.

    The rule this replaces was a centre-to-centre minimum (78-95 px) against art
    150-220 px wide, so neighbouring houses were not merely close: their ROOFS
    overlapped by half a house, guaranteed by arithmetic, on every frontage row.
    """
    themes = [t for t in sorted(SPEC) if SPEC[t].build]
    for theme in themes:
        for seed in (1, 3, 7):
            pairs, plan = _strip(theme, seed)
            for i in range(len(pairs)):
                for j in range(i + 1, len(pairs)):
                    a, b = pairs[i][0], pairs[j][0]
                    ox = min(a[2], b[2]) - max(a[0], b[0])
                    oy = min(a[3], b[3]) - max(a[1], b[1])
                    assert not (ox > 0.0 and oy > 0.0), (
                        f"{theme} seed {seed}: {pairs[i][1].kind} at "
                        f"({pairs[i][1].x:.0f},{pairs[i][1].y:.0f}) and "
                        f"{pairs[j][1].kind} at ({pairs[j][1].x:.0f},"
                        f"{pairs[j][1].y:.0f}) cover the same ground by "
                        f"{ox:.0f}x{oy:.0f} px - the spacing rule is a centre "
                        "distance again, or an ink extent that no longer matches "
                        "the art")


def test_declared_ink_matches_the_art():
    """The spacing numbers must be the ART's numbers.

    Every spacing rule in the planner derives from `INK`. If a prop is redrawn
    bigger and the table is not updated, the layouts go wrong in exactly the way
    that produced the pile-up - and no test that looks only at the plan can see
    it. So measure the PNGs.
    """
    from terrain.tilekit import TileKit
    kit = TileKit()
    import numpy
    for name, (dw, dh) in INK.items():
        assert name in kit.props, f"no prop art named {name!r}"
        a = numpy.transpose(pygame.surfarray.array_alpha(kit.props[name]))
        ys, xs = numpy.nonzero(a > 8)
        assert len(xs) > 0, f"{name} is empty"
        w = float(xs.max() - xs.min() + 1)
        h = float(ys.max() - ys.min() + 1)
        assert abs(w - dw) <= 4.0 and abs(h - dh) <= 4.0, (
            f"{name}: art ink is {w:.0f}x{h:.0f} but art_table.INK says "
            f"{dw:.0f}x{dh:.0f} - the spacing rules are derived from these "
            "numbers, so one of them is now a guess")


def test_a_neighborhood_is_a_row_of_houses_on_a_lane():
    """Houses that share a road, facing it, reached by a drive.

    A neighborhood is not "several houses that happen to be near each other",
    which is what a scatter of legal objects produces. Its houses are placed
    ALONG a lane, turned to face it, and each has a drive whose far end is on
    that lane.
    """
    for theme in ("countryside", "city", "ruins"):
        plan = plan_site(theme, 3, Geom(h=1120 * 6, cyclic=False))
        homes = [b for b in plan.buildings if b.group == "neighborhood"]
        if len(homes) < 3:
            continue
        lanes = [r for r in plan.roads if r.kind == "spur"]
        assert lanes, "houses without a lane to belong to"
        for b in homes:
            assert b.drive, f"a {b.group} house has no drive"
            # the drive must reach a lane
            end = b.drive[-1]
            assert any(_near(b.drive[0], end, r.path, 24.0) for r in lanes), \
                f"{b.kind}'s drive leaves the house but reaches no lane"
            # and the house must face the lane, not a random direction
            near = min((math.hypot(end[0] - b.x, end[1] - b.y), end)
                        for r in lanes for end in [b.drive[-1]])[1]
            facing = (math.cos(math.radians(b.angle)),
                      math.sin(math.radians(b.angle)))
            to_lane = (near[0] - b.x, near[1] - b.y)
            ln = math.hypot(*to_lane) or 1.0
            dot = (facing[0] * to_lane[0] + facing[1] * to_lane[1]) / ln
            assert dot > -0.2, (
                f"a neighborhood house faces {b.angle} deg while its lane is at "
                f"{math.degrees(math.atan2(*reversed(to_lane))):.0f} - buildings "
                "tilted every which way read as a pile, not a lane")


def _near(a, b, path, tol):
    from terrain.design.geometry import _near_path
    return _near_path(Geom(h=1120 * 6, cyclic=False), b[0], b[1], path, tol)


def test_a_campground_faces_its_fire():
    """Cabins around a clearing, turned INWARD. The layout is what says people
    sleep here; nothing about a scatter of huts does."""
    seen = 0
    for theme in ("countryside", "forest"):
        for seed in (3, 7):
            plan = plan_site(theme, seed, Geom(h=1120 * 6, cyclic=False))
            fires = [g for g in plan.greens if g.mat == "earth_cracked"]
            for g in fires:
                camp = [b for b in plan.buildings
                        if b.group == "campground"
                        and math.hypot(b.x - g.x, b.y - g.y) < 200.0]
                if len(camp) < 3:
                    continue
                seen += 1
                for b in camp:
                    dx, dy = g.x - b.x, g.y - b.y
                    ln = math.hypot(dx, dy) or 1.0
                    dot = (math.cos(math.radians(b.angle)) * dx
                           + math.sin(math.radians(b.angle)) * dy) / ln
                    assert dot > 0.0, (
                        f"a cabin stands at {b.angle} deg with the fire behind it "
                        "- the ring is what makes this a campground")
    assert seen, "no campgrounds were built to check"


def test_a_highway_keeps_its_corridor_clear():
    """What a highway forbids is what makes it a highway."""
    seen = 0
    for theme in ("city", "industrial", "airbase"):
        plan = plan_site(theme, 3, Geom(h=1120 * 6, cyclic=False))
        ways = [r for r in plan.roads if r.kind == "highway"]
        for r in ways:
            seen += 1
            for b in plan.buildings:
                if b.group == "highway":
                    continue          # the rest stop belongs to the road
                from terrain.design.geometry import _dist_path
                d = _dist_path(plan.geom, b.x, b.y, r.path)
                edge = d - r.width * 0.5      # px from the carriageway's edge
                assert edge >= 30.0, (
                    f"a {b.group} building at ({b.x:.0f},{b.y:.0f}) stands "
                    f"{edge:.0f} px from the edge of a {r.width:.0f} px highway - "
                    "building up to the edge of a highway is how it stops "
                    "reading as one")
    assert seen, "no highway was built to check"


def test_ink_size_follows_scale_and_facing():
    """The footprint helper must be the art at that scale, turned.

    "Turned" means turned so its FRONT faces the facing: the house art is drawn
    with its door at the bottom, so facing 90 (down, the plan's y-down degrees) is
    the art as drawn, and facing 0 or 180 is a quarter turn. (This test used to
    assert facing 0 was the art as drawn, which encoded the bug that turned every
    long building sideways to its street.)
    """
    w, h = ink_size("house", 1.0, 90)
    assert (w, h) == INK["house_top"], "the plan kind does not resolve to its art"
    w90, h90 = ink_size("house", 1.0, 0)
    assert (w90, h90) == (h, w), "a quarter turn does not swap the footprint"
    ws, hs = ink_size("house", 0.5, 90)
    assert abs(ws - w * 0.5) < 1e-6 and abs(hs - h * 0.5) < 1e-6
    assert prop_art("barn") == "barn_red", (
        "a plan kind with no art alias is drawn as the fallback sprite, which is "
        "how every barn in the game has so far been a house")


def test_a_lake_is_water_in_the_middle():
    """A closed water body is a REGION. Stroked like a river it becomes a ring of
    water with a bank line on each side of the ring and flow glints down the middle
    of it - what the user described as "lakes appear to be roadways made in a circle
    because they still have the centre lines inside".

    The first version of this test compared the middle of the lake to ground 260 px
    away and was wrong on its own terms: with woodlands and relief shading, ground
    outside a lake is regularly DARKER than the water, which says nothing about the
    bug. Two invariants do measure the defect:

    * the water is darker than its OWN bank, which is pale gravel/snow by design -
      the adjacency the painter relies on to make water readable at all;
    * the interior is smooth. One material, one darkening pass. A ring leaves dry
      ground in the middle, and that ground carries a bank line, a shoreline and
      glints through it, which is texture no filled body has.
    """
    import math

    import numpy as np
    import pygame

    from level.strip import STRIP_MARGIN, STRIP_SLICE, TerrainStrip
    from terrain.design.geometry import _in_poly
    from terrain.design.site import plan_site
    from terrain.plan.geom import Geom

    rows = STRIP_SLICE * 4
    checked = 0
    for seed in (5, 3, 11):
        plan = plan_site("countryside", seed, Geom(h=rows, cyclic=False))
        lakes = [w for w in plan.water if w.closed and w.inside is not None]
        if not lakes:
            continue
        strip = TerrainStrip(plan, "near", slice_h=rows, margin=STRIP_MARGIN)
        band = np.asarray(pygame.surfarray.array3d(strip.paint(0))).astype(int)
        lum = band.mean(axis=2)      # [x][y] in painted px
        h = lum.shape[1]
        for w in lakes:
            ix, iy = w.inside
            # world row -> band column: the band is turned over (`_paint` flips every
            # band so its far world row lands nearest the top of the screen)
            col = (rows - 1 - int(iy)) // 2
            row = int(ix // 2)
            if not (0 <= col < h and 0 <= row < lum.shape[0]):
                continue
            # scan the whole body and a little past both shores: the middle against the
            # water, the band just outside against the bank material
            xs = [q[0] for q in w.path]
            span = int((max(xs) - min(xs)) * 0.5) + 90
            inside, bank = [], []
            for d in range(-span, span + 1, 5):
                wx = ix + d * 2
                wy = iy
                r2 = int(wx // 2)
                if not (0 <= r2 < lum.shape[0] and 0 <= col < h):
                    continue
                near = min(math.hypot(wx - qx, wy - qy)
                           for qx, qy in w.path)
                if _in_poly(wx, wy, w.path):
                    # the fill is feathered, so a sample a pixel or two inside the
                    # geometric outline can legitimately be bank material. Only the
                    # body's actual interior is water; the shoreline itself is not
                    # evidence either way.
                    if near > 16.0:
                        inside.append(lum[r2, col])
                elif near < w.half + 30.0:
                    # the bank band: outside the water, but against the shore
                    bank.append(lum[r2, col])
            if len(inside) < 8 or len(bank) < 4:
                continue
            checked += 1
            wat, shore = float(np.mean(inside)), float(np.mean(bank))
            assert wat < shore - 3.0, (
                f"the water inside a {(w.kind)} is not darker than its own shore band "
                f"({wat:.0f} vs {shore:.0f}): the middle is not water")
            # The middle has to be WATER, not ground with water round it. The art
            # decides the number: `water_river` darkened the way the painter darkens a
            # wet body reads 20.5 mean, 52 at its brightest texel, and a lake interior
            # measured over a filled body runs 17-24. Dry ground in the same sectors
            # runs 35-70. A mean separates those with room to spare; a per-sample count
            # did not, because a scan at fixed pitch walks straight into the water
            # material's own ripple texels and calls them land.
            assert float(np.mean(inside)) < 28.0, (
                f"the middle of a {w.kind} is not water: its interior samples average "
                f"{float(np.mean(inside)):.0f} where the water material on this theme "
                "averages 20 and dry ground averages 40-60")
    assert checked >= 2, (
        f"only {checked} lake(s) could be sampled across three countryside "
        "sectors - the test cannot pass on a plan with nothing to measure")


def test_a_neighborhood_lane_holds_houses_on_both_sides():
    """A neighborhood is a STREET network: houses along each street, facing it, on
    BOTH sides of it, meeting at intersections.

    Two things are measured and they are not the same thing:

    * the STRUCTURE, on every street that exists - three or more fronting houses and
      they do not all stand on the same side. A loop road is exempt: its houses face
      the green in the middle of it, which is why a loop is built.
    * the PRESENCE, across the sectors. A sector that is half lake or all ridge
      cannot hold a subdivision and should not try. Requiring one in every sector
      measures the geography, not the design; requiring them in most sectors is what
      says the blueprint actually reaches the ground it wants.
    """
    sectors = 0
    with_estates = 0
    streets = 0
    for seed in (3, 5, 7, 9, 11, 13, 17, 21):
        plan = plan_site("countryside", seed, Geom(h=1120 * 4, cyclic=False))
        sectors += 1
        homes = [b for b in plan.buildings if b.group == "neighborhood"]
        if homes:
            with_estates += 1
        for r in plan.roads:
            # an estate's own streets. A main road's frontage row is a different
            # thing and holds houses wherever the ground allows; a subdivision is
            # the thing the user is asking to be organised.
            if r.kind not in ("spur", "track") or len(r.path) < 3:
                continue
            if math.hypot(r.path[0][0] - r.path[-1][0],
                          r.path[0][1] - r.path[-1][1]) < 40.0:
                continue              # a closed loop: it faces its own centre
            on_street, sides = 0, []
            for b in plan.buildings:
                if b.group != "neighborhood":
                    continue
                # measured against the PATH, not its chord: a collector that winds
                # puts its own frontage outside a +-170 px band around the straight
                # line between its ends, which is how a street with six houses on
                # both sides read as holding none.
                end = b.drive[-1] if b.drive else (b.x, b.y)
                best = None
                for i in range(len(r.path) - 1):
                    (ax, ay), (bx, by) = r.path[i], r.path[i + 1]
                    vx, vy = bx - ax, by - ay
                    seg = math.hypot(vx, vy) or 1.0
                    t = max(0.0, min(1.0, ((b.x - ax) * vx + (b.y - ay) * vy)
                                     / (seg * seg)))
                    qx, qy = ax + vx * t, ay + vy * t
                    d = math.hypot(b.x - qx, b.y - qy)
                    if best is None or d < best[0]:
                        best = (d, vx / seg, vy / seg, qx, qy)
                if best is None or best[0] > 170.0:
                    continue
                # FRONTS this street: its drive ends ON it (on the path, between its
                # vertices - drives end at a point along the lane). The 90 px slack
                # this used to allow counted the houses of a crossing street at every
                # junction as this street's frontage.

                def on_path(path: list, px: float, py: float) -> float:
                    out = 1e9
                    for i in range(len(path) - 1):
                        (ax, ay), (bx, by) = path[i], path[i + 1]
                        vx, vy = bx - ax, by - ay
                        seg2 = (vx * vx + vy * vy) or 1.0
                        t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / seg2))
                        out = min(out, math.hypot(px - ax - vx * t, py - ay - vy * t))
                    return out
                if on_path(r.path, end[0], end[1]) > 3.0:
                    continue
                _d, vx, vy, qx, qy = best
                on_street += 1
                sides.append(1 if (vx * (b.y - qy) - vy * (b.x - qx)) >= 0.0
                             else -1)
            if on_street >= 3:
                streets += 1
                assert len(set(sides)) >= 2, (
                    f"seed {seed}: {on_street} houses front one {r.kind} street and "
                    "every one of them is on the same side of it")
    assert streets >= 6, (
        f"{streets} street(s) across {sectors} sectors hold three or more fronting "
        "houses: a neighborhood is a row of houses along a street, and rows of one "
        "or two are scattered houses")
    assert with_estates >= sectors // 2, (
        f"only {with_estates} of {sectors} countryside sectors have a neighborhood "
        "at all - the blueprint is not reaching the ground it wants")
