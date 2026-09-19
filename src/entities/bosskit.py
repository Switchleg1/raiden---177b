"""Movement and firing primitives that give each sector boss its habits.

:meth:`entities.enemy.Enemy._update_boss` used to hold one strafe path and a
three-shot cycle shared by all nine bosses. This module keeps the *state
machine* in the enemy (it owns its slots) and the *personality* in
:data:`config.BOSS_HABITS`, and implements the vocabulary both talk about:

Movement
    ``strafe``, ``pendulum``, ``orbit``, ``hunt``, ``lunge``, ``eight``,
    ``hop``, ``edge``, ``stalker`` — each sets ``vx``/``vy`` (the caller still
    integrates through :func:`physics.advance`) and every strategy is clamped
    into the boss band, so no boss ever parks in the player's face.

Attack
    ``aimed``, ``fan``, ``ring``, ``spiral``, ``pinwheel``, ``wall``,
    ``mine``, ``shell``, ``spray``, ``beam`` — each emits through the game's
    ``fire`` callback, so the bullet cap, cluster shells and bomb clearing all
    keep applying exactly as they do for regular enemies.

No strategy reads wall-clock time or ``id()``: everything is driven by the
boss's own clock and the game's seeded RNG, so a replay of a seed reproduces a
boss's every volley.
"""
from __future__ import annotations

import math
import random
from collections.abc import Callable
from typing import Any

import config as C
import physics as P

# Structural typing keeps this module free of an import cycle: it reads and
# writes Enemy slots (``x, y, vx, vy, r, t, hp, max_hp, boss_shot, boss_step,
# boss_anchor``) without importing the class.
FireFn = Callable[..., None]
MoveFn = Callable[..., None]
ShotFn = Callable[..., None]

DOWN = 180.0          # P.from_deg measures from straight up

# The band a boss may occupy. The top of it is where the boss glides in; the
# bottom is deliberately far enough above the player that a 56-unit hull can
# never body-block the dodge space.
BAND_LO = C.BOSS_TOP + 10.0
BAND_HI = C.BOSS_BOTTOM - 10.0

ENTRY_DOWN = 62.0     # vertical glide-in speed
ENTRY_ACROSS = 240.0  # side glide-in speed


def _mix(lo: float, hi: float, t: float) -> float:
    """Linear interpolation; the geometry helpers do not carry one."""
    return lo + (hi - lo) * t


def _band(e: Any) -> tuple[float, float]:
    """Horizontal limits for this boss's centre, given its hull radius."""
    pad = e.r + 10.0
    return C.FIELD_LEFT + pad, C.FIELD_RIGHT - pad


def keep_in_band(e: Any) -> None:
    """Hard safety net: a fighting boss never leaves its band.

    Not applied while ``boss_step`` is negative, i.e. during the entry glide.
    That phase is scripted and deliberately starts off screen - clamping it
    would turn an entrance into a pop at the top edge of the field.
    """
    if e.boss_step < 0.0:
        return
    if e.y < BAND_LO:
        e.y = BAND_LO
        if e.vy < 0.0:
            e.vy = 0.0
    elif e.y > BAND_HI:
        e.y = BAND_HI
        if e.vy > 0.0:
            e.vy = 0.0


# ---------------------------------------------------------------------------
# Entry: how the boss comes on screen
# ---------------------------------------------------------------------------
def _begin_entry(e: Any, habit: Any, cx: float) -> None:
    """Position a side-entering boss off-screen and start the glide.

    Runs on the boss's very first update, before it has ever been drawn, so
    moving it sideways here is invisible; the player only sees it sail in.
    """
    if habit.entry == "left":
        e.x = C.FIELD_LEFT - e.r - 20.0
        e.y = C.BOSS_ENTRY_Y - 30.0
        e.boss_anchor = cx - (C.FIELD_RIGHT - C.FIELD_LEFT) * 0.18
    elif habit.entry == "right":
        e.x = C.FIELD_RIGHT + e.r + 20.0
        e.y = C.BOSS_ENTRY_Y - 30.0
        e.boss_anchor = cx + (C.FIELD_RIGHT - C.FIELD_LEFT) * 0.18


def _glide(e: Any, dt: float, habit: Any) -> bool:
    """Move the boss in. Returns True once it has arrived and may fight."""
    if habit.entry in ("left", "right"):
        step = ENTRY_ACROSS * dt
        dx = e.boss_anchor - e.x
        if abs(dx) <= step:
            e.x, e.vx = e.boss_anchor, 0.0
        else:
            e.vx = ENTRY_ACROSS if dx > 0 else -ENTRY_ACROSS
        dy = C.BOSS_ENTRY_Y - e.y
        e.vy = ENTRY_DOWN if dy > 0 else 0.0
        return abs(dx) <= step and abs(dy) <= ENTRY_DOWN * dt + 0.5
    e.vx = 0.0
    e.vy = ENTRY_DOWN
    return e.y >= C.BOSS_ENTRY_Y - 0.5


# ---------------------------------------------------------------------------
# Movement strategies
# ---------------------------------------------------------------------------
def _strafe(e: Any, dt: float, habit: Any, px: float,
            rng: random.Random, cx: float) -> None:
    """Classic gatekeeper: march across the band and bob. Sector 1."""
    lo, hi = _band(e)
    e.vx = 55.0 * habit.speed * e.drift_dir
    if e.x < lo + 4.0:
        e.drift_dir = 1
    elif e.x > hi - 4.0:
        e.drift_dir = -1
    e.vy = 14.0 * math.sin(e.t * 0.6)


def _follow(e: Any, dt: float, tx: float, ty: float,
            rate: float = 2.6) -> None:
    """Ease the boss onto a point of its path instead of teleporting it.

    Path-based strategies name where the boss should be, not how fast to get
    there. Chasing that point keeps the geometry exact (no drifting, no
    amplitude doubling, no dependence on where the boss happened to be when its
    habit started) and makes the handover from the entry glide a merge instead
    of a jump.
    """
    k = min(1.0, rate * dt)
    e.x += (tx - e.x) * k
    e.y += (ty - e.y) * k
    e.vx = e.vy = 0.0


def _pendulum(e: Any, dt: float, habit: Any, px: float,
              rng: random.Random, cx: float) -> None:
    """Hang from the middle of the band and swing wide, slow and heavy."""
    half = (C.FIELD_RIGHT - C.FIELD_LEFT) / 2.0 - e.r - 16.0
    w = 0.5 * habit.speed
    _follow(e, dt,
            cx + half * math.sin(e.t * w + e.phase),
            C.BOSS_ENTRY_Y + 18.0 * math.sin(e.t * 1.05))


def _orbit(e: Any, dt: float, habit: Any, px: float,
           rng: random.Random, cx: float) -> None:
    """Cycle an ellipse: it is never in the corner you aimed at."""
    half = (C.FIELD_RIGHT - C.FIELD_LEFT) / 2.0 - e.r - 40.0
    w = 0.6 * habit.speed
    mid = (BAND_LO + BAND_HI) / 2.0
    _follow(e, dt,
            cx + half * math.sin(e.t * w + e.phase),
            mid + 28.0 * math.cos(e.t * w + e.phase))


def _hunt(e: Any, dt: float, habit: Any, px: float,
          rng: random.Random, cx: float) -> None:
    """Slide over the player's head. Standing still under it is fatal."""
    limit = 150.0 * habit.speed
    dx = px - e.x
    e.vx = 0.0 if abs(dx) < 14.0 else P.clamp(dx * 2.2, -limit, limit)
    e.vy = 18.0 * math.sin(e.t * 0.9)


def _lunge(e: Any, dt: float, habit: Any, px: float,
           rng: random.Random, cx: float) -> None:
    """Pitch down to the bottom of the band, hold, climb back: commitment."""
    period = 3.4 / habit.speed
    p = (e.t % period) / period
    # 0-45% high, 45-62% dive, 62-78% low, 78-100% climb.
    if p < 0.45:
        ty = BAND_LO + 6.0
    elif p < 0.62:
        ty = _mix(BAND_LO + 6.0, BAND_HI, (p - 0.45) / 0.17)
    elif p < 0.78:
        ty = BAND_HI
    else:
        ty = _mix(BAND_HI, BAND_LO + 6.0, (p - 0.78) / 0.22)
    e.vy = (ty - e.y) * 3.4
    e.vx = 46.0 * e.drift_dir * habit.speed
    lo, hi = _band(e)
    if e.x < lo + 10.0:
        e.drift_dir = 1
    elif e.x > hi - 10.0:
        e.drift_dir = -1


def _eight(e: Any, dt: float, habit: Any, px: float,
           rng: random.Random, cx: float) -> None:
    """Trace a figure of eight, crossing itself over the player's lane."""
    half = (C.FIELD_RIGHT - C.FIELD_LEFT) / 2.0 - e.r - 60.0
    mid = (BAND_LO + BAND_HI) / 2.0
    th = e.t * 0.55 * habit.speed + e.phase
    _follow(e, dt, cx + half * math.sin(th), mid + 36.0 * math.sin(2.0 * th))


def _hop(e: Any, dt: float, habit: Any, px: float,
         rng: random.Random, cx: float) -> None:
    """Judder between anchor points: it parks, snaps sideways, parks again."""
    lo, hi = _band(e)
    if e.boss_anchor == 0.0 or abs(e.x - e.boss_anchor) < 12.0:
        e.boss_timer -= dt
        if e.boss_timer <= 0.0:
            e.boss_timer = 1.35 / habit.speed
            e.boss_anchor = rng.uniform(lo, hi)
    dx = e.boss_anchor - e.x
    e.vx = 0.0 if abs(dx) < 4.0 else P.clamp(dx * 6.0, -360.0, 360.0)
    e.vy = (C.BOSS_ENTRY_Y - e.y) * 1.6 + 12.0 * math.sin(e.t * 1.6)


def _edge(e: Any, dt: float, habit: Any, px: float,
          rng: random.Random, cx: float) -> None:
    """Fight from cover: dart to a wall, hug it, then cross to the other."""
    lo, hi = _band(e)
    e.boss_timer -= dt
    if e.boss_timer <= 0.0:
        e.drift_dir = -e.drift_dir
        e.boss_timer = 1.1      # seconds spent hugging the wall
    target = lo + 18.0 if e.drift_dir < 0 else hi - 18.0
    dx = target - e.x
    if abs(dx) < 6.0:
        e.vx = 0.0
    else:
        e.vx = P.clamp(dx * 4.0, -330.0 * habit.speed, 330.0 * habit.speed)
    e.vy = 12.0 * math.sin(e.t * 1.3)


def _stalker(e: Any, dt: float, habit: Any, px: float,
             rng: random.Random, cx: float) -> None:
    """Loom: take the bottom of the band, weave wide, and stay there."""
    e.vy = (BAND_HI - 4.0 - e.y) * 1.4 + 8.0 * math.sin(e.t * 1.7)
    e.vx = 128.0 * math.sin(e.t * 0.52) * habit.speed


_MOVES: dict[str, MoveFn] = {
    "strafe": _strafe,
    "pendulum": _pendulum,
    "orbit": _orbit,
    "hunt": _hunt,
    "lunge": _lunge,
    "eight": _eight,
    "hop": _hop,
    "edge": _edge,
    "stalker": _stalker,
}


def move(e: Any, dt: float, habit: Any, px: float, rng: random.Random) -> None:
    """Advance one boss's movement for one step, entry phase included.

    ``boss_step`` is the phase clock: negative while the boss is still coming
    on screen, then the time it has been fighting. ``boss_timer`` and
    ``boss_anchor`` belong to whichever strategy is running.
    """
    cx = (C.FIELD_LEFT + C.FIELD_RIGHT) / 2.0
    if not e.boss_ready:
        e.boss_ready = True
        e.boss_step = -1.0
        e.boss_timer = 0.8
        e.boss_anchor = 0.0
        _begin_entry(e, habit, cx)
    if e.boss_step < 0.0:
        if _glide(e, dt, habit):
            e.boss_step = 0.01
            e.vx = e.vy = 0.0
        return
    e.boss_step += dt
    strategy = _MOVES.get(habit.move, _strafe)
    strategy(e, dt, habit, px, rng, cx)
    keep_in_band(e)


# ---------------------------------------------------------------------------
# Attack primitives
# ---------------------------------------------------------------------------
def _aimed(e: Any, atk: Any, n: int, px: float, py: float,
           fire: FireFn, speed: float, rng: random.Random) -> None:
    """A spread centred on the player. Honest, and it never misses by much."""
    ox, oy = e.x, e.y + e.r * 0.45
    base = P.to_deg(px - ox, py - oy)
    for i in range(n):
        ang = base + (_mix(-atk.arc / 2, atk.arc / 2, i / (n - 1))
                      if n > 1 else 0.0)
        vx, vy = P.from_deg(ang, speed * atk.speed)
        fire(ox, oy, vx, vy)


def _fan(e: Any, atk: Any, n: int, px: float, py: float,
         fire: FireFn, speed: float, rng: random.Random) -> None:
    """A fixed downward fan. It does not track you; it covers the sky."""
    ox, oy = e.x, e.y + e.r * 0.45
    for i in range(n):
        ang = DOWN + (_mix(-atk.arc / 2, atk.arc / 2, i / (n - 1))
                      if n > 1 else 0.0)
        vx, vy = P.from_deg(ang, speed * atk.speed)
        fire(ox, oy, vx, vy)


def _ring(e: Any, atk: Any, n: int, px: float, py: float,
          fire: FireFn, speed: float, rng: random.Random) -> None:
    """A full 360 ring, slowly rotating between volleys."""
    base = e.t * atk.param
    for i in range(n):
        vx, vy = P.from_deg(base + 360.0 * i / n, speed * atk.speed)
        fire(e.x, e.y, vx, vy)


def _spiral(e: Any, atk: Any, n: int, px: float, py: float,
            fire: FireFn, speed: float, rng: random.Random) -> None:
    """Arms stepped by volley index, so fast volleys draw a spiral."""
    base = e.boss_shot * atk.param
    for i in range(n):
        vx, vy = P.from_deg(base + 360.0 * i / n, speed * atk.speed)
        fire(e.x, e.y, vx, vy)


def _pinwheel(e: Any, atk: Any, n: int, px: float, py: float,
              fire: FireFn, speed: float, rng: random.Random) -> None:
    """Fast thin spokes thrown like lancelets: cuts the screen, never fills it."""
    base = e.t * atk.param
    for i in range(n):
        ang = base + 360.0 * i / n
        vx, vy = P.from_deg(ang, 1.0)
        for step in (0.55, 1.05):
            fire(e.x + vx * e.r * step, e.y + vy * e.r * step,
                 vx * speed * atk.speed, vy * speed * atk.speed)


def _wall(e: Any, atk: Any, n: int, px: float, py: float,
          fire: FireFn, speed: float, rng: random.Random) -> None:
    """A full-width curtain with one reachable gap, in a new place each time."""
    y = min(BAND_HI + 26.0, e.y + e.r * 0.7)
    lo, hi = C.FIELD_LEFT + 14.0, C.FIELD_RIGHT - 14.0
    gap = max(96.0, atk.param)
    centre = rng.uniform(lo + gap / 2.0, hi - gap / 2.0)
    step = (hi - lo) / (n + 1)
    for i in range(1, n + 1):
        x = lo + step * i
        if abs(x - centre) < gap / 2.0:
            continue
        fire(x, y, 0.0, speed * atk.speed)


def _mine(e: Any, atk: Any, n: int, px: float, py: float,
          fire: FireFn, speed: float, rng: random.Random) -> None:
    """Near-hovering orbs that hang in the air as a curtain to thread."""
    oy = e.y + e.r * 0.4
    for i in range(n):
        ang = DOWN + (_mix(-atk.arc / 2, atk.arc / 2, i / (n - 1))
                      if n > 1 else 0.0)
        vx, vy = P.from_deg(ang, speed * atk.speed * 0.22)
        fire(e.x, oy, vx, vy)


def _shell(e: Any, atk: Any, n: int, px: float, py: float,
           fire: FireFn, speed: float, rng: random.Random) -> None:
    """Cluster shells lobed into your retreat; they burst later, where you went."""
    oy = e.y + e.r * 0.5
    for i in range(n):
        ang = DOWN + (_mix(-18.0, 18.0, i / (n - 1)) if n > 1 else 0.0)
        vx, vy = P.from_deg(ang, speed * atk.speed * 0.72)
        fire(e.x, oy, vx, vy, shell=max(1, atk.frag), fuse=atk.fuse)


def _spray(e: Any, atk: Any, n: int, px: float, py: float,
           fire: FireFn, speed: float, rng: random.Random) -> None:
    """Chaotic cone. Uneven, sloppier, and unnerving precisely because of it."""
    ox, oy = e.x, e.y + e.r * 0.45
    for _ in range(n):
        ang = DOWN + rng.uniform(-atk.arc / 2.0, atk.arc / 2.0)
        vx, vy = P.from_deg(ang, speed * atk.speed * rng.uniform(0.8, 1.15))
        fire(ox, oy, vx, vy)


def _beam(e: Any, atk: Any, n: int, px: float, py: float,
          fire: FireFn, speed: float, rng: random.Random) -> None:
    """A sweeping lance: several bullets along one ray, fast, then it pans."""
    ang = DOWN + atk.arc * math.sin(e.t * math.radians(atk.param))
    dx, dy = P.from_deg(ang, 1.0)
    for i in range(n):
        stand = e.r * 0.55 + i * 30.0
        fire(e.x + dx * stand, e.y + dy * stand,
             dx * speed * atk.speed, dy * speed * atk.speed)


_ATTACKS: dict[str, ShotFn] = {
    "aimed": _aimed,
    "fan": _fan,
    "ring": _ring,
    "spiral": _spiral,
    "pinwheel": _pinwheel,
    "wall": _wall,
    "mine": _mine,
    "shell": _shell,
    "spray": _spray,
    "beam": _beam,
}


def attack(e: Any, atk: Any, px: float, py: float, fire: FireFn,
           speed: float, enraged: bool, extra: int,
           rng: random.Random) -> None:
    """Fire one volley of a boss's sequence."""
    shot = _ATTACKS.get(atk.kind, _aimed)
    shot(e, atk, max(1, atk.count + (extra if enraged else 0)),
         px, py, fire, speed, rng)


__all__ = ["BAND_HI", "BAND_LO", "attack", "keep_in_band", "move"]
