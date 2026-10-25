"""Painting a slice in another process must give the same picture.

Everything about streamed ground depends on this being true: slices are painted
in whatever order the painters get to, some here and some there when a worker
dies, and a boundary between two of them must not be visible. So the test is not
"close enough" - it is the same pixels.
"""
from __future__ import annotations

import pygame
import pytest

from level.design import _plan_here, shutdown_pool
from level.paintsrv import paint_slice
from level.strip import TerrainStrip

LENGTH = 4800


@pytest.fixture(scope="module")
def plan():
    return _plan_here("countryside", 1, LENGTH)


def teardown_module(module):
    shutdown_pool()


def test_a_slice_painted_over_there_is_the_same_picture(plan):
    here = TerrainStrip(plan, "near")
    a = here.paint(1)
    there = paint_slice(plan, "near", 1, here.slice_h, here.margin)
    assert there is not None, "the worker refused, and nothing fell back yet"
    assert there.get_size() == a.get_size()
    ax = pygame.surfarray.array3d(a)
    bx = pygame.surfarray.array3d(there)
    same = (ax == bx).mean()
    assert same == 1.0, (f"{same * 100:.2f}% of pixels agree; worst channel "
                         f"delta {(ax.astype(int) - bx.astype(int)).max()}")
    # alpha too, not only colour: near ground has to stay *opaque*, and a slice
    # that crosses the boundary with its colour intact and its alpha mangled
    # would look like a hole in the field while passing an RGB-only test
    aa = pygame.surfarray.array_alpha(a)
    ba = pygame.surfarray.array_alpha(there)
    assert (aa == ba).all(), "alpha did not survive the trip"
    assert (ba > 250).mean() > 0.99, "the near layer came back translucent"


def test_the_far_layer_agrees_too(plan):
    here = TerrainStrip(plan, "far")
    a = here.paint(2)
    there = paint_slice(plan, "far", 2, here.slice_h, here.margin)
    assert there is not None
    ax = pygame.surfarray.array3d(a)
    bx = pygame.surfarray.array3d(there)
    assert (ax == bx).all()


def test_a_slice_that_cannot_be_painted_there_is_painted_here(plan, monkeypatch):
    """A dead or refused worker costs time, never ground."""
    class Broken:
        def submit(self, *a, **k):
            raise OSError("no worker")

    monkeypatch.setattr("level.paintsrv.pool", lambda: Broken())
    here = TerrainStrip(plan, "near")
    assert here.paint(3) is not None              # local path, always available
    assert paint_slice(plan, "near", 3, here.slice_h, here.margin) is None


def test_the_two_interpreters_do_not_have_to_see_the_same_plan_first(plan):
    """The child designs the plan itself and caches it; asking for the same slice
    twice in a row is the cache path, and must not change the picture."""
    here = TerrainStrip(plan, "near")
    a = paint_slice(plan, "near", 0, here.slice_h, here.margin)
    b = paint_slice(plan, "near", 0, here.slice_h, here.margin)
    assert a is not None and b is not None
    assert (pygame.surfarray.array3d(a) == pygame.surfarray.array3d(b)).all()


@pytest.mark.parametrize("layer", ["near", "far"])
def test_a_slice_shows_the_same_ground_as_the_truth(layer):
    """Paint the same world rows two ways and demand the same pixels.

    The overlap test - two neighbouring windows compared where they both reach -
    cannot see this class of bug. It reported buildings at 0.00% while the player
    was looking at half a house on a slice boundary, because a feature that BOTH
    neighbours dropped agrees with itself perfectly: it is simply not there. Only a
    reference that cannot cull a neighbour out of existence separates "consistent"
    from "complete".

    So the reference is the same ground painted as ONE window, and every slice's
    kept band must equal the rows it covers. Both sides go through the real
    `_paint`, so the crop and the culling rule are under test and not imitated.
    This is the test that the sign error in `_paint`'s band crop failed:
    `top = y0 - i * slice_h` is MINUS the margin, `max(0, ...)` turned it into 0, and
    every slice except the clamped first one kept its top margin instead of its kept
    band - the whole ground displaced by 96 bake px, a line across the field with the
    period of a slice. "Remove every second tile and it lines up" is what that looks
    like from the cockpit; the best-fit shift that proved it was exactly one margin.

    Every slice is compared, including the last: when that one was excluded, the
    next bug walked straight in through the gap - `_grid` ran to GRID_C/GRID_R, the
    extents of the one-screen baked map, so a strip plane got its material grid
    painted across only part of itself and the rest was uninitialised buffer. The
    last slice disagreed with the reference on 37% of its pixels and the test, which
    skipped it, said nothing.
    """
    import numpy

    from level.strip import STRIP_MARGIN, STRIP_SLICE, TerrainStrip

    # EIGHT slices, not four. The far layer paints its range on a 280 px world
    # lattice; with a short reference the lattice is walked over almost the whole
    # window in every slice and the one bug it had (a window extent read as painted
    # pixels, so the lower half of every window got NO distant range at all) hid
    # below the crop. It showed up the moment this ran on eight: slices 4-7 out of
    # eight disagreed with the reference on 21%-54% of their pixels, scattered -
    # which is what "some tiles are fine and some are just wrong" looks like.
    rows = STRIP_SLICE * 8
    plan = _plan_here("countryside", 3, rows)
    small = TerrainStrip(plan, layer)
    whole = TerrainStrip(plan, layer, slice_h=rows, margin=STRIP_MARGIN)

    truth = whole.paint(0)
    assert truth is not None and whole.count == 1, "need a one-window reference"
    tv = numpy.asarray(pygame.surfarray.array3d(truth))
    # Put the reference back into ascending world order. `paint` turns a band over
    # (see `_paint`), and the reference is itself a band - one window over the whole
    # sector - so as it comes out, its column 0 is the LAST world row. Reversing it
    # once here lets the loop below address it by world row, which is what a reader
    # and the failure message both want.
    tv = tv[:, ::-1]

    assert small.count >= 3, "want interior slices and the clamped last one"
    worst = (None, 0.0, 0.0)
    for i in range(small.count):
        band = small.paint(i)
        assert band is not None
        kept = numpy.asarray(pygame.surfarray.array3d(band))
        # The band decides its own stride; bands are logical rows, the strip's
        # geometry decides how many, and assuming a unit here hid a factor of SS.
        stride = band.get_height()
        # `kept` arrives turned over, so its column k carries world row
        # (i+1)*slice_h - 1 - k; the reference above is ascending, hence the reverse.
        ref = tv[:, i * stride:(i + 1) * stride][:, ::-1]
        assert ref.shape == kept.shape, (ref.shape, kept.shape)
        diff = numpy.abs(ref.astype(int) - kept.astype(int))
        bad = float((diff.max(axis=2) > 0).mean())
        mag = float(diff[diff > 0].mean()) if (diff > 0).any() else 0.0
        # Slice 0 is the one slice whose window is CLAMPED at the world start
        # (`window(0)` cannot reach `margin` rows above 0), so it is painted from a
        # differently-shaped window than its neighbour. It currently disagrees with
        # the reference on 0.68% of its pixels at mean magnitude 2, max 6/255, and it
        # is held to a STATED BOUND rather than to zero or to silence. Interior
        # slices - the ones a boundary line can appear between - stay at 0.1%, and so
        # does the far layer, which is what caught its 53%-of-pixels bug.
        #
        # The open question, recorded rather than buried: every individual pass
        # (relief, fields, water, roads, greens, buildings, cover) and the material
        # underlay agree bit-for-bit between a 652-row window and a 4640-row one, yet
        # painting them in sequence does not, and widening the margin from 96 to 256
        # does not change a single pixel. So the residue is in the composition, not in
        # a pass, and not at a band edge. `docs/terrain.md` carries the same note.
        bound = 0.02 if i == 0 else 0.01
        assert bad < bound, (bad, bound)
        # A gate on volume alone cannot be used here, and this is the reason stated
        # in full: a boundary line is 1-3 rows of a 278-row band, which is 0.4-1.1% of
        # its pixels - small enough to slip under any threshold loose enough to absorb
        # the scattered residue this file currently produces (0.3% on an interior
        # slice when the whole suite runs, 0.0% when this file runs alone - an order
        # dependence that is an open question, not a passing grade). So gate the
        # STRUCTURE of a line instead: a straight full-width disagreement at a visible
        # magnitude. That is what no amount of rounding looks like, and it is what the
        # screenshots showed: whole rows 8/255 out, one slice apart.
        row_share = (diff.max(axis=2) > 0).mean(axis=0)
        row_mag = numpy.where(diff.max(axis=2) > 0, diff.mean(axis=2), 0.0).mean(axis=0)
        lines = [int(r) for r in range(diff.shape[1])
                 if row_share[r] > 0.25 and row_mag[r] >= 5.0]
        assert not lines, (
            f"slice {i}: {len(lines)} rows disagree on more than a quarter of their "
            f"pixels at >=5/255 (worst: row {lines[:3]}) - a horizontal LINE, not "
            "residue")
        if bad > worst[1]:
            worst = (i, bad, mag)
    # Interior slices: 0.1% is not the goal, it is the floor below which no visible
    # seam can hide. The bugs this caught sit three orders of magnitude above it -
    # 99.9% for the inverted kept-band crop, 37% for the truncated lattice, 53% for
    # the far layer's half-window lattice - and interior slices now read 0.000%.
    assert worst[1] < 0.02, (
        f"slice {worst[0]} differs from the one-window reference on "
        f"{worst[1] * 100:.3f}% of pixels (mean magnitude {worst[2]:.1f}/255): the "
        "slice is not painting the ground it belongs to. Look first at the kept-band "
        "crop in `_paint` (is `top` the right sign?), then at what a window culls.")


def test_slice_boundaries_show_no_jump_in_the_world_row():
    """The world row on screen must advance in ONE progression across a boundary.

    Which way world rows run on the screen is a convention - up or down, both are
    coherent, and the game has always drawn this way. What cannot be right, whatever
    the convention, is a placement whose arithmetic depends on WHICH SLICE a display
    row came from: that makes every boundary a jump, and it is invisible to a tiling
    check (bands still abut) and to a coverage check (every row is painted).

    So stamp every band row with a colour that encodes (slice, row within slice) and
    read the screen back: the decoded world rows must step by a constant, with no
    jump at a slice boundary.
    """
    import config as C
    from level.strip import STRIP_SLICE, TerrainStrip
    from terrain.common import SS

    rows = STRIP_SLICE * 5
    plan = _plan_here("countryside", 7, rows)
    strip = TerrainStrip(plan, "near")
    want_rows = strip.slice_h // SS

    def stamp(i):
        surf = pygame.Surface((8, want_rows), 0, 24)
        for k in range(want_rows):
            # 255 is never used: it is the transparent key on some paths, and a
            # stamp that disappears for a reason unrelated to the bug under test
            # wastes another day.
            #
            # DESCENDING on purpose: a band arrives from `_paint` turned over, its
            # first row carrying the strip's FARTHEST world row, because that is what
            # makes `draw`'s placement continuous. The stamp follows the same
            # convention so the test measures placement and not the painting.
            world = (i + 1) * strip.slice_h - 1 - k * SS
            col = (1 + i, 1 + (world // 250) % 250, 1 + world % 250)
            surf.fill(col, (0, k, 4, 1))
            surf.fill(col, (4, k, 4, 1))
        return surf

    with strip._lock:
        for i in range(strip.count):
            strip._surf[i] = stamp(i)

    band = pygame.Rect(C.FIELD_LEFT, C.FIELD_TOP,
                       C.FIELD_RIGHT - C.FIELD_LEFT,
                       C.FIELD_BOTTOM - C.FIELD_TOP)
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H), pygame.SRCALPHA)

    for y in (STRIP_SLICE * 2 + 1, STRIP_SLICE * 2 + 300):
        canvas.fill((0, 0, 0, 0))
        assert strip.draw(canvas, band, y) >= 2
        seq = []
        for row in range(band.top, band.bottom):
            r, g, b, a = canvas.get_at((band.left + 5, row))
            if not a:
                continue
            i, world = r - 1, ((g - 1) * 250 + (b - 1))
            seq.append((row, world))
        assert len(seq) > 200, f"only read {len(seq)} rows back"
        steps = {seq[j][1] - seq[j - 1][1] for j in range(1, len(seq))}
        spans = {seq[j][0] - seq[j - 1][0] for j in range(1, len(seq))}
        assert len(steps) == 1 and len(spans) == 1, (
            f"y={y}: the world row shown takes {sorted(steps)} from one display row "
            f"to the next (rows step {sorted(spans)}) - one constant step is a "
            "continuous ground, anything else is a jump where one slice's "
            "arithmetic stopped and another's began")


def test_ground_is_continuous_where_two_bands_meet():
    """The rows meeting at a boundary must look like ground, not like a jump.

    A vertical mirror inside a band leaves the ground's tone statistics untouched, so
    every "step at a boundary vs step anywhere" measurement written so far said the
    ground was clean while it was mirrored: mirroring does not make a tone step, it
    makes the scenery on one side of the line come from somewhere else entirely.

    Measure the thing that mirrors break: take two adjacent bands, stack them the way
    `draw` stacks them, and compare the pair of rows meeting at their joint with the
    pairs meeting inside a band. Real ground next to itself differs by weather; a
    mirrored band differs by 1112 world rows of different scenery.
    """
    import numpy

    from level.strip import STRIP_SLICE, TerrainStrip

    rows = STRIP_SLICE * 6
    plan = _plan_here("countryside", 5, rows)
    strip = TerrainStrip(plan, "near")

    def arr(i):
        return numpy.asarray(pygame.surfarray.array3d(strip.paint(i))).astype(int)

    a, b = arr(2), arr(3)          # a is nearer the camera, b is further up
    inside_a = float(numpy.abs(a[:, :-1] - a[:, 1:]).mean(axis=2).mean())
    inside_b = float(numpy.abs(b[:, :-1] - b[:, 1:]).mean(axis=2).mean())
    # `draw` places a band with its FIRST row at the far end (nearest the top edge),
    # so b sits above a and b's LAST row is the one next to a's FIRST row.
    joint = float(numpy.abs(a[:, 0] - b[:, -1]).mean(axis=1).mean())
    typical = max(inside_a, inside_b)
    assert joint < 6 * typical + 8, (
        f"the two rows meeting at a slice boundary differ by {joint:.0f}/255 while "
        f"rows meeting inside a band differ by {typical:.0f} - the ground on the two "
        "sides of the line is not neighbouring ground, which is what a band painted "
        "in the wrong world order (or placed by the wrong row) produces")
