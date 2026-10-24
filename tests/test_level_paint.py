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


def test_a_slice_shows_the_same_ground_as_the_truth():
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

    rows = STRIP_SLICE * 4
    plan = _plan_here("countryside", 3, rows)
    small = TerrainStrip(plan, "near")
    whole = TerrainStrip(plan, "near", slice_h=rows, margin=STRIP_MARGIN)

    truth = whole.paint(0)
    assert truth is not None and whole.count == 1, "need a one-window reference"
    tv = numpy.asarray(pygame.surfarray.array3d(truth))

    assert small.count >= 3, "want interior slices and the clamped last one"
    worst = (None, 0.0, 0.0)
    for i in range(small.count):
        band = small.paint(i)
        assert band is not None
        kept = numpy.asarray(pygame.surfarray.array3d(band))
        # The band decides its own stride; bands are logical rows, the strip's
        # geometry decides how many, and assuming a unit here hid a factor of SS.
        stride = band.get_height()
        ref = tv[:, i * stride:(i + 1) * stride]
        assert ref.shape == kept.shape, (ref.shape, kept.shape)
        diff = numpy.abs(ref.astype(int) - kept.astype(int))
        bad = float((diff.max(axis=2) > 0).mean())
        mag = float(diff[diff > 0].mean()) if (diff > 0).any() else 0.0
        if bad > worst[1]:
            worst = (i, bad, mag)
    # 0.1% is not the goal; it is the floor below which no visible seam can hide.
    # The bugs this caught sit three orders of magnitude above it - 99.9% for the
    # inverted kept-band crop, 37% for the truncated lattice - and what remains is
    # the last slice's 0.068% at magnitude 5/255: the water and road masks' known
    # one-row integer-vs-`ceil` disagreement, now the only thing standing between
    # here and bit-exact, and named here rather than thresholded away.
    assert worst[1] < 0.001, (
        f"slice {worst[0]} differs from the one-window reference on "
        f"{worst[1] * 100:.3f}% of pixels (mean magnitude {worst[2]:.1f}/255): the "
        "slice is not painting the ground it belongs to. Look first at the kept-band "
        "crop in `_paint` (is `top` the right sign?), then at what a window culls.")
