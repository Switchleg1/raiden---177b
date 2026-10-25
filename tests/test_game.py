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
from game.items import Item

DT = C.SIM_DT


def make_game(seed=1234, items=True):
    g = Game(rng=random.Random(seed), enable_items=items)
    g.new_game()
    return g


def types_of(events):
    return [e["type"] for e in events]


# ------------------------------------------------------- ground-planned spawns
def test_release_puts_the_group_at_the_column_the_ground_chose():
    """The whole point of planning a fight against the land: the column is not
    drawn from a hat any more, it is where the rooftop or the ridge is."""
    g = make_game()
    made = g.release("sentry", 400.0, 1, "single")
    assert made == 1
    e = g.enemies[-1]
    assert e.kind is C.EnemyKind.SENTRY
    assert abs(e.x - 400.0) < 1.0
    assert e.y < C.FIELD_TOP, "a spawn must enter above the field, not inside it"


def test_release_centres_a_group_on_its_column_rather_than_starting_one():
    g = make_game()
    g.release("grunt", 400.0, 3, "line")
    xs = sorted(e.x for e in g.enemies)
    assert len(xs) == 3
    assert abs(sum(xs) / 3 - 400.0) < 1.0, "the group drifted off its site"
    assert xs[0] < xs[1] < xs[2]


def test_release_cannot_put_a_group_under_the_side_wall():
    g = make_game()
    g.release("grunt", 0.0, 5, "v")
    for e in g.enemies:
        assert C.FIELD_LEFT <= e.x <= C.FIELD_RIGHT


def test_a_v_trails_its_tip_behind():
    g = make_game()
    g.release("weaver", 400.0, 5, "v")
    ys = [e.y for e in g.enemies]
    assert max(ys) == C.FIELD_TOP - 30.0, "the tip leads"
    assert min(ys) <= C.FIELD_TOP - 80.0, "the wings do not trail"


def test_ground_spawns_stop_the_clock():
    """Two systems deciding when things arrive means twice the density, so the
    timer director stands down the moment the ground starts handing things over.
    Leaving the flag False is the fallback: a baked sector spawns as it always
    did, and nothing else about a sector changes."""
    g = make_game()
    g.new_game()
    plain = make_game()
    g.ground_spawns = True
    for _ in range(400):
        g.update(DT, move_x=0.0, move_y=0.0, firing=False)
    for _ in range(400):
        plain.update(DT, move_x=0.0, move_y=0.0, firing=False)
    assert not any(e.kind is not C.EnemyKind.BOSS for e in g.enemies) \
        or all(e.kind is C.EnemyKind.BOSS for e in g.enemies), \
        "the clock kept spawning while the ground was driving"
    assert len(plain.enemies) > 0, "the timer path stopped working"


def test_a_release_waits_when_the_field_is_already_busy():
    from game.model import FIELD_SOFT_CAP
    g = make_game()
    for _ in range(FIELD_SOFT_CAP):
        g.release("grunt", 300.0 + (_ % 6) * 30.0, 1, "single")
    assert len(g.enemies) <= FIELD_SOFT_CAP
    assert g.release("heavy", 400.0, 1, "single") == 0


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


def test_timed_powers_buy_a_block_and_not_a_reset():
    """Two seconds left plus a full pod means two plus a full pod, not a reset.

    A timed power that resets on pickup is a punishment for catching it late,
    and a shield caught at 6.9 s left is almost the whole pod thrown away. Both
    timed tracks stack, and both stop at two blocks so the run cannot be farmed
    into permanent invulnerability.
    """
    g = make_game()
    pl = g.player
    pl.shield = 2.0
    g._apply_item(Item(C.ItemKind.SHIELD, 0, 0), [])
    assert pl.shield == 2.0 + C.SHIELD_TIME
    assert pl.shield_span == pl.shield, "the deploy pop lost its reference point"
    g._apply_item(Item(C.ItemKind.SHIELD, 0, 0), [])
    assert pl.shield == C.SHIELD_MAX, "the shield stack ran away"

    g.whip_timer = 2.0
    g._apply_item(Item(C.ItemKind.WHIP, 0, 0), [])
    assert g.whip_timer == 2.0 + C.WHIP_TIME
    g._apply_item(Item(C.ItemKind.WHIP, 0, 0), [])
    assert g.whip_timer == C.WHIP_MAX, "the lash stack ran away"


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
