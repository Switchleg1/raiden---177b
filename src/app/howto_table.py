"""The How To Play screen's text, one line per entry."""
from __future__ import annotations

HOWTO_LINES: tuple[str, ...] = (
    "Objective: destroy every enemy wave and the sector boss.",
    "You have 3 lives. Weapon levels reset when you die, but a cleared",
    "  sector is a reward: your power-ups carry into the next one.",
    "  A bonus life is awarded once at 40000 points.",
    "",
    "Power-ups fall from enemies (toggleable in Settings):",
    "  W up-arrow: wider weapon   M rocket: missiles   B: smart bomb",
    "  shield: temporary protection   medal: score   heart: extra life",
    "  Timed powers fire alongside your guns and wear off: the magenta",
    "  coil is the energy lash, the red pod is a flamethrower. A second",
    "  pod buys more time instead of restarting the clock.",
    "Hazards: J jams your weapon (downgrade); a floating mine costs a",
    "  life unless your shield or respawn invulnerability is active.",
    "",
    "Bosses fire aimed, fan and ring patterns; they enrage below half",
    "  health, and call in escort fighters while they fight. Smart",
    "  bombs clear every bullet and scar the boss.",
    "A boss fight gets its own music - it never repeats the same cue.",
    "",
    "A placing run is signed with three initials and saved to the",
    "  high score table (High Scores from the title screen).",
    "",
    "Move:  WASD / arrows, or the mouse (craft follows the pointer).",
    "Fire:  hold SPACE or the Left mouse button (auto-repeat).",
    "Bomb:  X or the Right mouse button.",
    "Pause (opens menu):  P or Esc.   Fullscreen:  F11.",
    "Losing window focus pauses the game automatically.",
)

__all__ = ["HOWTO_LINES"]
