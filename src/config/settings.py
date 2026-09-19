"""User-settings schema, defaults and validation (never raises)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .screen import DISPLAY_MODES, FPS_LIMITS, WINDOW_SCALES


# ---------------------------------------------------------------------------
# User settings schema (validated & persisted). Defaults live here.
# Identical shape to Breakout Classic so persistence and the settings UI reuse.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    display_mode: str = "windowed"      # "windowed" | "fullscreen"
    window_scale: int = 1               # index into WINDOW_SCALES
    vsync: bool = True
    fps_limit: int = 60                  # 60 | 120 | 144 | 0 (unlimited)
    master_volume: int = 80             # 0..100
    music_volume: int = 60              # 0..100
    sfx_volume: int = 90                # 0..100
    master_mute: bool = False
    screen_shake: bool = False
    reduced_flashing: bool = False
    high_contrast: bool = False
    powerups: bool = True               # falling power-ups & hazards


DEFAULT_SETTINGS = Settings()


# ---------------------------------------------------------------------------
# Settings validation (never raises; invalid fields fall back to defaults).
# ---------------------------------------------------------------------------
def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, iv))


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    return default


def validate_settings(raw: Any) -> Settings:
    d = DEFAULT_SETTINGS
    if not isinstance(raw, dict):
        return d

    mode = raw.get("display_mode", d.display_mode)
    mode = mode if mode in DISPLAY_MODES else d.display_mode

    scale = raw.get("window_scale", d.window_scale)
    scale = scale if scale in WINDOW_SCALES else d.window_scale

    fps = raw.get("fps_limit", d.fps_limit)
    fps = fps if fps in FPS_LIMITS else d.fps_limit

    return Settings(
        display_mode=mode,
        window_scale=int(scale),
        vsync=_bool(raw.get("vsync", d.vsync), d.vsync),
        fps_limit=int(fps),
        master_volume=_clamp_int(
            raw.get("master_volume", d.master_volume), 0, 100, d.master_volume),
        music_volume=_clamp_int(raw.get("music_volume", d.music_volume), 0, 100,
                                d.music_volume),
        sfx_volume=_clamp_int(raw.get("sfx_volume", d.sfx_volume), 0, 100,
                              d.sfx_volume),
        master_mute=_bool(raw.get("master_mute", d.master_mute), d.master_mute),
        screen_shake=_bool(raw.get("screen_shake", d.screen_shake), d.screen_shake),
        reduced_flashing=_bool(raw.get("reduced_flashing", d.reduced_flashing),
                               d.reduced_flashing),
        high_contrast=_bool(raw.get("high_contrast", d.high_contrast), d.high_contrast),
        powerups=_bool(raw.get("powerups", d.powerups), d.powerups),
    )


def settings_to_dict(s: Settings) -> dict[str, Any]:
    return {
        "display_mode": s.display_mode,
        "window_scale": s.window_scale,
        "vsync": s.vsync,
        "fps_limit": s.fps_limit,
        "master_volume": s.master_volume,
        "music_volume": s.music_volume,
        "sfx_volume": s.sfx_volume,
        "master_mute": s.master_mute,
        "screen_shake": s.screen_shake,
        "reduced_flashing": s.reduced_flashing,
        "high_contrast": s.high_contrast,
        "powerups": s.powerups,
    }
