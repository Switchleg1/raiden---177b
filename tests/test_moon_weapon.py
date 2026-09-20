"""The half-moon blade: a third power track, and a bullet that does not stop.

Two ideas live here and each is worth its own kind of test.

The first is the *track*. The crescents level up on their own counter, so a run
can specialise in the fan without touching vulcan power or missile level, and a
death takes the track back to nothing like everything else does.

The second is *pierce*, which is the only place a bullet survives its own hit.
The interesting failure is the opposite one - a blade that cuts the same hull
once per frame and eats a boss in four frames - so the tests below pin both
halves: everything else on the line still gets hit, and the thing already cut
does not get hit again. Damage numbers are checked, not vibes.
"""

import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest  # noqa: E402

pygame.init()

import config as C  # noqa: E402
import sprites  # noqa: E402
import ui  # noqa: E402
from entities import Enemy  # noqa: E402
from entities.bullet import Bullet  # noqa: E402
from game import Game  # noqa: E402
from items import Item, roll_item  # noqa: E402

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


def _hull(kind: C.EnemyKind, x: float, y: float, hp: int = 99) -> Enemy:
    """A stationary, hard-to-kill target: these tests count damage, not deaths."""
    e = Enemy(kind, x, y)
    e.hp = hp
    e.max_hp = max(hp, e.max_hp)
    e.vy = 0.0
    e.vx = 0.0
    return e


# --------------------------------------------------------------- the track

def test_a_moon_pod_raises_its_own_track_only():
    g = _game()
    pl = g.player
    before = (pl.weapon_level, pl.missile_level, pl.bomb_stock)
    g._apply_item(Item(C.ItemKind.MOON, 0.0, 0.0), [])
    assert pl.moon_level == C.MOON_BASE_LEVEL + 1
    assert (pl.weapon_level, pl.missile_level, pl.bomb_stock) == before


def test_the_moon_track_caps_like_the_others():
    g = _game()
    pl = g.player
    for _ in range(C.MOON_MAX_LEVEL + 4):
        g._apply_item(Item(C.ItemKind.MOON, 0.0, 0.0), [])
    assert pl.moon_level == C.MOON_MAX_LEVEL


def test_a_moon_pod_is_beneficial():
    assert C.ItemKind.MOON in C.BENEFICIAL
    assert C.ItemKind.MOON not in C.HAZARDS


def test_moon_pods_really_drop():
    rng = random.Random(1971)
    seen = {roll_item(rng) for _ in range(4000)}
    assert C.ItemKind.MOON in seen


def test_a_fresh_craft_has_no_blades_and_dying_takes_them_back():
    g = _game()
    assert g.player.moon_level == 0
    g.player.moon_level = 3
    g.player.moon_timer = 1.0
    g.player.full_restore()
    assert g.player.moon_level == C.MOON_BASE_LEVEL
    assert g.player.moon_timer == 0.0


# ---------------------------------------------------------------- the volley

def test_the_volley_grows_with_the_track():
    g = _game()
    for level in range(1, C.MOON_MAX_LEVEL + 1):
        g.bullets.clear()
        g.player.moon_level = level
        evs: list[dict] = []
        g._fire_moons(evs)
        blades = [b for b in g.bullets if b.pierce]
        assert len(blades) == C.MOON_STREAMS[level]
        assert all(b.friendly for b in blades)
        assert all(b.dmg == C.MOON_DMG for b in blades)
        assert {"type": "moon"} in evs


def test_level_one_throws_blades_because_one_weak_blade_is_not_a_weapon():
    assert C.MOON_STREAMS[1] >= 2


def test_the_fan_is_centred_on_the_craft():
    g = _game()
    g.player.moon_level = C.MOON_MAX_LEVEL
    g._fire_moons([])
    xs = sorted(b.x for b in g.bullets if b.pierce)
    # symmetric about the ship, and the middle blade flies straight up
    assert xs[len(xs) // 2] == pytest.approx(g.player.x)
    assert (xs[0] - g.player.x) == pytest.approx(-(xs[-1] - g.player.x))


def test_blades_fire_on_their_own_clock_without_being_told_to():
    """Automatic, at the missile's cadence - not tied to the vulcan trigger."""
    g = _game()
    pl = g.player
    pl.moon_level = 2
    pl.moon_timer = 0.0
    volleys = 0
    for _ in range(int(2.0 / DT)):
        volleys += sum(1 for e in g.update(DT) if e.get("type") == "moon")
    # ~0.62 s between volleys, so two seconds is about three of them: more than
    # one means automatic, and fewer than twenty means it is not a machine gun.
    assert 2 <= volleys <= 6
    assert pl.moon_timer > 0.0, "the blade clock should have reloaded"
    assert any(b.pierce for b in g.bullets)


def test_a_craft_with_no_blades_throws_nothing():
    g = _game()
    g.player.moon_level = 0
    for _ in range(int(2.0 / DT)):
        g.update(DT)
    assert not [b for b in g.bullets if b.pierce]


def test_missiles_and_shells_do_not_pierce():
    g = _game()
    g.player.missile_level = C.MISSILE_MAX_LEVEL
    for _ in range(int(1.5 / DT)):
        g.update(DT)
    assert g.bullets, "expected the craft to be shooting"
    assert not [b for b in g.bullets if b.pierce], \
        "pierce belongs to the crescent alone"


def test_a_blade_is_not_a_bigger_gun_in_disguise():
    """Pierce is the whole advantage, so nothing else may be better too.

    Same damage per hit as a shell or less, slower than every shell, and a
    trigger slower than the vulcan. If a future tune pushes any of these the
    other way the weapon stops being a trade and becomes the only gun worth
    picking up, which is the moment a power system dies.
    """
    assert C.MOON_DMG <= C.PLAYER_BULLET_DMG
    assert C.MOON_SPEED < C.PLAYER_BULLET_SPEED
    assert C.MOON_INTERVAL > C.WEAPON_FIRE_INTERVAL


# ------------------------------------------------------------------- pierce

def test_a_blade_cuts_every_hull_on_its_line():
    """One blade, one column, one hit each: thrown through the whole file.

    The column is walked, not teleported, because that is the behaviour under
    test: the blade overlaps a hull for several frames and must still charge for
    it once, then carry on to the next hull behind it.
    """
    g = _game()
    column = [_hull(C.EnemyKind.GRUNT, 400.0, 200.0 + i * 24.0)
              for i in range(4)]
    g.enemies.extend(column)
    blade = Bullet(400.0, 300.0, 0.0, -C.MOON_SPEED, C.MOON_R, C.MOON_DMG,
                   friendly=True, pierce=True)
    g.bullets.append(blade)
    for _ in range(40):                 # ~0.33 s of flight, up through the file
        blade.y += blade.vy * DT
        if blade.y < 120.0:
            break
        g._collide([])
    for e in column:
        assert e.hp == e.max_hp - C.MOON_DMG,             "each hull took the blade exactly once"
    assert blade.alive, "a piercing shot is not spent by what it goes through"


def test_a_shell_is_spent_by_the_first_hull_it_touches():
    g = _game()
    front = _hull(C.EnemyKind.GRUNT, 400.0, 200.0)
    behind = _hull(C.EnemyKind.GRUNT, 400.0, 214.0)
    g.enemies.extend([front, behind])
    shell = Bullet(400.0, 200.0, 0.0, 0.0, C.PLAYER_BULLET_R,
                   C.PLAYER_BULLET_DMG, friendly=True)
    g.bullets.append(shell)
    g._collide([])
    assert not shell.alive
    assert front.hp == front.max_hp - C.PLAYER_BULLET_DMG
    assert behind.hp == behind.max_hp, "a shell stops; that is the whole trade"


def test_a_blade_does_not_cut_the_same_hull_twice():
    """The failure this exists to prevent: contact damage once per frame.

    A blade that lingers on a hull for ten frames while a shell dies in one hit
    would deal ten times the damage, so pierce without a memory is a boss delete
    button. Ten frames of contact must still be exactly one hit.
    """
    g = _game()
    target = _hull(C.EnemyKind.HEAVY, 400.0, 200.0, hp=999)
    g.enemies.append(target)
    blade = Bullet(400.0, 200.0, 0.0, 0.0, C.MOON_R, C.MOON_DMG,
                   friendly=True, pierce=True)
    g.bullets.append(blade)
    for _ in range(10):
        g._collide([])
    assert target.hp == target.max_hp - C.MOON_DMG


def test_the_memory_is_identity_not_a_number():
    """Cut hulls are remembered by object, not by ``id()``.

    The deaths a blade causes free the very id it would later reuse, and a new
    grunt allocated at a dead grunt's address would be cut nothing. Holding the
    object is the fix, so the test holds the object too.
    """
    g = _game()
    first = _hull(C.EnemyKind.GRUNT, 400.0, 200.0)
    g.enemies.append(first)
    blade = Bullet(400.0, 200.0, 0.0, 0.0, C.MOON_R, C.MOON_DMG,
                   friendly=True, pierce=True)
    g.bullets.append(blade)
    g._collide([])
    assert blade.cut is not None and first in blade.cut
    stranger = _hull(C.EnemyKind.GRUNT, 400.0, 200.0)
    assert not blade.has_cut(stranger)


def test_pierce_memory_is_not_allocated_for_ordinary_shots():
    shell = Bullet(0.0, 0.0, 0.0, -100.0, C.PLAYER_BULLET_R,
                   C.PLAYER_BULLET_DMG, friendly=True)
    assert shell.cut is None
    assert not shell.pierce
    assert not shell.has_cut(object())


def test_a_blade_cuts_a_boss_once_and_keeps_flying():
    g = _game()
    boss = _hull(C.EnemyKind.BOSS, 400.0, 200.0, hp=999)
    g.enemies.append(boss)
    blade = Bullet(400.0, 200.0, 0.0, 0.0, C.MOON_R, C.MOON_DMG,
                   friendly=True, pierce=True)
    g.bullets.append(blade)
    for _ in range(6):
        g._collide([])
    assert boss.hp == boss.max_hp - C.MOON_DMG
    assert blade.alive


def test_a_blade_that_kills_does_not_swallow_the_rest_of_the_line():
    g = _game()
    front = _hull(C.EnemyKind.GRUNT, 400.0, 200.0, hp=1)
    behind = _hull(C.EnemyKind.GRUNT, 400.0, 208.0, hp=1)
    g.enemies.extend([front, behind])
    blade = Bullet(400.0, 200.0, 0.0, 0.0, C.MOON_R, C.MOON_DMG,
                   friendly=True, pierce=True)
    g.bullets.append(blade)
    evs: list[dict] = []
    g._collide(evs)
    assert not front.alive and not behind.alive
    kills = [e for e in evs if e.get("type") == "enemy_killed"]
    assert len(kills) == 2


# --------------------------------------------------------------- the art

def test_the_blade_has_its_own_sheet_and_frames():
    meta = sprites.SPRITES["shot_moon"]
    assert meta["cell"] == (26, 26)
    frames, _fps, loop = sprites.anim_spec("shot_moon", "run")
    assert frames == [0, 1, 2, 3]
    assert loop
    assert sprites.sheet_path("shot_moon").exists()


def test_the_blade_pod_appended_itself_to_the_item_sheet():
    """New kinds append. If this moves, every shipped pod moved with it."""
    assert C.ItemKind.MOON is list(C.ItemKind)[-1]
    assert ui.ITEM_TILE[C.ItemKind.MOON.value] == 36
    frames, _fps, _loop = sprites.anim_spec("items", "moon")
    assert frames == [36, 37, 38, 39]
    assert sprites.tile_count("items") >= 40


def test_the_blade_pod_has_its_own_glyph_and_its_own_colour():
    base, accent, glyph = ui.ITEM_STYLE[C.ItemKind.MOON.value]
    assert glyph == "moon"
    assert accent != base
    glyphs = [ui.ITEM_STYLE[k.value][2] for k in C.ItemKind]
    assert len(set(glyphs)) == len(glyphs), "one shape per kind: the pod is read"


def test_the_renderer_picks_the_crescent_for_a_piercing_shot():
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rend = ui.Renderer(canvas, C.Settings())
    real = rend._bullet_frame
    seen: list[str] = []

    def spy(sheet: str):
        seen.append(sheet)
        return real(sheet)

    rend._bullet_frame = spy  # type: ignore[method-assign]
    blade = Bullet(300.0, 300.0, 0.0, -C.MOON_SPEED, C.MOON_R, C.MOON_DMG,
                   friendly=True, pierce=True)
    rend._draw_bullet(blade, rend.palette)
    assert seen[0] == "shot_moon"


def test_the_crescent_survives_the_high_contrast_pen():
    """With no art, the fallback still has to draw a crescent.

    A disc would be a lie about the hitbox shape and about what the weapon is,
    so the test checks the geometry that matters: the middle of a crescent is
    empty and its belly is not.
    """
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rend = ui.Renderer(canvas, C.Settings(high_contrast=True))
    rend._bullet_frame = lambda sheet: None  # type: ignore[assignment]
    bx, by = 400.0, 300.0
    blade = Bullet(bx, by, 0.0, -C.MOON_SPEED, C.MOON_R, C.MOON_DMG,
                   friendly=True, pierce=True)
    rend._draw_bullet(blade, rend.palette)
    r = max(4, int(C.MOON_R))
    centre = canvas.get_at((int(bx), int(by) - 1))[:3]
    belly = canvas.get_at((int(bx), int(by) + r - 1))[:3]
    black = (0, 0, 0)
    assert belly != black, "the cut edge should be painted"
    assert sum(centre) < sum(belly), "a crescent is hollow, not a blob"


def test_every_power_track_gets_the_same_readout():
    """Three tracks, one shape: glyph, label, pips.

    The HUD showed the gun as pips, the missiles as a bare number and the blades
    as an icon-plus-number, so the one track a player had just discovered looked
    like the only one that existed. The layout is now a single function over
    POWER_TRACKS, and this is what it promises: all three, in order, each with a
    glyph before its label and pips after it.
    """
    canvas, readouts = _hud({})
    assert [ro["kind"] for ro in readouts] == ["vulcan", "rocket", "moon"]
    for ro in readouts:
        assert ro["glyph_x"] < ro["label_x"] < ro["pip_x"]
        assert ro["max"] >= 1
        assert ro["label"], "a glyph alone is colour-only reasoning by another name"
    # A fourth track would have to be added to POWER_TRACKS to render at all.
    assert len(readouts) == len(ui.Renderer.POWER_TRACKS)
    assert canvas is not None


def test_the_readouts_fit_the_hud_line_without_touching_each_other():
    """Boxes, not pixels: neighbours must not overlap, or cover the bombs."""
    _canvas, readouts = _hud({})
    # A tail-shift is deliberately one shorter: pairs, not siblings.
    for first, second in zip(readouts, readouts[1:], strict=False):
        assert first["box"].right <= second["box"].left, (
            f'{first["kind"]} covers {second["kind"]}')
    bomb_left = (C.LOGICAL_W - C.FIELD_LEFT - C.BOMB_MAX * 16 - 30)
    assert readouts[-1]["box"].right <= bomb_left, "the strip reaches the bombs"
    for ro in readouts:
        assert ro["box"].top >= 26 and ro["box"].bottom <= 48, (
            f'{ro["kind"]} sits outside the HUD line')


def test_raising_a_track_changes_its_own_readout_and_no_other():
    """The pips are per track: a blade must not brighten the gun."""
    for kind, _label, _slot, cap in ui.Renderer.POWER_TRACKS:
        plain, boxes = _hud({})
        raised, _ = _hud({kind: cap})
        box = next(ro["box"] for ro in boxes if ro["kind"] == kind)
        assert _bytes(plain.subsurface(box)) != _bytes(raised.subsurface(box)), (
            f'{kind} never redraws for its level')
        for ro in boxes:
            if ro["kind"] == kind:
                continue
            other = ro["box"]
            assert _bytes(plain.subsurface(other)) == _bytes(
                raised.subsurface(other)), f'{kind} spilled into {ro["kind"]}'


# ----------------------------------------------------------------- helpers

def _bytes(surf: pygame.Surface) -> bytes:
    """Pixel bytes of a crop, for "did this region change at all" checks."""
    return pygame.image.tostring(surf, "RGBA")


def _hud(levels: dict[str, int]) -> tuple[pygame.Surface, list[dict]]:
    """The HUD with power tracks set by kind, plus the layout it was drawn on.

    The layout comes back because it is the contract under test: the boxes are
    computed by the renderer, so the assertions are about its own geometry
    rather than about coordinates the test invented.
    """
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rend = ui.Renderer(canvas, C.Settings())
    game = _game()
    for kind, _label, slot, _cap in ui.Renderer.POWER_TRACKS:
        if kind in levels:
            setattr(game.player, slot, levels[kind])
    rend.draw_hud(game, 3.0)
    return canvas, rend.power_readouts(game)
