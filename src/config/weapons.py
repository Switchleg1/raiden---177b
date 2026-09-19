"""Weapon / missile / bomb / whip power-system tables."""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Player weapons (the "power system")
# ---------------------------------------------------------------------------
# Primary "vulcan" cannon: fires a fixed cadence upward. Weapon power level
# (1..WEAPON_MAX_LEVEL) widens the spread by adding streams (see WEAPON_TABLE).
# Power level PERSISTS for the life of the craft and resets to 1 on death, just
# like the arcade original.
WEAPON_BASE_LEVEL = 1


WEAPON_MAX_LEVEL = 5


WEAPON_FIRE_INTERVAL = 1.0 / 11.0          # base seconds between shots


WEAPON_LEVELS: tuple[tuple[tuple[float, float], ...], ...] = (
    # Each entry is the set of (dx offset, angle-from-vertical deg) streams for
    # weapon level index+1. Angles are symmetric; 0 = straight up.
    ((0.0, 0.0),),                                                    # L1
    ((-9.0, 0.0), (9.0, 0.0)),                                        # L2
    ((-12.0, 0.0), (0.0, 0.0), (12.0, 0.0)),                          # L3
    ((-12.0, 0.0), (0.0, 0.0), (12.0, 0.0),                           # L4
     (-9.0, -14.0), (9.0, 14.0)),
    ((-14.0, 0.0), (0.0, 0.0), (14.0, 0.0),                           # L5
     (-11.0, -18.0), (11.0, 18.0)),
)


# Secondary missiles: level 0..MISSILE_MAX_LEVEL. Each shot spawns this many
# side missiles; higher levels add more and a little more damage.
MISSILE_MAX_LEVEL = 4


MISSILE_BASE_LEVEL = 0


MISSILE_INTERVAL = 0.55                    # seconds between missile volleys


MISSILE_STREAMS = (0, 1, 2, 3, 4)         # by level index


# Smart bombs: screen-clearing. Press to spend one from BOMB_STOCK.
BOMB_START = 1


BOMB_MAX = 3


BOMB_DAMAGE = 8                            # damage dealt to every enemy on screen


BOMB_BOSS_DAMAGE = 60                      # bombs hit bosses with this instead


BOMB_CLEAR_BULLETS = True                  # erases all enemy bullets


# Bullet geometry / physics
PLAYER_BULLET_SPEED = 760.0


PLAYER_BULLET_R = 3.0


PLAYER_BULLET_DMG = 1


MISSILE_SPEED = 640.0


MISSILE_R = 4.0


MISSILE_DMG = 2


# Energy whip: a timed power that REPLACES the vulcan while active (arcade
# homage: a beaded energy lash that snakes across the field and carves
# anything it touches). Modelled as a chain of points on a swept, phase-
# lagged curve; contact damage with a short per-enemy re-hit cooldown.
WHIP_TIME = 12.0            # seconds the power lasts (pickup refreshes)


WHIP_LEN = 210.0            # lash length in logical units


WHIP_POINTS = 14            # sampled link points along the curve


WHIP_SWEEP_HZ = 0.85        # side-to-side sweep rate


WHIP_MAX_ANGLE = 64.0       # sweep extent from vertical, degrees


WHIP_WAVE_HZ = 1.6          # snake-wave travelling down the lash


WHIP_WAVE_AMP = 0.30        # wave amplitude, radians


WHIP_DMG = 4                # damage per contact


WHIP_HIT_CD = 0.45          # seconds before the same enemy can be hit again


WHIP_BEAD_R = 10.0          # contact radius of each energy bead
