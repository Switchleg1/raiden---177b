"""Unit tests for the falling-item model (the 'power system')."""

import random

import config as C
from game import Game
from items import Item, build_weights, roll_item


def test_build_weights_filters_bad_entries():
    tbl = (("weapon", 5), ("bogus", 3), ("mine", 0))
    kinds, weights = build_weights(tbl)
    assert kinds == [C.ItemKind.WEAPON]
    assert weights == [5.0]


def test_build_weights_default_table_covers_all_kinds():
    kinds, weights = build_weights()
    assert set(kinds) == set(C.ItemKind)
    assert all(w > 0 for w in weights)


def test_roll_item_deterministic_per_seed():
    seq1 = [roll_item(random.Random(11)) for _ in range(30)]
    # each call gets a fresh Random(11): every draw must repeat identically
    assert all(k == seq1[0] for k in seq1)
    # one seeded rng played twice yields the identical sequence
    rng_a, rng_b = random.Random(11), random.Random(11)
    assert ([roll_item(rng_a) for _ in range(30)] ==
            [roll_item(rng_b) for _ in range(30)])


def test_roll_item_only_returns_known_kinds():
    rng = random.Random(3)
    for _ in range(200):
        assert roll_item(rng) in set(C.ItemKind)


def test_hazards_are_rarer_than_beneficial():
    w = dict(C.ITEM_WEIGHTS)
    hazard_names = {h.value for h in C.HAZARDS}
    hw = sum(v for k, v in w.items() if k in hazard_names)
    bw = sum(v for k, v in w.items() if k not in hazard_names)
    assert hw < bw


def test_item_falls_and_is_culled_offscreen():
    it = Item(C.ItemKind.MEDAL, 100.0, C.FIELD_BOTTOM - 1.0)
    assert it.alive
    for _ in range(50):
        it.update(1.0 / 60.0)
    assert not it.alive


def test_item_weight_table_names_are_valid_enum_values():
    for name, w in C.ITEM_WEIGHTS:
        assert w > 0
        C.ItemKind(name)  # must not raise


def test_phase_is_deterministic_and_desyncs_a_cluster():
    """The aura's per-item offset is cosmetic, reproducible, and never shared.

    It must not come from the game RNG (that would make the simulation stream
    depend on a renderer detail) nor from wall-clock/id() (a recorded run has
    to animate identically), so it is quantised from the spawn.
    """
    a = Item(C.ItemKind.WEAPON, 120.0, 200.0)
    b = Item(C.ItemKind.WEAPON, 120.0, 200.0)
    assert a.phase == b.phase                     # same spawn -> same phase
    assert 0.0 <= a.phase < 1.0
    spots = [(120.0, 200.0), (122.5, 200.0), (120.0, 214.0), (640.0, 88.0),
             (300.0, 300.0)]
    phases = {Item(C.ItemKind.MEDAL, x, y).phase for x, y in spots}
    assert len(phases) == len(spots)              # a cluster never syncs


def test_phase_does_not_touch_the_simulation_stream():
    """Two runs of the same seed drop the same kinds in the same order."""
    def drops(seed: int) -> list[str]:
        g = Game(rng=random.Random(seed))
        g.new_game()
        seen: list[str] = []
        for _ in range(1200):
            for it in g.items:
                if it.kind.value not in seen:
                    seen.append(it.kind.value)
            g.update(C.SIM_DT)
        return seen

    assert drops(5) == drops(5)
