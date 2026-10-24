"""The streamed sector: `Level` and its painted strip.

A sector used to be one screen of ground, repeated. These tests are the contract
for replacing that with one designed strip painted off the frame thread: the
ground must be whole, a slice must not care when it is painted, the painting must
outrun the scroll, and building a level in the middle of a fight must not cost
the frame anything.

Designing a whole sector costs seconds, so the plans here are module-scoped and
the behaviour tests ask for short sectors (`tail` is the boss tail: it is what
makes a test sector long enough to be a sector at all). The one test that needs
a realistically long strip - culling and the painting-rate guard - shares a
single medium plan.
"""
from __future__ import annotations

import itertools
import threading
import time

import pygame
import pytest

import config as C
from level.level import Level, strip_length
from level.strip import STRIP_MARGIN, STRIP_SLICE, TerrainStrip
from terrain.common import NEAR_SPEED, SS, TILE2
from terrain.siteplan import CELL, Geom, plan_site

TAIL = 6.0                    # seconds of boss tail for a behaviour test
WAVE = 6.0                    # and a wave short enough to plan in a breath


class Spec:
    """A sector shaped like the real table, sized for a test."""

    def __init__(self, wave: float = WAVE, theme: str = "countryside") -> None:
        self.wave_seconds = wave
        self.theme = theme
        self.name = f"test-{theme}"
        self.spawn_interval = 1.0
        self.spawns = (("grunt", 60), ("weaver", 26), ("darter", 14))


@pytest.fixture(scope="module")
def plan() -> object:
    """One designed short sector, shared by the strip tests."""
    length = strip_length(Spec(), tail=TAIL)
    return plan_site("countryside", 1, Geom(h=length, cell=CELL, cyclic=False))


@pytest.fixture(scope="module")
def long_plan() -> object:
    """A sector long enough that culling matters, designed once."""
    length = strip_length(Spec(30.0), tail=12.0)
    return plan_site("countryside", 1, Geom(h=length, cell=CELL, cyclic=False))


def _strip(seed: int = 1, pl: object = None) -> TerrainStrip:
    if pl is None:
        pl = plan_site("countryside", seed,
                       Geom(h=strip_length(Spec(), tail=TAIL), cell=CELL,
                            cyclic=False))
    return TerrainStrip(pl, "near")


# --------------------------------------------------------------- geometry ---

def test_a_sector_is_longer_than_a_screen():
    """The point of the strip: the ground outlasts the sector."""
    length = strip_length(Spec(51.0))
    seconds = length / SS / NEAR_SPEED
    assert seconds > 51.0 + 30.0, f"only {seconds:.0f} s of ground for a wave"
    assert length > TILE2 * 10, "a strip barely longer than the field"


def test_slices_cover_the_strip_without_gaps(plan):
    st = TerrainStrip(plan)
    assert st.count * st.slice_h >= st.height
    for i in range(st.count):
        lo, h = st.window(i)
        assert lo == max(0, i * st.slice_h - STRIP_MARGIN)
        assert lo + h <= st.height
        # the window reaches past the kept band on both sides, or a feature
        # anchored in the next slice is missing from this one. The clamp at the
        # ends is the exception: a strip has ends, it does not wrap.
        assert i * st.slice_h - lo >= min(i * st.slice_h, STRIP_MARGIN)
        hi = (i + 1) * st.slice_h
        if hi < st.height:
            assert lo + h - hi >= 1
        else:
            assert lo + h == st.height


# ------------------------------------------------------------- determinism --

def test_a_slice_does_not_care_when_it_is_painted(plan):
    """Painting is a pure function of (plan, index).

    If this breaks, streaming breaks invisibly: a slice painted early (while the
    level is loading) and one painted late (while bullets are flying) would be
    different ground, and the difference would show as a line across the field.
    """
    a, b = TerrainStrip(plan), TerrainStrip(plan)
    order = [3, 0, 2, 1] if a.count > 3 else [0, 1]
    for i in order:
        a.paint(i)
    for i in reversed(order):
        b.paint(i)
    for i in set(order):
        assert (pygame.surfarray.array3d(a.surface(i))
                == pygame.surfarray.array3d(b.surface(i))).all(), (
                    f"slice {i} depends on painting order")


def test_the_same_seed_designs_the_same_ground():
    a = _strip(1, plan_site("countryside", 5, Geom(h=strip_length(Spec(),
                                                                  tail=TAIL),
                                                   cell=CELL, cyclic=False)))
    b = _strip(5, a.plan)
    for i in (0, min(1, a.count - 1)):
        assert (pygame.surfarray.array3d(a.paint(i))
                == pygame.surfarray.array3d(b.paint(i))).all()


def test_a_slice_is_ground_not_a_hole(plan):
    """A slice with a hole in it is a black band across the field - the exact
    shape of a masking bug, and invisible in a thumbnail."""
    st = TerrainStrip(plan)
    for i in (0, st.count - 1):
        arr = pygame.surfarray.array_alpha(st.paint(i))
        assert (arr > 250).mean() > 0.995, f"slice {i} has holes in it"


# ---------------------------------------------------------------- frontier --

def test_the_frontier_is_contiguous(plan):
    """The renderer draws up to the frontier and no further.

    A slice that finished out of order must not open a hole in the ground, so
    the frontier is the first *missing* slice, not a count of finished ones.
    """
    st = TerrainStrip(plan)
    last = st.count - 1
    if last > 0:
        st.paint(last)
        assert st.frontier() == 0
    for i in range(min(3, st.count)):
        st.paint(i)
    assert st.frontier() == min(3, st.count)
    assert st.missing_at(0) == (3 if st.count > 3 else -1)


def test_painting_outruns_the_scroll(long_plan):
    """The level starts while its ground is still being drawn, so the painters
    have to beat the camera - not race it."""
    st = TerrainStrip(long_plan)
    probe = min(3, st.count - 1)
    t = time.perf_counter()
    st.paint(probe)
    per_slice = time.perf_counter() - t
    crossing = st.slice_h / (NEAR_SPEED * SS)
    assert per_slice < crossing * 0.8, (
        f"a slice takes {per_slice:.2f} s to paint but the camera crosses it in "
        f"{crossing:.2f} s: the ground would run out")


# ------------------------------------------------------------------ levels --

def test_making_a_level_costs_the_frame_thread_nothing():
    """A Level is created mid-fight (for the sector after this one)."""
    t = time.perf_counter()
    lvl = Level(Spec(60.0), seed=2, tail=TAIL)
    made = time.perf_counter() - t
    assert made < 0.05, f"constructing a level cost {made:.2f} s"
    assert not lvl.built() and lvl.progress() == 0.0
    assert lvl.draw(pygame.Surface((800, 560), pygame.SRCALPHA),
                    pygame.Rect(0, 0, 800, 560)) == 0


def test_a_level_paints_itself_while_you_wait():
    """The contract is ahead of the camera, not finished: a Level paints the
    ground the craft is about to reach and leaves the rest alone until it is
    approached - a restart or a sector change throws the rest away."""
    lvl = Level(Spec(), seed=1, tail=TAIL)
    lvl.start()
    try:
        deadline = time.time() + 120.0
        while not lvl.built() and time.time() < deadline:
            time.sleep(0.05)
        assert lvl.built(), "the sector was never designed"
        while not lvl.ready_at(0.0) and time.time() < deadline:
            time.sleep(0.05)
        assert lvl.ready_at(0.0), "the ground under the craft never appeared"
        target = pygame.Surface((800, 560), pygame.SRCALPHA)
        lvl.update(1.0)
        assert lvl.draw(target, pygame.Rect(0, 0, 800, 560)) > 0
        assert lvl.progress() < 0.9, "painted the whole sector up front"
    finally:
        lvl.stop()


def test_stopping_a_level_leaves_no_thread_painting():
    before = threading.active_count()
    lvl = Level(Spec(), seed=1, tail=TAIL)
    lvl.start()
    time.sleep(0.4)
    lvl.stop(timeout=5.0)
    assert not any(t.name.startswith("raiden-strip")
                   for t in threading.enumerate()), "strip workers outlived it"
    assert threading.active_count() <= before


def test_the_ground_flows_down_the_screen(plan):
    """Direction, not rate - and the direction is not a matter of taste.

    The baked ground moves *down* past the craft (`terrain/layer.py` blits at
    `HUD_H + off`, and `off` grows). A strip that scrolled up would disagree with
    the baked map the renderer still falls back to, inside the same frame, and
    the tell would be unmistakable the moment a slice was missing. So: move the
    camera forward and the picture must move down by the same amount.
    """
    st = _strip(1, plan)
    for i in range(6):
        st.paint(i)
    surf = st.surface(0)
    # a band as tall as the field, so moving the camera one slice leaves rows
    # behind to compare against
    band = pygame.Rect(0, 0, surf.get_width(), C.FIELD_BOTTOM - C.FIELD_TOP)

    def shot(y: float):
        canvas = pygame.Surface((band.w, band.h), pygame.SRCALPHA)
        assert st.draw(canvas, band, y) >= 2, "the band should not be empty"
        return pygame.surfarray.array3d(canvas).transpose(1, 0, 2)

    y0 = 4 * STRIP_SLICE
    step = STRIP_SLICE // SS               # logical px for one slice of camera
    a, b = shot(y0), shot(y0 + STRIP_SLICE)
    # every row of the later picture above `step` is the row `step` above it was
    moved = (b[step:] == a[:-step]).mean()
    held = (b == a).mean()
    assert moved > 0.90, (f"the ground did not flow down: only {moved:.2f} of "
                          f"rows matched a downward shift of {step} px")
    assert held < 0.90, "the ground did not move at all"


def test_a_sector_opens_on_ground_not_on_a_hole(plan):
    """The camera starts one screen into the strip, so the opening band is full
    of ground on the first frame instead of showing the strip's own top edge."""
    lvl = Level(Spec(), seed=1, tail=TAIL)
    try:
        lvl.build()
        assert lvl.near_y == pytest.approx(TILE2)
        st = lvl.strips["near"]
        for i in range(4):
            st.paint(i)
        surf = st.surface(0)
        band = pygame.Rect(0, 0, surf.get_width(), surf.get_height())
        canvas = pygame.Surface((band.w, band.h), pygame.SRCALPHA)
        drawn = lvl.draw(canvas, band)
        assert drawn >= 2, f"only {drawn} slice(s) in the opening band"
        alpha = pygame.surfarray.array_alpha(canvas)
        assert (alpha > 200).mean() > 0.85, "the opening band is not covered"
    finally:
        lvl.stop()


def test_a_sector_fights_where_its_ground_is(plan):
    """A Level plans its encounters with its ground, on its own thread."""
    lvl = Level(Spec(), seed=1, tail=TAIL)
    try:
        lvl.build()
        assert lvl.encounters, "the sector designed ground but no fights"
        kinds = {str(e.kind) for e in lvl.encounters}
        assert kinds <= {k for k, _w in Spec().spawns}
        ys = [e.y for e in lvl.encounters]
        assert ys == sorted(ys)
        assert all(0.0 <= e.y <= lvl.length for e in lvl.encounters)
    finally:
        lvl.stop()


def test_two_levels_are_independent():
    """The sector being flown and the sector being prepared."""
    now = Level(Spec(), seed=1, tail=TAIL)
    nxt = Level(Spec(), seed=2, tail=TAIL)
    now.build()
    nxt.build()
    assert now.plan is not nxt.plan
    a = pygame.surfarray.array3d(TerrainStrip(now.plan).paint(0))
    b = pygame.surfarray.array3d(TerrainStrip(nxt.plan).paint(0))
    assert (a != b).any(), "two seeds designed the same ground"
    same = Level(Spec(), seed=1, tail=TAIL)
    same.build()
    c = pygame.surfarray.array3d(TerrainStrip(same.plan).paint(0))
    assert (a == c).all()


def test_a_window_never_walks_the_whole_plan(long_plan):
    """The perf cliff this architecture has to clear: long strips of props.

    Culling by the plan's own spatial index is what took a slice from half a
    minute to under a second. If someone rewrites a painter to walk every
    feature again, the ground quietly stops keeping up and the level shows its
    end.
    """
    mid = long_plan.geom.h // 2
    seen = long_plan.band("woods", mid, mid + STRIP_SLICE)
    assert 0 < len(seen) < len(long_plan.woods) * 0.5, "no culling happened"
    # indices, in plan order: the painter's jitter is keyed to them
    assert seen == sorted(seen)
    # a wrapping plan is not culled: its features cross the seam
    one = plan_site("countryside", 1)
    assert one.band("woods", 0, 10) == list(range(len(one.woods)))


def test_slices_meet_exactly_without_a_gap_or_a_crop(plan):
    """No bare band-height strip at a slice boundary, and no cropped slice.

    This was a real defect, and it read as the HUD being stamped between the
    tiles: the blit's third argument is a rect *inside the source surface*, so
    passing the band cropped FIELD_TOP rows off the top of every slice and
    FIELD_LEFT columns off its left. Each slice then left a bare strip of exactly
    the toolbar's height beneath it, and the ground sat too high in both layers.

    A pixel test would not have caught it: the crop shifts every slice by the
    same amount, so "the ground flows down the screen" still held. The
    relationships between the blits are what broke, so the relationships are what
    is asserted here - nothing cropped, destinations that tile, band spanned.
    """
    st = _strip(1, plan)
    for i in range(6):
        st.paint(i)

    class Ledger:
        def __init__(self) -> None:
            self.calls: list = []
            self.clips: list = []

        def set_clip(self, rect) -> None:
            self.clips.append(rect)

        def blit(self, surf, dest, area=None) -> None:
            self.calls.append((surf, dest, area))

    band = pygame.Rect(C.FIELD_LEFT, C.FIELD_TOP,
                       C.FIELD_RIGHT - C.FIELD_LEFT,
                       C.FIELD_BOTTOM - C.FIELD_TOP)
    ledger = Ledger()
    assert st.draw(ledger, band, 4 * STRIP_SLICE) >= 2, "one slice is not a test"

    tops = []
    for surf, dest, area in ledger.calls:
        if area is not None:
            assert int(area[0]) == 0 and int(area[1]) == 0, (
                f"a slice was cropped from ({area[0]}, {area[1]}): the top and "
                "left of the source are not the top and left of the band")
        tops.append((int(dest[1]), surf.get_height()))
    tops.sort()
    for (top0, h0), (top1, _) in itertools.pairwise(tops):
        assert top1 == top0 + h0, (
            f"slices meet at {top1}, not at {top0 + h0}: "
            f"{top1 - (top0 + h0)} px of band left bare between them")
    assert tops[0][0] <= band.top, "the band's top edge is not covered"
    assert tops[-1][0] + tops[-1][1] >= band.bottom, "the band's bottom row is bare"
    # ground stays inside the field: the drawing is clipped to the band, so a
    # slice that reaches past its edge is cut by the clip and not by cropping the
    # picture itself (that is what left the HUD-height gaps at every boundary)
    assert any(r == band for r in ledger.clips if r is not None), \
        "the strip is not drawn clipped to the band"
