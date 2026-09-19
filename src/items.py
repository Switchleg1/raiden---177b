"""Falling power-ups & hazards — the Raiden Shadow "power system".

Direct analogue of Breakout Classic's item system: a killed enemy may drop one
falling item, chosen from a weighted table (:data:`config.ITEM_WEIGHTS`). The
player collects an item by flying into it; beneficial items upgrade the craft
and hazard items punish it. The whole system is on/off via ``Settings.powerups``
and every drop is drawn from the game's seeded RNG, so a run is reproducible.

Applying an item's effect is the :class:`~raiden_shadow.game.Game` model's job;
this module only models the falling entity and the weighted selection.
"""

from __future__ import annotations

import random

import config as C


class Item:
    """A single falling item. Falls straight down until collected or off-screen."""

    __slots__ = ("kind", "x", "y", "vx", "vy", "size", "alive", "phase")

    def __init__(self, kind: C.ItemKind, x: float, y: float):
        self.kind = kind
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = C.ITEM_FALL_SPEED
        self.size = C.ITEM_SIZE
        self.alive = True
        # Drawing-only offset in 0..1 for the shared orbiting aura and the
        # pod's own animation, so a cluster of five pickups does not pulse in
        # lockstep. Quantised from where it spawned rather than drawn from the
        # game's RNG: the aura is a renderer concern, and letting it consume
        # the run's stream would make *gameplay* depend on how many pickups
        # happened to be drawn. Never wall-clock or id() either, so a recorded
        # run animates identically. Gameplay ignores this field.
        k = sum(ord(ch) for ch in str(getattr(kind, "value", kind)))
        self.phase = abs(x) * 0.0371 + abs(y) * 0.0113 + k * 0.173
        self.phase -= int(self.phase)

    def update(self, dt: float) -> None:
        self.y += self.vy * dt
        if self.y > C.FIELD_BOTTOM + self.size:
            self.alive = False


def build_weights(table: tuple[tuple[str, int], ...] | None = None
                  ) -> tuple[list[C.ItemKind], list[float]]:
    """Turn the weight table into parallel (kinds, weights) lists."""
    tbl = table if table is not None else C.ITEM_WEIGHTS
    kinds: list[C.ItemKind] = []
    weights: list[float] = []
    for name, w in tbl:
        if w <= 0:
            continue
        try:
            kinds.append(C.ItemKind(name))
        except ValueError:
            continue
        weights.append(float(w))
    return kinds, weights


def roll_item(rng: random.Random,
              table: tuple[tuple[str, int], ...] | None = None) -> C.ItemKind:
    kinds, weights = build_weights(table)
    if not kinds:
        return C.ItemKind.MEDAL
    return rng.choices(kinds, weights=weights, k=1)[0]


__all__ = ["Item", "roll_item", "build_weights"]
