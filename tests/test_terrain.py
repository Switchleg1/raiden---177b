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
