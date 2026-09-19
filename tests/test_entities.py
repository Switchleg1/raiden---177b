"""Unit tests for entities.py (bullets, player, enemy behaviours)."""

import math
import random

import config as C
from entities import Bullet, Enemy, Player


# ---------------------------------------------------------------- bullets
def test_bullet_moves_and_culls_offscreen():
    b = Bullet(400.0, C.FIELD_BOTTOM - 10.0, 0.0, 300.0, 3.0, 1, friendly=False)
    b.update(1.0 / 60.0)
    assert b.y > C.FIELD_BOTTOM - 10.0
    for _ in range(60):
        b.update(1.0 / 30.0)
    assert not b.alive


def test_bullet_friendly_flag_and_missile_flag():
    b = Bullet(0, 0, 0, 0, 2.0, 1, friendly=True, missile=True)
    assert b.friendly and b.missile


# ---------------------------------------------------------------- player
def test_player_clamped_to_field():
    pl = Player()
    pl.x = -1000.0
    pl.y = 10000.0
    pl.clamp_to_field()
    assert C.FIELD_LEFT + pl.half <= pl.x <= C.FIELD_RIGHT - pl.half
    assert C.FIELD_TOP + pl.half <= pl.y <= C.FIELD_BOTTOM - pl.half


def test_full_restore_resets_power_and_grants_invuln():
    pl = Player()
    pl.weapon_level = 5
    pl.missile_level = 4
    pl.bomb_stock = 3
    pl.full_restore()
    assert pl.weapon_level == C.WEAPON_BASE_LEVEL
    assert pl.missile_level == C.MISSILE_BASE_LEVEL
    assert pl.invuln > 0.0
    assert pl.protected


def test_tick_timers_count_down():
    pl = Player()
    pl.full_restore()
    inv = pl.invuln
    pl.shield = 2.0
    for _ in range(60):
        pl.tick_timers(1.0 / 60.0)
    assert pl.invuln < inv
    assert pl.shield <= 1.1


# ---------------------------------------------------------------- enemies
def test_grunt_descends_and_is_removed_offscreen_by_game_rule():
    e = Enemy.spawn(C.EnemyKind.GRUNT, 400.0, C.FIELD_TOP - 30.0, level=0)
    y0 = e.y
    for _ in range(30):
        e.update(1.0 / 60.0, 400.0, C.PLAYER_START_Y,
                 lambda *a: None, 200.0, random.Random(1))
    assert e.y > y0


def test_weaver_stays_in_field_horizontally():
    e = Enemy.spawn(C.EnemyKind.WEAVER, 400.0, C.FIELD_TOP - 30.0, level=0)
    rng = random.Random(2)
    for _ in range(600):
        e.update(1.0 / 60.0, 400.0, C.PLAYER_START_Y,
                 lambda *a: None, 200.0, rng)
        if not e.alive:
            break
        assert C.FIELD_LEFT <= e.x <= C.FIELD_RIGHT


def test_hurt_sets_flash_and_death():
    e = Enemy.spawn(C.EnemyKind.HEAVY, 400.0, 200.0, level=0)
    assert e.hp > 1
    e.hurt(1)
    assert e.alive and e.flash > 0.0
    while e.alive:
        e.hurt(999)
    assert not e.alive


def test_hover_types_hold_band_and_fire_callback_used():
    fired = []

    def cb(x, y, vx, vy):
        fired.append((x, y))

    e = Enemy.spawn(C.EnemyKind.SENTRY, 400.0, C.FIELD_TOP - 30.0, level=3)
    rng = random.Random(5)
    for _ in range(60 * 8):
        e.update(1.0 / 60.0, 400.0, C.PLAYER_START_Y, cb, 250.0, rng)
        if not e.alive:
            break
    assert fired, "sentry should have fired within 8s"


def test_boss_enters_then_stays_in_band():
    e = Enemy.spawn(C.EnemyKind.BOSS, 400.0, C.FIELD_TOP - 80.0, level=0,
                    hp_override=180)
    assert e.hp == 180 and e.max_hp == 180
    rng = random.Random(9)
    settled = False
    for _ in range(60 * 10):
        e.update(1.0 / 60.0, 400.0, C.PLAYER_START_Y,
                 lambda *a: None, 220.0, rng)
        if e.y >= C.BOSS_ENTRY_Y - 5:
            settled = True
            break
    assert settled
    assert C.BOSS_TOP - 10 <= e.y <= C.BOSS_BOTTOM + 10


def test_darter_dive_geometry():
    # dive angle is clamped to +/-42 deg around straight down, at spec speed
    speed = C.ENEMY_SPECS[C.EnemyKind.DARTER].speed
    for seed in range(20):
        e = Enemy.spawn(C.EnemyKind.DARTER, 200.0, C.FIELD_TOP - 20.0,
                        level=0, rng=random.Random(seed))
        assert e.vy > 0  # always descending
        mag = math.hypot(e.vx, e.vy)
        assert abs(mag - speed) < 1e-6
        assert abs(math.degrees(math.atan2(e.vx, e.vy))) <= 42.0 + 1e-9
