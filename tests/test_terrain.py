"""Terrain map tests: baked data files and the procedural fallback."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pygame.surfarray
import pytest

import config as C
import terrain


def _render(theme: str, seed: int) -> bytes:
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    ter = terrain.Terrain(theme, seed)
    ter.draw(canvas)
    return pygame.surfarray.array3d(canvas).tobytes()


@pytest.mark.parametrize("theme", list(C.StageTheme))
def test_theme_builds_and_draws(theme):
    ter = terrain.Terrain(theme, 1)
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    ter.draw(canvas)          # must not raise
    assert len(ter.layers) == 2


def test_same_seed_same_map():
    assert _render("city", 3) == _render("city", 3)


def test_different_themes_different_maps():
    assert _render("city", 1) != _render("ocean", 1)


def test_scroll_offset_stays_wrapped():
    ter = terrain.Terrain("ruins", 2)
    for _ in range(200):
        ter.update(0.25, 1.0)
    for layer in ter.layers:
        assert 0.0 <= layer.off < terrain.TILE_H


def test_draw_clips_to_field_band():
    """Terrain must never bleed into the HUD band above FIELD_TOP."""
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    canvas.fill((1, 1, 1))
    ter = terrain.Terrain("wasteland", 1)
    ter.update(3.0, 1.0)
    ter.draw(canvas)
    for x in range(0, C.LOGICAL_W, 37):
        assert canvas.get_at((x, 10))[:3] == (1, 1, 1)


# --- baked data --------------------------------------------------------

def _scheduled(level: C.LevelSpec) -> list[tuple[str, int]]:
    """(theme, seed) pairs one sector loads, in schedule order."""
    seed = C.LEVELS.index(level) + 1
    return [(p.theme, seed) for p in level.phases] or [(level.theme, seed)]


@pytest.mark.parametrize("level", C.LEVELS, ids=[lv.name for lv in C.LEVELS])
def test_baked_art_shipped_for_every_level(level):
    for theme, seed in _scheduled(level):
        paths = terrain.baked_paths(theme, seed)
        assert all(p.is_file() for p in paths), f"missing bake: {paths}"


@pytest.mark.parametrize("level", C.LEVELS, ids=[lv.name for lv in C.LEVELS])
def test_baked_matches_procedural(level):
    """Stale-bake detector: change painters -> re-run bake_terrain.py."""
    for theme, seed in _scheduled(level):
        paths = terrain.baked_paths(theme, seed)
        base, far, near = terrain.build_procedural(theme, seed)
        for surf, path in ((base, paths[0]), (far, paths[1]), (near, paths[2])):
            loaded = pygame.image.load(str(path))
            assert loaded.get_size() == surf.get_size()
            fmt = "RGBA" if surf.get_flags() & pygame.SRCALPHA else "RGB"
            assert (pygame.image.tostring(loaded, fmt)
                    == pygame.image.tostring(surf, fmt))


# --- phase schedule ------------------------------------------------------

def test_plane_masks_stay_inside_the_canvas():
    """The painter fills only the box a mask covers. If a box is wrong, the bug
    is invisible as an artefact and visible as a black region - so check the
    bookkeeping directly."""
    from terrain.design.site import plan_site
    from terrain.paint.plane import Plane
    from terrain.paint.raster import _path_mask, _poly_mask
    from terrain.paint.surface import _PAD
    from terrain.tilekit import CH, CW

    p = plan_site("countryside", 1)
    plane = Plane(CW, CH, wrap=CH)
    masks = ([_path_mask(w.path, w.half * 2.0, plane) for w in p.water]
             + [_path_mask(r.path, 24.0, plane) for r in p.roads]
             + [_poly_mask(f.poly, plane) for f in p.fields])
    for m in masks:
        x0, y0, x1, y1 = m.box
        # The box is the GEOMETRY's, so it may lean over the edge - by a bounded
        # amount, and it is that bound which keeps a pathological path from asking
        # for a canvas-sized surface. What must never leave the canvas is a PIXEL,
        # and `clip` is the only way anything writes, two tests below.
        assert -_PAD <= x0 <= x1 <= CW + _PAD, m.box
        assert -_PAD <= y0 <= y1 <= CH + _PAD, m.box
        # pygame's arrays are (x, y): the box is (width, height)
        assert m.arr.shape == (x1 - x0, y1 - y0)
        assert m.arr.max() <= 1.0 and m.arr.min() >= 0.0
        # The clip agrees with itself: box and array always describe one thing.
        cbox, carr = m.clip(CW, CH)
        if carr is not None:
            cx0, cy0, cx1, cy1 = cbox
            assert 0 <= cx0 <= cx1 <= CW and 0 <= cy0 <= cy1 <= CH, cbox
            assert carr.shape == (cx1 - cx0, cy1 - cy0), (cbox, carr.shape)
        # A mask entirely outside the canvas must clip to nothing rather than
        # write a wrapped slice with negative indices.
        if x1 <= 0 or y1 <= 0 or x0 >= CW or y0 >= CH:
            assert m.clip(CW, CH)[1] is None, m.box


def test_a_window_paints_its_own_local_geometry():
    """A plane is a window of the world. Masks and stamps come back in WINDOW
    coordinates and must stay inside it - a mask that leaks outside shows up as
    a missing strip, and a stamp at world coordinates lands somewhere else."""
    from terrain.design.site import plan_site
    from terrain.paint.plane import Plane
    from terrain.paint.raster import _path_mask
    from terrain.paint.surface import _PAD
    from terrain.plan.geom import Geom
    from terrain.tilekit import CH, CW

    strip = plan_site("countryside", 1, Geom(h=3 * CH, cyclic=False))
    win = Plane(CW, CH, x0=0, y0=2 * CH)
    assert win.wrap == 0.0 and win.shifts() == (0.0,)
    inside = 0
    for w in strip.water:
        m = _path_mask(w.path, w.half * 2.0, win)
        x0, y0, x1, y1 = m.box
        # A window's mask may reach `_PAD` beyond it - the shape of a river cannot
        # depend on where the window ends, which is what used to make a feature
        # change shape at a slice boundary. Only writes are clipped.
        assert -_PAD <= x0 <= x1 <= CW + _PAD, m.box
        assert -_PAD <= y0 <= y1 <= win.h + _PAD, m.box
        assert m.arr.shape == (x1 - x0, y1 - y0)
        cbox, carr = m.clip(CW, win.h)
        if carr is not None:
            cx0, cy0, cx1, cy1 = cbox
            assert 0 <= cx0 <= cx1 <= CW and 0 <= cy0 <= cy1 <= win.h, cbox
            assert carr.shape == (cx1 - cx0, cy1 - cy0), (cbox, carr.shape)
        # geometry far above the window must not paint into it at all
        if all(p[1] < 2 * CH - 200.0 for p in w.path):
            assert (x1 - x0) * (y1 - y0) == 0 or m.arr.max() == 0.0
        else:
            inside += 1
    assert inside, "the window should overlap some of the strip's water"
    # a one-screen plan does wrap, so its seam copies still get stamped
    whole = Plane(CW, CH, wrap=CH)
    assert whole.shifts() == (0.0, -float(CH), float(CH))


def test_planned_ground_covers_the_layer():
    """A painted layer must be opaque ground across the whole field: box math
    that skips a region reads as a black band while the map scrolls."""
    import random

    from terrain.compose import kit_available
    from terrain.design.site import plan_site
    from terrain.paint.plane import Plane
    from terrain.paint.site import paint_site
    from terrain.tilekit import CH, CW, kit

    if not kit_available():
        pytest.skip("no generated tileset")
    pl = Plane(CW, CH)
    pl.stamp.fill((30, 30, 30, 255))       # base ground stands in for the grid
    pl.sync()
    paint_site(pl, kit(), plan_site("canyon", 2), random.Random(5))
    surf = pl.surface()
    a = pygame.surfarray.array_alpha(surf)
    assert (a > 200).mean() > 0.99, f"{(a > 200).mean():.2f} of the layer painted"
    rgb = pygame.surfarray.array3d(surf).astype(int).sum(axis=2)
    assert (rgb < 12).mean() < 0.005, "unpainted black region in the layer"


def test_levels_schedule_phases():
    for lv in C.LEVELS:
        assert lv.phases, f"{lv.name} has no terrain phases"
        assert lv.phases[0].theme == lv.theme
        assert all(p.weight > 0 for p in lv.phases)
        assert sum(p.weight for p in lv.phases) == pytest.approx(1.0)


def test_track_boundaries_follow_weights():
    lv = C.LEVELS[0]
    track = terrain.TerrainTrack(lv.phases, 1)
    assert track._idx(0.0) == 0
    b = track.segs[1][1]
    expect = terrain.PHASE_PLAN * lv.phases[0].weight
    assert b == pytest.approx(expect)
    assert track._idx(b - 0.1) == 0
    assert track._idx(b + 0.1) == 1
    assert track._idx(terrain.PHASE_PLAN * 10) == len(track.segs) - 1


def test_zone_handover_is_a_seam_and_never_a_fade():
    """Mid-sector the environment changes, but the ground must never go
    translucent: every pixel of a mid-handover frame is one zone's pixels or
    the other's, byte for byte. A blended pixel means a fade."""
    import numpy as np

    lv = C.LEVELS[3]                       # ruins -> canyon
    a, b = lv.phases

    def shot(seconds: float, phases: tuple):
        tr = terrain.TerrainTrack(phases, 4)
        for _ in range(int(seconds / 0.05)):
            tr.update(0.05, 1.0)
        canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
        tr.draw(canvas)
        return pygame.surfarray.array3d(canvas)

    t0 = terrain.PHASE_PLAN * a.weight
    mid = t0 + 0.5 * terrain.PHASE_SWEEP
    solo_a = shot(mid, (a,))
    solo_b = shot(mid, (b,))
    during = shot(mid, lv.phases)

    x0, x1 = 0, C.LOGICAL_W
    y0, y1 = C.HUD_H, terrain.TILE_H + C.HUD_H
    box = (slice(x0, x1), slice(y0, y1), slice(None))
    D, A, B = during[box], solo_a[box], solo_b[box]
    is_a = np.all(D == A, axis=2)
    is_b = np.all(D == B, axis=2)
    assert is_a.sum() > 500 and is_b.sum() > 500, "only one zone is visible"

    # where the boundary (and its crest/foot shading) can actually reach
    edge = C.HUD_H + int(terrain.TILE_H * 0.5)
    cols = np.arange(x0, x1)
    line = np.array([terrain.seam_y(float(c), edge) for c in cols])[:, None]
    rows = np.arange(y0, y1)[None, :]
    near = np.abs(rows - line) <= terrain.SEAM_SHADOW + 2

    def scaled(p, q):
        """Is p q under one lighting factor? The boundary lights its crest and
        shades its foot in the colours of the ground it stands on, which is not
        a mixture of the two zones - and a mixture is the thing that must never
        appear. Fitted over a grid of factors, loose enough for near-black
        pixels where rounding is a large share of the value."""
        q = q.astype(np.float64)
        p = p.astype(np.float64)
        best = np.full(p.shape[:2], 1e9)
        for k in np.arange(0.35, 1.45, 0.05):
            r = np.abs(p - np.clip(k * q, 0.0, 255.0)).max(axis=2)
            best = np.minimum(best, r)
        return best < 8.0

    allowed = is_a | is_b | scaled(D, A) | scaled(D, B)
    blended = ~(allowed | ~near)
    assert blended.sum() == 0, \
        f"{blended.sum()} pixels mix the two zones: the ground is dissolving"
    # away from the boundary every pixel is one zone's ground, exactly: a fade
    # would show up as a whole field of in-between pixels, not 40 rows of them
    far = ~near
    assert np.all((is_a | is_b)[far]), "ground blended outside the boundary band"
    assert (scaled(D, A) | scaled(D, B))[near].sum() > 200, \
        "no edge dressing: the scarp has no crest or foot"
    # the boundary has a SHAPE: a perfectly straight cut reads as a rendering
    # glitch, so the seam must land at several different heights across the field
    heights = set()
    for col in range(x0, x1, terrain.SEAM_STEP):
        ys = np.flatnonzero(is_b[col - x0, :])
        if len(ys):
            heights.add(int(ys.max()))
    assert len(heights) >= 8, f"seam is nearly straight: {sorted(heights)}"
    # the seam travels with the scroll: later means more of the incoming zone
    late = t0 + 0.9 * terrain.PHASE_SWEEP
    late_box = (slice(x0, x1), slice(y0, y1), slice(None))
    n_b = np.all(shot(late, lv.phases)[late_box]
                 == shot(late, (b,))[late_box], axis=2).sum()
    assert n_b > is_b.sum()
    # and it settles: past the sweep the sector is plain incoming ground
    end = t0 + terrain.PHASE_SWEEP + 1.0
    assert np.array_equal(shot(end, lv.phases), shot(end, (b,)))


def test_track_update_advances_all_segments():
    lv = C.LEVELS[0]
    tr = terrain.TerrainTrack(lv.phases, 1)
    for _ in range(40):
        tr.update(0.25, 1.0)
    for seg in tr.segs:
        for layer in seg[0].layers:
            assert 0.0 <= layer.off < terrain.TILE_H


def test_track_empty_phases_rejected():
    with pytest.raises(ValueError):
        terrain.TerrainTrack((), 1)


def test_renderer_set_terrain_builds_track():
    import ui
    rend = ui.Renderer(pygame.Surface((C.LOGICAL_W, C.LOGICAL_H)),
                       C.Settings())
    rend.set_terrain(C.LEVELS[0], 1)
    assert isinstance(rend._terrain, terrain.TerrainTrack)
    rend.update_background(0.1, 1.0)       # must scroll without error
    rend.clear_terrain()
    assert rend._terrain is None


def test_terrain_without_baked_art_falls_back():
    """An unbaked (theme, seed) still builds procedurally and is stable."""
    paths = terrain.baked_paths("countryside", 4242)
    assert not paths[0].exists()
    a = terrain.Terrain("countryside", 4242)
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    a.draw(canvas)
    px_a = pygame.surfarray.array3d(canvas).tobytes()
    b = terrain.Terrain("countryside", 4242)
    canvas2 = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    b.draw(canvas2)
    assert px_a == pygame.surfarray.array3d(canvas2).tobytes()


def test_a_bridge_deck_lies_along_its_road():
    """The deck is the road over the water, so it is where the road is and
    nowhere else: on the road's centreline the water is covered, and beside the
    road - just past the parapets - the river still shows.

    The old deck was a plank rectangle rotated to "the road's heading" with
    pygame's counter-clockwise rotation in a y-down plan, so any crossing that
    was not square lay across the river at the mirrored angle: the second half
    of this test is what that looked like. Colour, not alpha: water is teal
    (green over red), a deck is grey.
    """
    import math
    import random

    from terrain.compose import kit_available
    from terrain.design.site import plan_site
    from terrain.paint.plane import Plane
    from terrain.paint.road_table import BRIDGE
    from terrain.paint.roads import _deck_run, _offset
    from terrain.paint.site import paint_site
    from terrain.plan.geom import CELL, Geom
    from terrain.tilekit import kit

    if not kit_available():
        pytest.skip("no generated tileset")
    plan = plan_site("countryside", 2, Geom(h=1120 * 8, cell=CELL, cyclic=False))

    def teal(c) -> float:
        return c[1] - c[0]

    checked = 0
    for r in plan.roads:
        for b in r.bridges[:2]:
            run = _deck_run(plan, r, *b)
            if run is None:
                continue
            pts, lo, hi = run
            body = min(plan.water, key=lambda w: min(
                math.hypot(x - b[0], y - b[1]) for x, y in w.path))
            y0 = int(b[1] - 200)
            pl = Plane(1600, 400, x0=0, y0=y0)
            paint_site(pl, kit(), plan, random.Random(1))
            surf = pl.surface()

            def at(x, y, surf=surf, y0=y0):
                return surf.get_at((int(x), int(y - y0)))[:3]

            def deep(x, y, body=body):
                return min(math.hypot(x - a, y - c) for a, c in body.path) \
                    < body.half - 6.0
            span = pts[lo + 1:hi]
            on = [at(x, y) for x, y in span]
            assert on and sum(map(teal, on)) / len(on) < 4.0, (
                f"the {r.kind} road at ({b[0]:.0f},{b[1]:.0f}) has no deck "
                "over the water")
            past = r.width * 0.85 + BRIDGE["kerb"] + 14.0
            beside = [at(x, y) for side in (-1.0, 1.0)
                      for x, y in _offset(span, side * past)
                      if deep(x, y) and 0 <= y - y0 < 400]
            if beside:
                assert sum(map(teal, beside)) / len(beside) > 8.0, (
                    f"the deck at ({b[0]:.0f},{b[1]:.0f}) covers the river beside "
                    f"the {r.kind} road: it does not lie along it")
            checked += 1
    assert checked >= 4, f"only {checked} bridges to check"
