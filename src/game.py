"""Gameplay model for Raiden Shadow — entities, scoring, waves, boss, power-ups.

:class:`Game` owns the player craft, projectiles, enemies and falling items and
applies the primitives from :mod:`physics` / behaviours from :mod:`entities`. It
imports no pygame and owns no state machine: :meth:`Game.update` advances one
fixed step and returns a list of event dicts (``{"type": ..., ...}``) exactly as
Breakout Classic's model does, so :mod:`app` keeps the state machine, audio and
effects wiring unchanged in spirit.

Event ``type`` values include the high-level signals

    life_lost, level_clear, game_over, victory, powerup, hazard, bomb

plus flavour events used only for audio/particles::

    shoot, missile, enemy_killed, boss_spawn, boss_down, item_drop, medal
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

import config as C
import physics as P
from entities import Bullet, Enemy, Player, Whip
from items import Item, roll_item

# High-level outcome signals (shared names with Breakout Classic's model).
SIG_LIFE_LOST = "life_lost"
SIG_LEVEL_CLEAR = "level_clear"
SIG_GAME_OVER = "game_over"
SIG_VICTORY = "victory"
SIG_POWERUP = "powerup"
SIG_HAZARD = "hazard"
SIG_BOMB = "bomb"
SIG_BOSS = "boss_spawn"


@dataclass
class Game:
    rng: random.Random = field(default_factory=random.Random)
    high_score: int = 0
    enable_items: bool = True

    level_index: int = 0
    score: int = 0
    lives: int = C.START_LIVES
    bonus_awarded: int = 0

    player: Player = field(init=False)
    bullets: list[Bullet] = field(default_factory=list)
    enemies: list[Enemy] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)

    run_enemies_destroyed: int = 0
    # Energy-whip power (timed): timer > 0 means the lash is out and the
    # vulcan is replaced. whip_clock drives per-enemy re-hit cooldowns.
    whip_timer: float = 0.0
    whip_clock: float = 0.0
    whip: Whip = field(init=False)
    _whip_cd: dict[int, float] = field(init=False, default_factory=dict)
    _started: bool = False
    _wave_timer: float = 0.0
    _spawn_timer: float = 0.0
    _boss_spawned: bool = False
    _escort_timer: float = 0.0
    _cleared: bool = False

    def __post_init__(self) -> None:
        self.player = Player()
        self.whip = Whip()
        self._whip_cd = {}

    @property
    def whip_active(self) -> bool:
        return self.whip_timer > 0.0

    # ------------------------------------------------------------------ setup
    def new_game(self) -> None:
        self.level_index = 0
        self.score = 0
        self.lives = C.START_LIVES
        self.bonus_awarded = 0
        self.run_enemies_destroyed = 0
        self._started = True
        self.start_level(0)

    def start_level(self, index: int, keep_power: bool = False) -> None:
        """Begin a sector. ``keep_power`` carries the loadout across sectors.

        Arcade convention is that dying wipes your upgrades, and that stays
        true: ``_serve_craft`` calls ``full_restore``. Clearing a sector is a
        reward, not a wipe - the weapon and missile levels you earned roll into
        the next sector with you.
        """
        carried = None
        if keep_power:
            carried = (self.player.weapon_level, self.player.missile_level)
        self.level_index = max(0, min(index, C.FINAL_LEVEL_INDEX))
        self._wave_timer = 0.0
        self._spawn_timer = 0.35
        self._boss_spawned = False
        self._escort_timer = 0.0
        self._cleared = False
        self._started = True
        self.enemies = []
        self.bullets = []
        self.items = []
        self._serve_craft()
        if carried is not None:
            self.player.weapon_level, self.player.missile_level = carried

    def advance_level(self) -> None:
        # Sector cleared: the loadout comes with the player.
        self.start_level(self.level_index + 1, keep_power=True)

    def is_final_level(self) -> bool:
        return self.level_index >= C.FINAL_LEVEL_INDEX

    def boss_alive(self) -> bool:
        """True while a sector boss is on screen (drives music and escorts)."""
        return any(e.alive and e.kind is C.EnemyKind.BOSS for e in self.enemies)

    def wave_progress(self) -> float:
        """0..1 through this sector's pre-boss wave (1.0 once the boss is out).

        Read-only progress for the loader: half-way through the wave is the last
        quiet moment before a boss appears, so it is when its art gets warmed.
        """
        if self._boss_spawned:
            return 1.0
        return min(1.0, self._wave_timer / max(0.001, self._spec().wave_seconds))

    def boss_hp_fraction(self) -> float | None:
        """The boss's remaining hull as 0..1, or None when no boss is live.

        The App watches this so the *next* sector starts loading while the
        player is still shooting: when the boss is halved, what replaces it is
        already being built off-thread.
        """
        for e in self.enemies:
            if e.alive and e.kind is C.EnemyKind.BOSS:
                return max(0.0, min(1.0, e.hp / max(1.0, float(e.max_hp))))
        return None

    def boss_sheet(self, index: int | None = None) -> str:
        """Art/behaviour key of a sector's boss (default: the current one)."""
        i = (self.level_index if index is None else
             max(0, min(int(index), C.FINAL_LEVEL_INDEX)))
        return C.LEVELS[i].boss

    def _serve_craft(self) -> None:
        self.player.full_restore()
        self.whip_timer = 0.0          # arcade: the lash dies with the craft
        self._whip_cd.clear()
        self.whip = Whip()
        self.bullets = []
        self.items = []
        # Keep any boss/enemies? On respawn mid-wave we clear the field of shots
        # so re-entry is fair; enemies remain.
        for b in self.bullets:
            if not b.friendly:
                b.alive = False

    def commit_high_score(self) -> None:
        if self.score > self.high_score:
            self.high_score = self.score

    # --------------------------------------------------------------- helpers
    def _spec(self) -> C.LevelSpec:
        return C.LEVELS[self.level_index]

    def _fire_enemy_bullet(self, x: float, y: float, vx: float, vy: float,
                           events: list[dict[str, Any]],
                           shell: int = 0, fuse: float = 0.0) -> None:
        if len(self.bullets) >= C.MAX_BULLETS:
            return
        # A cluster shell is fatter than a bolt and carries its own burst.
        self.bullets.append(Bullet(x, y, vx, vy,
                                   C.SHELL_R if shell else C.ENEMY_BULLET_R,
                                   1, friendly=False,
                                   split_in=fuse if shell else 0.0,
                                   frag=shell))

    def _burst_shells(self, bullet_speed: float) -> None:
        """Detonate every cluster shell whose fuse has run out.

        Fragments leave as ordinary enemy bullets, so dodging rules, bomb
        clearing and the bullet cap all keep applying to them.
        """
        hatched = [b for b in self.bullets
                   if b.alive and not b.friendly and b.frag
                   and b.split_in <= 0.0]
        for b in hatched:
            b.alive = False
            self._spawn_fragments(b.x, b.y, b.frag, bullet_speed)

    def _spawn_fragments(self, x: float, y: float, n: int,
                         bullet_speed: float) -> None:
        if n <= 0:
            return
        speed = bullet_speed * C.FRAG_SPEED
        if C.FRAG_SPREAD_DEG >= 360.0:
            base = self.rng.uniform(0.0, 360.0)
            angles = [base + 360.0 * i / n for i in range(n)]
        else:
            span = C.FRAG_SPREAD_DEG
            step = span / (n - 1) if n > 1 else 0.0
            angles = [-span / 2 + step * i for i in range(n)]
        for ang in angles:
            if len(self.bullets) >= C.MAX_BULLETS:
                return
            vx, vy = P.from_deg(ang, speed)
            self.bullets.append(Bullet(x, y, vx, vy, C.ENEMY_BULLET_R, 1,
                                       friendly=False))

    def _pick_spawn_kind(self) -> C.EnemyKind:
        spec = self._spec()
        kinds = [k for k, _ in spec.spawns]
        weights = [w for _, w in spec.spawns]
        return C.EnemyKind(self.rng.choices(kinds, weights=weights, k=1)[0])

    def _spawn_formation(self, events: list[dict[str, Any]]) -> None:
        kind = self._pick_spawn_kind()
        spec = C.ENEMY_SPECS[kind]
        # small formation: a single, a horizontal line, or a V of the same kind
        roll = self.rng.random()
        if kind in (C.EnemyKind.HEAVY, C.EnemyKind.SENTRY):
            count = 1
        elif roll < 0.5:
            count = 1
        elif roll < 0.85:
            count = 3
        else:
            count = 5
        gap = spec.r * 2 + 14.0
        total = gap * (count - 1)
        start_x = self.rng.uniform(C.FIELD_LEFT + 40, C.FIELD_RIGHT - 40 - total)
        for i in range(count):
            x = start_x + gap * i
            x = P.clamp(x, C.FIELD_LEFT + spec.r, C.FIELD_RIGHT - spec.r)
            y = C.FIELD_TOP - 30.0 - 26.0 * abs(i - (count - 1) / 2)
            self.enemies.append(
                Enemy.spawn(kind, x, y, level=self.level_index, rng=self.rng))

    def _update_escorts(self, dt: float) -> None:
        """Boss escorts: keep the fight two-layered while the boss is up.

        A boss screen with nothing else on it is a strafing gallery. Small
        craft bleed out of the boss on a sector-scaled timer, capped so the
        screen never stops being readable, and they stop the moment the boss
        dies (the sector is already won at that point).
        """
        if self._cleared or not self.boss_alive():
            return
        self._escort_timer -= dt
        if self._escort_timer > 0.0:
            return
        room = C.escort_cap(self.level_index) - sum(
            1 for e in self.enemies
            if e.alive and e.kind is not C.EnemyKind.BOSS)
        for _ in range(max(0, min(room, C.escort_group(self.level_index)))):
            self._spawn_escort()
        self._escort_timer = C.escort_interval(self.level_index)

    def _spawn_escort(self) -> None:
        """Launch one escort over the top edge from the weighted escort mix."""
        kinds = [k for k, _w in C.ESCORT_SPAWNS]
        weights = [w for _k, w in C.ESCORT_SPAWNS]
        kind = C.EnemyKind(self.rng.choices(kinds, weights=weights, k=1)[0])
        x = self.rng.uniform(C.FIELD_LEFT + 40.0, C.FIELD_RIGHT - 40.0)
        self.enemies.append(Enemy.spawn(kind, x, C.FIELD_TOP - 30.0,
                                        level=self.level_index, rng=self.rng))

    def _spawn_boss(self, events: list[dict[str, Any]]) -> None:
        spec = self._spec()
        boss = Enemy.spawn(C.EnemyKind.BOSS, (C.FIELD_LEFT + C.FIELD_RIGHT) / 2,
                           C.FIELD_TOP - 80.0, level=self.level_index,
                           hp_override=spec.boss_hp, rng=self.rng)
        boss.sheet = spec.boss
        self.enemies.append(boss)
        self._boss_spawned = True
        # Arm the escort director: a short grace period so the boss entrance
        # reads first, then a steady sector-scaled trickle.
        self._escort_timer = C.ESCORT_FIRST_WAVE
        events.append({"type": SIG_BOSS, "name": spec.name})

    # ---------------------------------------------------------------- firing
    def _fire_weapon(self, events: list[dict[str, Any]]) -> None:
        pl = self.player
        streams = C.WEAPON_LEVELS[max(0, min(C.WEAPON_MAX_LEVEL, pl.weapon_level) - 1)]
        for dx, ang in streams:
            if len(self.bullets) >= C.MAX_BULLETS:
                break
            vx, vy = P.from_deg(ang, C.PLAYER_BULLET_SPEED)
            self.bullets.append(Bullet(
                pl.x + dx, pl.y - pl.half, vx, vy,
                C.PLAYER_BULLET_R, C.PLAYER_BULLET_DMG, friendly=True))
        events.append({"type": "shoot"})

    def _fire_missiles(self, events: list[dict[str, Any]]) -> None:
        pl = self.player
        n = C.MISSILE_STREAMS[max(0, min(C.MISSILE_MAX_LEVEL, pl.missile_level))]
        if n <= 0:
            return
        for i in range(n):
            off = -14.0 if i % 2 == 0 else 14.0
            ang = -12.0 if off < 0 else 12.0
            vx, vy = P.from_deg(ang, C.MISSILE_SPEED)
            self.bullets.append(Bullet(
                pl.x + off, pl.y - 4.0, vx, vy,
                C.MISSILE_R, C.MISSILE_DMG + pl.missile_level // 2,
                friendly=True, missile=True))
        events.append({"type": "missile"})

    # ------------------------------------------------------------- apply items
    def _apply_item(self, item: Item, events: list[dict[str, Any]]) -> None:
        kind = item.kind
        pl = self.player
        if kind is C.ItemKind.MEDAL:
            self.score += C.MEDAL_SCORE
            events.append({"type": "medal", "amount": C.MEDAL_SCORE})
            return
        if kind is C.ItemKind.EXTRA_LIFE:
            self.lives = min(self.lives + 1, 9)
            events.append({"type": SIG_POWERUP, "kind": kind.value})
            return
        if kind in C.HAZARDS:
            if kind is C.ItemKind.JAMMER:
                pl.weapon_level = max(C.WEAPON_BASE_LEVEL,
                                      pl.weapon_level - C.JAMMER_DROP_PENALTY)
            events.append({"type": SIG_HAZARD, "kind": kind.value})
            return
        # beneficial upgrades
        if kind is C.ItemKind.WEAPON:
            pl.weapon_level = min(C.WEAPON_MAX_LEVEL, pl.weapon_level + 1)
        elif kind is C.ItemKind.MISSILE:
            pl.missile_level = min(C.MISSILE_MAX_LEVEL, pl.missile_level + 1)
        elif kind is C.ItemKind.BOMB:
            pl.bomb_stock = min(C.BOMB_MAX, pl.bomb_stock + 1)
        elif kind is C.ItemKind.SHIELD:
            pl.shield = max(pl.shield, C.SHIELD_TIME)
        elif kind is C.ItemKind.WHIP:
            self.whip_timer = C.WHIP_TIME      # refresh, does not stack
        events.append({"type": SIG_POWERUP, "kind": kind.value})

    def _maybe_drop_item(self, enemy: Enemy, events: list[dict[str, Any]]) -> None:
        if not self.enable_items or len(self.items) >= C.MAX_ITEMS:
            return
        chance = enemy.drop
        if self.rng.random() < chance:
            kind = roll_item(self.rng)
            it = Item(kind, enemy.x, enemy.y)
            self.items.append(it)
            events.append({"type": "item_drop", "kind": kind.value,
                           "x": it.x, "y": it.y})

    # --------------------------------------------------------------- bombing
    def _use_bomb(self, events: list[dict[str, Any]]) -> None:
        pl = self.player
        if pl.bomb_stock <= 0:
            return
        pl.bomb_stock -= 1
        if C.BOMB_CLEAR_BULLETS:
            for b in self.bullets:
                if not b.friendly:
                    b.alive = False
        for e in self.enemies:
            if not e.alive:
                continue
            if e.kind is C.EnemyKind.BOSS:
                if e.hurt(C.BOMB_BOSS_DAMAGE):
                    self._on_enemy_killed(e, events)
            else:
                if e.hurt(C.BOMB_DAMAGE):
                    self._on_enemy_killed(e, events)
        events.append({"type": SIG_BOMB})

    def _on_enemy_killed(self, enemy: Enemy, events: list[dict[str, Any]]) -> None:
        self.score += enemy.score
        self.run_enemies_destroyed += 1
        events.append({"type": "enemy_killed", "x": enemy.x, "y": enemy.y,
                       "color": list(enemy.color), "kind": enemy.kind.value})
        if enemy.kind is C.EnemyKind.BOSS:
            self._cleared = True
            events.append({"type": "boss_down", "x": enemy.x, "y": enemy.y})
        else:
            self._split_enemy(enemy, events)
            self._maybe_drop_item(enemy, events)

    def _split_enemy(self, parent: Enemy, events: list[dict[str, Any]]) -> None:
        """Break a splitter into its shards.

        Children fan out left/right of the corpse and can split no further, so
        one death always means exactly ``split_count`` extras, never a chain.
        """
        spec = C.ENEMY_SPECS[parent.kind]
        n = spec.split_count
        if spec.split_into is None or n <= 0:
            return
        for i in range(n):
            child = Enemy.spawn(spec.split_into, parent.x, parent.y,
                                level=self.level_index, rng=self.rng)
            off = (i - (n - 1) / 2.0) * parent.r * 1.3
            child.drift_dir = -1 if off < 0.0 else 1
            child.x = P.clamp(parent.x + off,
                              C.FIELD_LEFT + child.r, C.FIELD_RIGHT - child.r)
            self.enemies.append(child)
            events.append({"type": "enemy_split", "x": child.x, "y": child.y,
                           "color": list(child.color),
                           "kind": child.kind.value})

    # ------------------------------------------------------------------ update
    def update(self, dt: float, move_x: float = 0.0, move_y: float = 0.0,
               firing: bool = False, bomb: bool = False) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if not self._started or self._cleared:
            return events
        pl = self.player
        pl.tick_timers(dt)

        if bomb:
            self._use_bomb(events)

        # --- movement -----------------------------------------------------
        mx = P.clamp(move_x, -1.0, 1.0)
        my = P.clamp(move_y, -1.0, 1.0)
        pl.x += mx * C.PLAYER_SPEED * dt
        pl.y += my * C.PLAYER_SPEED * dt
        pl.clamp_to_field()

        # --- firing -------------------------------------------------------
        # The energy whip replaces the vulcan while it lasts (missiles stay).
        if firing and pl.fire_timer <= 0.0 and not self.whip_active:
            self._fire_weapon(events)
            pl.fire_timer = C.WEAPON_FIRE_INTERVAL
        if pl.missile_level > 0 and pl.missile_timer <= 0.0:
            self._fire_missiles(events)
            pl.missile_timer = C.MISSILE_INTERVAL
        if self.whip_timer > 0.0:
            self.whip_clock += dt
            self.whip_timer = max(0.0, self.whip_timer - dt)
            self.whip.update(dt, pl.x, pl.y)
        else:
            self.whip.points = []
            if self._whip_cd:
                self._whip_cd.clear()   # ids may be recycled by new enemies

        # --- spawn director ----------------------------------------------
        spec = self._spec()
        if not self._boss_spawned:
            self._wave_timer += dt
            self._spawn_timer -= dt
            if self._spawn_timer <= 0.0:
                self._spawn_formation(events)
                self._spawn_timer = spec.spawn_interval * self.rng.uniform(0.7, 1.2)
            if self._wave_timer >= spec.wave_seconds:
                self._spawn_boss(events)
        else:
            self._update_escorts(dt)

        # --- advance enemies (they may fire) ------------------------------
        for e in self.enemies:
            if not e.alive:
                continue
            # A boss throws faster than the mooks around it, and by a per-sector
            # amount (LevelSpec.boss_bullet), so lateness buys the boss speed as
            # well as its own habits.
            bullet_speed = spec.bullet_speed * (
                spec.boss_bullet if e.kind is C.EnemyKind.BOSS else 1.0)
            e.update(dt, pl.x, pl.y,
                     lambda x, y, vx, vy, shell=0, fuse=0.0:
                     self._fire_enemy_bullet(x, y, vx, vy, events, shell, fuse),
                     bullet_speed, self.rng)
            if (e.kind is not C.EnemyKind.BOSS
                    and P.offscreen_below(e.y, e.r + 40)):
                e.alive = False  # escaped enemies are removed silently

        # --- advance bullets ------------------------------------------------
        for b in self.bullets:
            if b.alive:
                b.update(dt)
        self._burst_shells(spec.bullet_speed)

        # --- advance items --------------------------------------------------
        for it in self.items:
            if it.alive:
                it.update(dt)

        # --- collisions -----------------------------------------------------
        self._collide(events)

        # --- cleanup --------------------------------------------------------
        self.bullets = [b for b in self.bullets if b.alive]
        self.enemies = [e for e in self.enemies if e.alive]
        self.items = [it for it in self.items if it.alive]

        # --- bonus life -----------------------------------------------------
        if (self.bonus_awarded < C.BONUS_LIFE_MAX
                and self.score >= C.BONUS_LIFE_THRESHOLD):
            self.bonus_awarded += 1
            self.lives = min(self.lives + 1, 9)
            events.append({"type": SIG_POWERUP, "kind": "extra_life"})

        # --- level clear ----------------------------------------------------
        if self._cleared and not any(e.kind is C.EnemyKind.BOSS for e in self.enemies):
            events.append({"type": SIG_LEVEL_CLEAR})
            self._cleared = True  # guard against double emit already handled below
            self._started = False
        return events

    # --------------------------------------------------------------- collisions
    def _collide_whip(self, events: list[dict[str, Any]]) -> None:
        """Contact damage from the lash. Each enemy may be carved at most
        once per WHIP_HIT_CD seconds (the bead has to swing back around)."""
        pts = self.whip.points
        if not pts:
            return
        cd = self._whip_cd
        for k in [k for k, t in cd.items() if t <= self.whip_clock
                  - C.WHIP_HIT_CD]:
            del cd[k]
        for e in self.enemies:
            if not e.alive:
                continue
            if self.whip_clock < cd.get(id(e), 0.0):
                continue
            for wx, wy in pts:
                if P.circle_hit(wx, wy, C.WHIP_BEAD_R, e.x, e.y, e.r):
                    cd[id(e)] = self.whip_clock + C.WHIP_HIT_CD
                    events.append({"type": "whip_hit", "x": e.x, "y": e.y})
                    if e.hurt(C.WHIP_DMG):
                        self._on_enemy_killed(e, events)
                    break

    def _collide(self, events: list[dict[str, Any]]) -> None:
        pl = self.player
        # energy whip first: the lash carves before bullets resolve
        if self.whip_active:
            self._collide_whip(events)
        if self._cleared:
            return
        # friendly bullets vs enemies
        for b in self.bullets:
            if not (b.alive and b.friendly):
                continue
            for e in self.enemies:
                if not e.alive:
                    continue
                if P.circle_hit(b.x, b.y, b.r, e.x, e.y, e.r):
                    b.alive = False
                    if e.hurt(b.dmg):
                        self._on_enemy_killed(e, events)
                    break
        if self._cleared:
            return
        # player vs hazards / enemies / enemy bullets (skipped while protected)
        if not pl.protected:
            hit = False
            for b in self.bullets:
                if (b.alive and not b.friendly
                        and P.circle_hit(b.x, b.y, b.r, pl.x, pl.y, pl.r)):
                    b.alive = False
                    hit = True
                    break
            if not hit:
                for e in self.enemies:
                    if e.alive and P.circle_hit(e.x, e.y, e.r * 0.7, pl.x, pl.y, pl.r):
                        if e.kind is not C.EnemyKind.BOSS:
                            e.alive = False
                        hit = True
                        break
            if hit:
                self._lose_life(events)
                return
        # player vs items. Mines are live hazards: they cost a life unless the
        # craft is shielded/invulnerable; every other item is collected freely.
        for it in self.items:
            if not it.alive:
                continue
            if not P.circle_hit(it.x, it.y, it.size * 0.5, pl.x, pl.y,
                                pl.half * 0.8):
                continue
            if it.kind is C.ItemKind.MINE and not pl.protected:
                it.alive = False
                events.append({"type": SIG_HAZARD, "kind": it.kind.value})
                self._lose_life(events)
                return
            it.alive = False
            self._apply_item(it, events)

    def _lose_life(self, events: list[dict[str, Any]]) -> None:
        self.lives -= 1
        if self.lives <= 0:
            self.lives = 0
            events.append({"type": SIG_GAME_OVER})
            self._started = False
            return
        events.append({"type": SIG_LIFE_LOST})
        self._serve_craft()


__all__ = [
    "Game",
    "SIG_LIFE_LOST", "SIG_LEVEL_CLEAR", "SIG_GAME_OVER", "SIG_VICTORY",
    "SIG_POWERUP", "SIG_HAZARD", "SIG_BOMB",
]
