"""Nine sectors, nine bosses, nine different habits (model layer, no pygame).

What is being pinned down is the contract the habit table makes to the game:
a boss is data, its movement and volleys are written in a fixed vocabulary, it
never leaves its band while fighting, it never opens fire before it has arrived,
and the whole fight reproduces from a seed. Whether the habits *feel* different
is reviewed with scripts/preview_bosses.py; these tests stop them from quietly
becoming the same boss nine times.
"""

import math
import random

import config as C
from entities import Enemy, bosskit

DT = C.SIM_DT
ENTRY_Y = C.FIELD_TOP - 80.0        # where the campaign drops a boss in
SPEED = 220.0                       # bullet speed a mid-game sector throws


def _boss(level, hp=220, seed=1):
    """The sector's boss, on the sheet the level data picked for it."""
    e = Enemy.spawn(C.EnemyKind.BOSS, 400.0, ENTRY_Y, level=level,
                    hp_override=hp, rng=random.Random(seed))
    e.sheet = C.LEVELS[level].boss
    return e


def _fight(e, seconds, seed=3, pilot=None, hp_at=None, hp_to=None):
    """Fly one boss. Returns (bullet log, sampled path).

    ``pilot(t)`` replaces the usual motionless test dummy; aimed patterns are a
    conversation, and a boss that never has to lead a target is only half
    exercised. ``hp_at`` / ``hp_to`` drop the boss into its enrage phase
    partway through, which is a different fight and a different band of risk.
    """
    rng = random.Random(seed)
    shots = []
    path = []

    def fire(x, y, vx, vy, shell=0, fuse=0.0):
        shots.append({"volley": e.boss_shot, "x": x, "y": y, "vx": vx, "vy": vy,
                      "shell": shell, "fuse": fuse})

    for i in range(int(seconds / DT)):
        t = i * DT
        if hp_at is not None and t >= hp_at:
            e.hp = hp_to
        px, py = pilot(t) if pilot is not None else (400.0, C.PLAYER_START_Y)
        e.update(DT, px, py, fire, SPEED, rng)
        path.append((e.x, e.y, e.boss_step))
    return shots, path


def _volleys(shots):
    """Group the bullet log by volley, in the order they were fired."""
    out = {}
    for s in shots:
        out.setdefault(s["volley"], []).append(s)
    return [out[k] for k in sorted(out)]


# ------------------------------------------------------------------ the table

def test_habit_table_covers_the_campaign():
    for i, spec in enumerate(C.LEVELS):
        habit = C.habit_for(spec.boss)
        assert habit.move in bosskit._MOVES, f"sector {i + 1}: {habit.move}"
        assert len(habit.attacks) >= 2, f"sector {i + 1} has no repertoire"
        for atk in habit.attacks:
            assert atk.kind in bosskit._ATTACKS, f"{spec.boss}: {atk.kind}"
            assert atk.cd > 0.0, "a volley with no cooldown never ends"
            assert atk.count > 0
        assert 0.0 < habit.enrage_at < 1.0
        assert 0.0 < habit.enrage_cd <= 1.0


def test_no_two_bosses_share_a_move_or_a_sequence():
    habits = [C.habit_for(spec.boss) for spec in C.LEVELS]
    moves = [h.move for h in habits]
    sequences = [tuple(a.kind for a in h.attacks) for h in habits]
    assert len(set(moves)) == len(habits), f"reused movement: {moves}"
    assert len(set(sequences)) == len(habits), "two sectors fire the same way"


def test_habit_for_always_answers():
    assert C.habit_for(None) is C.DEFAULT_HABIT
    assert C.habit_for("no_such_sheet") is C.DEFAULT_HABIT
    assert C.DEFAULT_HABIT in C.BOSS_HABITS.values()


# ------------------------------------------------------------------- entrances

def test_entry_is_an_entrance_not_a_teleport():
    """A boss arrives from off screen, and it takes its time.

    The band clamp is a rule for the fight, not for the arrival; if it were
    applied on the entry frames the boss would pop into existence at the top of
    the field and the campaign would lose its nine curtain-raisers.
    """
    e = _boss(0)
    _shots, path = _fight(e, 0.25)
    assert path[0][1] < C.FIELD_TOP, "boss should still be off screen"
    assert all(y < C.BOSS_TOP for _x, y, _s in path), "clamped into the band"


def test_boss_is_silent_until_it_lands():
    e = _boss(0)
    shots, path = _fight(e, 1.0)
    assert shots == [], "fired before it arrived"
    assert path[-1][2] < 0.0, "entry should still be running after 1s"


def test_boss_starts_firing_once_it_settles():
    e = _boss(0)
    shots, path = _fight(e, 8.0)
    assert path[-1][2] > 0.0
    assert len(shots) >= 5


def test_side_entry_comes_from_outside_the_field():
    sides = [(i, h.entry) for i, spec in enumerate(C.LEVELS)
             for h in [C.habit_for(spec.boss)] if h.entry != "top"]
    assert sides, "no boss enters from the side"
    for level, side in sides:
        e = _boss(level)
        _shots, path = _fight(e, 0.25)
        assert path, f"sector {level + 1} never updated"
        if side == "left":
            assert path[0][0] < C.FIELD_LEFT, f"sector {level + 1} x={path[0][0]}"
        else:
            assert path[0][0] > C.FIELD_RIGHT, f"sector {level + 1} x={path[0][0]}"


# ---------------------------------------------------------------------- the band

def test_a_fighting_boss_never_leaves_its_band():
    """Nine strategies, one law: the band the player was taught to aim at.

    Includes a mid-run enrage and a pilot that flies the width of the field,
    because those are the two things that make a strategy reach.
    """
    def pilot(t):
        return (400.0 + 330.0 * math.sin(t * 0.7),
                C.PLAYER_START_Y + 40.0 * math.sin(t * 1.3))

    for level in range(len(C.LEVELS)):
        habit = C.habit_for(C.LEVELS[level].boss)
        e = _boss(level)
        _shots, path = _fight(e, 22.0, seed=11 + level, pilot=pilot,
                              hp_at=10.0, hp_to=int(e.max_hp * 0.2))
        fighting = [(x, y) for x, y, step in path if step > 0.0]
        assert len(fighting) > 400, f"sector {level + 1} never settled"
        for x, y in fighting:
            assert C.BOSS_TOP <= y <= C.BOSS_BOTTOM, \
                f"sector {level + 1} ({habit.move}) left the band at y={y:.1f}"
            assert C.FIELD_LEFT + e.r - 0.5 <= x <= C.FIELD_RIGHT - e.r + 0.5, \
                f"sector {level + 1} ({habit.move}) left the field at x={x:.1f}"


def test_habits_actually_move():
    """A "moving" boss that never moved would still pass the band test."""
    travelled = {}
    for level in range(len(C.LEVELS)):
        habit = C.habit_for(C.LEVELS[level].boss)
        e = _boss(level)
        _shots, path = _fight(e, 20.0, seed=5 + level)
        fighting = [(x, y) for x, y, step in path if step > 0.0]
        span_x = max(x for x, _y in fighting) - min(x for x, _y in fighting)
        span_y = max(y for _x, y in fighting) - min(y for _x, y in fighting)
        travelled[habit.move] = (span_x, span_y)
        assert span_x > 40.0, f"{habit.move} does not cross the field"
    assert len(set(travelled)) == len(travelled), \
        f"two movements traced the same footprint: {travelled}"


# --------------------------------------------------------------------- volleys

def test_volleys_follow_the_habit_in_order():
    """The sequence is the personality; it must repeat, exactly, in order."""
    for level, spec in enumerate(C.LEVELS):
        habit = C.habit_for(spec.boss)
        kinds = [a.kind for a in habit.attacks]
        if "wall" in kinds:
            continue        # a wall's bullet count depends on where its gap was
        e = _boss(level)
        shots, _path = _fight(e, 40.0, seed=31 + level)
        groups = _volleys(shots)
        assert len(groups) >= 3 * len(habit.attacks)
        for i, group in enumerate(groups):
            want = habit.attacks[i % len(habit.attacks)]
            n = want.count * (2 if want.kind == "pinwheel" else 1)
            assert len(group) == n, \
                f"{spec.boss} volley {i}: {kinds[i % len(kinds)]} " \
                f"expected {n}, got {len(group)}"


# Primitives that are defined as "toward the player / toward the floor". Rings,
# spirals and pinwheels deliberately throw shots upward too.
DOWNWARD_KINDS = {"aimed", "fan", "mine", "shell", "spray", "beam"}


def test_downward_volleys_actually_go_down():
    """The old boss aimed its "downward" fan with 0 degrees pointing up.

    Angles are measured from straight up, so a primitive that forgets to add the
    half turn fires at the ceiling and off the top of the screen. Every shot
    that is defined as descending has to arrive.
    """
    for level in range(len(C.LEVELS)):
        habit = C.habit_for(C.LEVELS[level].boss)
        e = _boss(level)
        shots, _path = _fight(e, 40.0, seed=17 + level)
        assert shots, f"sector {level + 1} never fired"
        groups = _volleys(shots)
        for i, group in enumerate(groups):
            kind = habit.attacks[i % len(habit.attacks)].kind
            if kind not in DOWNWARD_KINDS:
                continue
            for s in group:
                assert s["vy"] > 0.0, \
                    f"{spec_label(level)} fired {kind} upward " \
                    f"({s['vx']:.0f},{s['vy']:.0f})"
                assert s["y"] >= C.BOSS_TOP, "shot spawned above the boss band"


def spec_label(level):
    return C.LEVELS[level].boss


def test_wall_volley_always_leaves_a_way_through():
    """A curtain you cannot thread is not a pattern, it is a coin flip."""
    seen = 0
    for level, spec in enumerate(C.LEVELS):
        habit = C.habit_for(spec.boss)
        if not any(a.kind == "wall" for a in habit.attacks):
            continue
        e = _boss(level)
        shots, _path = _fight(e, 60.0, seed=41 + level)
        curtains = 0
        for group in _volleys(shots):
            xs = sorted(s["x"] for s in group)
            if len(xs) < 5 or xs[-1] - xs[0] < 500.0:
                continue        # an aimed spread shares an origin, not a width
            curtains += 1
            # A corridor may sit between two shots or along an edge; either way
            # the pilot has to be able to stand somewhere in this volley.
            gaps = [b - a for a, b in zip(xs, xs[1:], strict=False)]
            gaps += [xs[0] - C.FIELD_LEFT, C.FIELD_RIGHT - xs[-1]]
            assert max(gaps) >= 90.0, \
                f"{spec.boss} sealed the field: widest corridor " \
                f"{max(gaps):.0f}px"
        assert curtains >= 2, f"{spec.boss} threw no wall in 60s"
        seen += 1
    assert seen >= 2, "wall attack is not used by any boss"


def test_shell_volleys_ask_for_cluster_shells():
    for level, spec in enumerate(C.LEVELS):
        habit = C.habit_for(spec.boss)
        if not any(a.kind == "shell" for a in habit.attacks):
            continue
        e = _boss(level)
        shots, _path = _fight(e, 40.0, seed=23 + level)
        shells = [s for s in shots if s["shell"]]
        assert shells, f"{spec.boss} lobbed nothing"
        assert all(s["fuse"] > 0.0 for s in shells)


def test_enrage_quickens_the_rhythm():
    """Below the habit's threshold the same repertoire comes faster."""
    for level in range(len(C.LEVELS)):
        e = _boss(level)
        shots, _path = _fight(e, 6.0, seed=61 + level)
        assert len(shots) >= 2

        calm = _boss(level)
        calm_shots, _ = _fight(calm, 30.0, seed=71 + level)
        hot = _boss(level)
        hot.hp = 1
        hot_shots, _ = _fight(hot, 30.0, seed=71 + level)
        assert len(hot_shots) > len(calm_shots), \
            f"{C.LEVELS[level].boss} calms down when it is cornered"


def test_boss_fight_reproduces_from_its_seed():
    """Same seed, same fight - the replay of a run has to be the run."""
    def run(seed):
        e = _boss(4)
        shots, path = _fight(e, 12.0, seed=seed)
        return ([(round(s["x"], 6), round(s["y"], 6), round(s["vx"], 6),
                  round(s["vy"], 6)) for s in shots],
                [(round(x, 6), round(y, 6)) for x, y, _s in path])

    assert run(3) == run(3)
    assert run(3) != run(4), "the seed is not steering the fight"
