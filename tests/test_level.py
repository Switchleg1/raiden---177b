"""The streamed sector: `Level` and its painted strip.

A sector used to be one screen of ground, repeated. These tests are the contract
for replacing that with one designed strip painted off the frame thread: the
ground must be whole, a slice must not care when it is painted, the painting must
outrun the scroll, and building a level in the middle of a fight must not cost
the frame anything.
"""
from __future__ import annotations

import threading
import time

import pygame

from level.level import Level, strip_length
from level.strip import STRIP_MARGIN, STRIP_SLICE, TerrainStrip
from terrain.common import NEAR_SPEED, SS, TILE2


class Spec:
    """A sector small enough to test, shaped like the real table."""

    def __init__(self, wave=20.0, theme="countryside") -> None:
        self.wave_seconds = wave
        self.theme = theme


SPECS = {"Sector 1: Countryside Approach": Spec(20.0)}


def _strip(wave: float = 20.0, theme: str = "countryside") -> TerrainStrip:
    from terrain.siteplan import CELL, Geom, plan_site
    length = strip_length(Spec(wave, theme))
    plan = plan_site(theme, 1, Geom(h=length, cell=CELL, cyclic=False))
    return TerrainStrip(plan, "near")


# --------------------------------------------------------------- geometry ---

def test_a_sector_is_longer_than_a_screen():
    """The point of the strip: the ground outlasts the sector."""
    length = strip_length(Spec(51.0))
    seconds = length / SS / NEAR_SPEED
    assert seconds > 51.0 + 30.0, f"only {seconds:.0f} s of ground for a wave"
    assert length > TILE2 * 10, "a strip barely longer than the field"


def test_slices_cover_the_strip_without_gaps():
    st = _strip()
    assert st.count * st.slice_h >= st.height
    for i in range(st.count):
        lo, h = st.window(i)
        assert lo == max(0, i * st.slice_h - STRIP_MARGIN)
        assert lo + h <= st.height
        # the window reaches past the kept band on both sides, or a feature
        # anchored in the next slice is missing from this one. The clamp at the
        # ends of the strip is the exception: a strip has ends, it does not wrap
        want_lo = min(i * st.slice_h, STRIP_MARGIN)
        assert i * st.slice_h - lo >= want_lo
        hi = (i + 1) * st.slice_h
        if hi < st.height:
            assert lo + h - hi >= 1
        else:
            assert lo + h == st.height


# ------------------------------------------------------------- determinism --

def test_a_slice_does_not_care_when_it_is_painted():
    """Painting is a pure function of (plan, index).

    If this breaks, streaming breaks invisibly: a slice painted early (while the
    level is loading) and one painted late (while bullets are flying) would be
    different ground, and the difference would show as a line across the field.
    """
    a = _strip()
    b = _strip()
    order = [3, 0, 2, 1] if a.count > 3 else [0, 1]
    for i in order:
        a.paint(i)
    for i in reversed(order):
        b.paint(i)
    for i in set(order):
        sa = pygame.surfarray.array3d(a.surface(i))
        sb = pygame.surfarray.array3d(b.surface(i))
        assert (sa == sb).all(), f"slice {i} depends on painting order"


def test_the_same_seed_designs_the_same_ground():
    a, b = _strip(), _strip()
    for i in (0, min(2, a.count - 1)):
        assert (pygame.surfarray.array3d(a.paint(i))
                == pygame.surfarray.array3d(b.paint(i))).all()


def test_a_slice_is_ground_not_a_hole():
    """A slice with a hole in it is a black band across the field - the exact
    shape of a masking bug, and invisible in a thumbnail."""
    st = _strip()
    for i in (0, st.count - 1):
        surf = st.paint(i)
        arr = pygame.surfarray.array_alpha(surf)
        assert (arr > 250).mean() > 0.995, f"slice {i} has holes in it"


# ---------------------------------------------------------------- frontier --

def test_the_frontier_is_contiguous():
    """The renderer draws up to the frontier and no further.

    A slice that finished out of order must not open a hole in the ground, so
    the frontier is the first *missing* slice, not a count of finished ones.
    """
    st = _strip()
    last = st.count - 1
    if last > 0:
        st.paint(last)
        assert st.frontier() == 0
    for i in range(min(3, st.count)):
        st.paint(i)
    assert st.frontier() == min(3, st.count)
    assert st.missing_at(0) == (3 if st.count > 3 else -1)


def test_painting_outruns_the_scroll():
    """The level starts while its ground is still being drawn, so the painters
    have to beat the camera - not race it."""
    st = _strip(wave=75.0)                   # the longest sector in the table
    t = time.perf_counter()
    st.paint(min(3, st.count - 1))
    per_slice = (time.perf_counter() - t) / 1.0
    crossing = st.slice_h / (NEAR_SPEED * SS)
    assert per_slice < crossing * 0.8, (
        f"a slice takes {per_slice:.2f} s to paint but the camera crosses it in "
        f"{crossing:.2f} s: the ground would run out")


# ------------------------------------------------------------------ levels --

def test_making_a_level_costs_the_frame_thread_nothing():
    """A Level is created mid-fight (for the sector after this one)."""
    t = time.perf_counter()
    lvl = Level(Spec(60.0), seed=2)
    made = time.perf_counter() - t
    assert made < 0.05, f"constructing a level cost {made:.2f} s"
    assert not lvl.built() and lvl.progress() == 0.0
    assert lvl.draw(pygame.Surface((800, 560), pygame.SRCALPHA),
                    pygame.Rect(0, 0, 800, 560)) == 0


def test_a_level_paints_itself_while_you_wait():
    lvl = Level(Spec(12.0), seed=1)
    lvl.start()
    try:
        deadline = time.time() + 60.0
        while lvl.progress() < 0.25 and time.time() < deadline:
            time.sleep(0.05)
        assert lvl.built(), "the sector was never designed"
        assert lvl.progress() >= 0.25, "the painters never got ahead"
        target = pygame.Surface((800, 560), pygame.SRCALPHA)
        lvl.update(1.0)
        assert lvl.draw(target, pygame.Rect(0, 0, 800, 560)) > 0
    finally:
        lvl.stop()


def test_stopping_a_level_leaves_no_thread_painting():
    lvl = Level(Spec(12.0), seed=1)
    lvl.start()
    time.sleep(0.3)
    lvl.stop(timeout=5.0)
    assert threading.active_count() < 6, "strip workers outlived the level"


def test_two_levels_are_independent():
    """The sector being flown and the one being prepared."""
    now = Level(Spec(10.0), seed=1)
    nxt = Level(Spec(10.0), seed=2)
    now.build()
    nxt.build()
    assert now.plan is not nxt.plan
    a = pygame.surfarray.array3d(TerrainStrip(now.plan).paint(0))
    b = pygame.surfarray.array3d(TerrainStrip(nxt.plan).paint(0))
    assert (a != b).any(), "two seeds designed the same ground"
    same = Level(Spec(10.0), seed=1)
    same.build()
    c = pygame.surfarray.array3d(TerrainStrip(same.plan).paint(0))
    assert (a == c).all()


def test_a_window_never_walks_the_whole_plan():
    """The perf cliff this architecture has to clear: 30 screens of props.

    Culling by the plan's own spatial index is what took a slice from half a
    minute to under a second. If someone rewrites a painter to walk every
    feature again, the ground stops keeping up and the level shows its end.
    """
    from terrain.siteplan import CELL, Geom, plan_site
    length = strip_length(Spec(90.0))
    plan = plan_site("countryside", 1, Geom(h=length, cell=CELL, cyclic=False))
    mid = length // 2
    seen = plan.band("woods", mid, mid + STRIP_SLICE)
    assert 0 < len(seen) < len(plan.woods) * 0.5, "no culling happened"
    # indices, in plan order: the painter's jitter is keyed to them
    assert seen == sorted(seen)
    # a wrapping plan is not culled: its features cross the seam
    one = plan_site("countryside", 1)
    assert one.band("woods", 0, 10) == list(range(len(one.woods)))
