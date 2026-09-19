"""Audio manager with original, procedurally generated sounds (Raiden Shadow).

No third-party audio is used: every effect is synthesised at runtime as 16-bit
mono PCM and wrapped in in-memory WAVs (see :func:`wav_bytes`) so SDL resamples
correctly on any device. The mixer degrades gracefully to silence when no audio
device is available (headless tests). Playback is rate-limited per sound and
uses a small fixed channel pool so overlapping shots never clip or grow
unbounded. Music is produced by :mod:`music` (unchanged synthwave engine) on a
background thread so mixer-init never blocks.
"""

from __future__ import annotations

import math
import random
import threading
import time
from typing import Any

import config as C
from audio_effects import (
    BOMB,
    BOSS_EXPLOSION,
    BOSS_WARN,
    EFFECT_NAMES,
    EXPLOSION,
    GAME_OVER,
    HAZARD,
    LEVEL_COMPLETE,
    LIFE_LOST,
    MEDAL,
    MENU_ACTIVATE,
    MENU_NAV,
    MIN_GAP,
    MISSILE,
    POWERUP,
    SHOOT,
    VICTORY,
    WHIP_HIT,
)

MIXER_RATE = 22050
MIXER_CHANNELS = 12
MUSIC_CHANNEL = MIXER_CHANNELS - 1   # reserved for the looping level track
MENU_KEY = "menu"                   # sentinel: "the menu playlist is wanted"
LEVEL_KEY = "level"                 # sentinel: "the level playlist is wanted"
BOSS_KEY = "boss"                   # sentinel: "a boss cue is wanted"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _i16(v: float) -> bytes:
    iv = int(max(-1.0, min(1.0, v)) * 32767)
    if iv < 0:
        iv += 65536
    return iv.to_bytes(2, "little", signed=False)


def _tone(freq: float, dur: float, *, vol: float = 0.5, shape: str = "sine",
          rate: int = MIXER_RATE, sweep: float | None = None,
          attack: float = 0.008, decay: float = 3.0) -> bytes:
    """Generate 16-bit signed mono PCM bytes for a short tone."""
    n = max(1, int(dur * rate))
    out = bytearray()
    sweep = freq if sweep is None else sweep
    for i in range(n):
        t = i / rate
        f = freq + (sweep - freq) * (i / max(1, n - 1))
        phase = 2.0 * math.pi * f * t
        if shape == "square":
            s = 1.0 if math.sin(phase) >= 0 else -1.0
        elif shape == "tri":
            s = (2 / math.pi) * math.asin(math.sin(phase))
        elif shape == "noise":
            s = random.uniform(-1.0, 1.0)
        else:
            s = math.sin(phase)
        a = min(1.0, t / attack) if attack > 0 else 1.0
        env = a * math.exp(-decay * (i / max(1, n)))
        sample = _clamp(s * env * vol, -1.0, 1.0)
        out += _i16(sample)
    return bytes(out)


def wav_bytes(mono: bytes, rate: int = MIXER_RATE) -> bytes:
    """Wrap 16-bit mono PCM in an in-memory WAV container (self-describing)."""
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(mono)
    return buf.getvalue()


def _chord(notes: list[tuple[float, float]], dur_each: float, vol: float,
           rate: int = MIXER_RATE) -> bytes:
    parts = []
    for f, swp in notes:
        parts.append(_tone(f, dur_each, vol=vol, shape="tri", sweep=swp, rate=rate))
    return b"".join(parts)


def _noise_burst(dur: float, vol: float, rate: int, decay: float = 6.0,
                 shape: str = "noise") -> bytes:
    return _tone(90, dur, vol=vol, shape=shape, sweep=40, rate=rate,
                 attack=0.002, decay=decay)


def build_samples(rate: int = MIXER_RATE) -> dict[str, bytes]:
    """Build every effect buffer once (original, procedural)."""
    return {
        SHOOT: _tone(880, 0.05, vol=0.22, shape="square", sweep=520, rate=rate,
                     decay=7.0),
        MISSILE: _tone(300, 0.16, vol=0.3, shape="tri", sweep=720, rate=rate),
        EXPLOSION: _noise_burst(0.22, 0.5, rate, decay=9.0),
        BOSS_EXPLOSION: _noise_burst(0.7, 0.6, rate, decay=3.0),
        BOSS_WARN: _chord([(196, 196), (185, 185), (196, 196)], 0.16, 0.4, rate),
        BOMB: _noise_burst(0.6, 0.55, rate, decay=2.2),
        MEDAL: _tone(1200, 0.06, vol=0.35, shape="square", sweep=1600, rate=rate),
        LIFE_LOST: _tone(320, 0.4, vol=0.45, shape="noise", sweep=90, rate=rate),
        LEVEL_COMPLETE: _chord([(523, 523), (659, 659), (784, 784)], 0.14, 0.4, rate),
        MENU_NAV: _tone(440, 0.04, vol=0.3, shape="square", sweep=480, rate=rate),
        MENU_ACTIVATE: _tone(660, 0.07, vol=0.35, shape="square", sweep=880, rate=rate),
        GAME_OVER: _chord([(392, 392), (330, 330), (262, 262)], 0.22, 0.4, rate),
        VICTORY: _chord([(523, 523), (659, 659), (784, 784), (1046, 1046)], 0.16,
                        0.42, rate),
        POWERUP: _chord([(659, 880), (880, 1174)], 0.09, 0.4, rate),
        HAZARD: _tone(180, 0.28, vol=0.45, shape="noise", sweep=60, rate=rate),
        # crack-zap: noisy high sweep collapsing fast (energy lash contact)
        WHIP_HIT: _tone(1500, 0.07, vol=0.3, shape="noise", sweep=420,
                        rate=rate, decay=13.0),
    }


class AudioManager:
    """Owns the mixer and generated sounds; safe when audio is unavailable."""

    def __init__(self, settings: C.Settings) -> None:
        self.settings = settings
        self.available = False
        self._sounds: dict[str, Any] = {}
        self._last: dict[str, float] = {}
        self._music_ch: Any = None
        self._music_key: str | None = None
        self._ntracks: int = 0
        self._menu_keys: list[str] = []
        self._last_menu_key: str | None = None
        self._level_keys: list[str] = []
        self._last_level_key: str | None = None
        self._boss_keys: list[str] = []
        self._last_boss_key: str | None = None
        self._track_bytes: dict[str, bytes] = {}
        self._music_sounds: dict[str, Any] = {}
        self._track_lock = threading.Lock()
        self._music_stop = False
        self._music_thread: threading.Thread | None = None
        self._mix_rate = MIXER_RATE

    def init(self) -> bool:
        """Initialise the mixer; returns availability. Never raises."""
        import pygame  # lazy import so logic tests need no pygame

        if self.available:
            return True
        try:
            pygame.mixer.init(frequency=MIXER_RATE, size=-16,
                              channels=MIXER_CHANNELS)
        except pygame.error:
            self.available = False
            return False
        try:
            pygame.mixer.set_num_channels(MIXER_CHANNELS)
        except (AttributeError, pygame.error):
            pass
        try:
            import io as _io
            for name, buf in build_samples(MIXER_RATE).items():
                self._sounds[name] = pygame.mixer.Sound(
                    file=_io.BytesIO(wav_bytes(buf, MIXER_RATE)))
        except pygame.error:
            self.available = False
            return False
        try:
            import music as _music_mod
            self._music_ch = pygame.mixer.Channel(MUSIC_CHANNEL)
            self._ntracks = len(_music_mod.THEMES)
            self._music_thread = threading.Thread(
                target=self._build_music_bytes, name="raiden-music", daemon=True)
            self._music_thread.start()
        except Exception:
            self._ntracks = 0
            self._music_ch = None
        self.available = True
        self.apply_settings(self.settings)
        return True

    def _music_build_plan(self, _music_mod: Any) -> list[tuple[str, int, dict]]:
        """Ordered (pool, key-ident, theme) render steps.

        First menu track, first level track and first boss cue go first (so all
        three pools can start playing within a few seconds of launch), then the
        remainder of each pool. Level pool is shuffled for variety (seeded by
        module RNG, not gameplay). The boss pool rides early because a boss can
        warp in during the first minute, and silence during the fight is the
        worst possible place to be still rendering.
        """
        menu_plan = list(_music_mod.MENU_THEMES)
        boss_pool = list(getattr(_music_mod, "BOSS_THEMES", ()))
        boss_plan = list(range(len(boss_pool)))
        level_plan = list(range(self._ntracks))
        random.shuffle(level_plan)
        steps: list[tuple[str, int, dict]] = []
        if menu_plan:
            steps.append(("menu", 0, menu_plan.pop(0)))
        if level_plan:
            idx = level_plan.pop(0)
            steps.append(("level", idx, _music_mod.THEMES[idx]))
        if boss_plan:
            steps.append(("boss", 0, boss_pool[boss_plan.pop(0)]))
        steps += [("menu", n, t) for n, t in enumerate(menu_plan, start=1)]
        steps += [("level", i, _music_mod.THEMES[i]) for i in level_plan]
        steps += [("boss", i, boss_pool[i]) for i in boss_plan]
        return steps

    def _build_music_bytes(self) -> None:
        """Background worker: render tracks and publish EACH one as soon as
        it is ready (incremental, not whole-pool batches).

        Ordering matters: first menu track, then first level track, then the
        rest of each pool. Publishing one track per pool up front means a
        player who starts the game seconds after launch already has a level
        track within ~2 s instead of waiting for every menu track to render
        first (the old batch order starved the level pool for 30+ s, so the
        retry loop had nothing to play and gameplay ran silent).
        """
        try:
            import music as _music_mod
            render = _music_mod.render_track
            steps = self._music_build_plan(_music_mod)
            for pool, ident, theme in steps:
                if self._music_stop:
                    return
                try:
                    buf = render(theme, MIXER_RATE)
                except Exception:
                    continue          # one bad track must not kill the playlist
                if pool == "menu":
                    k, keys = f"{MENU_KEY}{ident}", self._menu_keys
                elif pool == "boss":
                    k, keys = f"{BOSS_KEY}{ident}", self._boss_keys
                else:
                    k, keys = f"{LEVEL_KEY}{ident}", self._level_keys
                with self._track_lock:
                    self._track_bytes[k] = buf
                    keys.append(k)
        except Exception:
            pass

    def _ensure_music_sound(self, key: str) -> Any:
        import pygame
        with self._track_lock:
            snd = self._music_sounds.get(key)
            if snd is not None:
                return snd
            buf = self._track_bytes.pop(key, None)
        if buf is None:
            return None
        try:
            import io as _io
            snd = pygame.mixer.Sound(file=_io.BytesIO(wav_bytes(buf, MIXER_RATE)))
        except Exception:
            return None
        with self._track_lock:
            self._music_sounds[key] = snd
        return snd

    def _music_gain(self) -> float:
        s = self.settings
        master = 0.0 if s.master_mute else s.master_volume / 100.0
        return master * (s.music_volume / 100.0)

    def _play_music(self, key: str, loops: int = -1) -> None:
        if not self.available or self._music_ch is None:
            return
        snd = self._ensure_music_sound(key)
        if snd is None:
            return
        try:
            self._music_ch.stop()
            self._music_ch.play(snd, loops=loops)
            self._music_ch.set_volume(self._music_gain())
            self._music_key = key
        except Exception:
            pass

    def _pool_lists(self, pool: str) -> tuple[list[str], str | None]:
        with self._track_lock:
            if pool == LEVEL_KEY:
                return list(self._level_keys), self._last_level_key
            if pool == BOSS_KEY:
                return list(self._boss_keys), self._last_boss_key
            return list(self._menu_keys), self._last_menu_key

    def _mark_pool_key(self, pool: str, key: str) -> None:
        if pool == LEVEL_KEY:
            self._last_level_key = key
        elif pool == BOSS_KEY:
            self._last_boss_key = key
        else:
            self._last_menu_key = key

    def _play_random(self, pool: str) -> None:
        if not self.available or self._music_ch is None:
            return
        keys, last = self._pool_lists(pool)
        if not keys:
            return
        choices = [k for k in keys if k != last] or keys
        key = random.choice(choices)
        self._mark_pool_key(pool, key)
        self._play_music(key, loops=0)

    def play_level_music(self, level_index: int = 0) -> None:
        self._play_random(LEVEL_KEY)

    def play_menu_music(self) -> None:
        self._play_random(MENU_KEY)

    def play_boss_music(self) -> bool:
        """Start a boss cue; returns False while the pool is still rendering.

        The App calls this when a boss warps in and retries on later frames
        until it succeeds, so the switch is never silently dropped. Never
        repeats whichever cue the previous boss got.
        """
        if not self.available or self._music_ch is None:
            return False
        keys, last = self._pool_lists(BOSS_KEY)
        if not keys:
            return False
        choices = [k for k in keys if k != last] or keys
        key = random.choice(choices)
        self._mark_pool_key(BOSS_KEY, key)
        self._play_music(key, loops=0)
        return self._music_key == key

    def _playlist_playing(self, pool: str) -> bool:
        if not self.available or self._music_ch is None:
            return False
        if self._music_key is None or not self._music_key.startswith(pool):
            return False
        try:
            return bool(self._music_ch.get_busy())
        except Exception:
            return False

    def menu_playing(self) -> bool:
        return self._playlist_playing(MENU_KEY)

    def level_playing(self) -> bool:
        return self._playlist_playing(LEVEL_KEY)

    def boss_playing(self) -> bool:
        return self._playlist_playing(BOSS_KEY)

    @property
    def ntracks(self) -> int:
        return self._ntracks

    def apply_settings(self, settings: C.Settings) -> None:
        self.settings = settings
        if not self.available:
            return
        import pygame
        master = 0.0 if settings.master_mute else settings.master_volume / 100.0
        sfx_v = master * (settings.sfx_volume / 100.0)
        for _name, snd in self._sounds.items():
            try:
                snd.set_volume(sfx_v)
            except pygame.error:
                pass
        if self._music_ch is not None:
            try:
                self._music_ch.set_volume(self._music_gain())
            except pygame.error:
                pass

    def play(self, name: str) -> None:
        if not self.available or name not in self._sounds:
            return
        import pygame
        now = time.monotonic()
        gap = MIN_GAP.get(name, 0.0)
        if now - self._last.get(name, -1.0) < gap:
            return
        self._last[name] = now
        try:
            self._sounds[name].play()
        except pygame.error:
            pass

    def stop_all(self) -> None:
        if not self.available:
            return
        try:
            import pygame
            pygame.mixer.stop()
        except Exception:
            pass

    def dispose(self) -> None:
        self._music_stop = True
        self._sounds.clear()
        self._music_sounds.clear()
        self._track_bytes.clear()
        self.available = False
        try:
            import pygame
            pygame.mixer.quit()
        except Exception:
            pass


__all__ = ["AudioManager", "build_samples", "wav_bytes", "MIXER_RATE",
           "MENU_KEY", "LEVEL_KEY", "BOSS_KEY", "EFFECT_NAMES", "MIN_GAP",
           "SHOOT", "MISSILE", "EXPLOSION", "BOSS_EXPLOSION", "BOSS_WARN",
           "BOMB", "MEDAL", "LIFE_LOST", "LEVEL_COMPLETE", "MENU_NAV",
           "MENU_ACTIVATE", "GAME_OVER", "VICTORY", "POWERUP", "HAZARD",
           "WHIP_HIT"]
