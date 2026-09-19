"""Unit tests for the gameplay model: game.py (no pygame required)."""

import random

import config as C
from entities import Enemy
from game import (
    SIG_BOMB,
    SIG_GAME_OVER,
    SIG_HAZARD,
    SIG_LEVEL_CLEAR,
    SIG_LIFE_LOST,
    Game,
)
from items import Item

DT = C.SIM_DT


def make_game(seed=1234, items=True):
    g = Game(rng=random.Random(seed), enable_items=items)
    g.new_game()
    return g


def types_of(events):
    return [e["type"] for e in events]


# ---------------------------------------------------------------- lifecycle
def test_new_game_initial_state():
    g = make_game()
    assert g.lives == C.START_LIVES
    assert g.score == 0
    assert g.level_index == 0
    assert g.player.weapon_level == C.WEAPON_BASE_LEVEL
    assert g.player.bomb_stock == C.BOMB_START
    assert g.enemies == [] and g.bullets == [] and g.items == []


def test_update_produces_events_and_spawns_over_time():
    g = make_game()
    seen_enemy = False
    for _ in range(int(3.0 / DT)):
        g.update(DT)
        if g.enemies:
            seen_enemy = True
    assert seen_enemy, "wave director should spawn enemies within 3s"


def test_boss_spawns_after_wave_seconds():
    g = make_game()
    g.lives = 999  # survive long enough to reach the boss wave
    spec = C.LEVELS[0]
    t = 0.0
    boss = None
    while t < spec.wave_seconds + 2.0 and boss is None:
        g.update(DT)
        t += DT
        for e in g.enemies:
            if e.kind is C.EnemyKind.BOSS:
                boss = e
    assert boss is not None
    assert boss.hp == spec.boss_hp


def test_level_clear_emits_once_and_halts_sim():
    g = make_game()
    g._spawn_boss([])
    boss = [e for e in g.enemies if e.kind is C.EnemyKind.BOSS][0]
    clears = 0
    g.player.bomb_stock = 999
    for _ in range(400):
        evs = g.update(DT, bomb=boss.alive)
        clears += sum(1 for t in types_of(evs) if t == SIG_LEVEL_CLEAR)
        if clears:
            break
    assert clears == 1, "exactly one level_clear signal"
    # model is halted after the level-clear signal
    assert g.update(DT) == []


def test_advance_level_wraps_progress():
    g = make_game()
    g.advance_level()
    assert g.level_index == 1
    g.start_level(C.FINAL_LEVEL_INDEX)
    assert g.is_final_level()
    g.advance_level()  # clamps at the final level
    assert g.level_index == C.FINAL_LEVEL_INDEX


# ---------------------------------------------------------------- firing
def test_fire_weapon_respects_cadence_and_bounds():
    g = make_game()
    evs = g.update(DT, firing=True)
    assert "shoot" in types_of(evs)
    shots = len([b for b in g.bullets if b.friendly])
    assert shots >= 1
    # immediate second step must not re-fire (fire_timer gating)
    evs2 = g.update(DT, firing=True)
    assert "shoot" not in types_of(evs2)


def test_missiles_fire_automatically_once_upgraded():
    g = make_game()
    g.player.missile_level = 2
    got = False
    for _ in range(int(2.0 / DT)):
        if "missile" in types_of(g.update(DT)):
            got = True
            break
    assert got
    assert any(b.missile for b in g.bullets if b.friendly)


def test_bullet_cap_honoured():
    g = make_game()
    g.player.weapon_level = C.WEAPON_MAX_LEVEL
    g.player.missile_level = C.MISSILE_MAX_LEVEL
    for _ in range(60 * 30):
        g.update(DT, firing=True)
        assert len(g.bullets) <= C.MAX_BULLETS + 32  # enemy fire shares the cap


# ---------------------------------------------------------------- bombs
def test_bomb_clears_bullets_and_kills_enemies():
    g = make_game()
    e = Enemy.spawn(C.EnemyKind.GRUNT, 400.0, 300.0, rng=random.Random(1))
    g.enemies.append(e)
    g._fire_enemy_bullet(100.0, 100.0, 0.0, 100.0, [])
    evs = g.update(DT, bomb=True)
    assert SIG_BOMB in types_of(evs)
    assert not any(b.alive and not b.friendly for b in g.bullets)
    assert not e.alive
    assert g.score >= C.ENEMY_SPECS[C.EnemyKind.GRUNT].score
    assert g.run_enemies_destroyed == 1


def test_bomb_requires_stock():
    g = make_game()
    g.player.bomb_stock = 0
    evs = g.update(DT, bomb=True)
    assert SIG_BOMB not in types_of(evs)


def test_bomb_boss_damage_scaled():
    g = make_game()
    g._spawn_boss([])
    boss = g.enemies[-1]
    hp0 = boss.hp
    g.update(DT, bomb=True)
    assert boss.hp == hp0 - C.BOMB_BOSS_DAMAGE


# ---------------------------------------------------------------- items
def test_apply_item_upgrade_caps():
    g = make_game()
    for _ in range(10):
        g._apply_item(Item(C.ItemKind.WEAPON, 0, 0), [])
    assert g.player.weapon_level == C.WEAPON_MAX_LEVEL
    for _ in range(10):
        g._apply_item(Item(C.ItemKind.MISSILE, 0, 0), [])
    assert g.player.missile_level == C.MISSILE_MAX_LEVEL
    for _ in range(10):
        g._apply_item(Item(C.ItemKind.BOMB, 0, 0), [])
    assert g.player.bomb_stock == C.BOMB_MAX


def test_medal_scores_without_powerup_event():
    g = make_game()
    evs = []
    g._apply_item(Item(C.ItemKind.MEDAL, 0, 0), evs)
    assert g.score == C.MEDAL_SCORE
    assert types_of(evs) == ["medal"]


def test_jammer_downgrades_and_signals_hazard():
    g = make_game()
    g.player.weapon_level = C.WEAPON_MAX_LEVEL
    evs = []
    g._apply_item(Item(C.ItemKind.JAMMER, 0, 0), evs)
    assert g.player.weapon_level == C.WEAPON_MAX_LEVEL - C.JAMMER_DROP_PENALTY
    assert SIG_HAZARD in types_of(evs)


def test_extra_life_caps_at_nine():
    g = make_game()
    g.lives = 9
    g._apply_item(Item(C.ItemKind.EXTRA_LIFE, 0, 0), [])
    assert g.lives == 9


def test_drops_follow_enable_items_toggle():
    g = make_game(items=False)
    e = Enemy.spawn(C.EnemyKind.HEAVY, 400.0, 200.0, rng=random.Random(1))
    e.drop = 1.0
    g._maybe_drop_item(e, [])
    assert g.items == []

    g2 = make_game(items=True)
    e2 = Enemy.spawn(C.EnemyKind.HEAVY, 400.0, 200.0, rng=random.Random(1))
    e2.drop = 1.0
    g2._maybe_drop_item(e2, [])
    assert len(g2.items) == 1


def test_mine_costs_life_unless_protected():
    g = make_game()
    pl = g.player
    pl.invuln = 0.0
    pl.shield = 0.0
    mine = Item(C.ItemKind.MINE, pl.x, pl.y)
    g.items.append(mine)
    evs = g.update(DT)
    assert SIG_HAZARD in types_of(evs)
    assert SIG_LIFE_LOST in types_of(evs)
    assert g.lives == C.START_LIVES - 1

    # with a shield, the same contact is harmless (collected as a dud hazard)
    g2 = make_game()
    g2.player.shield = 5.0
    g2.items.append(Item(C.ItemKind.MINE, g2.player.x, g2.player.y))
    evs2 = g2.update(DT)
    assert g2.lives == C.START_LIVES
    assert SIG_LIFE_LOST not in types_of(evs2)


# ---------------------------------------------------------------- lives
def test_life_lost_resets_craft_with_invuln():
    g = make_game()
    evs = []
    g._lose_life(evs)
    assert SIG_LIFE_LOST in types_of(evs)
    assert g.lives == C.START_LIVES - 1
    assert g.player.protected
    assert g.player.weapon_level == C.WEAPON_BASE_LEVEL  # power resets on death


def test_game_over_at_zero_lives_halts_model():
    g = make_game()
    g.lives = 1
    evs = []
    g._lose_life(evs)
    assert SIG_GAME_OVER in types_of(evs)
    assert g.lives == 0
    assert g.update(DT) == []


def test_bonus_life_awarded_once():
    g = make_game()
    g.lives = 2
    g.score = C.BONUS_LIFE_THRESHOLD
    g.update(DT)
    assert g.lives == 3
    g.score = C.BONUS_LIFE_THRESHOLD + 1000
    g.update(DT)
    assert g.lives == 3  # no second bonus


# ---------------------------------------------------------------- determinism
def _scripted_run(seed):
    g = Game(rng=random.Random(seed))
    g.new_game()
    g.lives = 99  # survive long enough for a meaningful comparison
    total_score = 0
    for i in range(int(30.0 / DT)):
        g.update(DT, move_x=1.0 if (i // 60) % 2 == 0 else -1.0,
                       firing=True)
        total_score = g.score
    return total_score, len(g.enemies), len(g.bullets)


def test_seeded_runs_are_reproducible():
    a = _scripted_run(42)
    b = _scripted_run(42)
    assert a == b
    assert a[0] > 0, "firing for 30s should score something"


def test_different_seeds_diverge():
    assert _scripted_run(1)[0] != _scripted_run(2)[0]


def test_full_game_smoke_across_all_levels():
    # bomb-every-step trivially clears the game but exercises every level's
    # wave director, boss pattern phases, and the level-advance lifecycle.
    g = Game(rng=random.Random(7))
    g.new_game()
    g.lives = 50
    cleared = 0
    for lvl in range(len(C.LEVELS)):
        assert g.level_index == lvl
        g.player.bomb_stock = 999
        for _ in range(int(240.0 / DT)):
            g.player.bomb_stock = 999  # keep the smoke run bombing throughout
            evs = g.update(DT, firing=True, bomb=True)
            if SIG_LEVEL_CLEAR in types_of(evs):
                cleared += 1
                g.advance_level()
                g.player.bomb_stock = 999
                break
        else:
            raise AssertionError(f"level {lvl} never cleared")
    assert cleared == len(C.LEVELS)
    assert g.score > 0
