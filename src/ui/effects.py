"""Particles, screen shake, pickup flash (bounded pools)."""
from __future__ import annotations

import math
import random

import config as C

from .constants import MAX_EXPLOSIONS, MAX_PARTICLES, SHAKE_MAX
from .explosion import Explosion
from .particle import Particle


class Effects:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.particles: list[Particle] = []
        self.explosions: list[Explosion] = []
        self.shake: float = 0.0
        self.screen_flash: float = 0.0
        self.enabled_shake: bool = False
        self.reduced_flash: bool = False

    def configure(self, *, shake: bool, reduced_flashing: bool) -> None:
        self.enabled_shake = shake
        self.reduced_flash = reduced_flashing
        if not shake:
            self.shake = 0.0

    def add_burst(self, x: float, y: float, color: tuple[int, int, int],
                  n: int = 10) -> None:
        if len(self.particles) >= MAX_PARTICLES:
            return
        n = min(n, MAX_PARTICLES - len(self.particles))
        for _ in range(n):
            a = self.rng.uniform(0.0, math.tau)
            sp = self.rng.uniform(50.0, 220.0)
            self.particles.append(Particle(
                x, y, math.cos(a) * sp, math.sin(a) * sp,
                self.rng.uniform(0.18, 0.5), color))

    def add_explosion(self, x: float, y: float, tier: str) -> None:
        """Queue one multi-stage sprite explosion (bounded list). A tiny
        particle spark rides along so the death still reads even if sheet
        art is missing."""
        if len(self.explosions) >= MAX_EXPLOSIONS:
            return
        self.explosions.append(Explosion(x, y, tier))

    def do_shake(self, amount: float) -> None:
        if self.enabled_shake:
            self.shake = min(SHAKE_MAX, max(self.shake, amount))

    def do_screen_flash(self, amount: float = 0.6) -> None:
        if not self.reduced_flash:
            self.screen_flash = max(self.screen_flash, min(1.0, amount))

    def update(self, dt: float) -> None:
        if self.particles:
            for p in self.particles:
                p.life -= dt
                p.x += p.vx * dt
                p.y += p.vy * dt
            self.particles = [p for p in self.particles
                              if p.life > 0 and p.y < C.FIELD_BOTTOM + 30]
        if self.explosions:
            for ex in self.explosions:
                ex.t += dt
            self.explosions = [ex for ex in self.explosions if not ex.done()]
        if self.shake > 0:
            self.shake = max(0.0, self.shake - 30.0 * dt)
        if self.screen_flash > 0:
            self.screen_flash = max(0.0, self.screen_flash - 2.5 * dt)

    def reset(self) -> None:
        self.particles.clear()
        self.explosions.clear()
        self.shake = 0.0
        self.screen_flash = 0.0
