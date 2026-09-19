"""Player craft tuning."""
from __future__ import annotations

from .screen import LOGICAL_H

# ---------------------------------------------------------------------------
# Player craft
# ---------------------------------------------------------------------------
PLAYER_START_Y = LOGICAL_H - 72.0


PLAYER_HALF = 15.0            # visual half-extent (sprite is ~30x34)


PLAYER_HITBOX_R = 6.0         # small hitbox for fair shmup play


PLAYER_SPEED = 320.0          # logical units / second (keyboard)


PLAYER_BANK_SOFT = 40.0       # |vx| above this leans the craft one notch


PLAYER_BANK_HARD = 200.0      # |vx| above this banks it fully


PLAYER_SPRITE_SCALE = 0.8     # display scale of the 64x72 craft art (hitbox


                              # unchanged; keeps it next to 32-52 px enemies)
PLAYER_INVULN = 2.0           # invulnerable seconds after (re)spawn


START_LIVES = 3


BONUS_LIFE_THRESHOLD = 40000  # award one bonus life at this score


BONUS_LIFE_MAX = 1
