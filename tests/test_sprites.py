"""Sprite sheets, animation playheads, baked art, whip + explosions.

Mirrors the terrain test philosophy: shipped PNGs must exist for every
declared sheet and must byte-match a fresh procedural bake (stale-art
detector). Model-level pieces (whip, explosion lifecycle) run headless.
"""
import math
import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

pygame.init()
pygame.display.set_mode((32, 32))

import config as C  # noqa: E402
import sprites  # noqa: E402
import ui  # noqa: E402
from entities import Enemy, Whip  # noqa: E402
from game import Game  # noqa: E402
from items import Item  # noqa: E402

# ---- manifest --------------------------------------------------------------

def test_manifest_wellformed():
    for name, meta in sprites.SPRITES.items():
        cw, ch = meta["cell"]
        assert cw > 0 and ch > 0, name
        n_first = len(next(iter(meta["anims"].values()))["frames"])
        cols = sprites.cols_for(name)
        total_tiles = cols * ((n_first + cols - 1) // cols)
        for aname, spec in meta["anims"].items():
            assert spec["frames"], f"{name}/{aname} has no frames"
            assert spec["fps"] > 0, name
            assert max(spec["frames"]) < total_tiles, name


def test_anim_playhead():
    a = sprites.Anim([0, 1, 2, 3], 10.0, loop=True)
    a.advance(0.15)                       # 1.5 frames in
    assert a.tile == 1 and not a.done
    a.advance(0.25)                       # wrap: 4.0 frames -> index 0
    assert a.tile == 0
    b = sprites.Anim([5, 6], 10.0, loop=False)
    b.advance(1.0)
    assert b.tile == 6 and b.done


def test_anim_spec_matches_manifest():
    frames, fps, loop = sprites.anim_spec("explosion_big", "boom")
    spec = sprites.SPRITES["explosion_big"]["anims"]["boom"]
    assert frames == spec["frames"] and fps == spec["fps"]
    assert loop is spec["loop"]


# ---- baked art --------------------------------------------------------------

@pytest.mark.parametrize("name", list(sprites.SPRITES))
def test_baked_sheets_shipped(name):
    assert sprites.sheet_path(name).is_file(), f"bake missing: {name}"


@pytest.mark.parametrize("name", list(sprites.SPRITES))
def test_baked_matches_procedural(name):
    """Stale-bake detector: change painters -> re-run bake_sprites.py."""
    surf = sprites.build_procedural(name)
    loaded = pygame.image.load(str(sprites.sheet_path(name)))
    assert loaded.get_size() == surf.get_size()
    fmt = "RGBA" if surf.get_flags() & pygame.SRCALPHA else "RGB"
    assert (pygame.image.tostring(loaded, fmt)
            == pygame.image.tostring(surf, fmt))


@pytest.mark.parametrize("name",
                         ["explosion_mid", "e_boss1", "shot_plasma"])
def test_procedural_deterministic(name):
    a = sprites.build_procedural(name)
    b = sprites.build_procedural(name)
    assert pygame.image.tostring(a, "RGBA") == pygame.image.tostring(b, "RGBA")


def _need_display() -> None:
    """App-state tests may have quit the display; ensure one exists."""
    pygame.display.init()
    if pygame.display.get_surface() is None:
        pygame.display.set_mode((64, 64))


def test_bank_frame_grid_roundtrip():
    """Every declared tile index must address its own in-bounds tile cell."""
    _need_display()
    bank = sprites.Bank()
    for name, meta in sprites.SPRITES.items():
        surf = bank.sheet(name)
        assert surf is not None, name
        cw, ch = meta["cell"]
        n_frames = len(meta["anims"][next(iter(meta["anims"]))]["frames"])
        for tile in range(n_frames):
            sub = bank.frame(surf, name, tile)
            assert sub.get_width() == cw and sub.get_height() == ch
            assert sub.get_offset() == sprites.tile_xy(name, tile)


def test_bank_white_silhouette_keeps_alpha():
    bank = sprites.Bank()
    surf = sprites.build_procedural("e_grunt")      # guaranteed SRCALPHA
    tile_s = bank.frame(surf, "e_grunt", 0)
    w = bank.white(surf, "e_grunt", 0)              # tile-sized silhouette
    sa = pygame.surfarray.pixels_alpha(tile_s)
    wa = pygame.surfarray.pixels_alpha(w)
    assert (sa == wa).all()                         # alpha map untouched
    px = pygame.surfarray.pixels3d(w)
    opaque = sa > 0
    assert (px[opaque] == 255).all()                # pixels turned white
    del px, opaque


# ---- per-sector bosses ------------------------------------------------------

def test_each_sector_declares_its_own_boss_sheet():
    bosses = [spec.boss for spec in C.LEVELS]
    assert len(set(bosses)) == len(bosses), "boss art must be unique per sector"
    for spec in C.LEVELS:
        assert spec.boss in sprites.SPRITES, spec.boss


def test_boss_sheets_are_wider_than_tall():
    """A boss must fill the screen width, so its cell is a wide rectangle."""
    for i in range(1, len(C.LEVELS) + 1):
        cw, ch = sprites.SPRITES[f"e_boss{i}"]["cell"]
        assert cw > ch, f"e_boss{i} cell {cw}x{ch}"
        assert cw >= C.FIELD_W * 0.2


def test_spawned_boss_carries_sector_art():
    for i, spec in enumerate(C.LEVELS):
        g = _game()
        g.start_level(i)
        g._spawn_boss([])
        boss = next(e for e in g.enemies if e.kind is C.EnemyKind.BOSS)
        assert boss.sheet == spec.boss
        assert boss.r >= C.FIELD_W * 0.05


def test_boss_frames_are_anchored_to_their_core():
    """Derived anchors must land on the art, not in the empty margin."""
    from sprites import rawkit
    for i in range(1, len(C.LEVELS) + 1):
        stem = f"e_boss{i}"
        if not rawkit.has_source(stem):
            pytest.skip("sprite sources not shipped")
        art = rawkit.load_src(stem)
        assert art is not None
        anchors = rawkit.anchors_for(stem)
        assert anchors.get("glow"), f"{stem}: no core detected"
        ax, ay = anchors["glow"][0][:2]
        ys, xs = art[..., 3].nonzero()
        x0, x1, y0, y1 = xs.min() / art.shape[1], xs.max() / art.shape[1], \
            ys.min() / art.shape[0], ys.max() / art.shape[0]
        assert x0 <= ax <= x1 and y0 <= ay <= y1, f"{stem}: glow off the hull"


# ---- whip model --------------------------------------------------------------

def _game():
    g = Game(rng=random.Random(7))
    g.new_game()
    return g


def test_whip_pickup_sets_power_and_event():
    g = _game()
    g.items.append(Item(C.ItemKind.WHIP, g.player.x, g.player.y))
    evs = g.update(1 / 60)
    assert g.whip_active
    kinds = [e for e in evs if e["type"] == "powerup"]
    assert any(k["kind"] == "whip" for k in kinds)


def test_whip_replaces_vulcan_and_expires():
    g = _game()
    g.whip_timer = 5.0
    evs = []
    for _ in range(10):
        evs.extend(g.update(C.SIM_DT * 10, firing=True))
    assert not any(b.friendly and not b.missile for b in g.bullets)
    assert not any(e["type"] == "shoot" for e in evs)
    while g.whip_timer > 0:
        g.update(C.SIM_DT * 10, firing=True)
    assert not g.whip_active
    assert g.whip.points == []
    for _ in range(3):
        g.update(C.SIM_DT * 10, firing=True)
    assert any(b.friendly and not b.missile for b in g.bullets)


def test_whip_shape_is_forward_and_bounded():
    w = Whip()
    for _ in range(120):
        w.update(1 / 60, 400.0, 500.0)
    assert len(w.points) == C.WHIP_POINTS
    ax, ay = 400.0, 500.0 - 12.0          # attach point above the cockpit
    for x, y in w.points:
        d = math.hypot(x - ax, y - ay)
        assert d <= C.WHIP_LEN + 1.0      # chord never exceeds lash length
    assert any(y < ay - C.WHIP_LEN * 0.5 for _, y in w.points)


def test_the_lash_is_long_enough_to_be_a_weapon():
    """Length is the reason to take the whip at all.

    At 210 px the lash could not reach a hostile before it reached the craft,
    so the power was a shorter gun with a nicer picture. The tip must actually
    put beads where a hostile 250 px up is sitting.
    """
    w = Whip()
    for _ in range(400):
        w.update(1 / 120, 400.0, 500.0)
    ax, ay = 400.0, 500.0 - 12.0
    far = max(math.hypot(x - ax, y - ay) for x, y in w.points)
    assert far >= 250.0, f"tip only reaches {far:.0f}px"
    assert far <= C.WHIP_LEN + 1.0


def _sway(power: float) -> list[float]:
    """Lateral offset of every bead at one aim, with a fixed wave phase.

    The wave term is identical in both samples because the clock is, so the two
    profiles differ only in how the lean is distributed along the lash.
    """
    old = C.WHIP_CURL_POWER
    C.WHIP_CURL_POWER = power
    try:
        w = Whip()
        w.t = 0.75
        w.aim = 0.85
        return [x - 400.0 for x, _y in w._shape(400.0, 500.0)]
    finally:
        C.WHIP_CURL_POWER = old


def test_the_lash_curls_instead_of_tilting():
    """A rod tilts, a whip curls: the sway must grow faster than length.

    With a linear lean the halfway bead carries half the tip's offset and the
    whole lash is a straight stick rocking on a pivot. Curl is the outer section
    doing more of the turning than the inner one, measured here as the midpoint
    holding less than half the tip's sway - and less than the same whip would
    hold with the power set to 1.0.
    """
    curl = _sway(C.WHIP_CURL_POWER)
    rod = _sway(1.0)
    mid = len(curl) // 2
    assert curl[mid] < 0.5 * curl[-1], "the lean is still linear"
    assert curl[mid] < rod[mid], "the curl power is not reaching the shape"


def test_the_whip_turns_toward_a_hostile():
    """The lash settles on the *bearing* to the hostile, not on its position.

    A whip has no reach beyond its length, so "aim" means "lean along the line
    to the target": the anchor, the handle and the target should be collinear,
    which is what atan2 of the offset says. That is a stronger claim than "the
    tip got near", and it is the claim the design makes.
    """
    w = Whip()
    ax, ay = 400.0, 500.0
    target = (180.0, 260.0)             # up and to the left
    for _ in range(180):
        w.update(1 / 60, ax, ay, target)
    bearing = math.atan2(target[0] - ax, ay - target[1])
    assert w.aim == pytest.approx(bearing, abs=0.05), "not leaning at the hostile"
    tip_x, tip_y = w.tip
    assert tip_x < ax - 40.0, "the tip is still on the wrong side of the craft"
    assert tip_y < ay - 100.0, "a thrown lash does not droop"

    # and it genuinely closed on the target rather than waving nearby
    free = Whip()
    for _ in range(180):
        free.update(1 / 60, ax, ay, None)
    d_locked = math.hypot(tip_x - target[0], tip_y - target[1])
    d_free = math.hypot(free.tip[0] - target[0], free.tip[1] - target[1])
    assert d_locked < d_free


def test_the_turn_is_a_slew_and_not_a_snap():
    """Homing that arrives in one frame is a missile wearing a rope.

    The lash may move at most WHIP_AIM_RATE * dt per update, so the swing is
    visible and dodgeable and the whip keeps its risk.
    """
    w = Whip()
    dt = 1 / 60
    before = w.aim
    w.update(dt, 400.0, 500.0, (60.0, 120.0))
    assert abs(w.aim - before) <= C.WHIP_AIM_RATE * dt + 1e-9


def test_a_hostile_below_the_craft_is_not_a_target():
    """The lash is thrown upward; folding it back through the hull is not aim."""
    w = Whip()
    for _ in range(30):
        w.update(1 / 60, 400.0, 500.0, None)
    held = w.aim
    for _ in range(10):
        w.update(1 / 60, 400.0, 500.0, (400.0, 560.0))
    assert w.aim == held


def test_with_nothing_to_chase_the_lash_sweeps():
    w = Whip()
    seen = []
    for _ in range(300):
        w.update(1 / 60, 400.0, 500.0, None)
        seen.append(w.aim)
    assert min(seen) < -0.5 and max(seen) > 0.5, "the sweep never crossed over"


def test_the_whip_is_deterministic():
    """Same clock, same targets, same curve: no RNG anywhere in the lash."""
    def run() -> list[float]:
        w = Whip()
        out: list[float] = []
        for step in range(120):
            target = (300.0 + 90.0 * (step % 3), 200.0) if step % 7 else None
            w.update(1 / 60, 400.0, 500.0, target)
            out.extend(w.tip)
        return out

    assert run() == run()


def test_the_game_chooses_the_nearest_reachable_hostile():
    g = _game()
    g.whip_timer = C.WHIP_TIME
    for e in list(g.enemies):
        e.alive = False
    near = Enemy(C.EnemyKind.GRUNT, 300.0, g.player.y - 150.0)
    far = Enemy(C.EnemyKind.GRUNT, 520.0, g.player.y - 350.0)
    g.enemies.extend([near, far])
    assert g._whip_target() == (near.x, near.y)

    near.alive = False
    assert g._whip_target() == (far.x, far.y), "a dead hostile is still a target"

    far.y = g.player.y - (C.WHIP_SEEK_RANGE + 40.0)
    assert g._whip_target() is None, "reached past the seeking range"


def test_the_game_ignores_the_hostiles_below_the_craft():
    g = _game()
    g.whip_timer = C.WHIP_TIME
    for e in list(g.enemies):
        e.alive = False
    below = Enemy(C.EnemyKind.GRUNT, 400.0, g.player.y + 80.0)
    g.enemies.append(below)
    assert g._whip_target() is None
    below.y = g.player.y - 100.0
    assert g._whip_target() == (below.x, below.y)
    below.alive = False
    assert g._whip_target() is None


def test_whip_contact_damage_with_cooldown():
    g = _game()
    g.whip_timer = C.WHIP_TIME
    g.update(C.SIM_DT, firing=True)             # build points
    e = g.enemies[0] if g.enemies else None
    from entities import Enemy
    if e is None:
        e = Enemy.spawn(C.EnemyKind.HEAVY, 400.0, 300.0, rng=g.rng)
        g.enemies.append(e)
    e.x, e.y = g.whip.points[10]                # pin onto the lash
    hp0 = e.hp
    g.update(C.SIM_DT)
    assert e.hp == hp0 - C.WHIP_DMG
    # second consecutive frame: cooldown blocks the re-hit
    e.x, e.y = g.whip.points[10]
    g.update(C.SIM_DT)
    assert e.hp == hp0 - C.WHIP_DMG
    # after the cooldown elapses the lash bites again
    for _ in range(int(C.WHIP_HIT_CD / C.SIM_DT) + 3):
        e.x, e.y = g.whip.points[10]
        g.update(C.SIM_DT)
    assert e.hp <= hp0 - 2 * C.WHIP_DMG


def test_whip_kills_emit_enemy_killed():
    g = _game()
    g.whip_timer = C.WHIP_TIME
    g.update(C.SIM_DT)
    from entities import Enemy
    e = Enemy.spawn(C.EnemyKind.GRUNT, 0.0, 0.0, rng=g.rng)
    g.enemies.append(e)
    e.x, e.y = g.whip.points[10]
    killed = False
    saw_hit = False
    for _ in range(150):
        e.x, e.y = g.whip.points[10]
        evs = g.update(C.SIM_DT)
        if any(ev["type"] == "whip_hit" for ev in evs):
            saw_hit = True
        if any(ev["type"] == "enemy_killed" for ev in evs):
            killed = True
            break
    assert saw_hit, "whip contact must emit a whip_hit event"
    assert killed


def test_death_clears_whip():
    g = _game()
    g.whip_timer = C.WHIP_TIME
    g._serve_craft()
    assert g.whip_timer == 0.0
    assert not g.whip_active


def test_item_weights_include_whip():
    from items import build_weights
    kinds, weights = build_weights()
    assert C.ItemKind.WHIP in kinds
    assert all(w > 0 for w in weights)


# ---- explosion effects --------------------------------------------------------

def test_explosion_lifecycle():
    fx = ui.Effects(random.Random(1))
    fx.add_explosion(100.0, 100.0, "explosion_small")
    assert len(fx.explosions) == 1
    ex = fx.explosions[0]
    ex0 = ex.tile()
    ex.t = 0.3
    assert ex.tile() != ex0                    # frames advance
    for _ in range(60):
        fx.update(0.05)
    assert fx.explosions == []                 # finished & pruned


def test_explosion_cap():
    fx = ui.Effects(random.Random(1))
    for i in range(ui.MAX_EXPLOSIONS + 8):
        fx.add_explosion(float(i), 50.0, "explosion_small")
    assert len(fx.explosions) == ui.MAX_EXPLOSIONS


def test_explosion_tier_covers_all_enemies():
    for kind in C.EnemyKind:
        assert kind.value in ui.EXPLOSION_TIER


def test_effects_reset_clears_explosions():
    fx = ui.Effects(random.Random(1))
    fx.add_explosion(1.0, 2.0, "explosion_big")
    fx.reset()
    assert fx.explosions == []


# ---- renderer smoke (baked sheets load + draw) --------------------------------

def test_renderer_draws_sprites_and_effects():
    _need_display()
    g = _game()
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rnd = ui.Renderer(canvas, C.DEFAULT_SETTINGS)
    g.whip_timer = C.WHIP_TIME
    for _ in range(30):
        g.update(C.SIM_DT, firing=True)
    fx = ui.Effects(random.Random(2))
    fx.add_explosion(400.0, 200.0, "explosion_mid")
    rnd.draw_field(g)
    rnd.draw_particles(fx)
    # sprite paths actually resolved (baked art shipped)
    assert rnd._bullet_frame("shot_vulcan") is not None
    assert rnd._bank_of().sheet("explosion_mid") is not None


def test_renderer_plasma_switch_at_high_weapon():
    _need_display()
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rnd = ui.Renderer(canvas, C.DEFAULT_SETTINGS)
    g = _game()
    g.player.weapon_level = C.WEAPON_MAX_LEVEL
    rnd.draw_field(g)
    pl = pygame.image.tostring(rnd._bullet_frame("shot_plasma"), "RGBA")
    vu = pygame.image.tostring(rnd._bullet_frame("shot_vulcan"), "RGBA")
    assert pl != vu                              # genuinely different art


# ---- player craft sheet ------------------------------------------------------

def test_p_ship_every_bank_frame_painted():
    """Rotation mirage: no bank tile may come out blank."""
    surf = sprites.build_procedural("p_ship")
    arr = pygame.surfarray.array_alpha(surf)
    cw, ch = sprites.SPRITES["p_ship"]["cell"]
    cols = surf.get_width() // cw
    for t in range(10):
        x, y = (t % cols) * cw, (t // cols) * ch
        cov = (arr[x:x + cw, y:y + ch] > 0).mean()
        assert cov > 0.05, f"tile {t} nearly empty ({cov:.1%})"


def test_p_ship_bank_anims_present():
    for anim in ("idle", "bank_soft", "bank_hard",
                 "bank_soft_l", "bank_hard_l"):
        frames, fps, loop = sprites.anim_spec("p_ship", anim)
        assert len(frames) == 2 and fps > 0 and loop


def test_player_facing_maps_velocity_to_bank():
    """Renderer picks lean from smoothed horizontal velocity."""
    _need_display()
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rnd = ui.Renderer(canvas, C.DEFAULT_SETTINGS)

    class FakePlayer:
        x = 400.0

    pl = FakePlayer()
    rnd._p_at = 0.0
    assert rnd._player_bank_anim(pl) == "idle"        # first frame, no hist
    # sustained hard right: velocity climbs past PLAYER_BANK_HARD
    anim = "idle"
    for _ in range(24):
        rnd._p_at += 1 / 60
        pl.x += 8.0
        anim = rnd._player_bank_anim(pl)
    assert anim == "bank_hard"
    # sustained hard left mirrors it
    for _ in range(48):
        rnd._p_at += 1 / 60
        pl.x -= 8.0
        anim = rnd._player_bank_anim(pl)
    assert anim == "bank_hard_l"
    # settle: velocity bleeds off back to idle
    for _ in range(48):
        rnd._p_at += 1 / 60
        anim = rnd._player_bank_anim(pl)
    assert anim == "idle"


def test_title_scene_attract_parade():
    """Title scene draws real hero + enemy sprites and keeps updating."""
    _need_display()
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rnd = ui.Renderer(canvas, C.DEFAULT_SETTINGS)
    rnd.draw_title_scene(0.0)
    mid = pygame.image.tostring(canvas, "RGB")
    rnd.draw_title_scene(1.37)
    assert pygame.image.tostring(canvas, "RGB") != mid   # scene animates
    # high-contrast falls back to the vector variant without error
    import dataclasses
    hc = dataclasses.replace(C.DEFAULT_SETTINGS, high_contrast=True)
    rnd2 = ui.Renderer(canvas, hc)
    rnd2.draw_title_scene(0.5)


def test_player_sprite_display_scaled():
    """Hero art is blitted at PLAYER_SPRITE_SCALE (and cached)."""
    _need_display()
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rnd = ui.Renderer(canvas, C.DEFAULT_SETTINGS)
    f = rnd._p_ship_frame(0)
    cw, ch = sprites.SPRITES["p_ship"]["cell"]
    assert f.get_size() == (round(cw * C.PLAYER_SPRITE_SCALE),
                            round(ch * C.PLAYER_SPRITE_SCALE))
    assert rnd._p_ship_frame(0) is f            # cached, not re-scaled


# ---- item pods + shared orbiting marker -------------------------------------

ITEM_FRAMES = 4


def test_item_sheet_covers_every_kind():
    kinds = list(C.ItemKind)
    for kind in kinds:
        key = str(getattr(kind, "value", kind))
        frames, fps, loop = sprites.anim_spec(ui.ITEM_SHEET, key)
        assert len(frames) == ITEM_FRAMES, key
        assert fps > 0 and loop, key
        assert ui.ITEM_TILE[kind] == frames[0], key     # base tile == frame 0
    assert sprites.tile_count(ui.ITEM_SHEET) == len(kinds) * ITEM_FRAMES


def test_item_pods_cover_their_hitbox():
    """Pickup art must not be smaller than the circle that collects it.

    The pod is what the player aims at; an icon that shrinks inside the
    collision radius reads as "I was there and nothing happened".
    """
    surf = sprites.build_procedural(ui.ITEM_SHEET)
    alpha = pygame.surfarray.array_alpha(surf)
    cw, ch = sprites.SPRITES[ui.ITEM_SHEET]["cell"]
    r = int(C.ITEM_SIZE / 2)
    for kind, base in ui.ITEM_TILE.items():
        x, y = sprites.tile_xy(ui.ITEM_SHEET, base)
        cx, cy = x + cw // 2, y + ch // 2
        inside = [(dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                  if dx * dx + dy * dy <= r * r]
        painted = sum(1 for dx, dy in inside if alpha[cx + dx][cy + dy] > 0)
        assert painted / len(inside) > 0.85, f"{kind}: pod too small"


def test_item_frames_actually_animate():
    bank = sprites.Bank()
    surf = sprites.build_procedural(ui.ITEM_SHEET)
    for kind, base in ui.ITEM_TILE.items():
        tiles = {pygame.image.tostring(
                     bank.frame(surf, ui.ITEM_SHEET, base + i), "RGBA")
                 for i in range(ITEM_FRAMES)}
        assert len(tiles) == ITEM_FRAMES, f"{kind}: frames identical"


def test_item_aura_orbits_and_is_hollow():
    frames, fps, loop = sprites.anim_spec(ui.ITEM_AURA_SHEET, "orbit")
    assert len(frames) >= 6 and fps > 0 and loop
    bank = sprites.Bank()
    surf = sprites.build_procedural(ui.ITEM_AURA_SHEET)
    alpha = pygame.surfarray.array_alpha(surf)
    cw, ch = sprites.SPRITES[ui.ITEM_AURA_SHEET]["cell"]
    x, y = sprites.tile_xy(ui.ITEM_AURA_SHEET, frames[0])
    assert alpha[x + cw // 2][y + ch // 2] == 0         # pod shows through
    assert alpha[x + cw // 2][y + 2] > 0                # ring reaches the rim
    a = pygame.image.tostring(bank.frame(surf, ui.ITEM_AURA_SHEET, frames[0]),
                              "RGBA")
    b = pygame.image.tostring(bank.frame(surf, ui.ITEM_AURA_SHEET, frames[3]),
                              "RGBA")
    assert a != b                                       # the blades travel


def test_item_palette_is_single_sourced():
    """Pod accent, aura tint and vector colour all come from ITEM_COLORS."""
    for kind in C.ItemKind:
        accent = C.ITEM_COLORS[kind][1]
        key = str(getattr(kind, "value", kind))
        assert ui.ITEM_STYLE[kind][1] == accent, key
        assert ui.ITEM_AURA_TINTS[key] == accent, key
    assert len({ui.ITEM_AURA_TINTS[k] for k in ui.ITEM_AURA_TINTS}) \
        == len(C.ItemKind)                              # no two share a hue


def test_bank_tint_recolours_keeps_alpha_and_caches():
    bank = sprites.Bank()
    plain = bank.sheet(ui.ITEM_AURA_SHEET)
    tint = bank.tinted(ui.ITEM_AURA_SHEET, (255, 0, 0))
    assert tint is not None and tint.get_size() == plain.get_size()
    assert tint is bank.tinted(ui.ITEM_AURA_SHEET, (255, 0, 0))
    assert bank.tinted("no_such_sheet", (255, 0, 0)) is None
    a0 = pygame.surfarray.pixels_alpha(plain)
    a1 = pygame.surfarray.pixels_alpha(tint)
    assert (a0 == a1).all()                             # silhouette untouched
    px = pygame.surfarray.pixels3d(tint)
    # The marker is translucent by design (peak alpha well under 255), so the
    # test samples its blades rather than assuming a solid sprite.
    hot = px[a0 > 120]
    assert hot.size and (hot[:, 0] > 0).any() and (hot[:, 1] == 0).all()


class _NoArt:
    """A bank with no sheets: the stripped-checkout / accessibility path."""

    def sheet(self, name):
        return None

    def tinted(self, sheet, colour):
        return None

    def frame(self, surf, name, tile):
        return None


def test_renderer_item_art_paints_and_falls_back():
    _need_display()
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rnd = ui.Renderer(canvas, C.DEFAULT_SETTINGS)
    rnd._scroll = 2.0
    it = Item(C.ItemKind.MEDAL, 400.0, 300.0)
    blank = pygame.image.tostring(canvas, "RGB")
    assert rnd._draw_item_art("medal", it.phase, it.x, it.y) is True
    assert pygame.image.tostring(canvas, "RGB") != blank
    # no art at all -> the glyph variant still has to identify the pickup
    rnd._bank = _NoArt()
    assert rnd._draw_item_art("medal", 0.0, 400.0, 300.0) is False
    canvas.fill((0, 0, 0))
    rnd._draw_item(it)                                  # dispatcher, no art
    assert pygame.image.tostring(canvas, "RGB") != blank


def test_renderer_high_contrast_uses_vectors():
    import dataclasses
    _need_display()
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    settings = dataclasses.replace(C.DEFAULT_SETTINGS, high_contrast=True)
    rnd = ui.Renderer(canvas, settings)
    rnd._bank = _NoArt()          # vectors must not need a bank at all
    for kind in C.ItemKind:
        rnd._draw_item(Item(kind, 200.0, 260.0))
    assert pygame.image.tostring(canvas, "RGB") != pygame.image.tostring(
        pygame.Surface((C.LOGICAL_W, C.LOGICAL_H)), "RGB")
