"""Designing a sector's ground in another interpreter.

The design pass is pure Python, so it does not share the GIL's mercy with the
frame thread: it competes for it. Moving it into a process only works because a
site plan is pure data and the planner is deterministic without leaning on
`hash()` or set order - so these tests are mostly about proving that the ground
thought up over there is the ground that would have been thought up here.
"""
from __future__ import annotations

import math
import multiprocessing
import pickle

from level.design import PROCESS_MIN_LENGTH, _plan_here, plan_sector, shutdown_pool

LENGTH = 4800           # bake px: over the line where a process pays for itself


def _signature(plan) -> tuple:
    """Everything a plan *is*, reduced to comparable numbers.

    Not `==`: the dataclasses do not define equality, and comparing reprs would
    pass on a plan whose floats differ in the last bit while meaning the same
    ground. This is the feature counts and coordinates a player could notice.
    """
    def pts(path):
        return [(round(p[0], 3), round(p[1], 3)) for p in path]

    return (
        plan.theme, plan.seed, plan.geom.h,
        len(plan.ridges), [pts(r.spine) for r in plan.ridges],
        [r.width for r in plan.ridges],
        len(plan.water), [pts(w.path) for w in plan.water],
        len(plan.roads), [pts(r.path) for r in plan.roads],
        [(round(b.x, 3), round(b.y, 3), b.kind, b.angle) for b in plan.buildings],
        (len(plan.fields), len(plan.woods), len(plan.greens)),
        [round(v, 4) for row in plan.relief[:40] for v in row[:12]],
        [sum(1 for v in row if v) for row in plan.wet[:60]],
        [sum(1 for v in row if v) for row in plan.built[:60]],
    )


def test_the_plan_survives_the_trip():
    """Pure data, and pure data that means the same thing on both sides."""
    here = _plan_here("countryside", 1, LENGTH)
    blob = pickle.dumps(here)
    back = pickle.loads(blob)
    assert len(blob) < 4_000_000, "a plan should not be a megabyte-scale payload"
    assert _signature(back) == _signature(here)
    assert back.geom.h == here.geom.h
    assert back.band("buildings", 0, 500) == here.band("buildings", 0, 500)


def test_the_other_interpreter_designs_the_same_ground():
    """The sector is designed in a child process whose interpreter is a different
    one - different hash seed, different everything - and must still place the
    same ridge, the same house, the same hedge. If this ever differs, replays and
    the prefetch are lying about which ground is which."""
    here = _plan_here("countryside", 1, LENGTH)
    there = plan_sector("countryside", 1, LENGTH, process=True)
    assert _signature(there) == _signature(here)


def test_a_different_theme_is_not_just_a_renamed_one():
    a = plan_sector("glacier", 6, LENGTH, process=True)
    b = plan_sector("canyon", 6, LENGTH, process=True)
    assert a.theme == "glacier" and b.theme == "canyon"
    assert _signature(a) != _signature(b)


def test_a_small_map_is_not_worth_a_process():
    """A one-screen baked map is designed where it is asked for: the spawn costs
    more than the couple of frames the design would have taken. The worker is
    shared on purpose, so what is asserted is that *this* call did not need one.
    """
    before = set(multiprocessing.active_children())
    plan = plan_sector("countryside", 1, 1120)
    assert plan.geom.h == 1120
    assert set(multiprocessing.active_children()) == before, \
        "a one-screen map started a design process"


def test_a_worker_that_cannot_be_trusted_ends_up_designing_here(monkeypatch):
    """The fallback is not decoration. A refused fork, a dead worker, a platform
    with no child support: the ground still arrives, from this interpreter."""
    class Broken:
        def submit(self, *a, **k):
            raise OSError("no worker here")

    monkeypatch.setattr("level.design.pool", lambda: Broken())
    plan = plan_sector("countryside", 1, LENGTH, process=True)
    assert plan.geom.h == LENGTH
    assert plan.buildings


def test_the_fallback_answers_when_no_child_is_possible(monkeypatch):
    monkeypatch.setattr("level.design.pool", lambda: None)
    plan = plan_sector("countryside", 1, LENGTH, process=True)
    assert plan.geom.h == LENGTH


def test_a_level_can_be_told_which_way_to_design():
    from level import Level

    class Spec:
        wave_seconds = 12.0
        theme = "countryside"
        name = "inline"
        spawn_interval = 1.0
        spawns = (("grunt", 60), ("weaver", 26), ("darter", 14))

    before = set(multiprocessing.active_children())
    lvl = Level(Spec(), seed=1, tail=2.0, process_design=False)
    try:
        lvl.build()
        assert lvl.plan is not None
        assert set(multiprocessing.active_children()) == before, \
            "a level told to design inline still used a worker"
    finally:
        lvl.stop()


def test_shutting_down_leaves_no_child_painting_the_ground():
    plan_sector("countryside", 1, LENGTH, process=True)
    assert multiprocessing.active_children(), "no design worker was ever made"
    shutdown_pool()
    deadline = 5.0
    import time
    end = time.time() + deadline
    while multiprocessing.active_children() and time.time() < end:
        time.sleep(0.05)
    assert multiprocessing.active_children() == []
    shutdown_pool()                    # twice is fine; teardown is not fragile


def test_the_line_is_where_the_cost_says_it_is():
    """The threshold is a cost judgement, so state it as one: a map at the line
    is long enough that designing here would cost visible frames."""
    assert PROCESS_MIN_LENGTH > 2000
    assert math.ceil(PROCESS_MIN_LENGTH / 1120) >= 2
