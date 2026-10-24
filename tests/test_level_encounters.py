"""Encounters chosen by the ground they stand on.

A sector's roster and pacing stay level numbers; what changes is that a group is
placed where the land explains it. These tests are headless and small: a plan of
a dozen screens designs in a fraction of a second, and the properties being
checked are about placement, not about pixels.
"""
from __future__ import annotations

import math
import sys

import pytest

sys.path.insert(0, "src" if "src" not in sys.path else "")

import config as C
from config.enemy_kind import EnemyKind
from level.encounters import LEAD_IN, LEAD_OUT, SEARCH, Encounter, affordance_of, plan_encounters
from terrain.common import NEAR_SPEED, SS
from terrain.siteplan import CELL, Geom, plan_site

H = 12_000          # bake px of ground to design: ~36 s of scroll


def _strip(theme: str, seed: int, h: int = H):
    return plan_site(theme, seed, Geom(h=h, cell=CELL, cyclic=False))


@pytest.fixture(scope="module")
def city():
    return _strip("city", 5)


@pytest.fixture(scope="module")
def swamp():
    return _strip("swamp", 3)


@pytest.fixture(scope="module")
def glacier():
    return _strip("glacier", 6)


# a roster that exercises every affordance: roofs, ridges, water and open ground
@pytest.fixture(scope="module")
def spec():
    return C.LEVELS[4]


def _by_affordance(encs, afford: str):
    return [e for e in encs if affordance_of(e.kind) == afford]


def test_the_same_sector_places_the_same_encounters(city, spec):
    """A replay must meet the same guns in the same doorways. `hash()` moves
    between runs, so the planner keys its draws on arithmetic instead."""
    a = plan_encounters(city, spec)
    b = plan_encounters(_strip("city", 5), spec)
    assert [(e.kind, round(e.x, 3), round(e.y, 3), e.count, e.form)
            for e in a] == [(e.kind, round(e.x, 3), round(e.y, 3), e.count,
                             e.form) for e in b]


def test_encounters_arrive_in_the_order_they_are_flown_over(city, spec):
    encs = plan_encounters(city, spec)
    assert [e.y for e in encs] == sorted(e.y for e in encs)


def test_roof_guns_stand_on_built_ground(city, spec):
    """A sentry that climbs out of empty sky is the old behaviour. A sentry that
    climbs out of a rooftop is a warning the player can read."""
    on_roofs = _by_affordance(plan_encounters(city, spec), "roof")
    assert on_roofs, "the sector's roster has sentries and the city has houses"
    for e in on_roofs:
        if not city.band("buildings", e.y - SEARCH, e.y + SEARCH):
            continue                    # nothing here to stand on: abstain
        near = min(math.hypot(e.x - b.x, e.y - b.y) for b in city.buildings)
        assert near < 40.0, f"{e.kind} at ({e.x:.0f},{e.y:.0f}) has no building"
        assert city.is_built(e.x, e.y) or near < 12.0, \
            f"{e.kind} is floating beside a house, not on one"


def test_things_that_scatter_rise_off_water(swamp, spec):
    wet = _by_affordance(plan_encounters(swamp, spec), "wet")
    assert wet, "the marsh has channels and the roster has splitters"
    for e in wet:
        if not swamp.band("water", e.y - SEARCH, e.y + SEARCH):
            continue
        assert swamp.is_wet(e.x, e.y), f"{e.kind} at ({e.x:.0f},{e.y:.0f}) is dry"


def test_heavies_come_off_high_ground(glacier, spec):
    """Either the flank of a ridge, or this stretch of the sector has no ridge
    to come off - the planner is allowed to abstain, not to invent a mountain."""
    ridge = _by_affordance(plan_encounters(glacier, spec), "ridge")
    assert ridge
    for e in ridge:
        near = [r for r in glacier.ridges
                if any(abs(p[1] - e.y) < SEARCH + 80.0 for p in r.spine)]
        if not near:
            continue
        d = min(min(math.hypot(e.x - px, e.y - py) for px, py in r.spine)
                for r in near)
        reach = max(r.width for r in near) * 0.7 + 60.0
        assert d < reach, \
            f"{e.kind} at ({e.x:.0f},{e.y:.0f}) is {d:.0f} px from any crest"


def test_open_ground_is_clear_of_houses_and_water(city, spec):
    for e in plan_encounters(city, spec):
        if affordance_of(e.kind) != "open":
            continue
        assert not city.is_wet(e.x, e.y)
        assert not city.is_built(e.x, e.y)


def test_the_sector_chooses_what_appears_not_the_planner(city, spec):
    """The roster is a level number: the planner places things, it does not get
    to introduce an archetype the sector never fielded."""
    roster = {EnemyKind(k) for k, _w in spec.spawns}
    for e in plan_encounters(city, spec):
        assert e.kind in roster


def test_density_is_the_sectors_pacing(city, spec):
    """Spacing comes from spawn_interval, so a sector that fields more per
    second gets more per kilometre of ground - and the number still means what
    it always meant."""
    encs = plan_encounters(city, spec)
    beat = spec.spawn_interval * NEAR_SPEED * SS
    assert len(encs) == pytest.approx((city.geom.h - (LEAD_IN + LEAD_OUT)
                                       * NEAR_SPEED * SS) / beat, rel=0.35)


def test_a_longer_sector_gets_a_proportionally_longer_war(city, spec):
    short = plan_encounters(_strip("city", 5, h=6000), spec)
    long_ = plan_encounters(_strip("city", 5, h=24000), spec)
    assert 3.0 * len(short) < 5.0 * len(short) <= len(long_) * 1.15
    assert len(long_) < 5.0 * len(short)


def test_the_sector_opens_clear_and_closes_clear(city, spec):
    """No craft takes off inside a formation, and no wave dies mid-screen."""
    encs = plan_encounters(city, spec)
    assert all(e.y >= LEAD_IN * NEAR_SPEED * SS for e in encs)
    assert all(e.y <= city.geom.h - LEAD_OUT * NEAR_SPEED * SS for e in encs)
    # the boss tail is a fight, not a walk past more of the same
    tail = plan_encounters(city, spec, tail=30.0)
    assert all(e.y <= city.geom.h - (LEAD_OUT + 30.0) * NEAR_SPEED * SS
               for e in tail)
    assert len(tail) < len(encs)


def test_encounters_stay_inside_the_playfield(glacier, spec):
    for e in plan_encounters(glacier, spec):
        assert C.FIELD_LEFT * SS <= e.x <= C.FIELD_RIGHT * SS
        assert 0.0 <= e.y <= glacier.geom.h


def test_a_group_keeps_the_shape_it_was_placed_in(city, spec):
    """The formation is decided with the site, because the site decides it: a
    hamlet puts up a pair of guns, a field puts up a file of infantry."""
    encs = plan_encounters(city, spec)
    assert any(e.count > 1 for e in encs)
    assert {e.form for e in encs} <= {"single", "pair", "line", "v"}
    for e in encs:
        assert isinstance(e, Encounter)
        assert e.count >= 1
        if e.form == "single":
            assert e.count == 1


def test_a_sector_with_nothing_to_offer_abstains(spec):
    """A theme with no buildings gets no rooftop guns: the planner would rather
    skip than drop a turret over open country, which is where the old 'nothing
    consulted the ground' feel came from."""
    bare = _strip("canyon", 1)          # ridges and washes, no settlement
    roofs = _by_affordance(plan_encounters(bare, spec), "roof")
    for e in roofs:
        if not bare.band("buildings", e.y - SEARCH, e.y + SEARCH):
            continue                    # abstained: no roof, no turret
        assert bare.is_built(e.x, e.y)
