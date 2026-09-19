"""Unit tests for the pygame-free primitives in physics.py."""

import math

import config as C
import physics as P


class Obj:
    def __init__(self, x, y, vx, vy):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy


def test_clamp():
    assert P.clamp(5, 0, 10) == 5
    assert P.clamp(-1, 0, 10) == 0
    assert P.clamp(11, 0, 10) == 10


def test_advance_matches_direct_integration():
    o = Obj(0.0, 0.0, 900.0, -450.0)
    dt = 1.0 / 120.0
    P.advance(o, dt)
    assert math.isclose(o.x, 900.0 * dt, rel_tol=1e-9)
    assert math.isclose(o.y, -450.0 * dt, rel_tol=1e-9)


def test_advance_zero_velocity_noop():
    o = Obj(1.0, 2.0, 0.0, 0.0)
    P.advance(o, 0.1)
    assert (o.x, o.y) == (1.0, 2.0)


def test_from_deg_cardinals():
    vx, vy = P.from_deg(0.0, 10.0)
    assert math.isclose(vx, 0.0, abs_tol=1e-9) and math.isclose(vy, -10.0, abs_tol=1e-9)
    vx, vy = P.from_deg(90.0, 10.0)
    assert math.isclose(vx, 10.0, abs_tol=1e-9) and math.isclose(vy, 0.0, abs_tol=1e-9)
    vx, vy = P.from_deg(-90.0, 10.0)
    assert math.isclose(vx, -10.0, abs_tol=1e-9) and math.isclose(vy, 0.0, abs_tol=1e-9)


def test_to_deg_roundtrip():
    for ang in (-160.0, -30.0, 0.0, 45.0, 120.0):
        vx, vy = P.from_deg(ang, 7.5)
        assert math.isclose(P.to_deg(vx, vy), ang, rel_tol=1e-6, abs_tol=1e-9)


def test_circle_hit_touching_and_miss():
    assert P.circle_hit(0, 0, 5, 7, 0, 2) is True   # distance == 7 == r+r
    assert P.circle_hit(0, 0, 5, 8, 0, 2) is False


def test_point_in_box():
    assert P.point_in_box(5, 5, 0, 0, 10, 10)
    assert not P.point_in_box(-0.1, 5, 0, 0, 10, 10)


def test_offscreen_predicates():
    assert P.offscreen_below(C.FIELD_BOTTOM + 1, 0.0)
    assert not P.offscreen_below(C.FIELD_BOTTOM - 1, 0.0)
    assert P.offscreen_above(C.FIELD_TOP - 1, 0.0)
    assert not P.offscreen_above(C.FIELD_TOP + 1, 0.0)


def test_advance_substeps_are_bounded_for_fast_objects():
    # a very fast object over a long dt must still land at the exact position
    o = Obj(0.0, 0.0, 5000.0, 0.0)
    P.advance(o, 0.05)
    assert math.isclose(o.x, 250.0, rel_tol=1e-9)
