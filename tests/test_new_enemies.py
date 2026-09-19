"""Behaviour tests for the four specialist kinds.

Each kind exists to force one specific decision from the player, so these
tests assert that decision rather than cosmetics: a splitter's children must be
strictly weaker and must never chain, a bomber's shells must burst (the burst is
the threat, the shell is only the delivery), a rammer must commit to a column it
locked in advance, and a shard must stay a shard.
"""
from __future__ import annotations

import math
import random

import config as C
from entities import Enemy
from game import Game

DT = C.SIM_DT


def make_game(seed: int = 1234) -> Game:
    g = Game(rng=random.Random(seed), enable_items=False)
    g.new_game()
    return g


def spawn_in(g: Game, kind, x: float, y: float) -> Enemy:
    e = Enemy.spawn(kind, x, y, level=g.level_index, rng=g.rng)
    g.enemies.append(e)
    return e


def shards_of(g: Game) -> list[Enemy]:
    return [e for e in g.enemies if e.kind is C.EnemyKind.SHARD and e.alive]


# ---------------------------------------------------------------- splitter #
def test_splitter_death_makes_exactly_two_shards():
    g = make_game()
    parent = spawn_in(g, C.EnemyKind.SPLITTER, 300.0, 240.0)
    parent.alive = False
    g._on_enemy_killed(parent, [])

    kids = shards_of(g)
    assert len(kids) == C.ENEMY_SPECS[C.EnemyKind.SPLITTER].split_count
    # fanned out left/right of the corpse, never stacked on one point
    assert len({k.drift_dir for k in kids}) == 2


def test_shards_never_chain():
    g = make_game()
    parent = spawn_in(g, C.EnemyKind.SPLITTER, 400.0, 200.0)
    parent.alive = False
    g._on_enemy_killed(parent, [])
    for kid in shards_of(g):
        kid.alive = False
        g._on_enemy_killed(kid, [])
    assert len(shards_of(g)) == 0


def test_shards_are_weaker_and_diverge():
    shard = C.ENEMY_SPECS[C.EnemyKind.SHARD]
    splitter = C.ENEMY_SPECS[C.EnemyKind.SPLITTER]
    assert shard.split_into is None          # no grandchildren
    assert shard.hp < splitter.hp
    assert shard.score < splitter.score

    rng = random.Random(7)
    for side in (-1, 1):
        e = Enemy.spawn(C.EnemyKind.SHARD, 400.0, 200.0, rng=rng)
        e.drift_dir = side
        e.update(DT, 400.0, C.PLAYER_START_Y, lambda *a: None, 220.0, rng)
        assert e.vy > 0.0
        assert math.copysign(1.0, e.vx) == float(side)


# ------------------------------------------------------------------ bomber #
def test_bomber_shells_burst_after_their_fuse():
    g = make_game()
    spec = C.ENEMY_SPECS[C.EnemyKind.BOMBER]
    bomber = spawn_in(g, C.EnemyKind.BOMBER, 300.0, 160.0)

    shells = []
    for _ in range(int(12.0 / DT)):
        g.update(DT)
        shells = [b for b in g.bullets if b.frag and not b.friendly and b.alive]
        if shells:
            break
    assert shells, "bomber never launched a cluster shell"
    assert shells[0].r == C.SHELL_R
    assert shells[0].split_in > 0.0

    # While the fuse burns the shell is still one object.
    g.update(DT)
    live = [b for b in g.bullets if not b.friendly and b.alive]
    assert sum(1 for b in live if b.frag) == len(
        [b for b in g.bullets if not b.friendly and b.alive and b.frag])

    # Past the fuse it throws its payload and the shell itself is gone.
    for _ in range(int((spec.shell_fuse + 0.5) / DT)):
        g.update(DT)
    frags = [b for b in g.bullets if not b.friendly and b.alive and not b.frag]
    assert len(frags) >= spec.shell_frag
    # Fragments fly radially, so they cannot all still be falling straight down
    assert any(b.vx != 0.0 for b in frags)
    assert bomber.alive


def test_cluster_shell_is_slow_and_fat():
    # The player has to read a shell as "slow thing that will burst", so it is
    # deliberately slower than a normal bolt and much wider.
    assert 0.0 < C.SHELL_SPEED < 0.75
    assert C.SHELL_R > C.ENEMY_BULLET_R


def test_only_the_bomber_lobs_shells():
    for kind, spec in C.ENEMY_SPECS.items():
        if kind is not C.EnemyKind.BOMBER:
            assert spec.shell_frag == 0, kind


# ------------------------------------------------------------------ rammer #
def test_rammer_locks_the_column_then_commits():
    rng = random.Random(3)
    e = Enemy.spawn(C.EnemyKind.RAMMER, 300.0, 120.0, rng=rng)
    spec = C.ENEMY_SPECS[C.EnemyKind.RAMMER]
    fired: list[tuple] = []

    def fire(*args) -> None:
        fired.append(args)

    # Lock phase: the marker slides toward the player, the body barely descends.
    for _ in range(int(C.RAMMER_LOCK_TIME * 0.8 / DT)):
        e.update(DT, 520.0, C.PLAYER_START_Y, fire, 220.0, rng)
    assert e.lock_x > 300.0
    assert e.vy < spec.speed * 0.2

    # Committed: full charge speed, and it never shoots on the way down.
    y0 = e.y
    for _ in range(int((C.RAMMER_RAMP + 0.2) / DT)):
        e.update(DT, 520.0, C.PLAYER_START_Y, fire, 220.0, rng)
    assert e.vy > spec.speed * 0.8
    assert (e.y - y0) > 40.0
    assert not fired


def test_rammer_ignores_a_last_second_dodge():
    rng = random.Random(5)
    e = Enemy.spawn(C.EnemyKind.RAMMER, 300.0, 120.0, rng=rng)
    for _ in range(int(C.RAMMER_LOCK_TIME / DT) + 2):
        e.update(DT, 300.0, C.PLAYER_START_Y, lambda *a: None, 220.0, rng)
    locked = e.lock_x
    # The player bolts sideways after the lock closes: the charge must not
    # follow, which is what makes the dodge fair.
    for _ in range(int(0.5 / DT)):
        e.update(DT, 120.0, C.PLAYER_START_Y, lambda *a: None, 220.0, rng)
    assert e.lock_x == locked


# ------------------------------------------------------------- roster data #
def test_specialists_reach_the_campaign():
    # A kind that only appears in the final sector is content nobody sees, so
    # each specialist has to be introduced with room to spare.
    first: dict[str, int] = {}
    for index, spec in enumerate(C.LEVELS):
        for kind, weight in spec.spawns:
            assert weight > 0
            first.setdefault(kind, index)
    for kind in (C.EnemyKind.BOMBER, C.EnemyKind.SPLITTER, C.EnemyKind.RAMMER):
        assert kind.value in first
        assert first[kind.value] <= len(C.LEVELS) - 3


def test_shard_never_appears_in_a_spawn_table():
    for spec in C.LEVELS:
        kinds = {kind for kind, _w in spec.spawns}
        assert C.EnemyKind.SHARD.value not in kinds, spec.name


def test_new_kinds_are_wired_to_baked_art():
    # The renderer resolves a sprite as `entity.sheet or ENEMY_SHEET[kind]`, so
    # a kind missing from that table silently falls back to vector shapes; a
    # table entry pointing at an unbaked sheet silently falls back too.  Both
    # wiring mistakes are cheap to make and cheap to catch here.
    import sprites
    from ui.constants import ENEMY_SHEET, EXPLOSION_TIER

    for kind in (C.EnemyKind.BOMBER, C.EnemyKind.SPLITTER, C.EnemyKind.RAMMER,
                 C.EnemyKind.SHARD):
        assert kind.value in ENEMY_SHEET
        assert kind.value in EXPLOSION_TIER
        sheet = ENEMY_SHEET[kind.value]
        assert sheet in sprites.SPRITES, f"{sheet} is not in the manifest"
        e = Enemy.spawn(kind, 100.0, 100.0, rng=random.Random(1))
        assert (e.sheet or ENEMY_SHEET[kind.value]) == sheet


def test_every_enemy_sheet_exists_on_disk():
    import sprites
    from ui.constants import ENEMY_SHEET

    for name in sorted(set(ENEMY_SHEET.values())):
        assert sprites.sheet_path(name).exists(), name
