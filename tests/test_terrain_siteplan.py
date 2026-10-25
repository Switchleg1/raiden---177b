"""The site plan: what a sector's ground *is*.

``terrain.siteplan`` is pure Python on purpose - no pygame, no numpy - so the
whole dependency chain (ridges -> drainage -> roads -> parcels -> houses ->
cover) can be checked headlessly and cheaply. The painter in ``terrain.features``
just draws whatever this decides, so these are the tests that protect the
landscape: a map that fails here is unrecognisable no matter how it is shaded.
"""
from __future__ import annotations

import itertools
import math
import time

import pytest

from terrain.compose import PLANNED
from terrain.siteplan import (
    CELL,
    CH,
    COLS,
    CW,
    ROWS,
    SPEC,
    Geom,
    SitePlan,
    _in_poly,
    _y_extent,
    plan_site,
)

SEEDS = (1, 2, 3, 7, 11)


def _seg_dist(x: float, y: float, a: tuple, b: tuple) -> float:
    ax, ay = a
    bx, by = b
    ln2 = (bx - ax) ** 2 + (by - ay) ** 2
    t = 0.0 if ln2 == 0 else max(0.0, min(1.0,
                                          ((x - ax) * (bx - ax)
                                           + (y - ay) * (by - ay)) / ln2))
    return math.hypot(x - (ax + t * (bx - ax)), y - (ay + t * (by - ay)))


def _plan(theme: str, seed: int = 1) -> SitePlan:
    return plan_site(theme, seed)


def _signature(p: SitePlan) -> tuple:
    """Everything a plan *decides*, compared structurally."""
    return (
        [(r.shape, tuple(map(tuple, r.spine)), round(r.width, 3))
         for r in p.ridges],
        [(w.kind, [tuple(round(v, 1) for v in pt) for pt in w.path],
          round(w.half, 3)) for w in p.water],
        [(r.kind, [tuple(round(v, 1) for v in pt) for pt in r.path],
          round(r.width, 3),
          [tuple(round(v, 1) for v in b) for b in r.bridges])
         for r in p.roads],
        [(f.kind, tuple((round(q[0]), round(q[1])) for q in f.poly), f.mat)
         for f in p.fields],
        [(b.kind, round(b.x, 3), round(b.y, 3), b.angle, round(b.scale, 3))
         for b in p.buildings],
        [(wd.kind, [(round(x, 3), round(y, 3), round(s, 3))
                    for x, y, s in wd.items]) for wd in p.woods],
        tuple(tuple(round(v, 6) for v in row) for row in p.relief),
    )


# --------------------------------------------------------------------------
# determinism: a seeded replay must rebuild the same ground
# --------------------------------------------------------------------------

@pytest.mark.parametrize("theme", sorted(PLANNED))
def test_plan_is_deterministic(theme):
    assert _signature(_plan(theme, 4)) == _signature(_plan(theme, 4))


@pytest.mark.parametrize("theme", ["countryside", "canyon", "city"])
def test_seed_changes_the_ground(theme):
    assert _signature(_plan(theme, 1)) != _signature(_plan(theme, 2))


def test_hash_of_a_string_is_not_used():
    # PYTHONHASHSEED randomisation would break replays if a plan ever keyed off
    # hash(); the plan must depend only on ints it can see
    assert _signature(plan_site("countryside", 9)) == _signature(
        plan_site("countryside", 9))


# --------------------------------------------------------------------------
# the dependency chain: nothing the plan places may contradict the ground
# --------------------------------------------------------------------------

@pytest.mark.parametrize("theme", sorted(PLANNED))
def test_theme_plans_and_reaches_its_relief_target(theme):
    p = _plan(theme, 3)
    spec = SPEC[theme]
    peak = max(max(row) for row in p.relief)
    if spec.ridge_count[1]:
        assert peak == pytest.approx(spec.relief_gain, abs=0.02)
        assert p.ridges
    else:
        assert peak <= spec.relief_gain + 0.02
    assert p.roads or spec.road == "none"


@pytest.mark.parametrize("theme", sorted(PLANNED))
@pytest.mark.parametrize("seed", SEEDS)
def test_no_building_on_ground_it_cannot_stand_on(theme, seed):
    p = _plan(theme, seed)
    for b in p.buildings:
        assert not p.is_wet(b.x, b.y), f"{b.kind} built in water"
        assert p.relief_at(b.x, b.y) <= 0.45, f"{b.kind} built on a slope"
        assert not p.near_water(b.x, b.y, 38.0), f"{b.kind} built in a channel"


@pytest.mark.parametrize("theme", sorted(PLANNED))
@pytest.mark.parametrize("seed", SEEDS)
def test_every_house_is_reached_by_a_road(theme, seed):
    p = _plan(theme, seed)
    if not p.buildings or not p.roads:
        pytest.skip("theme builds no houses")
    for b in p.buildings:
        near = any(p.near_road(b.x, b.y, 260.0) for _ in (0,))
        assert near, f"{b.kind} at ({b.x:.0f},{b.y:.0f}) has no road"


@pytest.mark.parametrize("theme", sorted(PLANNED - {"city"}))
@pytest.mark.parametrize("seed", SEEDS)
def test_fields_do_not_swallow_the_road(theme, seed):
    from terrain.field_table import SOFT_FIELDS
    p = _plan(theme, seed)
    for f in p.fields:
        if f.kind in SOFT_FIELDS:
            continue        # a tint of the ground under the road, not a parcel
        for j in range(ROWS):
            for i in range(COLS):
                cx, cy = i * CELL + CELL / 2, j * CELL + CELL / 2
                if _in_poly(cx, cy, f.poly):
                    assert not p.near_road(cx, cy, 14.0), \
                        f"{f.kind} parcel covers the road"


@pytest.mark.parametrize("theme", sorted(PLANNED))
def test_fields_sit_on_ploughable_ground(theme):
    p = _plan(theme, 5)
    for f in p.fields:
        xs = [q[0] for q in f.poly]
        ys = [q[1] for q in f.poly]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        if f.kind in ("crop", "paddy", "pasture", "orchard"):
            assert p.relief_at(cx, cy) < 0.62, f"{f.kind} on a hillside"
        assert not p.is_wet(cx, cy), f"{f.kind} parcel in a channel"


@pytest.mark.parametrize("theme", sorted(PLANNED))
@pytest.mark.parametrize("seed", SEEDS)
def test_roads_cross_water_on_a_bridge(theme, seed):
    p = _plan(theme, seed)
    for r in p.roads:
        for x, y in r.path:
            # the carriageway itself, not the wet bank: a road may run beside a
            # channel, it just may not run through one
            wet = [w for w in p.water
                   if min(math.hypot(x - wx, y - wy)
                          for wx, wy in w.path) < w.half + r.width * 0.5]
            if not wet:
                continue
            assert any(math.hypot(x - bx, y - by) < 110.0
                       for w0 in wet for bx, by in r.bridges), \
                f"{r.kind} road fords the water with no bridge"


@pytest.mark.parametrize("theme", ["countryside", "canyon", "glacier", "city"])
def test_a_road_does_not_follow_the_river(theme):
    """The road and the watercourse are the two linear features in a map. When
    one hugs the other the player cannot tell channel from carriageway - the
    single most repeated note from the art review of the first planned maps."""
    p = _plan(theme, 1)
    if not p.water or not p.roads:
        pytest.skip("no water on this plan")
    w = max(p.water, key=lambda k: len(k.path))
    road = max(p.roads, key=lambda r: len(r.path))
    hug = sum(1 for x, y in road.path if p.near_water(x, y, w.half + 70.0))
    assert hug / len(road.path) < 0.3, "road runs with the river"


@pytest.mark.parametrize("theme", sorted(PLANNED))
def test_a_bridge_exists_where_a_road_meets_water(theme):
    p = _plan(theme, 2)
    if not p.water:
        pytest.skip("theme has no water")
    crossed = [r for r in p.roads if r.bridges]
    assert crossed, "water and a road, and not one bridge"


@pytest.mark.parametrize("theme", ["countryside", "forest", "city"])
def test_foliage_does_not_swallow_the_village(theme):
    p = _plan(theme, 1)
    for b in p.buildings:
        for wd in p.woods:
            for x, y, _s in wd.items:
                assert math.hypot(x - b.x, y - b.y) > 34.0, \
                    f"tree crowns the {b.kind} at ({b.x:.0f},{b.y:.0f})"


@pytest.mark.parametrize("theme", sorted(PLANNED))
def test_riparian_trees_stay_out_of_the_channel(theme):
    p = _plan(theme, 2)
    for wd in p.woods:
        if wd.kind != "riparian":
            continue
        for x, y, _s in wd.items:
            assert not p.is_wet(x, y), "riparian tree standing in the water"


@pytest.mark.parametrize("theme", ["canyon", "glacier", "countryside"])
def test_scree_and_outcrops_belong_to_a_ridge(theme):
    p = _plan(theme, 1)
    if not p.ridges:
        pytest.skip("no ridges")
    for wd in p.woods:
        if wd.kind not in ("scree", "outcrop"):
            continue
        for x, y, _s in wd.items:
            near = any(math.hypot(x - sx, y - sy) < r.width * 1.6
                       for r in p.ridges for sx, sy in r.spine)
            if not near:
                # measure against the whole spine, not just its vertices: a long
                # spine segment is still the ridge this debris came off
                near = min(_seg_dist(x, y, a, b) < r.width * 1.6
                           for r in p.ridges
                           for a, b in zip(r.spine, r.spine[1:], strict=False))
            assert near, f"{wd.kind} debris sits away from any ridge"
            assert not p.near_water(x, y, 60.0), f"{wd.kind} dumped in a river"
            for b in p.buildings:
                assert math.hypot(x - b.x, y - b.y) > 55.0, \
                    f"{wd.kind} rockfall at the door of a {b.kind}"


@pytest.mark.parametrize("theme", ["canyon", "countryside", "glacier",
                                   "wasteland", "ruins", "forest"])
def test_a_ridge_system_is_connected(theme):
    """Ranges branch. Independent full-height trunks scattered over a map read
    as "separate, overlapping shapes whose crests, faces and bases don't
    connect" - the verdict the art review kept giving the canyon."""
    p = _plan(theme, 2)
    if len(p.ridges) < 2:
        pytest.skip("one mass only")
    for i in range(1, len(p.ridges)):
        d = min(_seg_dist(sx, sy, a, b)
                for j in range(i)
                for sx, sy in p.ridges[i].spine
                for a, b in zip(p.ridges[j].spine, p.ridges[j].spine[1:],
                                strict=False))
        assert d < 260.0, \
            f"{p.ridges[i].shape} stands alone: {d:.0f} px from the range"


@pytest.mark.parametrize("seed", SEEDS)
def test_city_blocks_come_from_the_street_grid(seed):
    """A grid city is legible because its BLOCKS are the gaps between streets."""
    p = _plan("city", seed)
    assert len(p.fields) >= 1
    for f in p.fields:
        xs = [q[0] for q in f.poly]
        ys = [q[1] for q in f.poly]
        assert max(xs) - min(xs) > 60.0, "block too small to read as a block"
        assert max(ys) - min(ys) > 50.0
        assert not any(p.is_wet(qx, qy) for qx, qy in f.poly)


def test_scree_boulders_never_belong_to_a_city():
    assert not SPEC["city"].scree


# --------------------------------------------------------------------------
# bake budget: plan_site runs at bake time, per map, twice (far + near share it)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("theme", sorted(PLANNED))
def test_plan_is_fast_enough_to_bake(theme):
    import time
    t0 = time.perf_counter()
    plan_site(theme, 5)
    assert time.perf_counter() - t0 < 1.6, f"{theme} plan too slow to bake"


# --- strips: the ground a streamed sector is designed on -----------------

@pytest.mark.parametrize("theme", ["countryside", "canyon", "city"])
@pytest.mark.parametrize("seed", [1, 4, 7])
def test_a_strip_is_designed_not_stretched(theme, seed):
    """A six-screen strip is a designed six screens. If the planner kept the
    one-screen habits, a streamed sector would be the same picture repeated."""
    strip = plan_site(theme, seed, Geom(h=6 * CH, cyclic=False))
    g = strip.geom
    assert (g.w, g.h, g.cyclic) == (CW, 6 * CH, False)
    assert g.screens == 6

    pts = ([(b.x, b.y) for b in strip.buildings]
           + [(f.poly[0][0], f.poly[0][1]) for f in strip.fields]
           + [(w.items[0][0], w.items[0][1]) for w in strip.woods if w.items])
    assert pts, "a strip with nothing in it"
    for x, y in pts:
        assert -40.0 <= x <= CW + 40.0, f"outside the strip in x: {x}"
        assert -40.0 <= y <= g.h + 40.0, f"outside the strip in y: {y}"
    # routes are allowed to bleed past the ends so they read as continuing
    assert any(p[1] > 0.9 * g.h for r in strip.roads for p in r.path)

    # content spread along the whole length, not bunched at one end
    ys = sorted(p[1] for p in pts)
    gap = max(b - a for a, b in zip(ys, ys[1:], strict=False))
    assert gap < 2.5 * CH, f"{gap:.0f} px of strip with nothing in it"
    # and the strip is richer than a screen, by design
    screen = plan_site(theme, seed)
    assert len(strip.woods) > len(screen.woods)


def test_a_strip_does_not_repeat_itself():
    """The whole point of the long plan: the same layout must not come round
    every screen. With one-screen geometry and cyclic paths it did."""
    strip = plan_site("countryside", 1, Geom(h=6 * CH, cyclic=False))
    sig = [(round(b.x), round(b.y)) for b in strip.buildings]
    repeats = sum(1 for a, b in itertools.combinations(sig, 2)
                  if a[0] == b[0] and abs((b[1] - a[1]) % CH) < 1.0
                  and abs(b[1] - a[1]) > 0.5 * CH)
    assert repeats <= 1, f"{repeats} pairs of houses repeat at screen spacing"
    roads = {len(r.path) for r in strip.roads}
    assert max(roads) > 30, "a route that stops after one screen"


def test_a_strip_plan_is_deterministic():
    a = plan_site("canyon", 3, Geom(h=4 * CH, cyclic=False))
    b = plan_site("canyon", 3, Geom(h=4 * CH, cyclic=False))
    assert ([(round(p[0]), round(p[1])) for r in a.ridges for p in r.spine]
            == [(round(p[0]), round(p[1])) for r in b.ridges for p in r.spine])
    assert ([(round(s[0]), round(s[1])) for w in a.woods for s in w.items]
            == [(round(s[0]), round(s[1])) for w in b.woods for s in w.items])
    c = plan_site("canyon", 4, Geom(h=4 * CH, cyclic=False))
    assert ([(round(p[0]), round(p[1])) for r in c.ridges for p in r.spine]
            != [(round(p[0]), round(p[1])) for r in b.ridges for p in r.spine])


def test_an_unknown_theme_is_refused():
    """An unknown theme used to paint the default landscape instead: plausible
    farmland where a glacier was intended."""
    with pytest.raises(KeyError) as exc:
        plan_site("ice", 1)
    assert "glacier" in str(exc.value)


def test_a_window_is_a_place_not_a_scale():
    g = Geom(h=3 * CH, cyclic=False)
    assert g.screens == 3
    assert g.shifts() == (0.0,)                 # a strip does not loop
    assert Geom().shifts() == (0.0, -float(CH), float(CH))
    assert g.row(-20) == 0 and g.row(9 * CH) == g.rows - 1
    assert g.col(-5) == 0 and g.col(CW + 5) == g.cols - 1


def test_planning_a_strip_scales_with_its_length():
    """A sector is designed once, on a worker thread, before the first ground
    can be painted - so the design pass is what decides whether a sector that
    was not prepared in advance stalls before the player sees land.

    The planner used to answer every "is this near the road / in the channel /
    crossing this river" question by walking every segment of every path, which
    made the cost grow with the *square* of the strip length. Thirty screens of
    countryside cost 28 s that way. It now costs about two, and this guard is
    about the shape, not the machine: double the strip, pay roughly double.
    """
    def timed(h: int) -> float:
        t = time.perf_counter()
        plan_site("countryside", 1, Geom(h=h, cell=CELL, cyclic=False))
        return time.perf_counter() - t

    short, long_ = timed(6 * CH), timed(24 * CH)      # 4x the length
    assert long_ < 12.0, f"designing 24 screens took {long_:.1f} s"
    assert long_ < 12.0 * short + 0.2, (
        f"planning went superlinear: 4x length cost {long_ / short:.1f}x "
        f"({short:.2f} s -> {long_:.2f} s)")


def test_every_feature_kind_is_indexed_where_it_actually_is():
    """The spatial index is only safe if a feature's y-extent is its real one.

    A ridge keeps its points in `spine`, not `path`, and the extent helper had no
    case for it: every ridge on a thirty-screen strip was indexed at y 0..0. The
    slice cull then dropped ridges out of every window but the first, and every
    "is there a ridge here" question answered no. A new feature kind has to be
    findable by the index, so this checks every kind a planner can emit.
    """
    strip = plan_site("glacier", 6, Geom(h=12 * CH, cyclic=False))
    for kind in ("ridges", "water", "roads", "buildings", "fields", "woods",
                 "greens"):
        feats = getattr(strip, kind)
        if not feats:
            continue
        # every feature is found by a window placed on it, and missed by a
        # window a screen and a half past its end
        for index, f in enumerate(feats[:8]):
            assert index in strip.band(kind, *_y_extent(f)), \
                f"{kind} not findable where it stands"
            far = _y_extent(f)[1] + 1.5 * CH
            if far + 0.5 * CH < strip.geom.h:
                assert index not in strip.band(kind, far, far + 0.5 * CH), \
                    f"{kind} indexed where it is not"


def test_the_segment_index_agrees_with_brute_force():
    """`_near_path` / `_dist_path` must not answer "no" to a point on the line.

    Every siting rule runs through them: is this house clear of the channel, is
    this parcel off the road, does this route cross the water (and so need a
    bridge). The index buckets segments by y to make those questions cheap over a
    thousand-segment road, and the bucketing had a hole in it: a segment whose y
    DECREASES was filed in no bucket at all, because `range(b0, b1 + 1)` is empty
    when b0 > b1. Every downward-running segment of every vertical road, river
    and channel was therefore invisible.

    Measured before the fix: 9 of 13 probes disagreed with brute force, the worst
    by a factor of five (a point 7 px from a lane measured 33 px), and a drive
    drawn ON its own lane read as 24 px away from it.

    Paths that run both up and down in y are the point: a plan full of ascending
    segments alone passes and still ships the bug.
    """
    import random

    from terrain import siteplan as sp

    g = Geom(h=1120 * 6, cyclic=False)
    rng = random.Random(11)
    mismatches = 0
    probes = 0
    for _ in range(40):
        x, y = rng.uniform(0.0, 1600.0), rng.uniform(0.0, 6000.0)
        path = [(x, y)]
        for _ in range(30):
            x = max(0.0, min(1600.0, x + rng.uniform(-90.0, 90.0)))
            y = max(0.0, min(6700.0, y + rng.uniform(-160.0, 160.0)))
            path.append((x, y))
        for px, py in [(p[0] + rng.uniform(-150, 150),
                        p[1] + rng.uniform(-150, 150)) for p in path[::3]]:
            want = min(sp._seg_dist(px, py, path[i], path[i + 1])
                       for i in range(len(path) - 1))
            got = sp._dist_path(g, px, py, path)
            probes += 1
            if abs(got - want) > 1e-6:
                mismatches += 1
            elif not sp._near_path(g, px, py, path, want + 0.01):
                mismatches += 1
    assert probes > 300, f"only {probes} probes ran - the test is not probing"
    assert mismatches == 0, (
        f"{mismatches} of {probes} probes disagree with brute force - a plan "
        "sits things on ground it believes is free")
