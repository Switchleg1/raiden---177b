"""Enemy stat table + enemy bullet geometry."""
from __future__ import annotations

from .enemy_kind import EnemyKind
from .enemy_spec import EnemySpec

# Enemy bullets
ENEMY_BULLET_SPEED = 240.0                 # base; scales with level


ENEMY_BULLET_R = 4.5


MAX_BULLETS = 220                          # hard bound on total projectiles

# --- cluster munitions (bomber) ------------------------------------------
SHELL_SPEED = 0.44           # shell speed as a fraction of level bullet speed
SHELL_R = 7.5                # a shell must look like a shell, not a bolt
FRAG_SPEED = 0.78            # fragment speed as a fraction of bullet speed
FRAG_SPREAD_DEG = 360.0      # 360 = full radial burst, less = a forward cone

# --- rammer ----------------------------------------------------------------
RAMMER_LOCK_TIME = 0.45      # seconds spent painting the target column
RAMMER_RAMP = 0.35           # seconds to reach full charge speed
RAMMER_DRIFT = 90.0          # px the locked column may still slide per second

# --- splitter --------------------------------------------------------------
SHARD_SPREAD = 0.55          # shard lateral speed as a fraction of descent


ENEMY_SPECS: dict[EnemyKind, EnemySpec] = {
    # Radii sit well inside the painted silhouette: turbine pods, sponsons
    # and wing tips overhang the hitbox, so nothing eats a bullet it does not
    # visibly take with its core.
    EnemyKind.GRUNT: EnemySpec(hp=1, r=15.0, speed=120.0, score=50,
                               drop=0.05, fires=True, fire_cd=2.6,
                               color=(210, 70, 80)),
    EnemyKind.WEAVER: EnemySpec(hp=2, r=15.0, speed=140.0, score=90,
                                drop=0.06, color=(230, 150, 60)),
    EnemyKind.DARTER: EnemySpec(hp=1, r=14.0, speed=280.0, score=120,
                                drop=0.04, color=(245, 210, 90)),
    EnemyKind.GUNNER: EnemySpec(hp=5, r=19.0, speed=90.0, score=250,
                                drop=0.28, fires=True, fire_cd=1.4,
                                color=(180, 90, 200)),
    EnemyKind.SENTRY: EnemySpec(hp=4, r=18.0, speed=70.0, score=220,
                                drop=0.24, fires=True, fire_cd=1.7,
                                color=(90, 150, 220)),
    EnemyKind.HEAVY: EnemySpec(hp=12, r=28.0, speed=58.0, score=500,
                               drop=0.6, fires=True, fire_cd=2.0,
                               color=(150, 70, 70)),
    # Bomber: the armoured seeder. Slow and high, it survives long enough to
    # drop two or three shell salvos, so the shell count is deliberately mean.
    EnemyKind.BOMBER: EnemySpec(hp=9, r=27.0, speed=52.0, score=420,
                                drop=0.34, fires=True, fire_cd=2.3,
                                color=(206, 172, 62),
                                shell_frag=6, shell_fuse=1.05),
    # Splitter: cheap and quick, but a wave of them becomes twice as many
    # things on screen once the player commits to killing them.
    EnemyKind.SPLITTER: EnemySpec(hp=4, r=20.0, speed=112.0, score=180,
                                  drop=0.14, color=(184, 122, 222),
                                  split_into=EnemyKind.SHARD, split_count=2),
    # Rammer: locked column, then a full-speed charge. No gun, just intent.
    EnemyKind.RAMMER: EnemySpec(hp=2, r=15.0, speed=250.0, score=200,
                                drop=0.05, color=(214, 62, 62)),
    # Shard: the splitter's left overs. Fast, fragile, worthless.
    EnemyKind.SHARD: EnemySpec(hp=1, r=11.0, speed=240.0, score=60,
                               drop=0.0, color=(206, 156, 240)),
    EnemyKind.BOSS: EnemySpec(hp=220, r=56.0, speed=40.0, score=8000,
                              drop=0.0, fires=True, fire_cd=0.9,
                              color=(230, 60, 120)),
}
