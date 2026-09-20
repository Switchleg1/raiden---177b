"""Application: main loop, state-machine wiring, display, lifecycle."""
from __future__ import annotations

import logging
import os
import random
import sys
import time
from typing import Any

import config as C
import persistence as Pers
import ui
from audio import BOSS_KEY, LEVEL_KEY, MENU_KEY
from game import (
    SIG_BOMB,
    SIG_BOSS,
    SIG_GAME_OVER,
    SIG_HAZARD,
    SIG_LEVEL_CLEAR,
    SIG_LIFE_LOST,
    SIG_POWERUP,
    Game,
)
from input import (
    ACT_BACK,
    ACT_BOMB,
    ACT_CONFIRM,
    ACT_FULLSCREEN,
    ACT_PAUSE,
    InputController,
    Viewport,
)
from state import State, StateMachine

from .settings_rows import (
    SETTINGS_ROWS,
    _replace,
)

log = logging.getLogger("raiden_shadow")


READY_TIME = 1.1          # seconds of "READY" before auto-launch


MOUSE_TRACK_SPEED = 760.0  # logical units / s cap for pointer following


class App:
    def __init__(self, *, seed: int | None = None, headless: bool = False) -> None:
        self.headless = headless
        self.settings, _ = Pers.load_settings()
        self.stats, _ = Pers.load_stats()
        self.settings_draft = self.settings

        self.sm = StateMachine(State.BOOT)
        self.game = Game(rng=random.Random(seed), high_score=self.stats.high_score,
                         enable_items=self.settings.powerups)
        self.input = InputController()
        self.effects = ui.Effects(random.Random((seed if seed is not None else 0) + 1))
        self.audio: Any = None  # built in init_display()
        self._music_want: str | None = None
        self._music_level: int = 0        # sector whose cue pool is wanted
        # High-score table + the arcade initials entry.
        self._scores: list[Pers.ScoreEntry] = []
        self._scores_loaded = False
        self._score_highlight = -1
        self._initials = list(C.INITIALS_START)
        self._initial_index = 0
        self._run_rank: int | None = None
        self._entry_score = 0
        self._entry_won = False
        self._sdl_window: Any = None    # pygame-ce Window wrapper (live resize)
        self._window_size = C.window_size(self.settings.window_scale)

        # timing
        self._acc = 0.0
        self._last = 0.0
        self._play_time = 0.0
        self._run_active = False
        self._ready_timer = 0.0
        self._bomb_pending = False

        # transient message overlay
        self._msg = ""
        self._msg_sub = ""
        self._transition_timer = 0.0
        self._pending_after_transition: str | None = None

        # window/display
        self.window: Any = None
        self.canvas: Any = None
        self.renderer: Any = None
        # Ahead-of-time loader: next sector's terrain and boss art are built on
        # its thread so the frame a sector ends has nothing left to load.
        self.prefetch: Any = None
        self._warmed_wave_sector = -1     # sector whose pre-boss art was queued
        self._warmed_next_sector = -1     # sector whose handoff was queued
        self.viewport = Viewport(0, 0, C.LOGICAL_W, C.LOGICAL_H)
        self._window_size = C.window_size(self.settings.window_scale)
        self._confirm_text = ""
        self.running = True

        # menus (built lazily per state)
        self._menu: ui.Menu | None = None
        self._pending_confirm: str | None = None
        self._submenu_origin: State = State.TITLE

    # ------------------------------------------------------------------ setup
    def init_display(self) -> None:
        import pygame
        pygame.init()
        pygame.display.set_caption(C.APP_NAME)
        if self.headless:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        self._create_window()
        self.canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
        self.renderer = ui.Renderer(self.canvas, self.settings)
        from prefetch import Prefetch
        self.prefetch = Prefetch(bank=self.renderer.bank())
        self.renderer.set_prefetch(self.prefetch)
        self.effects.configure(shake=self.settings.screen_shake,
                               reduced_flashing=self.settings.reduced_flashing)
        from audio import AudioManager
        self.audio = AudioManager(self.settings)
        self.audio.init()
        log.info("display %s vsync=%s fps=%s",
                 self.settings.display_mode, self.settings.vsync,
                 self.settings.fps_limit)

    def _create_window(self) -> None:
        """Create the display surface exactly once, with pygame.SCALED.

        Under SCALED the display surface stays at logical resolution forever
        and SDL scales it to whatever the window is. Every later display
        change (window scale, fullscreen, vsync) is then an attribute update
        on the EXISTING window (Window.size / toggle_fullscreen /
        SDL_GL_SetSwapInterval) - never pygame.display.set_mode(), whose
        window recreation wedges the present path on some Windows drivers:
        the game keeps running but the screen stops updating.
        """
        import pygame
        vsync = 1 if self.settings.vsync else 0
        self._window_size = C.window_size(self.settings.window_scale)
        try:
            pygame.display.set_mode((C.LOGICAL_W, C.LOGICAL_H),
                                    pygame.SCALED, vsync=vsync)
        except pygame.error:    # e.g. drivers without GL for SCALED
            pygame.display.set_mode(self._window_size, 0, vsync=vsync)
        self._sdl_window = self._wrap_window()
        if self._sdl_window is not None and \
                self.settings.display_mode == "fullscreen":
            try:
                pygame.display.toggle_fullscreen()
            except pygame.error:
                self.settings = _replace(self.settings, display_mode="windowed")
                self.settings_draft = self.settings
        self._sync_display_surface()

    @staticmethod
    def _wrap_window():
        """pygame-ce Window wrapper around the display-module window."""
        try:
            from pygame.window import Window
            return Window.from_display_module()
        except (AttributeError, ImportError, RuntimeError, ValueError):
            return None

    def _window_pixel_size(self) -> tuple[int, int]:
        if self._sdl_window is not None:
            try:
                return (int(self._sdl_window.size[0]),
                        int(self._sdl_window.size[1]))
            except (AttributeError, RuntimeError, TypeError):
                pass
        import pygame
        surf = pygame.display.get_surface()
        return surf.get_size() if surf is not None else (C.LOGICAL_W, C.LOGICAL_H)

    def _recompute_viewport(self) -> None:
        """Letterbox rect in *logical* space for the current window size.

        Under SCALED, SDL stretches the logical surface non-uniformly onto
        the window; pre-letterboxing inside the logical surface cancels that
        out, so the game content always keeps its aspect ratio.
        """
        w_px, h_px = self._window_pixel_size()
        if w_px <= 0 or h_px <= 0:
            self.viewport = Viewport(0, 0, 0, 0)
            return
        sx, sy = w_px / C.LOGICAL_W, h_px / C.LOGICAL_H
        m = min(sx, sy)
        tw, th = C.LOGICAL_W * m, C.LOGICAL_H * m
        vx = round((w_px - tw) / 2 / sx)
        vy = round((h_px - th) / 2 / sy)
        vw = max(1, min(C.LOGICAL_W, round(tw / sx)))
        vh = max(1, min(C.LOGICAL_H, round(th / sy)))
        self.viewport = Viewport(vx, vy, vw, vh)

    def _sync_display_surface(self) -> None:
        """Re-adopt the real display surface + viewport after any mode change.

        self.window must be pygame's current display surface or every blit
        lands on a dead surface and the screen 'stops updating'. The pump()
        lets SDL settle the mode change before the next flip.
        """
        import pygame
        surf = pygame.display.get_surface()
        if surf is not None:
            self.window = surf
        self._recompute_viewport()
        pygame.event.pump()

    def _resize_window_px(self, size: tuple[int, int]) -> bool:
        """Resize the existing window (no set_mode, no recreation)."""
        if self._sdl_window is None:
            return False
        try:
            self._sdl_window.size = size
        except (AttributeError, RuntimeError, ValueError):
            return False
        return True

    def _set_swap_interval(self, interval: int) -> bool:
        """Change vsync on the live GL context. Returns success.

        pygame has no runtime vsync API and set_mode(vsync=) recreates the
        window (see _create_window), so poke SDL directly on Windows where
        pygame bundles SDL2.dll. Other platforms get apply-at-next-launch.
        """
        if sys.platform != "win32":
            return False
        import ctypes

        import pygame
        try:
            dll = getattr(self, "_sdl2_dll", None)
            if dll is None:
                dll = ctypes.CDLL(os.path.join(os.path.dirname(pygame.__file__),
                                               "SDL2.dll"))
                self._sdl2_dll = dll
            return dll.SDL_GL_SetSwapInterval(int(interval)) == 0
        except (OSError, AttributeError):
            return False

    def _apply_display_mode_change(self, revert_to: str | None = None) -> None:
        """Windowed <-> fullscreen without recreating the window."""
        import pygame
        try:
            pygame.display.toggle_fullscreen()
        except pygame.error:
            # No live toggle (e.g. dummy driver). NEVER fall back to
            # set_mode here: recreating the display at runtime wedges the
            # present path on this stack (frozen screen, game still running).
            # Roll the setting back so menu state matches reality.
            log.warning("toggle_fullscreen unsupported; keeping %s",
                        revert_to or self.settings.display_mode)
            if revert_to and revert_to != self.settings.display_mode:
                self.settings = _replace(self.settings, display_mode=revert_to)
                self.settings_draft = self.settings
                Pers.save_settings(self.settings)
            return
        if self.settings.display_mode != "fullscreen":
            # SDL restores the pre-fullscreen window size; enforce ours.
            self._resize_window_px(self._window_size)
        self._sync_display_surface()

    def _apply_window_scale_change(self) -> None:
        self._window_size = C.window_size(self.settings.window_scale)
        if self.settings.display_mode != "fullscreen":
            if not self._resize_window_px(self._window_size):
                log.warning("window resize unsupported; applies next launch")
                return    # setting is saved; applies at startup
        self._sync_display_surface()

    def _apply_vsync_change(self) -> None:
        if not self._set_swap_interval(1 if self.settings.vsync else 0):
            # pygame-ce keeps no current GL context reachable from ctypes,
            # and set_mode(vsync=) recreates the window (= screen freeze).
            # vsync therefore applies at next launch.
            log.info("vsync change applies at next launch")

    # ------------------------------------------------------------------ title
    def start(self) -> None:
        self.init_display()
        self.sm.to(State.TITLE)
        self._build_title_menu()
        self._set_menu_music()
        self._last = time.monotonic()

    def _build_title_menu(self) -> None:
        self._menu = ui.Menu("title", [
            ui.Button("play", "Play", (C.LOGICAL_W // 2 - 140, 250, 280, 48)),
            ui.Button("howto", "How to Play", (C.LOGICAL_W // 2 - 140, 306, 280, 46)),
            ui.Button("scores", "High Scores", (C.LOGICAL_W // 2 - 140, 360, 280, 46)),
            ui.Button("settings", "Settings", (C.LOGICAL_W // 2 - 140, 414, 280, 46)),
            ui.Button("quit", "Quit", (C.LOGICAL_W // 2 - 140, 468, 280, 46)),
        ], focus_index=0)
        self._pending_confirm = None

    # ----------------------------------------------------------------- events
    def process_events(self) -> None:
        import pygame
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
                continue
            if ev.type == pygame.WINDOWFOCUSLOST and self.sm.state == State.PLAYING:
                self._pause()
            self.input.handle_event(ev, self.viewport)
            if self.sm.state == State.NAME_ENTRY:
                self._handle_name_entry_event(ev)
                continue
            self._handle_menu_events(ev)
        actions = self.input.drain_actions()
        self._dispatch_actions(actions)

    def _handle_menu_events(self, ev: Any) -> None:
        import pygame
        st = self.sm.state
        menu = self._menu
        if menu is None:
            return
        if st in (State.TITLE, State.GAME_OVER, State.VICTORY, State.SETTINGS,
                  State.HOW_TO_PLAY, State.PAUSED):
            if ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_UP, pygame.K_w):
                    menu.move(-1)
                    self._sfx(nav=True)
                elif ev.key in (pygame.K_DOWN, pygame.K_s):
                    menu.move(1)
                    self._sfx(nav=True)
                elif ev.key in (pygame.K_LEFT, pygame.K_a) and st == State.SETTINGS:
                    self._adjust_setting(-1)
                elif ev.key in (pygame.K_RIGHT, pygame.K_d) and st == State.SETTINGS:
                    self._adjust_setting(1)
            elif ev.type == pygame.MOUSEMOTION:
                lx, ly = self._logical_mouse(ev.pos)
                menu.set_hover(lx, ly)
                if menu.hovered >= 0:
                    menu.focus_index = menu.hovered
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                lx, ly = self._logical_mouse(ev.pos)
                idx = menu.set_press(lx, ly)
                if idx >= 0:
                    menu.focus_index = idx
                self._handle_click(lx, ly)
            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                menu.pressed = -1

    def _logical_mouse(self, pos: tuple[int, int]) -> tuple[int, int]:
        from input import map_mouse_to_logical
        return map_mouse_to_logical(pos[0], pos[1], self.viewport)

    def _dispatch_actions(self, actions: set[str]) -> None:
        st = self.sm.state
        if ACT_FULLSCREEN in actions:
            self.toggle_fullscreen()
        if ACT_BACK in actions:
            self._on_back()
        if ACT_PAUSE in actions:
            if st == State.PLAYING:
                self._pause()
            elif st == State.PAUSED:
                self._resume()
        if ACT_BOMB in actions and st == State.PLAYING:
            self._bomb_pending = True
        if ACT_CONFIRM in actions:
            self._on_confirm()

    def _on_confirm(self) -> None:
        st = self.sm.state
        if st == State.NAME_ENTRY:
            self._submit_initials()
        elif st == State.HIGH_SCORES:
            self._leave_scores()
        elif st == State.READY:
            self._launch_craft()
        elif st in (State.LIFE_LOST, State.LEVEL_COMPLETE):
            self._finish_transition()
        elif self._menu is not None and st in (State.TITLE, State.GAME_OVER,
                    State.VICTORY, State.SETTINGS, State.HOW_TO_PLAY, State.PAUSED):
            b = self._menu.current()
            if b:
                self._activate(b.id)

    def _handle_click(self, lx: int, ly: int) -> None:
        assert self._menu is not None
        for i, b in enumerate(self._menu.buttons):
            if b.enabled and b.contains(lx, ly):
                self._menu.focus_index = i
                self._activate(b.id)
                return

    def _on_back(self) -> None:
        st = self.sm.state
        if st == State.NAME_ENTRY:
            self._cancel_name_entry()
        elif st == State.HIGH_SCORES:
            self._leave_scores()
        elif st == State.TITLE:
            self.running = False
        elif st == State.HOW_TO_PLAY:
            self._return_from_submenu()
        elif st == State.SETTINGS:
            self._settings_cancel()
        elif st == State.PAUSED:
            if self._pending_confirm:
                self._pending_confirm = None
                self._build_pause_menu()
            else:
                self._resume()
        elif st in (State.GAME_OVER, State.VICTORY):
            self._goto_title()
        elif st in (State.PLAYING, State.READY):
            self._pause()

    # ------------------------------------------------------------- activation
    def _activate(self, bid: str) -> None:
        self._sfx(nav=False)
        if bid == "play":
            self._start_game()
        elif bid == "howto":
            self._enter_howto()
        elif bid == "settings":
            self._enter_settings()
        elif bid == "scores":
            self._enter_scores()
        elif bid == "quit":
            self.running = False
        elif bid == "resume":
            self._resume()
        elif bid == "restart":
            self._require_confirm("restart", "Restart the current game?")
        elif bid == "title":
            self._require_confirm("title", "Return to title? Progress is lost.")
        elif bid == "quit_desktop":
            self._require_confirm("quit_desktop", "Quit to desktop?")
        elif bid == "again":
            self._start_game()
        elif bid == "apply":
            self._settings_apply()
        elif bid == "cancel":
            self._settings_cancel()
        elif bid == "defaults":
            self._settings_restore_defaults()
        elif bid == "confirm_yes":
            self._run_confirmed(self._pending_confirm or "")
        elif bid == "confirm_no":
            self._pending_confirm = None
            self._build_pause_menu()
        elif bid.startswith("opt:"):
            self._toggle_setting_option(int(bid.split(":")[1]))

    def _require_confirm(self, action: str, text: str) -> None:
        self._pending_confirm = action
        self._confirm_text = text
        self._menu = ui.Menu("confirm", [
            ui.Button("confirm_yes", "Yes", (C.LOGICAL_W // 2 - 200, 430, 180, 44)),
            ui.Button("confirm_no", "No", (C.LOGICAL_W // 2 + 20, 430, 180, 44)),
        ], focus_index=1)

    def _run_confirmed(self, action: str) -> None:
        self._pending_confirm = None
        if action == "restart":
            self._start_game()
        elif action == "title":
            self._goto_title()
        elif action == "quit_desktop":
            self.running = False

    # ----------------------------------------------------------- game control
    def _start_game(self) -> None:
        self.game.high_score = self.stats.high_score
        self.game.enable_items = self.settings.powerups
        self.game.new_game()
        self._play_time = 0.0
        self._run_active = True
        self._bomb_pending = False
        self._run_rank = None
        self._score_highlight = -1
        self.effects.reset()
        # A new run is a new world, whatever the last one left on screen; this
        # is the deliberate opposite of the respawn rule in _enter_ready, which
        # keeps the ground because the camera never moved.
        if self.renderer is not None:
            self.renderer.clear_terrain()
        self._set_music(self.game.level_index)
        self._enter_ready()

    def _set_music(self, level_index: int = 0) -> None:
        if self.audio is None or self.audio.ntracks <= 0:
            self._music_want = None
            return
        self._music_want = LEVEL_KEY
        self._music_level = level_index
        self.audio.play_level_music(level_index)

    def _set_menu_music(self) -> None:
        if self.audio is None:
            self._music_want = None
            return
        self._music_want = MENU_KEY
        self.audio.play_menu_music()

    def _set_boss_music(self) -> None:
        """Swap to a boss cue.

        The boss pool renders in the background, so the first fight of a
        session can arrive before its music does: the call is allowed to fail
        and the update loop keeps retrying while ``_music_want`` is set. The
        cue is *not* cut when the boss dies - the sector is one beat away from
        transitioning anyway, and yanking the music mid-explosion is worse.
        """
        if self.audio is None or self.audio.ntracks <= 0:
            self._music_want = None
            return
        self._music_want = BOSS_KEY
        self.audio.play_boss_music()

    def _enter_ready(self, seamless: bool = False) -> None:
        """Show READY for the sector the player is now in.

        ``seamless`` is the sector-to-sector path: the incoming ground is
        revealed over the ground the player already flies above instead of being
        swapped in, which is only possible because it was prefetched during the
        boss fight.
        """
        if self.sm.state != State.READY:
            self.sm.to(State.READY)
        self._menu = None
        self._msg = "READY"
        self._msg_sub = "Get ready!"
        self._transition_timer = 0.0
        self._ready_timer = READY_TIME
        self._bomb_pending = False
        if self.renderer is not None:
            # every sector scrolls its own phase-scheduled terrain
            level = C.LEVELS[self.game.level_index]
            seed = self.game.level_index + 1
            if not (seamless and
                    self.renderer.handoff_terrain(level, seed)):
                # A respawn is the sector the craft already flew over; asking
                # for it must not rebuild the ground under the player.
                self.renderer.ensure_terrain(level, seed)
        self._warm_ahead()

    def _warm_ahead(self) -> None:
        """Queue what the end of this sector needs. Idempotent and off-thread.

        The sector's own boss art and the next sector's terrain plus boss art are
        all wanted before they are on screen. Prefetching is never required: if
        the work has not finished when the game asks for it, the caller loads it
        the old way.
        """
        if self.prefetch is None:
            return
        idx = self.game.level_index
        self.prefetch.request_art(self.game.boss_sheet(idx))
        if idx >= C.FINAL_LEVEL_INDEX:
            return
        nxt = idx + 1
        self.prefetch.request_sector(C.LEVELS[nxt], nxt + 1)
        self.prefetch.request_art(self.game.boss_sheet(nxt))

    def _watch_load_ahead(self) -> None:
        """The two checkpoints inside a sector, watching the model.

        Half-way through the pre-boss wave this sector's boss art is queued -
        loading a sheet on the frame the boss appears is the stutter this
        exists to remove. Once the boss is halved, the next sector is queued,
        so the sector handoff has real ground to reveal rather than a fresh
        load; the boss decides the timing because that is when the player has
        the least left to do about it.
        """
        if self.prefetch is None:
            return
        idx = self.game.level_index
        if self._warmed_wave_sector != idx and self.game.wave_progress() >= 0.5:
            self._warmed_wave_sector = idx
            self.prefetch.request_art(self.game.boss_sheet(idx))
        frac = self.game.boss_hp_fraction()
        if (frac is not None and frac <= 0.5
                and self._warmed_next_sector != idx):
            self._warmed_next_sector = idx
            self._warm_ahead()

    def _launch_craft(self) -> None:
        if self.sm.state == State.READY:
            self._msg = ""
            self._ready_timer = 0.0
            self.sm.to(State.PLAYING)
            self.input.clear_all()

    def _pause(self) -> None:
        if self.sm.state in (State.PLAYING, State.READY):
            self.sm.to(State.PAUSED)
            if self.audio:
                self.audio.stop_all()
            self._set_menu_music()
            self._build_pause_menu()

    def _resume(self) -> None:
        if self.sm.can(State.PLAYING):
            self.sm.to(State.PLAYING)
            self._menu = None
            if self.game.boss_alive():
                self._set_boss_music()
            else:
                self._set_music(self.game.level_index)
            self.input.clear_all()
            self._bomb_pending = False

    def _build_pause_menu(self) -> None:
        self._menu = ui.Menu("pause", [
            ui.Button("resume", "Resume", (C.LOGICAL_W // 2 - 140, 190, 280, 44)),
            ui.Button("restart", "Restart Game", (C.LOGICAL_W // 2 - 140, 240, 280, 44)),
            ui.Button("settings", "Settings", (C.LOGICAL_W // 2 - 140, 290, 280, 44)),
            ui.Button("howto", "How to Play", (C.LOGICAL_W // 2 - 140, 340, 280, 44)),
            ui.Button("title", "Return to Title", (C.LOGICAL_W // 2 - 140, 390, 280, 44)),
            ui.Button("quit_desktop", "Quit to Desktop", (C.LOGICAL_W // 2 - 140, 440, 280, 44)),
        ], focus_index=0)

    def _enter_howto(self) -> None:
        if self.sm.state in (State.TITLE, State.PAUSED):
            self._submenu_origin = self.sm.state
            self.sm.to(State.HOW_TO_PLAY)
        self._menu = None

    def _enter_settings(self) -> None:
        if self.sm.state in (State.TITLE, State.PAUSED):
            self._submenu_origin = self.sm.state
            self.sm.to(State.SETTINGS)
        self.settings_draft = self.settings
        self._build_settings_menu()

    def _return_from_submenu(self) -> None:
        if self.sm.state == State.HOW_TO_PLAY:
            if self._submenu_origin == State.PAUSED and self.sm.can(State.PAUSED):
                self.sm.to(State.PAUSED)
                self._build_pause_menu()
            elif self.sm.can(State.TITLE):
                self.sm.to(State.TITLE)
                self._build_title_menu()

    def _goto_title(self) -> None:
        self._pending_confirm = None
        self._run_active = False
        if self.renderer is not None:
            self.renderer.clear_terrain()   # title shows the starfield again
        self.game = Game(rng=random.Random(), high_score=self.stats.high_score,
                         enable_items=self.settings.powerups)
        self.effects.reset()
        self.sm.reset(State.TITLE)
        self._build_title_menu()
        self._set_menu_music()

    # ------------------------------------------------------------- settings UI
    def _build_settings_menu(self) -> None:
        rows = list(range(len(SETTINGS_ROWS)))
        y0 = 112
        row_h = 30
        gap = 30
        actions_y = y0 + len(rows) * gap + 16
        buttons = [
            ui.Button(f"opt:{i}", "", (150, y0 + i * gap, 500, row_h)) for i in rows
        ]
        actions = [
            ui.Button("apply", "Apply", (250, actions_y, 100, 44)),
            ui.Button("defaults", "Restore Defaults", (350, actions_y, 150, 44)),
            ui.Button("cancel", "Cancel", (510, actions_y, 100, 44)),
        ]
        self._menu = ui.Menu("settings", buttons + actions, focus_index=0)

    def _current_rows(self) -> list[tuple[str, str]]:
        d = self.settings_draft
        out = []
        for row in SETTINGS_ROWS:
            out.append((row.label, row.get(d)))
        return out

    def _adjust_setting(self, delta: int) -> None:
        if not self._menu:
            return
        b = self._menu.current()
        if b and b.id.startswith("opt:"):
            idx = int(b.id.split(":")[1])
            self.settings_draft = SETTINGS_ROWS[idx].adjust(self.settings_draft, delta)
            self._sfx(nav=True)

    def _toggle_setting_option(self, idx: int) -> None:
        self.settings_draft = SETTINGS_ROWS[idx].adjust(self.settings_draft, 1)
        self._sfx(nav=True)

    def _settings_apply(self) -> None:
        old = self.settings
        new = self.settings_draft
        self.settings = new
        Pers.save_settings(self.settings)
        self.renderer.set_settings(self.settings)
        self.effects.configure(shake=self.settings.screen_shake,
                               reduced_flashing=self.settings.reduced_flashing)
        if self.audio:
            self.audio.apply_settings(self.settings)
        if old.display_mode != new.display_mode:
            self._apply_display_mode_change(revert_to=old.display_mode)
        if old.window_scale != new.window_scale:
            self._apply_window_scale_change()
        if old.vsync != new.vsync:
            self._apply_vsync_change()
        # no window touch at all for audio/HUD-only changes
        self._sfx(nav=False)
        self._settings_back()

    def _settings_cancel(self) -> None:
        self.settings_draft = self.settings
        self._settings_back()

    def _settings_restore_defaults(self) -> None:
        self.settings_draft = C.DEFAULT_SETTINGS
        self._sfx(nav=True)

    def _settings_back(self) -> None:
        if self.sm.state == State.SETTINGS:
            if self._submenu_origin == State.PAUSED and self.sm.can(State.PAUSED):
                self.sm.to(State.PAUSED)
                self._build_pause_menu()
            elif self.sm.can(State.TITLE):
                self.sm.to(State.TITLE)
                self._build_title_menu()

    def toggle_fullscreen(self) -> None:
        old_mode = self.settings.display_mode
        new_mode = "windowed" if old_mode == "fullscreen" else "fullscreen"
        self.settings = _replace(self.settings, display_mode=new_mode)
        self.settings_draft = self.settings
        Pers.save_settings(self.settings)
        self._apply_display_mode_change(revert_to=old_mode)

    # -------------------------------------------------------------- gameplay
    def _on_signal(self, ev: dict[str, Any]) -> bool:
        et = ev.get("type")
        if et == SIG_BOSS:
            self._set_boss_music()
        elif et == "shoot":
            if self.audio:
                self.audio.play(_audio_mod.SHOOT)
        elif et == "missile":
            if self.audio:
                self.audio.play(_audio_mod.MISSILE)
        elif et == "whip_hit":
            if self.audio:
                self.audio.play(_audio_mod.WHIP_HIT)
            self.effects.add_burst(ev.get("x", 0.0), ev.get("y", 0.0),
                                   (235, 130, 255), 3)
        elif et == "medal":
            if self.audio:
                self.audio.play(_audio_mod.MEDAL)
        elif et == "enemy_killed":
            if self.audio:
                self.audio.play(_audio_mod.EXPLOSION)
            col = tuple(ev.get("color", (200, 200, 200)))[:3]
            x, y = ev.get("x", 0.0), ev.get("y", 0.0)
            tier = ui.EXPLOSION_TIER.get(ev.get("kind", "grunt"),
                                              "explosion_small")
            self.effects.add_explosion(x, y, tier)
            self.effects.add_burst(x, y, col, 6)
        elif et == "boss_spawn":
            if self.audio:
                self.audio.play(_audio_mod.BOSS_WARN)
            self.effects.do_shake(4.0)
        elif et == "boss_down":
            if self.audio:
                self.audio.play(_audio_mod.BOSS_EXPLOSION)
            self.effects.do_shake(8.0)
            self.effects.do_screen_flash(0.5)
            bx = ev.get("x", C.LOGICAL_W / 2)
            by = ev.get("y", C.FIELD_TOP + 120)
            self.effects.add_explosion(bx, by, "explosion_big")
            self.effects.add_burst(bx, by, (255, 220, 140), 40)
        elif et == SIG_BOMB:
            if self.audio:
                self.audio.play(_audio_mod.BOMB)
            self.effects.do_screen_flash(0.85)
            self.effects.do_shake(6.0)
        elif et == SIG_LIFE_LOST:
            if self.audio:
                self.audio.play(_audio_mod.LIFE_LOST)
            self.effects.do_shake(7.0)
            self.effects.add_explosion(self.game.player.x,
                                       self.game.player.y, "explosion_mid")
            self.effects.add_burst(self.game.player.x, self.game.player.y,
                                   (120, 210, 255), 30)
            self._begin_transition("SHIP DOWN", f"{self.game.lives} lives left",
                                   1.2, "ready")
        elif et == SIG_LEVEL_CLEAR:
            if self.audio:
                self.audio.play(_audio_mod.LEVEL_COMPLETE)
            if self.game.is_final_level():
                self._begin_transition("SECTOR CLEAR", "All sectors down!",
                                       1.4, "victory")
            else:
                self._begin_transition("SECTOR CLEAR",
                                       f"Sector {self.game.level_index + 1} secure",
                                       1.2, "next_level")
        elif et == SIG_GAME_OVER:
            if self.audio:
                self.audio.play(_audio_mod.GAME_OVER)
            self.effects.add_explosion(self.game.player.x,
                                       self.game.player.y, "explosion_big")
            self.effects.add_burst(self.game.player.x, self.game.player.y,
                                   (120, 210, 255), 30)
            self._begin_transition("GAME OVER", "", 1.2, "game_over")
        elif et == SIG_POWERUP:
            if self.audio:
                self.audio.play(_audio_mod.POWERUP)
        elif et == SIG_HAZARD:
            if self.audio:
                self.audio.play(_audio_mod.HAZARD)
            self.effects.do_shake(5.0)
        return et in (SIG_LIFE_LOST, SIG_LEVEL_CLEAR, SIG_GAME_OVER)

    def _begin_transition(self, msg: str, sub: str, dur: float, after: str) -> None:
        self._msg, self._msg_sub = msg, sub
        self._transition_timer = dur
        self._pending_after_transition = after
        if after == "game_over" and self.sm.can(State.GAME_OVER):
            self.sm.to(State.GAME_OVER)
            self._set_menu_music()
            self._commit_run(won=False)
            if self._run_rank is None:
                self._build_results_menu()
        elif after == "victory" and self.sm.can(State.VICTORY):
            self.sm.to(State.VICTORY)
            self._set_menu_music()
            self._commit_run(won=True)
            if self._run_rank is None:
                self._build_results_menu()
        elif after == "ready" and self.sm.can(State.LIFE_LOST):
            self.sm.to(State.LIFE_LOST)
        elif after == "next_level" and self.sm.can(State.LEVEL_COMPLETE):
            self.sm.to(State.LEVEL_COMPLETE)

    def _finish_transition(self) -> None:
        after = self._pending_after_transition
        self._pending_after_transition = None
        self._transition_timer = 0.0
        if after == "ready":
            if self.sm.can(State.READY):
                self._enter_ready()
        elif after == "next_level":
            self.game.advance_level()
            self._set_music(self.game.level_index)
            if self.sm.can(State.READY):
                # Seamless: the new sector's ground sweeps in over the old one.
                self._enter_ready(seamless=True)
        elif after in ("game_over", "victory"):
            # Banner finished rolling: ask for initials if the run placed,
            # otherwise the results menu is already up.
            if self._run_rank is not None:
                self._enter_name_entry()

    def _commit_run(self, *, won: bool) -> None:
        """Record the finished run and decide whether initials are warranted.

        Statistics always update. The leaderboard only takes a run that
        actually places, so an ordinary death never asks for a name - the
        arcade rule that keeps the table worth signing.
        """
        self.game.commit_high_score()
        self.stats.merge_run(
            score=self.game.score,
            sector_reached=self.game.level_index + 1,
            enemies_destroyed=self.game.run_enemies_destroyed,
            play_time=self._play_time,
        )
        Pers.save_stats(self.stats)
        self.game.high_score = self.stats.high_score
        self._entry_score = int(self.game.score)
        self._entry_won = won
        self._run_rank = Pers.rank_of(self.load_scores(), self._entry_score,
                                     C.HIGH_SCORE_TABLE)

    def load_scores(self) -> list[Pers.ScoreEntry]:
        """The leaderboard, read once per session and kept in memory."""
        if not self._scores_loaded:
            self._scores = Pers.load_scores()
            self._scores_loaded = True
        return self._scores

    # ------------------------------------------------- leaderboard screens
    def _enter_scores(self) -> None:
        """Show the table; remembers where we came from (title or pause)."""
        self._scores = Pers.load_scores()
        self._scores_loaded = True
        self._score_highlight = -1
        if self.sm.state in (State.TITLE, State.PAUSED):
            self._submenu_origin = self.sm.state
        if self.sm.can(State.HIGH_SCORES):
            self.sm.to(State.HIGH_SCORES)
        self._menu = None

    def _leave_scores(self) -> None:
        if self._submenu_origin == State.PAUSED and self.sm.can(State.PAUSED):
            self.sm.to(State.PAUSED)
            self._build_pause_menu()
            return
        if self.sm.can(State.TITLE):
            self.sm.to(State.TITLE)
            self._build_title_menu()

    def _enter_name_entry(self) -> None:
        if not self.sm.can(State.NAME_ENTRY):
            self._build_results_menu()
            return
        self.sm.to(State.NAME_ENTRY)
        self._initials = list(C.INITIALS_START)
        self._initial_index = 0
        self._menu = None

    def _cancel_name_entry(self) -> None:
        """Skip the entry: the run still counts, it just stays anonymous."""
        self._build_results_menu()
        if self._entry_won and self.sm.can(State.VICTORY):
            self.sm.to(State.VICTORY)
        elif self.sm.can(State.GAME_OVER):
            self.sm.to(State.GAME_OVER)

    def _submit_initials(self) -> None:
        entry = Pers.ScoreEntry(
            initials=C.sanitize_initials("".join(self._initials)),
            score=self._entry_score,
            sector=self.game.level_index + 1,
            won=self._entry_won)
        self._scores = Pers.add_score(self._scores, entry, C.HIGH_SCORE_TABLE)
        self._score_highlight = next(
            (i for i, e in enumerate(self._scores) if e is entry), -1)
        self._scores_loaded = True
        try:
            Pers.save_scores(self._scores)
        except OSError as exc:      # a full disk must not eat the session
            log.warning("score table save failed: %s", exc)
        if self.sm.can(State.HIGH_SCORES):
            self.sm.to(State.HIGH_SCORES)

    def _handle_name_entry_event(self, ev: Any) -> None:
        """Keyboard-only initials entry (the arcade machine had no mouse)."""
        import pygame
        if ev.type != pygame.KEYDOWN:
            return
        if ev.key in (pygame.K_LEFT, pygame.K_a):
            self._initial_index = max(0, self._initial_index - 1)
        elif ev.key in (pygame.K_RIGHT, pygame.K_d):
            self._initial_index = min(C.INITIALS_LEN - 1,
                                      self._initial_index + 1)
        elif ev.key in (pygame.K_UP, pygame.K_w):
            self._cycle_initial(1)
        elif ev.key in (pygame.K_DOWN, pygame.K_s):
            self._cycle_initial(-1)
        elif ev.key == pygame.K_BACKSPACE:
            self._initials[self._initial_index] = C.INITIALS_BLANK
            self._initial_index = max(0, self._initial_index - 1)
        else:
            ch = (ev.unicode or "").upper()
            if ch and ch in C.INITIALS_TYPED:
                self._initials[self._initial_index] = ch
                self._initial_index = min(C.INITIALS_LEN - 1,
                                          self._initial_index + 1)

    def _cycle_initial(self, step: int) -> None:
        letters = C.INITIALS_LETTERS
        cur = self._initials[self._initial_index]
        i = letters.index(cur) if cur in letters else 0
        self._initials[self._initial_index] = letters[(i + step) % len(letters)]

    def _build_results_menu(self) -> None:
        self._menu = ui.Menu("results", [
            ui.Button("again", "Play Again",
                      (C.LOGICAL_W // 2 - 220, 470, 200, 44)),
            ui.Button("scores", "High Scores",
                      (C.LOGICAL_W // 2 - 100, 470, 200, 44)),
            ui.Button("title", "Return to Title",
                      (C.LOGICAL_W // 2 + 20, 470, 200, 44)),
        ], focus_index=0)

    # -------------------------------------------------------------- sfx util
    def _sfx(self, *, nav: bool = False) -> None:
        if not self.audio:
            return
        self.audio.play(_audio_mod.MENU_NAV if nav else _audio_mod.MENU_ACTIVATE)

    # ------------------------------------------------------------- main loop
    def run(self, max_frames: int | None = None) -> int:
        self.start()
        import pygame
        clock = pygame.time.Clock()
        frames = 0
        while self.running:
            self.process_events()
            now = time.monotonic()
            frame_dt = min(now - self._last, C.MAX_FRAME_DT)
            self._last = now
            self._update(frame_dt)
            self._render()
            fps = self.settings.fps_limit
            clock.tick(fps if fps and fps > 0 else 0)
            frames += 1
            if max_frames is not None and frames >= max_frames:
                break
        self.shutdown()
        return frames

    def _update(self, dt: float) -> None:
        st = self.sm.state
        self.effects.update(dt)
        if self.renderer is not None:
            if st == State.PLAYING:
                self.renderer.update_background(dt, 1.0)
            elif st == State.PAUSED:
                self.renderer.update_background(dt, 0.0)
            else:
                self.renderer.update_background(dt, 0.5)
        # background music playlists (retry each frame until bytes are ready)
        if self._music_want is not None and self.audio is not None:
            if self._music_want == MENU_KEY:
                if not self.audio.menu_playing():
                    self.audio.play_menu_music()
            elif self._music_want == LEVEL_KEY:
                if not self.audio.level_playing():
                    self.audio.play_level_music(self._music_level)
            elif self._music_want == BOSS_KEY:
                if not self.audio.boss_playing():
                    self.audio.play_boss_music()
        if self._transition_timer > 0:
            self._transition_timer = max(0.0, self._transition_timer - dt)
            if self._transition_timer == 0.0:
                self._finish_transition()
            return

        if st == State.READY:
            # No simulation during READY: enemies never spawn or fire until the
            # countdown ends (the craft is already served by the model).
            self._ready_timer = max(0.0, self._ready_timer - dt)
            if self._ready_timer == 0.0:
                self._launch_craft()
        elif st == State.PLAYING:
            self._play_time += dt
            self._watch_load_ahead()
            self._apply_craft_input(dt)
            self._acc += dt
            steps = 0
            while self._acc >= C.SIM_DT and steps < C.MAX_CATCHUP_STEPS:
                mx, my = self.input.axis.direction()
                events = self.game.update(
                    C.SIM_DT, move_x=mx, move_y=my,
                    firing=self.input.fire_held, bomb=self._bomb_pending)
                self._bomb_pending = False
                self._acc -= C.SIM_DT
                steps += 1
                for ev in events:
                    if self._on_signal(ev):
                        self._acc = 0.0
                        break
                if self.sm.state != State.PLAYING:
                    break
            if steps == C.MAX_CATCHUP_STEPS:
                self._acc = 0.0  # drop backlog (spiral-of-death guard)

    def _apply_craft_input(self, dt: float) -> None:
        """Pointer following (capped, fair) — keyboard axes are applied by Game."""
        if self.input.uses_mouse():
            pl = self.game.player
            tx = float(self.input.mouse_x)
            ty = float(self.input.mouse_y)
            max_step = MOUSE_TRACK_SPEED * dt
            dx = tx - pl.x
            dy = ty - pl.y
            if abs(dx) > max_step:
                dx = max_step if dx > 0 else -max_step
            if abs(dy) > max_step:
                dy = max_step if dy > 0 else -max_step
            pl.x += dx
            pl.y += dy
            pl.clamp_to_field()

    def _render(self) -> None:
        r = self.renderer
        r.set_settings(self.settings)
        r.sync_effects(self.effects)
        r.clear()
        st = self.sm.state

        if st == State.TITLE:
            self._render_title_background()
            r.draw_menu(self._menu, C.APP_NAME,
                        f"HIGH SCORE  {self.stats.high_score}")
        elif st in (State.READY, State.PLAYING, State.LIFE_LOST, State.LEVEL_COMPLETE):
            r.draw_field(self.game)
            r.draw_particles(self.effects)
            r.draw_hud(self.game, self._play_time)
            if self._transition_timer > 0 or (st == State.READY and self._msg):
                r.draw_message(self._msg, self._msg_sub)
        elif st == State.PAUSED:
            r.draw_field(self.game)
            r.draw_hud(self.game, self._play_time)
            self._overlay_dim()
            if self._pending_confirm:
                r.draw_message(self._confirm_text or "Confirm?", "Yes / No")
            r.draw_menu(self._menu, "PAUSED")
        elif st in (State.GAME_OVER, State.VICTORY):
            r.draw_field(self.game)
            self._overlay_dim()
            # While a placing run's banner rolls there is no menu yet - the
            # initials screen follows as soon as the banner finishes.
            foot = ("" if self._run_rank is None
                    else f"NEW HIGH SCORE - rank {self._run_rank}!")
            r.draw_text_block("VICTORY!" if st == State.VICTORY else "GAME OVER",
                              self._result_lines(), foot)
            r.draw_menu(self._menu)
        elif st == State.NAME_ENTRY:
            # The wreck is still on screen behind the entry boxes: this is the
            # arcade moment, not a form.
            r.draw_field(self.game)
            self._overlay_dim()
            r.draw_initials_entry("".join(self._initials), self._initial_index,
                                  self._run_rank or 0, self._entry_score,
                                  "type or up/down: letter   left/right: slot"
                                  "   enter: sign it   esc: skip")
        elif st == State.HIGH_SCORES:
            if self._submenu_origin == State.PAUSED:
                r.draw_field(self.game)
                self._overlay_dim()
            else:
                self._render_title_background()
            r.draw_score_table(self._scores, self._score_highlight,
                               foot="Enter / Esc back")
        elif st == State.HOW_TO_PLAY:
            self._overlay_dim()
            r.draw_text_block("HOW TO PLAY", self._howto_lines(),
                              "Press Esc / Enter to go back")
        elif st == State.SETTINGS:
            self._overlay_dim()
            r.draw_settings(self._menu, "SETTINGS", self._current_rows())
            foot = "left/right adjust   Enter toggle/activate   Esc back"
            ff = ui.get_font(18)
            p = r.palette
            t = ff.render(foot, True, p.ui_focus)
            self.canvas.blit(t, t.get_rect(center=(C.LOGICAL_W // 2, C.LOGICAL_H - 30)))

        self._present()

    def _present(self) -> None:
        import pygame
        win = self.window
        win.fill(self.renderer.palette.bg)
        view = self.viewport
        if view.w > 0 and view.h > 0:
            scale_x = view.w / C.LOGICAL_W
            integer = abs(scale_x - round(scale_x)) < 1e-6
            scaled = (pygame.transform.scale if integer
                      else pygame.transform.smoothscale)
            surf = scaled(self.canvas, (view.w, view.h))
            win.blit(surf, (view.x, view.y))
        pygame.display.flip()

    def _overlay_dim(self) -> None:
        import pygame
        ov = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 160))
        self.canvas.blit(ov, (0, 0))

    def _render_title_background(self) -> None:
        self.renderer.draw_title_scene(time.monotonic())

    # --------------------------------------------------------------- text
    def _result_lines(self) -> list[str]:
        return [
            f"Final Score: {self.game.score}",
            f"High Score: {self.stats.high_score}",
            f"Sector Reached: {self.game.level_index + 1}",
            f"Enemies Destroyed: {self.game.run_enemies_destroyed}",
            f"Play Time: {self._play_time:.1f}s",
        ]

    def _howto_lines(self) -> list[str]:
        return [
            "Objective: destroy every enemy wave and the sector boss.",
            "You have 3 lives. Weapon levels reset when you die, but a cleared",
            "  sector is a reward: your power-ups carry into the next one.",
            "  A bonus life is awarded once at 40000 points.",
            "",
            "Power-ups fall from enemies (toggleable in Settings):",
            "  W up-arrow: wider weapon   M rocket: missiles   B: smart bomb",
            "  shield: temporary protection   medal: score   heart: extra life",
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
        ]

    # ------------------------------------------------------------- shutdown
    def shutdown(self) -> None:
        self.running = False
        if self.prefetch is not None:
            self.prefetch.shutdown()
        try:
            Pers.save_settings(self.settings)
        except Exception:
            log.exception("save settings on shutdown failed")
        if self.audio:
            self.audio.dispose()
        try:
            import pygame
            ui.clear_fonts()
            pygame.quit()
        except Exception:
            pass
        log.info("shutdown clean")


def _load_audio_mod():
    import audio
    return audio


_audio_mod = _load_audio_mod()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)

    if "-h" in argv or "--help" in argv:
        print("Raiden Shadow - vertical arcade shooter\n"
              "\n"
              "usage: python main.py [--self-test [FRAMES]] [-h]\n"
              "\n"
              "  --self-test [N]  run N frames headless (dummy video/audio)\n"
              "                   and exit (default 90)\n"
              "  -h, --help       show this help and exit\n"
              "\n"
              "Controls: WASD/arrows or mouse to move, SPACE / left click to\n"
              "fire, X / right click for smart bomb, P / ESC to pause.")
        return 0

    selftest = None
    if "--self-test" in argv:
        i = argv.index("--self-test")
        rest = argv[i + 1:] + argv[:i]
        n = 90
        if rest and rest[0].isdigit():
            n = int(rest[0])
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        selftest = n

    app = App(headless=selftest is not None)
    try:
        if selftest is not None:
            frames = app.run(max_frames=selftest)
            logging.getLogger("raiden_shadow").info("self-test ran %d frames", frames)
            return 0 if frames == selftest else 1
        app.run()
    except KeyboardInterrupt:
        app.shutdown()
    return 0
