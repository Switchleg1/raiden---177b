"""Settings-menu row definitions (labels, formatters, adjusters)."""
from __future__ import annotations

import config as C


# ---------------------------------------------------------------------------
# Settings option descriptors (label + get + adjust) — schema reused verbatim
# ---------------------------------------------------------------------------
class SettingRow:
    def __init__(self, key: str, label: str, fmt, adjust):
        self.key = key
        self.label = label
        self._fmt = fmt
        self._adjust = adjust

    def get(self, s: C.Settings) -> str:
        return self._fmt(getattr(s, self.key))

    def adjust(self, s: C.Settings, delta: int) -> C.Settings:
        return self._adjust(s, delta)


def _enum_cycle(values, cur, delta):
    i = values.index(cur) if cur in values else 0
    i = (i + (1 if delta > 0 else -1)) % len(values)
    return values[i]


def _fmt_display(v: str) -> str:
    return "Fullscreen" if v == "fullscreen" else "Windowed"


def _fmt_bool(v: bool) -> str:
    return "On" if v else "Off"


def _fmt_pct(v: int) -> str:
    return f"{v}%"


def _fmt_fps(v: int) -> str:
    return "Unlimited" if v == 0 else f"{v} FPS"


def _fmt_scale(v: int) -> str:
    return f"{v}x  ({v * 800}x{v * 600})"


def _adjust_pct(field: str):
    def adj(s: C.Settings, d: int) -> C.Settings:
        cur = getattr(s, field)
        return _replace(s, **{field: max(0, min(100, cur + (10 if d > 0 else -10)))})
    return adj


SETTINGS_ROWS: tuple[SettingRow, ...] = (
    SettingRow("display_mode", "Display Mode", _fmt_display,
               lambda s, d: _replace(
                   s, display_mode=_enum_cycle(C.DISPLAY_MODES, s.display_mode, d))),
    SettingRow("window_scale", "Window Scale", _fmt_scale,
               lambda s, d: _replace(
                   s, window_scale=_enum_cycle(C.WINDOW_SCALES, s.window_scale, d))),
    SettingRow("vsync", "VSync", _fmt_bool,
               lambda s, d: _replace(s, vsync=not s.vsync)),
    SettingRow("fps_limit", "Frame Limit", _fmt_fps,
               lambda s, d: _replace(s, fps_limit=_enum_cycle(C.FPS_LIMITS, s.fps_limit, d))),
    SettingRow("master_volume", "Master Volume", _fmt_pct, _adjust_pct("master_volume")),
    SettingRow("music_volume", "Music Volume", _fmt_pct, _adjust_pct("music_volume")),
    SettingRow("sfx_volume", "SFX Volume", _fmt_pct, _adjust_pct("sfx_volume")),
    SettingRow("master_mute", "Master Mute", _fmt_bool,
               lambda s, d: _replace(s, master_mute=not s.master_mute)),
    SettingRow("screen_shake", "Screen Shake", _fmt_bool,
               lambda s, d: _replace(s, screen_shake=not s.screen_shake)),
    SettingRow("reduced_flashing", "Reduced Flashing", _fmt_bool,
               lambda s, d: _replace(s, reduced_flashing=not s.reduced_flashing)),
    SettingRow("high_contrast", "High Contrast", _fmt_bool,
               lambda s, d: _replace(s, high_contrast=not s.high_contrast)),
    SettingRow("powerups", "Power-ups & Hazards", _fmt_bool,
               lambda s, d: _replace(s, powerups=not s.powerups)),
)


def _replace(s: C.Settings, **kw) -> C.Settings:
    from dataclasses import replace
    return replace(s, **kw)
