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
from terrain.siteplan import INK, SPEC, Geom, _ink_rect, ink_size, plan_site, prop_art

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
            f"{name}: art ink is {w:.0f}x{h:.0f} but siteplan.INK says "
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
    from terrain.siteplan import _near_path
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
                from terrain.siteplan import _dist_path
                d = _dist_path(plan.geom, b.x, b.y, r.path)
                edge = d - r.width * 0.5      # px from the carriageway's edge
                assert edge >= 30.0, (
                    f"a {b.group} building at ({b.x:.0f},{b.y:.0f}) stands "
                    f"{edge:.0f} px from the edge of a {r.width:.0f} px highway - "
                    "building up to the edge of a highway is how it stops "
                    "reading as one")
    assert seen, "no highway was built to check"


def test_ink_size_follows_scale_and_facing():
    """The footprint helper must be the art at that scale, turned."""
    w, h = ink_size("house", 1.0, 0)
    assert (w, h) == INK["house_top"], "the plan kind does not resolve to its art"
    w90, h90 = ink_size("house", 1.0, 90)
    assert (w90, h90) == (h, w), "a quarter turn does not swap the footprint"
    ws, hs = ink_size("house", 0.5, 0)
    assert abs(ws - w * 0.5) < 1e-6 and abs(hs - h * 0.5) < 1e-6
    assert prop_art("barn") == "barn_red", (
        "a plan kind with no art alias is drawn as the fallback sprite, which is "
        "how every barn in the game has so far been a house")
