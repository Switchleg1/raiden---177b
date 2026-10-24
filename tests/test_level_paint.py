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
