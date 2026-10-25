"""Buildings: drives, yards and the props themselves."""
from __future__ import annotations

import random

from ..plan.site_plan import SitePlan
from ..tilekit import CH, TileKit
from .ink import _fill_mask, _splat
from .plane import Plane
from .raster import _path_mask
from .sampling import _band, _frand
from .surface import _blit_wrap, _shadow_on, _target


def paint_buildings(canvas: Plane, kit: TileKit, plan: SitePlan,
                    rng: random.Random) -> None:
    for bi in _band(canvas, plan, "buildings"):
        b = plan.buildings[bi]
        frng = _frand(plan, bi, 47)
        # the approach first: a drive from the door to the road, and a yard
        if b.drive:
            _fill_mask(canvas, kit, "road_dirt",
                   _path_mask(b.drive, 12.0, canvas), 0.8)
        if b.yard:
            yx, yy, yr = b.yard
            _splat(kit, canvas, "splat_dirt", yx, yy, yr / 60.0, frng)
        # The plan speaks in plan kinds ("barn", "hut"); the atlas speaks in art
        # names ("barn_red", "hut_stilt"). That alias used to be missing, and the
        # fallback drew a HOUSE for every barn in the game - which is one reason a
        # farm read as a pile of houses.
        from ..design.art import prop_art
        name = prop_art(b.kind)
        if name not in kit.props:
            name = "house_top"
        import pygame
        p = kit.props[name]
        from ..design.art import art_turn
        p = pygame.transform.rotozoom(p, art_turn(b.kind, b.angle), b.scale)
        _shadow_on(canvas, b.x + p.get_width() * 0.06,
                   b.y + p.get_height() * 0.09,
                   p.get_width() * 0.42, p.get_height() * 0.34, 60)
        _blit_wrap(canvas, p, b.x - p.get_width() / 2, b.y - p.get_height() / 2)
        # a house's near edge catches the light: this is what makes a sprite
        # read as a built thing sitting on ground rather than pasted on it
        lx, ly = (canvas.local(b.x - p.get_width() * 0.18,
                               b.y - p.get_height() * 0.2)
                  if isinstance(canvas, Plane)
                  else (int(b.x - p.get_width() * 0.18),
                        int((b.y - p.get_height() * 0.2) % CH)))
        pygame.draw.circle(_target(canvas), (255, 255, 255), (int(lx), int(ly)),
                           1)
        if isinstance(canvas, Plane):
            canvas.touch_box(b.x - p.get_width() * 0.18 - 2,
                             b.y - p.get_height() * 0.2 - 2,
                             b.x + p.get_width() * 0.18 + 2,
                             b.y + p.get_height() * 0.2 + 2)
