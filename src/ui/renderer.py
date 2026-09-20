"""Canvas painting: terrain/starfield, sprites, HUD, menus, effects."""
from __future__ import annotations

import math
import random
from typing import Any

import config as C

from .button import Button
from .constants import (
    BOSS_FLASH_RADIUS,
    ENEMY_SHEET,
    ITEM_AURA_SHEET,
    ITEM_AURA_TINTS,
    ITEM_SHEET,
    ITEM_STYLE,
    ITEM_STYLE_DEFAULT,
    ITEM_TILE,
    SHIELD_DEPLOY_TIME,
    SHIELD_FX_RADIUS,
    SHIELD_SHEET,
)
from .effects import Effects
from .fonts import get_font
from .menu import Menu


def shield_lapse(remaining: float) -> float:
    """Opacity of the shield bubble with ``remaining`` seconds of shield left.

    One rule, shared by the baked bubble and the high-contrast pen ring: solid
    until ``C.SHIELD_WARN_TIME`` seconds remain, then a strobe that says "this
    is leaving" without anyone reading a timer, and over the last
    ``C.SHIELD_FADE_TIME`` a sink to nothing so the effect ends as an event
    instead of a cliff. The dark half of the strobe is dimmed, not hidden - a
    bubble that blinks out completely reads as "shield gone" one flash early.
    """
    if remaining <= 0.0:
        return 0.0
    if remaining > C.SHIELD_WARN_TIME:
        return 1.0
    if remaining < C.SHIELD_FADE_TIME:
        return remaining / C.SHIELD_FADE_TIME
    dark = int((C.SHIELD_WARN_TIME - remaining) * 2.0 * C.SHIELD_FLASH_HZ)
    return C.SHIELD_FLASH_DIM if dark % 2 else 1.0


def _scale_rgb(col: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    """Dim an RGB triple by ``k`` (0.0 - 1.0) for a fading shield rim."""
    r, g, b = col
    return (max(0, min(255, int(r * k))),
            max(0, min(255, int(g * k))),
            max(0, min(255, int(b * k))))


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------
class Renderer:
    def __init__(self, canvas: Any, settings: C.Settings) -> None:
        self.canvas = canvas          # logical-size Surface (800x600)
        self.settings = settings
        self._scroll: float = 0.0
        self._stars: list[tuple[float, float, float, int]] = []
        self._seed_stars()
        self._terrain: Any = None        # terrain.TerrainTrack when loaded
        self._terrain_key: Any = None    # terrain.sector_key of what is loaded
        self._handoff: Any = None        # terrain.SectorHandoff mid-transition
        self._prefetch: Any = None       # prefetch.Prefetch (background loader)
        self._bank: Any = None           # sprites.Bank (lazy; baked sheets)
        self._wpn_level = 1              # picks vulcan vs plasma bullet art
        self._p_at = 0.0                 # monotonic clock for craft anim
        self._p_prev_x: float | None = None
        self._p_prev_t = 0.0
        self._p_vx = 0.0                 # smoothed player horizontal vel
        self._p_scale_cache: dict[int, Any] = {}  # display-scaled p_ship tiles
        self._shield_fade: dict[tuple[int, int], Any] = {}
        self._shield_fade_src: Any = None

    @property
    def palette(self) -> C.Palette:
        return C.PALETTE_HC if self.settings.high_contrast else C.PALETTE

    def set_settings(self, settings: C.Settings) -> None:
        self.settings = settings

    # ---- terrain (sector backdrop; replaces the starfield in-game) --------
    def set_terrain(self, level: Any, seed: int = 1,
                    track: Any = None) -> None:
        """Load one sector's terrain: phase zones when the level defines
        them (dissolving backdrop as the sector scrolls), else one map.

        ``track`` - or a finished prefetch - supplies an already-built track,
        which turns "start sector N" into a pointer swap instead of a load.
        """
        if track is None and self._prefetch is not None:
            track = self._prefetch.sector_track(level, seed)
        self._terrain = track or self._build_track(level, seed)
        self._terrain_key = self._key_of(level, seed)
        self._handoff = None

    def ensure_terrain(self, level: Any, seed: int = 1) -> bool:
        """Put a sector's ground on screen unless that ground is already there.

        Dying does not move the camera. The craft is re-served inside the sector
        it already flew over, and while the SHIP DOWN banner rolls the world is
        still scrolling underneath it - so rebuilding the track here would
        teleport the player back to the sector's opening zone and read as the
        tiles changing. Answering "same sector?" with the sector's identity
        instead of a reload is what keeps respawn from disturbing the ground.

        Returns True when the ground already on screen was kept.
        """
        on_screen = self._terrain is not None or self._handoff is not None
        if on_screen and self._terrain_key == self._key_of(level, seed):
            return True
        self.set_terrain(level, seed)
        return False

    @staticmethod
    def _key_of(level: Any, seed: int) -> Any:
        import terrain
        return terrain.sector_key(terrain.sector_phases(level), seed)


    def handoff_terrain(self, level: Any, seed: int = 1,
                        dur: float | None = None, track: Any = None) -> bool:
        """Reveal the next sector's ground over the current one: no reload, no
        cut, and the outgoing ground keeps scrolling while it leaves.

        Returns False when there is nothing to hand off from (title screen, the
        very first sector); the caller then uses :meth:`set_terrain`.
        """
        if self._terrain is None and self._handoff is None:
            return False
        if track is None and self._prefetch is not None:
            track = self._prefetch.sector_track(level, seed)
        from terrain.handoff import SectorHandoff

        incoming = track or self._build_track(level, seed)
        args: dict[str, Any] = {} if dur is None else {"dur": dur}
        self._handoff = SectorHandoff(self._terrain, incoming, **args)
        self._terrain = None
        # The sector being revealed is the one the player is now in, even while
        # its ground is only half on screen: a respawn mid-sweep belongs here.
        self._terrain_key = self._key_of(level, seed)
        return True

    def terrain_handoff_active(self) -> bool:
        return self._handoff is not None

    def set_prefetch(self, prefetch: Any) -> None:
        """Hand over the background loader (the App owns the thread)."""
        self._prefetch = prefetch

    def bank(self) -> Any:
        """The sprite bank, so the prefetch thread warms the sheets this
        renderer will actually ask for instead of a copy nobody reads."""
        return self._bank_of()

    @staticmethod
    def _build_track(level: Any, seed: int) -> Any:
        """Build a sector track from scratch (the synchronous fallback)."""
        import terrain
        return terrain.TerrainTrack(terrain.sector_phases(level), seed,
                              plan=terrain.plan_span(level))

    def clear_terrain(self) -> None:
        self._terrain = None
        self._terrain_key = None
        self._handoff = None

    # ---- sprite bank (baked sheets; vector art is the fallback) ----------
    def _bank_of(self) -> Any:
        if self._bank is None:
            import sprites
            self._bank = sprites.Bank()
        return self._bank

    def _blit_center(self, frame: Any, x: float, y: float) -> None:
        r = frame.get_rect()
        r.center = (int(x), int(y))
        self.canvas.blit(frame, r)

    # ---- parallax background ---------------------------------------------
    def _seed_stars(self) -> None:
        r = random.Random(0xA11CE)
        self._stars = []
        for _ in range(96):
            z = r.choice((1.0, 1.8, 3.0))         # depth -> speed & brightness
            self._stars.append((
                r.uniform(C.FIELD_LEFT, C.FIELD_RIGHT),
                r.uniform(C.FIELD_TOP, C.FIELD_BOTTOM),
                z, int(max(1, z))))

    def update_background(self, dt: float, speed_scale: float = 1.0) -> None:
        self._p_at += dt
        self._scroll += dt * speed_scale
        if self._handoff is not None:
            self._handoff.update(dt, speed_scale)
            if self._handoff.done:
                self._terrain = self._handoff.new
                self._handoff = None
            return
        if self._terrain is not None:
            self._terrain.update(dt, speed_scale)
            return
        out: list[tuple[float, float, float, int]] = []
        for x, y, z, sz in self._stars:
            y += (18.0 * z) * dt * speed_scale
            if y > C.FIELD_BOTTOM:
                y = C.FIELD_TOP
                x = random.uniform(C.FIELD_LEFT, C.FIELD_RIGHT)
            out.append((x, y, z, sz))
        self._stars = out

    def _draw_starfield(self) -> None:
        import pygame
        p = self.palette
        base = p.field_bg
        for x, y, z, sz in self._stars:
            b = min(255, 90 + int(z * 45))
            col = (base[0] + b // 3, base[1] + b // 3, base[2] + b) if not \
                self.settings.high_contrast else (b, b, b)
            pygame.draw.rect(self.canvas, col, (int(x), int(y), sz, sz))

    # ---- attract / title scene ---------------------------------------------
    TITLE_PARADE = ("e_grunt", "e_weaver", "e_darter", "e_gunner", "e_sentry")

    def draw_title_scene(self, t: float) -> None:
        """Attract backdrop: starfield, a parade of the real enemy sprites
        descending exactly like in-game, and the hero craft cruising and
        banking near the bottom. Falls back to vector shapes when baked
        sheets are unavailable (or in high-contrast mode)."""
        import pygame
        p = self.palette
        rect = (C.FIELD_LEFT, C.FIELD_TOP,
                C.FIELD_RIGHT - C.FIELD_LEFT, C.FIELD_BOTTOM - C.FIELD_TOP)
        pygame.draw.rect(self.canvas, p.field_bg, rect)
        self._draw_starfield()
        bank = None if self.settings.high_contrast else self._bank_of()
        if bank is None or bank.sheet("p_ship") is None:
            self._draw_title_scene_vectors(t)
            return
        import sprites
        # enemy parade: idle-bobbing, slow descent, gentle horizontal sway
        usable = (C.FIELD_RIGHT - C.FIELD_LEFT) - 90
        span = (C.FIELD_BOTTOM - C.FIELD_TOP) + 110
        for i, sheet in enumerate(self.TITLE_PARADE):
            surf = bank.sheet(sheet)
            if surf is None:
                continue
            frames, fps, _loop = sprites.anim_spec(sheet, "idle")
            tile = frames[int(t * fps) % len(frames)]
            x = (C.FIELD_LEFT + 55 + usable * (i + 0.5) / len(self.TITLE_PARADE)
                 + 26.0 * math.sin(t * 0.7 + i * 1.9))
            y = C.FIELD_TOP - 55 + ((t * 46.0 + i * 121.0) % span)
            self._blit_center(bank.frame(surf, sheet, tile), x, y)
        # hero craft: cruises left/right, banking with its actual velocity
        hx = C.LOGICAL_W / 2.0 + 160.0 * math.sin(t * 1.1)
        vx = 160.0 * 1.1 * math.cos(t * 1.1)
        mag = abs(vx)
        if mag < C.PLAYER_BANK_SOFT:
            anim = "idle"
        elif mag < C.PLAYER_BANK_HARD:
            anim = "bank_soft"
        else:
            anim = "bank_hard"
        if mag >= C.PLAYER_BANK_SOFT and vx < 0:
            anim += "_l"
        hy = C.LOGICAL_H - 58.0 + 4.0 * math.sin(t * 1.4)
        frames, fps, _loop = sprites.anim_spec("p_ship", anim)
        tile = frames[int(t * fps) % len(frames)]
        self._blit_center(self._p_ship_frame(tile), hx, hy)
        # gentle dim so title + buttons stay readable over the scene
        ov = pygame.Surface((C.FIELD_RIGHT - C.FIELD_LEFT,
                             C.FIELD_BOTTOM - C.FIELD_TOP), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 90))
        self.canvas.blit(ov, (C.FIELD_LEFT, C.FIELD_TOP))

    def _draw_title_scene_vectors(self, t: float) -> None:
        """High-contrast / no-art fallback for the attract scene."""
        import pygame
        p = self.palette
        for i in range(5):
            x = 130 + i * 140 + 22 * math.sin(t * 0.6 + i * 1.7)
            y = 90 + 10 * math.sin(t * 1.1 + i)
            col = (180, 90, 110) if not self.settings.high_contrast else (230, 230, 230)
            pygame.draw.polygon(self.canvas, col,
                                [(x, y + 11), (x - 11, y - 11), (x + 11, y - 11)])
        hx = C.LOGICAL_W / 2
        hy = C.LOGICAL_H - 96 + 6 * math.sin(t * 1.4)
        x, y = int(hx), int(hy)
        col = p.player
        pygame.draw.polygon(self.canvas, (255, 200, 90),
                            [(x - 4, y + 14), (x + 4, y + 14), (x, y + 22)])
        pygame.draw.polygon(self.canvas, col,
                            [(x, y - 16), (x + 6, y + 2), (x + 14, y + 12),
                             (x + 4, y + 10), (x, y + 14), (x - 4, y + 10),
                             (x - 14, y + 12), (x - 6, y + 2)])

    # ---- field & entities -------------------------------------------------
    def clear(self) -> None:
        p = self.palette
        self.canvas.fill(p.bg)

    def draw_field(self, game: Any) -> None:
        import pygame
        p = self.palette
        # play area
        rect = (C.FIELD_LEFT, C.FIELD_TOP,
                C.FIELD_RIGHT - C.FIELD_LEFT, C.FIELD_BOTTOM - C.FIELD_TOP)
        if self._handoff is not None:
            self._handoff.draw(self.canvas)
            pygame.draw.rect(self.canvas, p.field_bg, rect, 1)
        elif self._terrain is not None:
            self._terrain.draw(self.canvas)
            pygame.draw.rect(self.canvas, p.field_bg, rect, 1)
        else:
            pygame.draw.rect(self.canvas, p.field_bg, rect)
            self._draw_starfield()
        # side rails
        pygame.draw.rect(self.canvas, p.wall, (C.FIELD_LEFT - 4, C.FIELD_TOP,
                        4, C.FIELD_BOTTOM - C.FIELD_TOP))
        pygame.draw.rect(self.canvas, p.wall, (C.FIELD_RIGHT, C.FIELD_TOP,
                        4, C.FIELD_BOTTOM - C.FIELD_TOP))

        pl = game.player
        self._wpn_level = getattr(pl, "weapon_level", 1)
        # entities never bleed into the HUD band (spawn above the top edge)
        old_clip = self.canvas.get_clip()
        self.canvas.set_clip(pygame.Rect(C.FIELD_LEFT, C.FIELD_TOP,
                                         C.FIELD_RIGHT - C.FIELD_LEFT,
                                         C.FIELD_BOTTOM - C.FIELD_TOP))
        # items (behind everything so entities read on top)
        for it in getattr(game, "items", []):
            self._draw_item(it)
        # enemies
        for e in game.enemies:
            if e.alive:
                self._draw_enemy(e)
        # bullets
        for b in game.bullets:
            if b.alive:
                self._draw_bullet(b, p)
        # player + energy whip (the lash reads over the craft)
        self._draw_player(game.player, game.bullets)
        if getattr(game, "whip_active", False):
            self._draw_whip(game)
        self.canvas.set_clip(old_clip)

    def _player_bank_anim(self, pl: Any) -> str:
        """Pick a bank anim from smoothed horizontal velocity (input-agnostic:
        works for keyboard and mouse since both move pl.x between frames)."""
        now = self._p_at
        if self._p_prev_x is None:
            self._p_prev_x, self._p_vx = pl.x, 0.0
        else:
            dt = max(now - self._p_prev_t, 1e-3)
            inst = (pl.x - self._p_prev_x) / dt
            self._p_vx += (inst - self._p_vx) * min(1.0, dt * 18.0)
            self._p_prev_x = pl.x
        self._p_prev_t = now
        mag = abs(self._p_vx)
        if mag < C.PLAYER_BANK_SOFT:
            return "idle"
        hard = mag >= C.PLAYER_BANK_HARD
        if self._p_vx > 0:
            return "bank_hard" if hard else "bank_soft"
        return "bank_hard_l" if hard else "bank_soft_l"

    def _p_ship_frame(self, tile: int) -> Any:
        """p_ship tile at display scale (cached; full-res art is baked once)."""
        import pygame

        import sprites
        f = self._p_scale_cache.get(tile)
        if f is None:
            surf = self._bank_of().sheet("p_ship")
            f0 = sprites.Bank.frame(surf, "p_ship", tile)
            if C.PLAYER_SPRITE_SCALE == 1.0:
                f = f0
            else:
                wh = (max(1, round(f0.get_width() * C.PLAYER_SPRITE_SCALE)),
                      max(1, round(f0.get_height() * C.PLAYER_SPRITE_SCALE)))
                f = pygame.transform.smoothscale(f0, wh)
            self._p_scale_cache[tile] = f
        return f

    def _draw_shield(self, pl: Any, bullets: Any) -> None:
        """Shield bubble: a plated dome that turns, drawn *behind* the craft.

        Two deliberate choices. It is blitted before the hull sprite, and the
        baked radius is wider than the ship is tall, so the effect that protects
        the craft never draws over it. And the rim lights up on the side where
        hostile fire is bearing down, which says "this is what is keeping you
        alive" in the one place the player is already looking - without touching
        a collision rule, since the bubble is presentation and the model's
        ``protected`` flag is the gameplay.
        """
        import pygame

        import sprites
        bank = self._bank_of()
        surf = bank.sheet(SHIELD_SHEET)
        if surf is None:
            return
        lapse = shield_lapse(pl.shield)
        if lapse <= 0.0:
            return                       # faded out: the craft is on its own
        deploy_frames, _fps, _loop = sprites.anim_spec(SHIELD_SHEET, "deploy")
        since = C.SHIELD_TIME - pl.shield
        if 0.0 <= since < SHIELD_DEPLOY_TIME:
            # One pass of the pop, driven by the shield's own countdown so the
            # FX needs no extra state; grabbing a second shield replays it.
            tile = deploy_frames[int(len(deploy_frames) * since
                                      / SHIELD_DEPLOY_TIME)]
        else:
            tile = self._anim_frame(SHIELD_SHEET, "spin", 0.0)
        self._blit_center(self._shield_frame(bank, surf, tile, lapse),
                          pl.x, pl.y)
        # Where the nearest bullet is closing on the bubble, light that side of
        # the rim - a warning ring, not a hit counter.
        threat = None
        reach = SHIELD_FX_RADIUS + 26.0
        for b in bullets:
            if b.friendly or not b.alive:
                continue
            d = math.hypot(b.x - pl.x, b.y - pl.y)
            if d < reach and (threat is None or d < threat[0]):
                threat = (d, b)
        if threat is None:
            return
        _d, b = threat
        ang = math.atan2(b.y - pl.y, b.x - pl.x)
        glow = 1.0 - max(0.0, min(1.0, (threat[0] - SHIELD_FX_RADIUS + 20.0)
                                      / 46.0))
        box = pygame.Rect(0, 0, int(SHIELD_FX_RADIUS * 2),
                          int(SHIELD_FX_RADIUS * 2))
        box.center = (int(pl.x), int(pl.y))
        # The warning ring lapses with the bubble it is painted on, or a shield
        # that has faded to a whisper would still shout.
        pygame.draw.arc(self.canvas, _scale_rgb((120, 205, 255), lapse), box,
                        ang - 0.5, ang + 0.5, 6)
        pygame.draw.arc(self.canvas, _scale_rgb((235, 250, 255), lapse), box,
                        ang - 0.26, ang + 0.26, max(1, int(1 + 3 * glow)))

    def _shield_frame(self, bank: Any, surf: Any, tile: int,
                      lapse: float) -> Any:
        """The bubble tile at ``lapse`` opacity, faded copies cached.

        ``Bank.frame`` hands back a *sub-surface* of the sheet, so the alpha mod
        cannot go on it - setting it there would set it for every tile the sheet
        holds. Opacity is quantised to 1/8 steps, which keeps a strobing bubble
        to four cached surfaces instead of one allocation per frame.
        """
        if lapse >= 1.0:
            return bank.frame(surf, SHIELD_SHEET, tile)
        if self._shield_fade_src is not surf:
            self._shield_fade.clear()
            self._shield_fade_src = surf
        step = max(1, min(7, int(lapse * 8)))
        cached = self._shield_fade.get((tile, step))
        if cached is None:
            cached = bank.frame(surf, SHIELD_SHEET, tile).copy()
            cached.set_alpha(step * 32)
            self._shield_fade[(tile, step)] = cached
        return cached

    def _draw_player(self, pl: Any, bullets: Any = ()) -> None:
        import pygame
        p = self.palette
        # blink while respawning (invuln), but stay solid under shield
        if pl.invuln > 0.0 and pl.shield <= 0.0:
            if int(pl.invuln * 12) % 2 == 0:
                return
        anim = self._player_bank_anim(pl)
        if not self.settings.high_contrast:
            bank = self._bank_of()
            surf = bank.sheet("p_ship")
            if surf is not None:
                import sprites
                frames, fps, _loop = sprites.anim_spec("p_ship", anim)
                tile = frames[int(self._p_at * fps) % len(frames)]
                if pl.shield > 0.0:
                    self._draw_shield(pl, bullets)
                self._blit_center(self._p_ship_frame(tile), pl.x, pl.y)
                return
        x, y = int(pl.x), int(pl.y)
        col = p.player
        # engine flame
        flame = 6 + int(4 * math.sin(self._scroll * 30.0))
        pygame.draw.polygon(self.canvas, (255, 200, 90),
                            [(x - 4, y + 14), (x + 4, y + 14), (x, y + 14 + flame)])
        # hull (a swept dart pointing up)
        pygame.draw.polygon(self.canvas, col,
                            [(x, y - 16), (x + 6, y + 2), (x + 14, y + 12),
                             (x + 4, y + 10), (x, y + 14), (x - 4, y + 10),
                             (x - 14, y + 12), (x - 6, y + 2)])
        # cockpit + spine shading (texture, not colour-coding)
        pygame.draw.polygon(self.canvas, self._shade(col, 60),
                            [(x, y - 12), (x + 3, y + 2), (x, y + 8), (x - 3, y + 2)])
        pygame.draw.line(self.canvas, self._shade(col, -70), (x, y - 12),
                         (x, y + 12), 1)
        if pl.shield > 0.0:
            # High-contrast fallback: the same rule as the baked bubble, just
            # drawn with a pen - a wide ring that clears the hull rather than a
            # halo painted over the craft.
            lapse = shield_lapse(pl.shield)
            if lapse > 0.0:
                pygame.draw.circle(self.canvas, _scale_rgb((150, 200, 255),
                                                           lapse),
                                   (x, y), int(SHIELD_FX_RADIUS * 0.78), 3)

    def _bullet_frame(self, sheet: str, spin: bool = True) -> Any:
        """A bullet tile from the sheet bank, or None when art is unavailable.

        ``spin`` keeps the classic shared-playhead animation that makes a stream
        read as one travelling pattern; ``spin=False`` pins frame 0 for a static
        icon such as the HUD readout, which must not fidget while it is read.
        """
        bank = self._bank_of()
        surf = bank.sheet(sheet)
        if surf is None:
            return None
        import sprites
        frames, fps, _loop = sprites.anim_spec(sheet, "run")
        tile = frames[int(self._scroll * fps) % len(frames)] if spin \
            else frames[0]
        return bank.frame(surf, sheet, tile)

    def _draw_bullet(self, b: Any, p: C.Palette) -> None:
        import pygame
        # Baked sprite art when available (classic tile animation, shared
        # global playhead so a stream reads as one travelling pattern).
        sheet = ("shot_missile" if b.missile else
                 "shot_enemy" if not b.friendly else
                 "shot_moon" if b.pierce else
                 "shot_plasma" if self._wpn_level >= 4 else "shot_vulcan")
        frame = self._bullet_frame(sheet)
        if frame is not None:
            self._blit_center(frame, b.x, b.y)
            return
        if b.friendly and b.pierce:
            # No art: draw the crescent outright. The high-contrast pen mode is
            # exactly where an unmistakable silhouette matters most, and a
            # crescent is two lines of pygame - an arc for the cut edge, a
            # thinner one for the shade behind it.
            ix, iy = int(b.x), int(b.y)
            rr = max(4, int(b.r))
            pygame.draw.arc(self.canvas, (222, 242, 255),
                            (ix - rr, iy - rr, rr * 2, rr * 2),
                            math.tau * 0.16, math.tau * 0.84, 2)
            pygame.draw.arc(self.canvas, (96, 140, 190),
                            (ix - rr + 3, iy - rr + 2, rr * 2 - 6, rr * 2 - 4),
                            math.tau * 0.2, math.tau * 0.8, 1)
            return
        if b.friendly:
            col = p.player_bullet if not b.missile else (255, 220, 120)
            if b.missile:
                pygame.draw.rect(self.canvas, col,
                                 (int(b.x) - 2, int(b.y) - 6, 4, 12), border_radius=2)
            else:
                pygame.draw.rect(self.canvas, col,
                                 (int(b.x) - 2, int(b.y) - 6, 4, 12), border_radius=2)
                pygame.draw.rect(self.canvas, self._shade(col, 70),
                                 (int(b.x) - 1, int(b.y) - 5, 2, 6))
        else:
            ix, iy = int(b.x), int(b.y)
            pygame.draw.circle(self.canvas, p.enemy_bullet, (ix, iy), int(b.r))
            pygame.draw.circle(self.canvas, (255, 255, 255), (ix, iy),
                               max(1, int(b.r) - 2), 1)

    def _draw_enemy(self, e: Any) -> None:
        import pygame
        # Baked sheet sprite (idle anim driven by the entity's own clock, so
        # phase is stable while it lives); vector silhouette as fallback.
        kind = e.kind.value if hasattr(e.kind, "value") else str(e.kind)
        sheet = getattr(e, "sheet", None) or ENEMY_SHEET.get(kind)
        if sheet is not None and not self.settings.high_contrast:
            bank = self._bank_of()
            surf = bank.sheet(sheet)
            if surf is not None:
                import sprites
                frames, fps, loop = sprites.anim_spec(sheet, "idle")
                i = int(e.t * fps)
                tile = frames[i % len(frames)] if loop else \
                    frames[min(i, len(frames) - 1)]
                frame = bank.frame(surf, sheet, tile)
                if e.flash > 0.0 and e.r > BOSS_FLASH_RADIUS:
                    # A grunt that blinks white reads as "I hit it". A boss eats
                    # a stream of fire, so its flash window never closes, and a
                    # white-out would erase the silhouette the player is aiming
                    # at - not to mention the bullet art leaking out from behind
                    # it. Light the hull up over itself instead of replacing it.
                    self._blit_center(frame, e.x, e.y)
                    lit = bank.white(surf, sheet, tile)
                    lit.set_alpha(90)
                    self._blit_center(lit, e.x, e.y)
                    return
                if e.flash > 0.0:
                    frame = bank.white(surf, sheet, tile)
                self._blit_center(frame, e.x, e.y)
                return
        x, y = int(e.x), int(e.y)
        col = e.color if not self.settings.high_contrast else e.color
        if e.flash > 0.0:
            col = (255, 255, 255)
        r = int(e.r)
        kind = e.kind.value if hasattr(e.kind, "value") else str(e.kind)
        if kind == "grunt":
            pts = [(x, y + r), (x - r, y - r), (x + r, y - r)]
        elif kind == "weaver":
            pts = [(x, y + r), (x + r, y), (x, y - r), (x - r, y)]
        elif kind == "darter":
            pts = [(x, y + r), (x + 4, y - r), (x - 4, y - r)]
        elif kind == "gunner":
            pts = self._hex(x, y, r)
        elif kind == "sentry":
            pts = self._oct(x, y, r)
        elif kind == "heavy":
            pts = [(x - r, y - r), (x + r, y - r), (x + r, y + r), (x - r, y + r)]
        elif kind == "boss":
            self._draw_boss(e, x, y, col)
            return
        else:
            pts = [(x, y + r), (x - r, y - r), (x + r, y - r)]
        pygame.draw.polygon(self.canvas, col, pts)
        pygame.draw.polygon(self.canvas, self._shade(col, -60), pts, 2)
        # core highlight (texture)
        pygame.draw.circle(self.canvas, self._shade(col, 40), (x, y), max(2, r // 3))

    def _draw_boss(self, e: Any, x: int, y: int, col) -> None:
        import pygame
        r = int(e.r)
        # main hull
        pygame.draw.polygon(self.canvas, col,
                            [(x - r, y - r // 2), (x + r, y - r // 2),
                             (x + r * 0.7, y + r // 2), (x - r * 0.7, y + r // 2)])
        pygame.draw.polygon(self.canvas, self._shade(col, -50),
                            [(x - r, y - r // 2), (x + r, y - r // 2),
                             (x + r * 0.7, y + r // 2), (x - r * 0.7, y + r // 2)], 3)
        # side pods
        for sx in (-r + 6, r - 6):
            pygame.draw.circle(self.canvas, self._shade(col, -20), (x + sx, y), r // 4)
        # core (weak point), brighter, pulses with remaining hp
        frac = 1.0 if e.max_hp <= 0 else max(0.0, e.hp / e.max_hp)
        core = self._shade(col, 60 + int((1 - frac) * 80))
        pygame.draw.circle(self.canvas, core, (x, y), max(3, r // 4))
        pygame.draw.circle(self.canvas, (255, 255, 255), (x, y), max(2, r // 8))

    def _hex(self, x, y, r):
        return [(x + r * math.cos(a), y + r * math.sin(a))
                for a in (i * math.tau / 6 for i in range(6))]

    def _oct(self, x, y, r):
        return [(x + r * math.cos(a), y + r * math.sin(a))
                for a in (i * math.tau / 8 + math.tau / 16 for i in range(8))]

    def _draw_item(self, it: Any) -> None:
        kind = str(getattr(it.kind, "value", it.kind))
        x, y = int(it.x), int(it.y)
        phase = float(getattr(it, "phase", 0.0))
        if not self.settings.high_contrast and self._draw_item_art(kind, phase,
                                                                   x, y):
            return
        self._draw_item_vector(kind, x, y)

    def _anim_frame(self, sheet: str, anim: str, phase: float) -> int:
        """Current tile of a looping sheet, offset by the item's own phase."""
        import sprites
        frames, fps, _ = sprites.anim_spec(sheet, anim)
        return frames[int(self._scroll * fps + phase * len(frames))
                      % len(frames)]

    def _draw_item_art(self, kind: str, phase: float,
                       x: float, y: float) -> bool:
        """Baked pod + shared orbiting marker. False if there is no art."""
        bank = self._bank_of()
        aura = bank.tinted(ITEM_AURA_SHEET,
                           ITEM_AURA_TINTS.get(
                               kind, C.ITEM_STYLE_DEFAULT_COLOR[1]))
        if aura is not None:
            tile = self._anim_frame(ITEM_AURA_SHEET, "orbit", phase)
            self._blit_center(bank.frame(aura, ITEM_AURA_SHEET, tile), x, y)
        icons = bank.sheet(ITEM_SHEET)
        base = ITEM_TILE.get(kind)
        if icons is None or base is None:
            return False          # no pod for this kind: fall back to the glyph
        self._blit_center(bank.frame(icons, ITEM_SHEET,
                                    self._anim_frame(ITEM_SHEET, kind, phase)),
                          x, y)
        return True

    def _draw_item_vector(self, kind: str, x: int, y: int) -> None:
        """Flat tile + glyph: no baked art (or high-contrast mode).

        Kept as a real drawing, not a placeholder: a stripped checkout and the
        accessibility mode both land here, so the glyph has to identify the
        pickup on its own.
        """
        import pygame
        fill, edge, glyph = ITEM_STYLE.get(kind, ITEM_STYLE_DEFAULT)
        h = int(C.ITEM_SIZE / 2)
        pygame.draw.rect(self.canvas, fill, (x - h, y - h, h * 2, h * 2),
                         border_radius=4)
        pygame.draw.rect(self.canvas, edge, (x - h, y - h, h * 2, h * 2),
                         width=2, border_radius=4)
        g = glyph
        if g == "up":
            pygame.draw.polygon(self.canvas, edge,
                                [(x, y - 6), (x + 6, y), (x + 2, y), (x + 2, y + 6),
                                 (x - 2, y + 6), (x - 2, y), (x - 6, y)])
        elif g == "rocket":
            pygame.draw.polygon(self.canvas, edge,
                                [(x, y - 7), (x + 4, y + 3), (x, y + 1), (x - 4, y + 3)])
            pygame.draw.line(self.canvas, edge, (x - 4, y + 5), (x + 4, y + 5), 2)
        elif g == "bomb":
            pygame.draw.circle(self.canvas, edge, (x, y + 1), 5)
            pygame.draw.line(self.canvas, edge, (x + 3, y - 3), (x + 6, y - 6), 2)
        elif g == "shield":
            pygame.draw.polygon(self.canvas, edge,
                                [(x, y - 6), (x + 6, y - 3), (x + 6, y + 2),
                                 (x, y + 7), (x - 6, y + 2), (x - 6, y - 3)], 2)
        elif g == "medal":
            pygame.draw.circle(self.canvas, edge, (x, y), 6, 2)
            pygame.draw.line(self.canvas, edge, (x, y - 3), (x, y + 3), 2)
            pygame.draw.line(self.canvas, edge, (x - 3, y), (x + 3, y), 2)
        elif g == "life":
            pygame.draw.circle(self.canvas, edge, (x - 3, y - 1), 3)
            pygame.draw.circle(self.canvas, edge, (x + 3, y - 1), 3)
            pygame.draw.polygon(self.canvas, edge,
                                [(x - 5, y + 1), (x + 5, y + 1), (x, y + 6)])
        elif g == "whip":
            # squashed S-lash with an energy bead at the tip
            pygame.draw.arc(self.canvas, edge,
                            (x - 7, y - 8, 8, 9), math.pi * 0.9,
                            math.pi * 2.1, 2)
            pygame.draw.arc(self.canvas, edge,
                            (x - 1, y - 1, 8, 9), math.pi * 1.9,
                            math.pi * 3.1, 2)
            pygame.draw.circle(self.canvas, edge, (x + 5, y + 6), 2)
        elif g == "jam":
            pygame.draw.line(self.canvas, edge, (x - 5, y - 5), (x + 5, y + 5), 2)
            pygame.draw.line(self.canvas, edge, (x + 5, y - 5), (x - 5, y + 5), 2)
        elif g == "mine":
            pygame.draw.circle(self.canvas, edge, (x, y), 4, 2)
            for a in range(0, 360, 45):
                vx = math.cos(math.radians(a)) * 7
                vy = math.sin(math.radians(a)) * 7
                pygame.draw.line(self.canvas, edge, (x, y), (x + vx, y + vy), 2)

    # ---- energy whip ------------------------------------------------------
    def _draw_whip(self, game: Any) -> None:
        import pygame
        pts = game.whip.points
        if len(pts) < 2:
            return
        # energy strand under the beads so the curve always reads
        pts_c = [(int(x), int(y)) for x, y in pts]
        head = (int(game.player.x), int(game.player.y) - 12)
        pygame.draw.lines(self.canvas, (120, 30, 150), False,
                          [head] + pts_c, 5)
        pygame.draw.lines(self.canvas, (235, 120, 255), False,
                          [head] + pts_c, 2)
        bank = self._bank_of()
        surf = bank.sheet("fx_whip")
        if surf is not None and not self.settings.high_contrast:
            import sprites
            frames, fps, _ = sprites.anim_spec("fx_whip", "run")
            for i, (x, y) in enumerate(pts):
                tile = frames[(int(self._scroll * fps) + i) % len(frames)]
                self._blit_center(bank.frame(surf, "fx_whip", tile), x, y)
        else:
            for i, (x, y) in enumerate(pts):
                r = 3 + (i * 5) // len(pts)
                pygame.draw.circle(self.canvas, (200, 90, 235), (int(x), int(y)),
                                   r + 2)
                pygame.draw.circle(self.canvas, (255, 210, 255), (int(x), int(y)),
                                   max(1, r - 1))

    # ---- particles + sprite explosions -----------------------------------
    def draw_particles(self, effects: Effects) -> None:
        import pygame
        old_clip = self.canvas.get_clip()
        self.canvas.set_clip(pygame.Rect(C.FIELD_LEFT, C.FIELD_TOP,
                                         C.FIELD_RIGHT - C.FIELD_LEFT,
                                         C.FIELD_BOTTOM - C.FIELD_TOP))
        if effects.explosions:
            bank = self._bank_of()
            for ex in effects.explosions:
                surf = bank.sheet(ex.sheet)
                if surf is None:
                    continue
                self._blit_center(bank.frame(surf, ex.sheet, ex.tile()),
                                  ex.x, ex.y)
        for pt in effects.particles:
            a = max(0.0, min(1.0, pt.life * 2.5))
            col = tuple(int(c * a) for c in pt.color)
            pygame.draw.rect(self.canvas, col, (int(pt.x), int(pt.y), 3, 3))
        self.canvas.set_clip(old_clip)
        if effects.screen_flash > 0.0 and not self.settings.high_contrast:
            alpha = int(150 * effects.screen_flash)
            surf = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H), pygame.SRCALPHA)
            surf.fill((255, 240, 200, alpha))
            self.canvas.blit(surf, (0, 0))

    # ---- HUD --------------------------------------------------------------
    def draw_hud(self, game: Any, elapsed: float) -> None:
        import pygame
        p = self.palette
        f = get_font(22)
        left = f.render(f"SCORE {game.score}", True, p.hud_text)
        self.canvas.blit(left, (C.FIELD_LEFT + 4, 10))
        mid = f.render(f"{game.level_index + 1}/{len(C.LEVELS)}", True, p.hud_text)
        self.canvas.blit(mid, mid.get_rect(center=(C.LOGICAL_W // 2, 18)))
        lr = f.render(f"LIVES {game.lives}", True, p.hud_text)
        self.canvas.blit(lr, (C.LOGICAL_W - lr.get_width() - C.FIELD_LEFT - 4, 10))
        hf = get_font(15)
        hs = hf.render(f"HIGH {game.high_score}", True, p.hud_text)
        self.canvas.blit(hs, (C.FIELD_LEFT + 4, 32))
        # weapon power bar + missile + bombs (icons + text, not colour-only)
        pl = game.player
        wx = C.LOGICAL_W // 2 - 60
        wf = get_font(15)
        self.canvas.blit(wf.render("WPN", True, p.hud_text), (wx, 30))
        for i in range(C.WEAPON_MAX_LEVEL):
            on = i < pl.weapon_level
            col = p.ui_selected if on else (60, 66, 86)
            pygame.draw.rect(self.canvas, col, (wx + 30 + i * 14, 32, 10, 10),
                             border_radius=2)
        self.canvas.blit(wf.render(f"MIS {pl.missile_level}", True, p.hud_text),
                         (wx + 30 + C.WEAPON_MAX_LEVEL * 14 + 12, 30))
        # Blades are a third track, so they get a third readout - drawn with the
        # weapon's own art so it is identifiable without reading the number,
        # and left blank at zero so a fresh craft does not advertise a weapon it
        # has not picked up.
        mx = wx + 30 + C.WEAPON_MAX_LEVEL * 14 + 12 + 58
        if pl.moon_level > 0:
            # Drawn, not blitted: the HUD line is 15 px and the blade tile is 26,
            # so the sprite either gets resampled (soft) or droops out of the
            # strip (it did). Two arcs are crisp at any size, cost nothing, and
            # match the crescent the pen-mode bullet already falls back to.
            pygame.draw.arc(self.canvas, (206, 234, 255), (mx, 32, 13, 12),
                            math.tau * 0.16, math.tau * 0.84, 2)
            pygame.draw.arc(self.canvas, (86, 128, 178), (mx + 3, 34, 7, 7),
                            math.tau * 0.2, math.tau * 0.8, 1)
            self.canvas.blit(wf.render(f"MOON {pl.moon_level}", True,
                                       p.hud_text), (mx + 19, 30))
        bx = C.LOGICAL_W - C.FIELD_LEFT - 8
        for i in range(C.BOMB_MAX):
            on = i < pl.bomb_stock
            col = (250, 210, 110) if on else (60, 66, 86)
            pygame.draw.circle(self.canvas, col, (bx - i * 16, 37), 5)
        self.canvas.blit(wf.render("BMB", True, p.hud_text), (bx - C.BOMB_MAX * 16 - 30, 30))

    # ---- transient messages ----------------------------------------------
    def draw_message(self, text: str, sub: str = "") -> None:
        import pygame
        p = self.palette
        f = get_font(40)
        s = f.render(text, True, p.ui_selected)
        r = s.get_rect(center=(C.LOGICAL_W // 2, C.LOGICAL_H // 2 - 10))
        bg = pygame.Surface((r.width + 32, r.height + 16), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 160))
        self.canvas.blit(bg, (r.x - 16, r.y - 8))
        self.canvas.blit(s, r)
        if sub:
            sf = get_font(20)
            ss = sf.render(sub, True, p.ui_text)
            self.canvas.blit(ss, ss.get_rect(center=(C.LOGICAL_W // 2,
                            C.LOGICAL_H // 2 + 34)))

    # ---- menus ------------------------------------------------------------
    def draw_menu(self, menu: Menu | None, title: str = "",
                  subtitle: str = "") -> None:
        """Draw a menu. ``None`` means "there is no menu right now" (a run
        whose banner is still rolling has no buttons yet) - titles and
        subtitles still draw, so a caller never has to guard every call."""
        p = self.palette
        if title:
            tf = get_font(46)
            t = tf.render(title, True, p.ui_selected)
            self.canvas.blit(t, t.get_rect(center=(C.LOGICAL_W // 2, 110)))
        if subtitle:
            sf = get_font(20)
            s = sf.render(subtitle, True, p.ui_text)
            self.canvas.blit(s, s.get_rect(center=(C.LOGICAL_W // 2, 158)))
        if menu is None:
            return
        for i, b in enumerate(menu.buttons):
            self._draw_button(b, focused=(i == menu.focus_index),
                              hovered=(i == menu.hovered),
                              pressed=(i == menu.pressed))

    def _draw_button(self, b: Button, *, focused: bool, hovered: bool,
                     pressed: bool) -> None:
        import pygame
        p = self.palette
        x, y, w, h = b.rect
        rect = (x, y, w, h)
        if pressed:
            fill = p.ui_focus
            text_col = (20, 20, 20)
        elif focused:
            fill = (40, 46, 66) if not self.settings.high_contrast else (40, 40, 40)
            text_col = p.ui_focus
        elif hovered:
            fill = (34, 38, 54) if not self.settings.high_contrast else (30, 30, 30)
            text_col = p.ui_text
        else:
            fill = (26, 29, 40) if not self.settings.high_contrast else (10, 10, 10)
            text_col = p.ui_text
        if not b.enabled:
            fill = (20, 22, 28)
            text_col = (110, 116, 132)
        pygame.draw.rect(self.canvas, fill, rect, border_radius=8)
        if focused:
            pygame.draw.rect(self.canvas, p.ui_focus, rect, width=3, border_radius=8)
        f = get_font(24)
        label = f.render(b.label, True, text_col)
        self.canvas.blit(label, label.get_rect(center=(x + w // 2, y + h // 2)))

    # ---- informational screen --------------------------------------------
    def draw_text_block(self, title: str, lines: list[str],
                        foot: str = "") -> None:
        p = self.palette
        tf = get_font(34)
        t = tf.render(title, True, p.ui_selected)
        self.canvas.blit(t, t.get_rect(center=(C.LOGICAL_W // 2, 70)))
        lf = get_font(20)
        y = 120
        for line in lines:
            ln = lf.render(line, True, p.ui_text)
            self.canvas.blit(ln, ln.get_rect(center=(C.LOGICAL_W // 2, y)))
            y += 28
        if foot:
            ff = get_font(18)
            ft = ff.render(foot, True, p.ui_focus)
            self.canvas.blit(ft, ft.get_rect(center=(C.LOGICAL_W // 2,
                            C.LOGICAL_H - 40)))

    # ---- settings rows ----------------------------------------------------
    def draw_settings(self, menu: Menu, title: str,
                      rows: list[tuple[str, str]]) -> None:
        import pygame
        p = self.palette
        tf = get_font(34)
        t = tf.render(title, True, p.ui_selected)
        self.canvas.blit(t, t.get_rect(center=(C.LOGICAL_W // 2, 80)))
        rf = get_font(22)
        for i, ((label, value), b) in enumerate(zip(rows, menu.buttons, strict=False)):
            x, y, w, h = b.rect
            focused = (i == menu.focus_index)
            pygame.draw.rect(self.canvas,
                             (40, 46, 66) if focused else (26, 29, 40),
                             (x, y, w, h), border_radius=6)
            if focused:
                pygame.draw.rect(self.canvas, p.ui_focus, (x, y, w, h), width=2,
                                 border_radius=6)
            ln = rf.render(label, True, p.ui_text)
            self.canvas.blit(ln, (x + 14, y + h // 2 - ln.get_height() // 2))
            vn = rf.render(value, True, p.ui_selected)
            self.canvas.blit(vn, (x + w - vn.get_width() - 14,
                                   y + h // 2 - vn.get_height() // 2))
        for j in range(len(rows), len(menu.buttons)):
            self._draw_button(menu.buttons[j], focused=(j == menu.focus_index),
                              hovered=False, pressed=False)

    # ---- high-score table + initials entry ------------------------------
    # Columns are placed on fixed pixel positions instead of padded strings:
    # the UI font is proportional, so ``f"{x:>8}"`` would not line up.
    _SCORE_COLS: tuple[tuple[str, int, str], ...] = (
        ("RANK", 116, "right"),
        ("NAME", 208, "left"),
        ("SCORE", 400, "right"),
        ("SECTOR", 512, "right"),
        ("RESULT", 616, "left"),
    )

    def draw_score_table(self, entries: list[Any], highlight: int = -1,
                         title: str = "HIGH SCORES",
                         foot: str = "Enter / Esc back") -> None:
        import pygame
        p = self.palette
        tf = get_font(34)
        t = tf.render(title, True, p.ui_selected)
        self.canvas.blit(t, t.get_rect(center=(C.LOGICAL_W // 2, 72)))

        hf = get_font(18)
        for label, x, align in self._SCORE_COLS:
            h = hf.render(label, True, p.ui_focus)
            r = h.get_rect(midtop=(x, 118)) if align == "left" \
                else h.get_rect(topright=(x, 118))
            self.canvas.blit(h, r)
        pygame.draw.line(self.canvas, p.wall, (96, 142), (704, 142), 1)

        if not entries:
            nf = get_font(22)
            n = nf.render("No runs recorded yet.  Play one.", True, p.ui_text)
            self.canvas.blit(n, n.get_rect(center=(C.LOGICAL_W // 2, 200)))
        rf = get_font(22)
        y = 156
        for i, e in enumerate(entries):
            won = bool(getattr(e, "won", False))
            cells = ((str(i + 1), self._SCORE_COLS[0]),
                     (str(getattr(e, "initials", "???")), self._SCORE_COLS[1]),
                     (str(getattr(e, "score", 0)), self._SCORE_COLS[2]),
                     (str(getattr(e, "sector", 1)), self._SCORE_COLS[3]),
                     ("SECTOR CLEARED" if won else "DOWNED", self._SCORE_COLS[4]))
            row_col = p.ui_selected if i == highlight else p.ui_text
            if i == highlight:
                pygame.draw.rect(self.canvas, (40, 46, 66),
                                 (96, y - 4, 608, 26), border_radius=4)
            for text, (_label, x, align) in cells:
                s = rf.render(text, True, row_col)
                r = s.get_rect(midleft=(x, y + 9)) if align == "left" \
                    else s.get_rect(midright=(x, y + 9))
                self.canvas.blit(s, r)
            y += 30
        if foot:
            ff = get_font(18)
            ft = ff.render(foot, True, p.ui_focus)
            self.canvas.blit(ft, ft.get_rect(center=(C.LOGICAL_W // 2,
                            C.LOGICAL_H - 40)))

    def draw_initials_entry(self, initials: str, cursor: int, rank: int,
                            score: int, foot: str = "") -> None:
        """Arcade three-letter entry: three boxes, cursor highlighted."""
        import pygame
        p = self.palette
        tf = get_font(34)
        t = tf.render("ENTER YOUR INITIALS", True, p.ui_selected)
        self.canvas.blit(t, t.get_rect(center=(C.LOGICAL_W // 2, 96)))
        sf = get_font(22)
        # Rank 0 is never real (ranks start at 1) - it means "not yet ranked",
        # so don't show a fake placing.
        label = f"RANK {rank}   SCORE {score}" if rank >= 1 \
            else f"SCORE {score}"
        s = sf.render(label, True, p.ui_text)
        self.canvas.blit(s, s.get_rect(center=(C.LOGICAL_W // 2, 146)))

        box, gap = 64, 16
        total = box * C.INITIALS_LEN + gap * (C.INITIALS_LEN - 1)
        x0 = (C.LOGICAL_W - total) // 2
        y0 = 200
        bf = get_font(44)
        for i in range(C.INITIALS_LEN):
            x = x0 + i * (box + gap)
            pygame.draw.rect(self.canvas, (40, 46, 66) if i != cursor
                             else (66, 78, 116), (x, y0, box, box + 12),
                             border_radius=6)
            pygame.draw.rect(self.canvas, p.ui_focus if i == cursor else p.wall,
                             (x, y0, box, box + 12), width=2, border_radius=6)
            ch = initials[i] if i < len(initials) else C.INITIALS_BLANK
            g = bf.render(ch if ch != C.INITIALS_BLANK else "-", True,
                          p.ui_selected if i == cursor else p.ui_text)
            self.canvas.blit(g, g.get_rect(center=(x + box // 2,
                            y0 + (box + 12) // 2)))
        if foot:
            ff = get_font(18)
            ft = ff.render(foot, True, p.ui_focus)
            self.canvas.blit(ft, ft.get_rect(center=(C.LOGICAL_W // 2,
                            C.LOGICAL_H - 40)))

    @staticmethod
    def _shade(c: tuple[int, int, int], d: int) -> tuple[int, int, int]:
        return tuple(max(0, min(255, comp + d)) for comp in c)  # type: ignore[return-value]

    def sync_effects(self, effects: Effects) -> None:
        pass
