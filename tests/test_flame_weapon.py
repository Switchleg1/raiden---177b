"""The flamethrower: fire that is thrown, not worn.

Two claims are worth pinning, and both are the opposite of what the whip does.

The first is *independence*. A lash bead is answerable to the bead ahead of it,
which is why the lash bends when the craft moves. A puff of fire is answerable
to nothing: it is born at the nozzle with a position and a velocity and every
later position is that birth point plus that velocity times its age. Move the
craft a screen to the left and a puff already in the air does not care.

The second is that the *fade is the damage*. The puff thins over its life and
the same number drives the picture and the hit, ending at half its opening
strength the instant it goes out - so the player can read how hard a puff is
hitting from how it looks, and there is no second, invisible damage curve for
the two to disagree.
"""

import math
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest  # noqa: E402

pygame.init()

import config as C  # noqa: E402
import sprites  # noqa: E402
import terrain  # noqa: E402
import ui  # noqa: E402
from entities import Enemy, Flame, FlameThrower  # noqa: E402
from game import Game  # noqa: E402
from game.items import Item  # noqa: E402

DT = C.SIM_DT


@pytest.fixture(autouse=True)
def _display():
    """Blitting needs a live display; other suites tear it down when they end."""
    pygame.init()
    if pygame.display.get_surface() is None:
        pygame.display.set_mode((32, 32))
    yield


def _game(seed: int = 7) -> Game:
    g = Game(rng=random.Random(seed))
    g.new_game()
    g.start_level(0)
    return g


def _hull(kind: C.EnemyKind, x: float, y: float, hp: int = 999) -> Enemy:
    """A stationary, hard-to-kill target: these tests count damage, not deaths."""
    e = Enemy(kind, x, y)
    e.hp = hp
    e.max_hp = max(hp, e.max_hp)
    e.vx = e.vy = 0.0
    return e


# ------------------------------------------------------- a puff is its own thing

def test_a_puff_is_its_birth_point_plus_a_constant_rate():
    """The whole model of a puff in one line: pos = birth + v * age."""
    p = Flame(400.0, 500.0, 12.0, -C.FLAME_SPEED)
    for step in (0.1, 0.25, 0.5):
        p.age = step
        assert p.x == pytest.approx(400.0 + 12.0 * step)
        assert p.y == pytest.approx(500.0 - C.FLAME_SPEED * step)


def test_moving_the_craft_leaves_the_fire_where_it_was():
    """The failure this weapon exists to avoid: fire riding along with the ship.

    The nozzle is moved a hundred units sideways after the puffs are away. The
    puffs born before the move must land exactly where their own velocity says,
    not one hundred units over.
    """
    t = FlameThrower()
    for _ in range(24):                       # 0.2 s of burning at x=400
        t.update(DT, 400.0, 500.0)
    born = {(p.x0, p.y0): p.age for p in t.puffs}
    assert born, "the thrower emitted nothing"
    for _ in range(12):                       # 0.1 s of burning at x=500
        t.update(DT, 500.0, 500.0)
    for (x0, y0), age0 in born.items():
        # the same puff, one tenth of a second later, is exactly where its own
        # velocity carried it - the nozzle's move is not in that number
        match = [p for p in t.puffs
                 if (p.x0, p.y0) == (x0, y0)
                 and p.age == pytest.approx(age0 + 0.1)]
        assert match, "a puff that was already away vanished or was re-born"
        p = match[0]
        assert p.x == pytest.approx(x0 + p.vx * p.age)
        assert abs(p.x - x0) < 0.2 * abs(500.0 - 400.0), "the puff followed the ship"


def test_the_fire_outruns_the_ground_it_falls_onto():
    """The puff's rate is defined against the world, not picked out of the air.

    The ground passes the craft at SCROLL_NEAR. A puff that travels slower than
    that is being carried backward with the terrain no matter what its number
    looks like on screen, so the rate is stated as a multiple of the scroll and
    the multiple is the knob.
    """
    assert C.FLAME_SPEED == pytest.approx(C.FLAME_SCROLL_MULT * C.SCROLL_NEAR)
    assert C.FLAME_SCROLL_MULT > 1.0, "the fire does not outrun the ground"
    # the scroll rate is one number, shared with the layer that draws it
    assert terrain.NEAR_SPEED == C.SCROLL_NEAR


def test_the_plume_reaches_a_head_ahead_of_the_craft():
    """Reach is speed times life, and it has to be worth taking the power."""
    t = FlameThrower()
    assert t.reach == pytest.approx(C.FLAME_SPEED * C.FLAME_LIFE)
    assert t.reach >= C.SCROLL_NEAR, "one second of fire does not clear a second of world"
    for _ in range(int(1.05 / DT)):
        t.update(DT, 400.0, 500.0)
    far = min(p.y for p in t.puffs)
    assert 500.0 - C.FLAME_NOZZLE - far >= t.reach * 0.95, "the plume falls short"


# ------------------------------------------------------------------ the fade

def test_the_puff_starts_at_full_strength_and_ends_at_half():
    p = Flame(400.0, 500.0, 0.0, -C.FLAME_SPEED)
    assert p.fade == pytest.approx(1.0)
    assert p.dmg == C.FLAME_DMG
    p.age = p.life
    assert p.fade == pytest.approx(0.0)
    assert p.dmg == pytest.approx(C.FLAME_DMG * 0.5, abs=0.5)


def test_the_damage_only_ever_falls_and_never_reaches_zero():
    """A spent puff still burns: half, but not nothing, until it is gone."""
    p = Flame(400.0, 500.0, 0.0, -C.FLAME_SPEED)
    seen = []
    while p.alive:
        p.update(DT)
        seen.append((p.fade, p.dmg))
    assert all(seen[i][1] >= seen[i + 1][1] for i in range(len(seen) - 1)), \
        "a puff got stronger as it cooled"
    assert all(d >= 1 for _f, d in seen), "a puff stopped hurting before it died"
    assert seen[-1][1] <= C.FLAME_DMG * 0.5 + 0.5, "it never faded to half"


def test_the_puff_spreads_as_it_cools():
    """The trade for the fading damage: a weak puff covers a wider patch."""
    p = Flame(400.0, 500.0, 0.0, -C.FLAME_SPEED)
    assert p.r == pytest.approx(C.FLAME_R)
    p.age = p.life
    assert p.r == pytest.approx(C.FLAME_R + C.FLAME_GROW)
    assert C.FLAME_GROW > 0.0


def test_a_puff_is_gone_exactly_when_its_fade_is():
    p = Flame(400.0, 500.0, 0.0, -C.FLAME_SPEED)
    steps = 0
    while p.alive:
        p.update(DT)
        steps += 1
        assert p.alive == (p.fade > 0.0)
    assert steps == pytest.approx(C.FLAME_LIFE / DT, abs=2)


# ------------------------------------------------------------- the weapon

def test_the_thrower_lays_puffs_on_a_bounded_plume():
    t = FlameThrower()
    peak = 0
    for _ in range(int(3.0 / DT)):
        t.update(DT, 400.0, 500.0)
        peak = max(peak, len(t.puffs))
    assert peak > 10, "the plume is a trickle"
    assert peak <= C.FLAME_MAX_PUFFS, "the plume is unbounded"


def test_the_plume_is_not_a_chain():
    """The whip's beads are held a fixed link apart; the puffs are not.

    Same clock, same nozzle. The lash is a rope, so every neighbour gap is the
    link length to within a hair. The plume is a crowd: puffs are born in
    bursts at the nozzle and die at the far end, so the gaps between neighbours
    are not one number and the whole thing spans speed times life rather than a
    fixed length.
    """
    from entities import Whip
    w = Whip()
    t = FlameThrower()
    for _ in range(int(0.9 / DT)):
        w.update(DT, 400.0, 500.0)
        t.update(DT, 400.0, 500.0)
    seg = C.WHIP_LEN / C.WHIP_POINTS
    pts = [w.anchor] + list(w.points)
    gaps = [math.hypot(b[0] - a[0], b[1] - a[1])
            for a, b in zip(pts[:-1], pts[1:], strict=True)]
    assert max(gaps) - min(gaps) < 0.2 * seg, "the lash is not a chain"

    ys = sorted(p.y for p in t.puffs)
    free = [b - a for a, b in zip(ys[:-1], ys[1:], strict=True)]
    assert max(free) > 2.0 * min(free), "the plume is evenly spaced like a rope"
    assert ys[-1] - ys[0] > C.WHIP_LEN * 0.5


def test_the_plume_keeps_burning_after_the_power_runs_out():
    """The timer stops the nozzle, it does not unmake fire already in the air."""
    g = _game()
    g.flame_timer = 0.5
    for _ in range(int(0.4 / DT)):
        g.update(DT, firing=False)
    assert g.flame_active and g.flame.puffs
    away = [(p.x0, p.y0) for p in g.flame.puffs]
    g.flame_timer = 0.0
    for _ in range(int(0.2 / DT)):
        g.update(DT, firing=False)
        assert not g.flame.puffs or all(
            (p.x0, p.y0) in away or p.x0 == g.player.x for p in g.flame.puffs)
    assert not g.flame_active
    assert g.flame.puffs, "the plume vanished with the timer"
    for _ in range(int(1.2 / DT)):
        g.update(DT, firing=False)
    assert g.flame.puffs == [], "the plume never burned out"


def test_the_flame_pod_adds_a_block_and_not_a_reset():
    g = _game()
    g.flame_timer = 2.0
    g._apply_item(Item(C.ItemKind.FLAME, 0, 0), [])
    assert g.flame_timer == 2.0 + C.FLAME_TIME
    g._apply_item(Item(C.ItemKind.FLAME, 0, 0), [])
    assert g.flame_timer == C.FLAME_MAX


def test_death_puts_the_thrower_away():
    g = _game()
    g.flame_timer = C.FLAME_TIME
    for _ in range(10):
        g.update(DT, firing=False)
    g._serve_craft()
    assert not g.flame_active
    assert g.flame.puffs == []


def test_the_plume_burns_a_hull_it_touches():
    g = _game()
    g.flame_timer = C.FLAME_TIME
    for e in list(g.enemies):
        e.alive = False
    victim = _hull(C.EnemyKind.GRUNT, g.player.x, g.player.y - 120.0)
    g.enemies.append(victim)
    hp0 = victim.hp
    evs = []
    for _ in range(int(0.6 / DT)):
        evs.extend(g.update(DT, firing=False))
    hits = [e for e in evs if e["type"] == "flame_hit"]
    assert hits, "the plume never touched the hull in front of the craft"
    assert victim.hp < hp0, "the hit was reported but not applied"
    assert all(h["dmg"] <= C.FLAME_DMG for h in hits), "a puff hit above its strength"


def test_the_plume_does_not_burn_one_hull_once_per_puff():
    """Fifty puffs over one hull is one burn at a time, not fifty.

    Without the shared cooldown a flamethrower is a damage multiplier on
    anything that cannot move out of the way.
    """
    g = _game()
    g.flame_timer = C.FLAME_TIME
    for e in list(g.enemies):
        e.alive = False
    victim = _hull(C.EnemyKind.GRUNT, g.player.x, g.player.y - 100.0)
    g.enemies.append(victim)
    hp0 = victim.hp
    for _ in range(int(0.5 / DT)):
        g.update(DT, firing=False)
    assert len(g.flame.puffs) > 5, "the test needs a plume, not a spark"
    lost = hp0 - victim.hp
    expected_max = C.FLAME_DMG * (0.5 / C.FLAME_HIT_CD + 1.0)
    assert lost <= expected_max, (
        f"one hull took {lost} damage in 0.5 s from a plume; the cooldown is "
        f"not shared by the puffs (cap {expected_max:.1f})")


def test_the_fire_does_not_holster_the_guns():
    g = _game()
    g.flame_timer = C.FLAME_TIME
    evs = []
    for _ in range(8):
        evs.extend(g.update(DT, firing=True))
    assert g.flame.puffs, "the thrower is not throwing"
    assert any(e["type"] == "shoot" for e in evs), "the vulcan stopped for the fire"


def test_the_plume_is_reproducible():
    """No RNG in the fire: a seeded replay reproduces the same plume."""
    def run() -> list[float]:
        g = Game(rng=random.Random(11))
        g.new_game()
        g.start_level(0)
        g.flame_timer = C.FLAME_TIME
        for e in list(g.enemies):
            e.alive = False
        out: list[float] = []
        for step in range(120):
            g.player.x = 400.0 + 60.0 * (step % 5)
            g.update(DT, firing=False)
            out.extend(p.y for p in g.flame.puffs)
        return out

    assert run() == run()


# -------------------------------------------------------------------- art

def test_the_flame_pod_appended_itself_to_the_item_sheet():
    """New kinds append: if this moves, every shipped pod moved with it."""
    assert C.ItemKind.FLAME is list(C.ItemKind)[-1]
    assert ui.ITEM_TILE[C.ItemKind.FLAME.value] == 40
    frames, _fps, _loop = sprites.anim_spec("items", "flame")
    assert frames == [40, 41, 42, 43]
    assert sprites.tile_count("items") >= 44


def test_the_flame_pod_has_its_own_glyph_and_its_own_colour():
    base, accent, glyph = ui.ITEM_STYLE[C.ItemKind.FLAME.value]
    assert glyph == "flame"
    assert accent == C.ITEM_COLORS["flame"][1]
    assert ui.ITEM_AURA_TINTS["flame"] == accent
    # fire is warm, and the only other warm powers are the bomb's yellow and
    # the medal's pale gold: the hue has to be the one that reads as burning
    assert accent[0] > 200 and accent[1] < 180 and accent[2] < 120


def test_the_puff_sheet_ships_and_is_baked():
    meta = sprites.SPRITES["fx_flame"]
    assert meta["cell"] == (32, 32)
    frames, fps, loop = sprites.anim_spec("fx_flame", "run")
    assert frames == [0, 1, 2, 3]
    assert fps > 0 and loop
    assert sprites.sheet_path("fx_flame").exists()


def test_the_puff_art_covers_the_radius_it_hits_at():
    """The contact radius is FLAME_R at birth; the tile has to be that big.

    A puff whose art is smaller than its hitbox reads as "I was there and
    nothing happened", which is the one thing a wide weapon cannot afford.
    """
    surf = sprites.build_procedural("fx_flame")
    alpha = pygame.surfarray.array_alpha(surf)
    cw, _ch = sprites.SPRITES["fx_flame"]["cell"]
    x, y = sprites.tile_xy("fx_flame", 0)
    cx, cy = x + cw // 2, y + cw // 2
    r = int(C.FLAME_R)
    inside = [(dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
              if dx * dx + dy * dy <= r * r]
    painted = sum(1 for dx, dy in inside if alpha[cx + dx][cy + dy] > 0)
    assert painted / len(inside) > 0.8, "the puff is smaller than its hitbox"


def test_the_renderer_draws_the_plume():
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rnd = ui.Renderer(canvas, C.DEFAULT_SETTINGS)
    g = _game()
    g.flame_timer = C.FLAME_TIME
    for _ in range(int(0.5 / DT)):
        g.update(DT, firing=False)
    assert g.flame.puffs
    blank = pygame.image.tostring(canvas, "RGB")
    rnd._draw_flame(g)
    assert pygame.image.tostring(canvas, "RGB") != blank
