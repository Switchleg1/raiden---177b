"""Simulation timing + collision safety constants (fixed timestep)."""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Simulation timing (fixed timestep, frame-rate independent)
# ---------------------------------------------------------------------------
SIM_HZ = 120


SIM_DT = 1.0 / SIM_HZ


MAX_CATCHUP_STEPS = 5


MAX_FRAME_DT = 0.10


# ---------------------------------------------------------------------------
# Collision safety: bound travel-per-substep so fast projectiles can never
# tunnel through small hitboxes at the simulation cap.
# ---------------------------------------------------------------------------
MAX_SUBSTEP = 3.0


COLLIDE_EPS = 0.6
