"""One enemy; movement/firing behaviour is per :class:`EnemyKind`."""
from __future__ import annotations

import math
import random

import config as C
import physics as P

from . import bosskit


class Enemy:
    """One enemy. Movement/firing is per :class:`EnemyKind`."""

    __slots__ = ("kind", "x", "y", "vx", "vy", "r", "hp", "max_hp", "score",
                 "drop", "alive", "t", "amp", "freq", "phase", "hover_y",
                 "fire_timer", "color", "sheet", "flash", "boss_shot",
                 "drift_dir", "lock_x",
                 # BOSS: habit phase clock (negative while entering), the
                 # running strategy's own timer, its next anchor x, and the
                 # volley index reached in the habit's attack list.
                 "boss_step", "boss_timer", "boss_anchor", "boss_ready",
                 "_rng")

    def __init__(self, kind: C.EnemyKind, x: float, y: float):
        spec = C.ENEMY_SPECS[kind]
        self.kind = kind
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = spec.speed
        self.r = spec.r
        self.hp = spec.hp
        self.max_hp = spec.hp
        self.score = spec.score
        self.drop = spec.drop
        self.alive = True
        self.t = 0.0
        self.amp = 0.0
        self.freq = 0.0
        self.phase = 0.0
        self.hover_y = 0.0
        self.fire_timer = spec.fire_cd
        self.color = spec.color
        # Per-sector art override (bosses); None -> ENEMY_SHEET[kind].
        self.sheet: str | None = None
        self.flash = 0.0
        self.boss_shot = 0
        self.boss_step = 0.0
        self.boss_timer = 0.0
        self.boss_anchor = 0.0
        self.boss_ready = False
        self.drift_dir = 1
        # RAMMER: the column it painted during its lock-on window.
        self.lock_x = x
        # Per-call RNG reference: update() injects the game's seeded rng so the
        # whole simulation is reproducible; the private default is never used
        # directly (update always supplies the game's rng).
        self._rng: random.Random = random.Random()

    @classmethod
    def spawn(cls, kind: C.EnemyKind, x: float, y: float,
              level: int = 0, hp_override: int | None = None,
              rng: random.Random | None = None) -> Enemy:
        """Spawn an enemy; pass the game's seeded ``rng`` for reproducibility."""
        r = rng if rng is not None else random
        e = cls(kind, x, y)
        e.drift_dir = 1 if r.random() < 0.5 else -1
        spec = C.ENEMY_SPECS[kind]
        e.fire_timer = spec.fire_cd * r.uniform(0.5, 1.0)
        if hp_override is not None:
            e.hp = hp_override
            e.max_hp = hp_override
        # WEAVER: sinusoidal horizontal velocity.
        e.amp = 90.0 + 8.0 * level
        e.freq = 2.2 + 0.1 * level
        e.phase = r.uniform(0.0, math.tau)
        # GUNNER / SENTRY / HEAVY / BOSS: hover band.
        e.hover_y = r.uniform(C.FIELD_TOP + 70.0, C.FIELD_TOP + 180.0)
        if kind is C.EnemyKind.BOSS:
            e.hover_y = C.BOSS_ENTRY_Y
            e.vy = 60.0
        # DARTER: aim a fast dive toward the field centre-ish on spawn. The
        # angle is measured from straight DOWN (+y) and clamped, so the darter
        # always descends.
        if kind is C.EnemyKind.DARTER:
            tx = r.uniform(C.FIELD_LEFT + 60, C.FIELD_RIGHT - 60)
            ang = math.degrees(math.atan2(tx - x, C.PLAYER_START_Y - y))
            ang = math.radians(P.clamp(ang, -42.0, 42.0))
            speed = C.ENEMY_SPECS[kind].speed
            e.vx, e.vy = math.sin(ang) * speed, math.cos(ang) * speed
        return e

    def hurt(self, dmg: int) -> bool:
        """Apply damage; returns True if this hit killed the enemy."""
        self.hp -= dmg
        self.flash = 0.08
        if self.hp <= 0:
            self.alive = False
            return True
        return False

    def update(self, dt: float, player_x: float, player_y: float,
               fire, bullet_speed: float, rng: random.Random) -> None:
        """Advance one step.

        ``fire(x, y, vx, vy, shell=0, fuse=0.0)`` emits an enemy bullet; a
        non-zero ``shell`` asks the game for a cluster shell that bursts into
        that many fragments once ``fuse`` seconds are up.
        """
        self._rng = rng
        self.t += dt
        if self.flash > 0.0:
            self.flash = max(0.0, self.flash - dt)
        kind = self.kind
        if kind is C.EnemyKind.GRUNT:
            self.vy = C.ENEMY_SPECS[kind].speed
            self.vx = 0.0
            self._maybe_fire_aimed(dt, player_x, player_y, fire, bullet_speed, 1)
        elif kind is C.EnemyKind.WEAVER:
            self.vy = C.ENEMY_SPECS[kind].speed
            self.vx = self.amp * math.cos(self.freq * self.t + self.phase)
        elif kind is C.EnemyKind.DARTER:
            pass  # constant aimed dive set at spawn
        elif kind is C.EnemyKind.GUNNER:
            self._descend_or_hover(dt, speed=C.ENEMY_SPECS[kind].speed)
            self._drift(dt, speed=60.0)
            self._maybe_fire_aimed(dt, player_x, player_y, fire, bullet_speed, 1)
        elif kind is C.EnemyKind.SENTRY:
            self._descend_or_hover(dt, speed=C.ENEMY_SPECS[kind].speed)
            self._maybe_fire_radial(dt, fire, bullet_speed, 6)
        elif kind is C.EnemyKind.HEAVY:
            self._descend_or_hover(dt, speed=C.ENEMY_SPECS[kind].speed,
                                   stop_margin=40.0)
            self._drift(dt, speed=40.0)
            self._maybe_fire_aimed(dt, player_x, player_y, fire, bullet_speed, 3)
        elif kind is C.EnemyKind.BOMBER:
            # Holds a high band and seeds the screen; the shells it drops keep
            # arriving long after it turned into a fireball.
            self._descend_or_hover(dt, speed=C.ENEMY_SPECS[kind].speed,
                                   stop_margin=26.0)
            self._drift(dt, speed=34.0)
            self._maybe_fire_shells(dt, fire, bullet_speed)
        elif kind is C.EnemyKind.SPLITTER:
            # Wide lazy weave: the children it leaves behind do the chasing.
            self.vy = C.ENEMY_SPECS[kind].speed
            self.vx = 1.15 * self.amp * math.cos(self.freq * self.t
                                                 + self.phase)
        elif kind is C.EnemyKind.RAMMER:
            self._update_rammer(dt, player_x)
        elif kind is C.EnemyKind.SHARD:
            spec = C.ENEMY_SPECS[kind]
            self.vy = spec.speed
            self.vx = spec.speed * C.SHARD_SPREAD * self.drift_dir
        elif kind is C.EnemyKind.BOSS:
            self._update_boss(dt, player_x, player_y, fire, bullet_speed, rng)
        P.advance(self, dt, max_step=8.0)
        # Side walls: bounce drifters so they never leave the field sideways.
        if kind in (C.EnemyKind.GUNNER, C.EnemyKind.SENTRY, C.EnemyKind.HEAVY,
                    C.EnemyKind.BOMBER, C.EnemyKind.BOSS):
            if kind is C.EnemyKind.BOSS and self.boss_step < 0.0:
                # Scripted entry: a boss that sails in from the side is meant to
                # start outside the field, so no wall rule applies yet.
                return
            lo = C.FIELD_LEFT + self.r
            hi = C.FIELD_RIGHT - self.r
            if self.x < lo:
                self.x = lo
                self.drift_dir = 1
            elif self.x > hi:
                self.x = hi
                self.drift_dir = -1
            if kind is C.EnemyKind.BOSS:
                # Re-clamp after integrating: no fighting boss leaves its band.
                bosskit.keep_in_band(self)

    # -- movement helpers --------------------------------------------------
    def _descend_or_hover(self, dt: float, speed: float,
                          stop_margin: float = 0.0) -> None:
        if self.y < self.hover_y:
            self.vy = speed
        else:
            self.vy = 0.0

    def _drift(self, dt: float, speed: float) -> None:
        self.vx = speed * self.drift_dir
        if self._rng.random() < 0.004:
            self.drift_dir *= -1

    # -- firing helpers ----------------------------------------------------
    def _fire_gate(self, dt: float, cd: float) -> bool:
        self.fire_timer -= dt
        if self.fire_timer <= 0.0:
            self.fire_timer = cd * self._rng.uniform(0.8, 1.2)
            return True
        return False

    def _aim(self, px: float, py: float, speed: float) -> tuple[float, float]:
        ang = P.to_deg(px - self.x, py - self.y)
        return P.from_deg(ang, speed)

    def _maybe_fire_aimed(self, dt: float, px: float, py: float, fire,
                          speed: float, count: int) -> None:
        if not self.alive or self.y <= C.FIELD_TOP + 10:
            return
        if not self._fire_gate(dt, C.ENEMY_SPECS[self.kind].fire_cd):
            return
        for i in range(count):
            spread = (i - (count - 1) / 2) * 9.0
            vx, vy = self._aim(px, py, speed)
            ang = P.to_deg(vx, vy) + spread
            vx, vy = P.from_deg(ang, speed)
            fire(self.x, self.y + self.r, vx, vy)

    def _maybe_fire_shells(self, dt: float, fire, speed: float) -> None:
        """Drop one cluster shell per bomb-bay drum.

        The shell is a fat, slow bullet carrying ``shell``/``fuse``; the game
        bursts it into fragments later, which is what makes a bomber worth
        killing before it gets overhead.
        """
        if not self.alive or self.y <= C.FIELD_TOP + 10:
            return
        spec = C.ENEMY_SPECS[self.kind]
        if not self._fire_gate(dt, spec.fire_cd):
            return
        shell_speed = speed * C.SHELL_SPEED
        for side in (-1.0, 1.0):
            # Angle 0 is straight down, so this is a dead-fall splay, not a
            # homing shot: shells are dropped, and the player outruns them.
            vx, vy = P.from_deg(side * 7.0, shell_speed)
            fire(self.x + side * self.r * 0.55, self.y + self.r * 0.8,
                 vx, vy, shell=spec.shell_frag, fuse=spec.shell_fuse)

    def _update_rammer(self, dt: float, player_x: float) -> None:
        """Paint a column, then commit to it.

        While the lock is open the rammer tracks the player almost lazily and
        barely descends; once it closes the column is frozen, so a sideways
        dodge at the last second works and the charge just falls past.
        """
        spec = C.ENEMY_SPECS[C.EnemyKind.RAMMER]
        if self.t <= C.RAMMER_LOCK_TIME:
            # The lock slides toward the player at a readable speed instead of
            # snapping, so moving early breaks it and moving late does not.
            step = C.RAMMER_DRIFT * dt
            self.lock_x += max(-step, min(step, player_x - self.lock_x))
            self.vx = 0.0
            self.vy = spec.speed * 0.14
            return
        ramp = min(1.0, (self.t - C.RAMMER_LOCK_TIME)
                   / max(C.RAMMER_RAMP, 1e-3))
        ang = P.to_deg(self.lock_x - self.x,
                       C.PLAYER_START_Y - self.y)
        vx, vy = P.from_deg(ang, spec.speed * (0.55 + 0.45 * ramp))
        self.vx, self.vy = vx, vy

    def _maybe_fire_radial(self, dt: float, fire, speed: float, n: int) -> None:
        if not self.alive or self.y <= C.FIELD_TOP + 10:
            return
        if not self._fire_gate(dt, C.ENEMY_SPECS[self.kind].fire_cd):
            return
        base = self.t * 40.0
        for i in range(n):
            ang = (360.0 / n) * i + base
            vx, vy = P.from_deg(ang, speed * 0.7)
            fire(self.x, self.y, vx, vy)

    def _update_boss(self, dt: float, px: float, py: float, fire, speed: float,
                     rng: random.Random) -> None:
        """Boss: play this sector's habit.

        Which boss you are fighting is data (:data:`config.BOSS_HABITS`, keyed
        by sprite sheet); :mod:`entities.bosskit` implements the movement and
        volley vocabulary it is written in. The enemy keeps only the state the
        performance needs - phase clock, strategy timer, next anchor, volley
        index - so a sector ten boss is a table entry, not a new method.

        (The old shared routine also aimed its "downward" fan with angles
        measured from straight *up*, so half of its shots left the top of the
        screen; the primitives here are explicit about the convention.)
        """
        habit = C.habit_for(self.sheet)
        bosskit.move(self, dt, habit, px, rng)
        if self.boss_step < 0.0:
            # Still coming on screen: hold the trigger, but keep it warm so the
            # boss answers the moment it settles.
            self.fire_timer = max(0.0, self.fire_timer - dt)
            return
        fraction = self.hp / max(1, self.max_hp)
        enraged = fraction < habit.enrage_at
        self.fire_timer -= dt
        if self.fire_timer > 0.0:
            return
        attack = habit.attacks[self.boss_shot % len(habit.attacks)]
        self.boss_shot += 1
        bosskit.attack(self, attack, px, py, fire, speed, enraged,
                       habit.enrage_count, rng)
        self.fire_timer = attack.cd * (habit.enrage_cd if enraged else 1.0)
