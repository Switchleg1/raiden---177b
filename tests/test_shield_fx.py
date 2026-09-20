"""The shield bubble: art that wraps the craft, painted behind it, no game rules.

The one rule worth defending in code is the one the eye notices: a shield that
draws over the ship hides the thing it is protecting. So the bubble is baked
wider than the hull and blitted before it, and this test asserts the hull's own
pixels come out unchanged - not that some constant was set, but that after
drawing the effect, the craft is still exactly itself.

The other rule is that an effect must not lie: the bubble is presentation, so
rendering it may not consume the run's seeded RNG or disturb a bullet.
"""

import dataclasses
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest  # noqa: E402

pygame.init()

import config as C  # noqa: E402
import sprites  # noqa: E402
import ui  # noqa: E402
from entities.bullet import Bullet  # noqa: E402
from game import Game  # noqa: E402

PX, PY = 400.0, 430.0       # where the craft stands in these scenes


@pytest.fixture(autouse=True)
def _display():
    """Blitting needs a live display; other suites tear it down when they end."""
    pygame.init()
    if pygame.display.get_surface() is None:
        pygame.display.set_mode((32, 32))
    yield


def _scene(shield: float, bullets=(), settings: C.Settings | None = None):
    """A canvas with the player drawn at a fixed pose, shield as given."""
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rend = ui.Renderer(canvas, settings or C.Settings())
    game = Game()
    game.new_game()
    game.start_level(0)
    pl = game.player
    pl.x, pl.y = PX, PY
    pl.invuln = 0.0        # not respawning: the craft is solid in every scene
    pl.shield = shield
    rend._draw_player(pl, bullets)
    return canvas, rend, game


def _hull_mask(rend, pl):
    """Opaque pixels of the frame the renderer is about to blit, in canvas space."""
    import sprites
    anim = rend._player_bank_anim(pl)
    frames, fps, _loop = sprites.anim_spec("p_ship", anim)
    tile = frames[int(rend._p_at * fps) % len(frames)]
    frame = rend._p_ship_frame(tile)
    # Fully opaque hull pixels only: a partly transparent edge is *supposed* to
    # pick up whatever is behind it, which is exactly what a shield is.
    # The hull, meaning the pixels that are effectively solid. A partly
    # transparent edge is supposed to pick up whatever is behind it - that is
    # what a shield is - so faint rim pixels are not counted as the craft.
    mask = pygame.mask.from_surface(frame, threshold=250)
    return mask, frame.get_size()


def _pixels(surf: pygame.Surface) -> bytes:
    tobytes = getattr(pygame.image, "tobytes", None) or pygame.image.tostring
    return tobytes(surf, "RGBA")


def _light(canvas: pygame.Surface, bare: pygame.Surface) -> float:
    """How much light the shield adds to a bare scene (mean per-channel delta).

    Counting touched pixels would not work: a 28 % bubble repaints almost as
    many pixels as a solid one. Summing how far each pixel moved measures the
    thing that actually changes during the lapse, which is opacity.
    """
    pa, pb = _pixels(canvas), _pixels(bare)
    total = 0
    for i in range(0, min(len(pa), len(pb)), 4):
        total += abs(pa[i] - pb[i]) + abs(pa[i + 1] - pb[i + 1])
        total += abs(pa[i + 2] - pb[i + 2])
    return total / (3.0 * C.LOGICAL_W * C.LOGICAL_H)


def _glow(shield: float, settings: C.Settings | None = None) -> float:
    """Bubble brightness with ``shield`` seconds left, against no bubble at all.

    The renderer's playhead is per-instance and starts at zero, so every scene
    here draws the same spin frame: the only variable is opacity.
    """
    lit, _r, _g = _scene(shield, settings=settings)
    bare, _r2, _g2 = _scene(0.0, settings=settings)
    return _light(lit, bare)


def _diff(a: pygame.Surface, b: pygame.Surface):
    """Pixel coordinates where two canvases differ."""
    pa, pb = _pixels(a), _pixels(b)
    stride = C.LOGICAL_W * 4
    return [(i % stride // 4, i // stride)
            for i in range(0, min(len(pa), len(pb)), 4)
            if pa[i:i + 4] != pb[i:i + 4]]


# ------------------------------------------------------------------------- art

def test_shield_art_is_wider_than_the_craft():
    """The bubble has to wrap the hull, not hug it - measured, not asserted."""
    bank = sprites.Bank()
    surf = bank.sheet("fx_shield")
    assert surf is not None, "fx_shield is not baked"

    def extent(sheet_name, tile):
        f = sprites.Bank.frame(surf if sheet_name == "fx_shield"
                               else bank.sheet(sheet_name), sheet_name, tile)
        w, h = f.get_size()
        mask = pygame.mask.from_surface(f)
        minx, miny, maxx, maxy = w, h, -1, -1
        for y in range(h):
            for x in range(w):
                if mask.get_at((x, y)):
                    minx = min(minx, x)
                    maxx = max(maxx, x)
                    miny = min(miny, y)
                    maxy = max(maxy, y)
        return max(maxx - minx, maxy - miny) + 1

    widest_shield = max(extent("fx_shield", t)
                        for t in sprites.SPRITES["fx_shield"]["anims"]
                        ["all"]["frames"])
    widest_ship = max(extent("p_ship", t)
                      for t in sprites.SPRITES["p_ship"]["anims"]["idle"]
                      ["frames"])
    assert widest_shield >= ui.SHIELD_FX_RADIUS * 2 * 0.85
    assert widest_shield > widest_ship, \
        f"bubble {widest_shield}px is not wider than the hull {widest_ship}px"


def test_shield_manifest_and_constants_agree():
    deploy = sprites.SPRITES[ui.SHIELD_SHEET]["anims"]["deploy"]
    spin = sprites.SPRITES[ui.SHIELD_SHEET]["anims"]["spin"]
    assert spin["loop"], "a shield that stops turning looks broken"
    assert ui.SHIELD_DEPLOY_TIME == len(deploy["frames"]) / float(deploy["fps"])
    assert 0.1 < ui.SHIELD_DEPLOY_TIME < C.SHIELD_TIME


# ------------------------------------------------------------------ draw order

def test_shield_never_draws_over_the_hull():
    """Not one of the craft's own pixels changes when the bubble comes on."""
    off, rend, game = _scene(0.0)
    on, _rend2, game2 = _scene(C.SHIELD_TIME - 3.0)
    mask, size = _hull_mask(rend, game2.player)
    w, h = size
    # Same anchoring the renderer uses: rect.center = (int(x), int(y)).
    ox, oy = int(PX) - w // 2, int(PY) - h // 2
    worst = 0
    covered = 0
    for y in range(h):
        for x in range(w):
            if not mask.get_at((x, y)):
                continue
            covered += 1
            cx, cy = ox + x, oy + y
            a, b = off.get_at((cx, cy)), on.get_at((cx, cy))
            worst = max(worst, max(abs(a[i] - b[i]) for i in range(3)))
    # A hull blitted after the bubble reproduces its own pixels; the residual is
    # the arithmetic of a near-opposite sprite over an underlay. Move the shield
    # blit to after the craft and this jumps from 1-2 levels to scores at once.
    assert worst <= 2, f"shield changed the hull by {worst}/255 at its core"
    assert covered > 400, "the hull mask is empty; the test proved nothing"


def test_shield_is_visible_outside_the_hull():
    """And it is really there: a wide ring of pixels beyond the airframe."""
    off, _rend, _game = _scene(0.0)
    on, _rend2, _game2 = _scene(C.SHIELD_TIME - 3.0)
    band = 0
    for y in range(int(PY - 52), int(PY + 52)):
        for x in range(int(PX - 52), int(PX + 52)):
            d = ((x - PX) ** 2 + (y - PY) ** 2) ** 0.5
            if 30.0 <= d <= ui.SHIELD_FX_RADIUS + 6.0 and \
                    off.get_at((x, y)) != on.get_at((x, y)):
                band += 1
    assert band > 400, f"only {band} pixels of bubble outside the hull"


def test_no_shield_no_bubble():
    a, _r, _g = _scene(0.0)
    b, _r2, _g2 = _scene(0.0)
    assert _diff(a, b) == []


# ------------------------------------------------------------------ the pop

def test_deploy_pops_once_and_a_second_pickup_pops_again():
    """The pop is derived from the shield's own countdown, so it needs no state
    and replays when a shield stacks on a running one."""
    fresh, _r, _g = _scene(C.SHIELD_TIME - 0.05)
    steady, _r2, _g2 = _scene(C.SHIELD_TIME - 3.0)
    assert _diff(fresh, steady), "the deploy frame is indistinguishable"
    stacked, _r3, _g3 = _scene(C.SHIELD_TIME - 0.05)
    assert _diff(fresh, stacked) == [], \
        "the pop depends on history it is not supposed to have"


def test_shield_fx_does_not_touch_the_run():
    """Presentation must not consume the seeded stream or eat a bullet."""
    game = Game()
    game.new_game()
    game.start_level(0)
    game.player.shield = C.SHIELD_TIME - 2.0
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rend = ui.Renderer(canvas, C.Settings())
    before = game.rng.getstate()
    bullets = [Bullet(PX + 30.0, PY - 20.0, 0.0, 120.0, C.ENEMY_BULLET_R, 1,
                      friendly=False)]
    for _ in range(30):
        rend._draw_player(game.player, bullets)
    assert game.rng.getstate() == before, "the bubble spent the run's numbers"
    assert len(bullets) == 1


def test_threat_flare_points_at_hostile_fire():
    """The rim lights on the side something is closing in from - and only for
    shots that are actually hostile."""
    calm, _r, _g = _scene(C.SHIELD_TIME - 3.0)
    near = [Bullet(PX - 44.0, PY - 18.0, 0.0, 90.0, C.ENEMY_BULLET_R, 1,
                   friendly=False)]
    lit, _r2, _g2 = _scene(C.SHIELD_TIME - 3.0, near)
    left = _diff(calm, lit)
    assert left, "a bullet at the rim did not light it"
    assert all(x < PX for x, _y in left), "flare lit the wrong side"

    friendly = [Bullet(PX - 44.0, PY - 18.0, 0.0, 90.0, C.ENEMY_BULLET_R, 1,
                       friendly=True)]
    same, _r3, _g3 = _scene(C.SHIELD_TIME - 3.0, friendly)
    assert _diff(calm, same) == [], "your own gunfire should not scare the shield"


def test_far_bullets_leave_the_rim_alone():
    far = [Bullet(PX, PY - 300.0, 0.0, 90.0, C.ENEMY_BULLET_R, 1,
                  friendly=False)]
    calm, _r, _g = _scene(C.SHIELD_TIME - 3.0)
    other, _r2, _g2 = _scene(C.SHIELD_TIME - 3.0, far)
    assert _diff(calm, other) == []


# --------------------------------------------------- the lapse: flash, then fade

def test_the_shield_is_solid_until_the_warning_window():
    """Nothing flickers while the shield has time left - a thing that always
    blinks is a thing that is never noticed blinking."""
    solid = _glow(C.SHIELD_TIME - 1.0)
    assert solid > 0.1, "no bubble to measure"
    for remaining in (C.SHIELD_WARN_TIME + 0.05, C.SHIELD_WARN_TIME + 1.4,
                      C.SHIELD_WARN_TIME + 0.5):
        assert _glow(remaining) == pytest.approx(solid), \
            f"the bubble flickered with {remaining:.2f}s still to run"


def test_the_shield_flashes_once_it_is_warning():
    """Inside the window the bubble alternates between full and dim. Sampled
    across two whole cycles so a rule that only fires once cannot pass."""
    solid = _glow(C.SHIELD_WARN_TIME + 0.5)
    samples = [round(C.SHIELD_WARN_TIME - 0.08 - i * 0.167, 3)
               for i in range(24)]
    levels = {_glow(r) for r in samples}
    bright = max(levels)
    dark = min(levels)
    assert len(levels) >= 2, "the bubble never dimmed inside the window"
    assert bright == pytest.approx(solid, abs=1e-6), "the flash lost its top end"
    assert dark < solid * 0.5, f"dim level {dark:.4f} is not a flash"
    # The dark half is dimmed, not hidden: it still says "you have a shield".
    assert dark > 0.005, "the bubble blinked out entirely"
    assert dark == pytest.approx(solid * C.SHIELD_FLASH_DIM, rel=0.25), \
        "the dark half is not the configured dim level"


def test_the_flash_is_periodic_not_random():
    """A strobe is a clock, not a flicker. Sampled every 50 ms across two
    seconds (well above Nyquist for a 3 Hz flash), the bubble has to change
    state about twelve times - not once, not every sample."""
    solid = _glow(C.SHIELD_WARN_TIME + 0.5)
    states = []
    t = C.SHIELD_WARN_TIME - 0.02
    while t > C.SHIELD_WARN_TIME - 2.0:
        states.append(_glow(t) > solid * 0.7)
        t -= 0.05
    assert any(states) and not all(states), "no flash in two whole seconds"
    flips = sum(1 for a, b in zip(states, states[1:], strict=False)
            if a != b)
    expected = 2.0 * C.SHIELD_FLASH_HZ * 1.98        # half-cycles in the span
    assert expected * 0.7 <= flips <= expected * 1.35, \
        f"{flips} transitions where {expected:.0f} were due (not a strobe)"


def test_the_shield_fades_rather_than_stopping():
    """Over the last second it sinks to nothing. Monotonic, and gone at zero."""
    fade = C.SHIELD_FADE_TIME
    levels = [_glow(fade * (1.0 - i / 8.0)) for i in range(9)]
    assert all(levels[i] >= levels[i + 1] - 1e-9 for i in range(len(levels) - 1)), \
        f"the fade brightened on the way out: {levels}"
    assert levels[0] > levels[-1], "the fade did not fade"
    assert levels[-1] < levels[0] * 0.2, "it expired without leaving"
    assert _glow(0.0) == pytest.approx(0.0), "a dead shield still draws"


def test_the_lapse_rule_is_presentation_only():
    """Flashing is not a mechanic: the model still owns the countdown, and the
    bubble must not spend the run's numbers or shorten anything."""
    game = Game()
    game.new_game()
    game.start_level(0)
    game.player.shield = C.SHIELD_WARN_TIME - 0.5   # mid-flash
    canvas = pygame.Surface((C.LOGICAL_W, C.LOGICAL_H))
    rend = ui.Renderer(canvas, C.Settings())
    before = game.rng.getstate()
    tick = 1.0 / 120.0
    elapsed = 0.0
    while game.player.shield > 0.0:
        rend._draw_player(game.player, [])
        game.player.tick_timers(tick)
        elapsed += tick
    assert game.rng.getstate() == before
    assert C.SHIELD_WARN_TIME - 0.6 < elapsed < C.SHIELD_WARN_TIME - 0.4, \
        f"shield lasted {elapsed:.3f}s, not the {C.SHIELD_WARN_TIME - 0.5}s asked"


def test_the_lapse_survives_the_high_contrast_pen():
    """The pen-drawn fallback ring follows the same rule as the baked bubble,
    or the accessibility mode hides the one warning the effect exists for."""
    hc = dataclasses.replace(C.Settings(), high_contrast=True)
    solid = _glow(C.SHIELD_WARN_TIME + 0.5, hc)
    dimmable = {_glow(C.SHIELD_WARN_TIME - 0.08 - i * 0.167, hc)
                for i in range(12)}
    assert solid > 0.05, "no fallback ring to measure"
    assert min(dimmable) < solid * 0.5, "the fallback ring never flashed"
    assert _glow(0.0, hc) == pytest.approx(0.0), "a dead shield still draws"
    assert _glow(C.SHIELD_FADE_TIME * 0.15, hc) < solid * 0.3, \
        "the fallback ring does not fade out with the bubble"
