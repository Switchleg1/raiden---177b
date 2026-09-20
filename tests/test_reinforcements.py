"""Boss escort waves and loadout retention (model layer, no pygame needed)."""

import random

import config as C
from game import Game

DT = C.SIM_DT


def make_game(seed=7, level=0):
    g = Game(rng=random.Random(seed))
    g.new_game()
    g.start_level(level)
    g.lives = 999            # survive long enough to study the boss phase
    return g


def boss_fight(level=0, seed=7):
    """A game whose sector boss is already on screen."""
    g = make_game(seed=seed, level=level)
    g._spawn_boss([])
    assert g.boss_alive()
    return g


def escorts(g):
    return [e for e in g.enemies
            if e.alive and e.kind is not C.EnemyKind.BOSS]


def run(g, seconds):
    for _ in range(int(seconds / DT)):
        g.update(DT)


def watch_reinforcements(g):
    """Return a list that records every escort the director launches."""
    calls: list[int] = []
    original = g._spawn_escort

    def counted() -> None:
        calls.append(1)
        original()

    g._spawn_escort = counted
    return calls


# ------------------------------------------------------------------ escorts
def test_escort_director_is_asleep_before_the_boss():
    g = make_game()
    run(g, 12.0)
    assert g._boss_spawned is False
    assert g._escort_timer == 0.0, "nothing may trickle in before the boss"


def test_boss_calls_in_escorts():
    g = boss_fight()
    assert escorts(g) == []
    run(g, C.ESCORT_FIRST_WAVE + 0.5)
    assert escorts(g), "boss should be covered by small craft"


def test_escorts_stop_the_moment_the_boss_dies():
    g = boss_fight()
    launched = watch_reinforcements(g)
    run(g, C.ESCORT_FIRST_WAVE + 0.5)
    assert launched, "expected escorts during the fight"

    for e in g.enemies:
        if e.kind is C.EnemyKind.BOSS:
            e.alive = False
    launched.clear()
    run(g, 12.0)
    assert launched == [], "the sector is won; stop reinforcing it"


def test_escort_screen_stays_readable():
    for level in (0, 4, 8):
        g = boss_fight(level=level)
        cap = C.escort_cap(level)
        for _ in range(int(40.0 / DT)):
            g.update(DT)
            assert len(escorts(g)) <= cap, (
                f"sector {level + 1} exceeded its escort cap")


def test_escorts_are_only_small_readable_kinds():
    g = boss_fight(level=5)
    run(g, 30.0)
    kinds = {e.kind for e in escorts(g)}
    allowed = {k for k, _w in C.ESCORT_SPAWNS}
    assert kinds and kinds <= allowed
    assert all(k in (C.EnemyKind.GRUNT, C.EnemyKind.WEAVER,
                     C.EnemyKind.DARTER) for k in allowed), \
        "heavies and sentries would swallow the boss silhouette"


def test_escort_seeds_are_stable():
    a = boss_fight(level=3, seed=11)
    b = boss_fight(level=3, seed=11)
    run(a, 10.0)
    run(b, 10.0)
    assert [(round(e.x, 6), e.kind) for e in escorts(a)] == \
           [(round(e.x, 6), e.kind) for e in escorts(b)]


# ------------------------------------------------------------- config scaling
def test_escort_pressure_rises_and_clamps():
    intervals = [C.escort_interval(i) for i in range(9)]
    assert intervals == sorted(intervals, reverse=True)
    assert min(intervals) >= C.ESCORT_INTERVAL_MIN

    caps = [C.escort_cap(i) for i in range(9)]
    assert caps == sorted(caps)
    assert caps[0] == C.ESCORT_CAP_0
    assert caps[-1] > caps[0]
    assert caps[-1] <= C.ESCORT_CAP_MAX

    for level in range(-1, 12):
        assert 1 <= C.escort_group(level) <= C.ESCORT_GROUP_MAX


# -------------------------------------------------------- loadout retention
def test_cleared_sector_keeps_the_loadout():
    g = make_game()
    g.player.weapon_level = 4
    g.player.missile_level = 2
    g.player.moon_level = 3
    g.advance_level()
    assert g.level_index == 1
    assert g.player.weapon_level == 4
    assert g.player.missile_level == 2
    assert g.player.moon_level == 3, "sector clear ate the blade track"


def test_death_and_new_game_still_wipe_the_loadout():
    g = make_game()
    g.player.weapon_level = 5
    g.player.missile_level = 3
    g.player.moon_level = C.MOON_MAX_LEVEL
    g.start_level(g.level_index)          # respawn path: no carry
    assert g.player.weapon_level == C.WEAPON_BASE_LEVEL
    assert g.player.missile_level == C.MISSILE_BASE_LEVEL
    assert g.player.moon_level == C.MOON_BASE_LEVEL

    g.player.weapon_level = 5
    g.player.moon_level = C.MOON_MAX_LEVEL
    g.new_game()
    assert g.player.weapon_level == C.WEAPON_BASE_LEVEL
    assert g.player.moon_level == C.MOON_BASE_LEVEL


def test_retention_does_not_resurrect_the_battlefield():
    g = boss_fight()
    g.player.weapon_level = 3
    # This test is about what a *cleared* sector keeps, so pin survival: a boss
    # now actually threatens a player that never moves, and dying would wipe the
    # loadout for reasons that have nothing to do with retention.
    g.player.invuln = 999.0
    run(g, 3.0)
    assert g.enemies
    g.advance_level()
    assert g.enemies == [] and g.bullets == []
    assert g.boss_alive() is False
    assert g.player.weapon_level == 3, "cleared, not lost"
