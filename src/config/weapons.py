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


# Half-moon blades: a third power track, separate from vulcan power and from
# missiles. The blade is deliberately weak - one damage, and it flies slower
# than a shell so the eye can follow it. What it buys is that it does not stop:
# a crescent cuts through every hostile in its line, so its value is the number
# of enemies in a column, not the number it kills per second. Level 1 already
# throws two, because a single weak blade that misses is no weapon at all.
MOON_MAX_LEVEL = 4


MOON_BASE_LEVEL = 0


MOON_INTERVAL = 0.62                   # seconds between blade volleys


MOON_STREAMS = (0, 2, 3, 4, 5)         # blades per volley, by level index


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


MOON_SPEED = 470.0                     # slower than any shell: read the line
MOON_R = 9.0                           # wide crescent, generous contact box
MOON_DMG = 1                           # weak by design; pierce is the payoff
MOON_SPREAD = 17.0                     # lateral offset between blade streams
MOON_FAN_DEG = 7.5                     # angular step across the fan


# Energy whip: a timed power that REPLACES the vulcan while active (arcade
# homage: a beaded energy lash that snakes across the field and carves
# anything it touches).
#
# The lash is a ROPE IN THE WORLD, not a curve welded to the craft. Only the
# handle bead is pinned to the ship; every bead past it keeps its own position
# and is pulled only by the no-stretch constraint. Strafe and the handle drags,
# the body lags, the tip retracts: the ship's motion *draws* the shape. A
# forward drive along the rope and a bend relaxation then push the lash back
# out ahead of the craft, so it keeps travelling forward in time. Contact
# damage with a short per-enemy re-hit cooldown.
# A second WHIP pod buys another full WHIP_TIME on top of what is left - two
# seconds and a fresh pod means fourteen, never a reset back to twelve. Capped
# at two blocks so the timed power cannot be farmed into a permanent one.
WHIP_TIME = 12.0            # seconds the lash stays out (pickup adds a block)


WHIP_MAX = 2 * WHIP_TIME


WHIP_LEN = 300.0            # arc length of the lash (world units, inextensible)


WHIP_POINTS = 18            # beads on the lash


WHIP_ATTACH = 12.0          # handle sits this far above the cockpit centre


WHIP_SWEEP_HZ = 0.85        # side-to-side sweep rate with nothing to chase


WHIP_SWEEP_ANGLE = 34.0     # degrees the free sweep swings; big swings knot the lash


WHIP_MAX_ANGLE = 92.0       # how far the handle may lean for a target, degrees


WHIP_DRIVE = 240.0          # px/s the lash feeds itself forward along its body


WHIP_AIM_PULL = 0.35        # part of that drive aims where the handle points


WHIP_STRAIGHT = 38.0        # 1/s bend relaxation: how badly the rope wants a line


WHIP_STRAIGHT_TIP = 0.65    # bend relaxation this much weaker at the tip (slack)


WHIP_SMOOTH = 8             # segments averaged into the forward drive direction


WHIP_DRAG = 10.0            # 1/s: how fast a bead's own momentum bleeds off


WHIP_JITTER = 300.0         # px/s of wander fed into the lash (liveliness)


WHIP_JITTER_TAPER = 1.6     # wander grows toward the tip as f ** this


WHIP_JITTER_HZ = 1.5        # base rate of the wander (three incommensurate sines)


WHIP_AIM_RATE = 3.4         # rad/s: how fast the handle may swing onto a target


WHIP_SEEK_RANGE = 460.0     # px: the whip reaches for a hostile this near


WHIP_DMG = 4                # damage per contact


WHIP_HIT_CD = 0.45          # seconds before the same enemy can be hit again


WHIP_BEAD_R = 10.0          # contact radius of each energy bead
