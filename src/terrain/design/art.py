"""Prop art as the planner sees it: size, facing, footprint."""
from __future__ import annotations

import math

from .art_table import ART_FRONT, ART_FRONT_DEFAULT, INK, INK_DEFAULT, PROP_OF


def prop_art(kind: str) -> str:
    """The prop art a plan kind is drawn with."""
    return PROP_OF.get(kind, kind)


def ink_size(kind: str, scale: float = 1.0, angle: float = 0.0
             ) -> tuple[float, float]:
    """Ink width and height of a prop as it will be PAINTED.

    ``angle`` is the plan's facing, snapped to the four cardinal facings by
    :func:`_face`. Snapping is what keeps a footprint axis-aligned, and an
    axis-aligned footprint is what makes "does this overlap that" an exact test
    instead of a rumour.
    """
    w, h = INK.get(prop_art(kind), INK_DEFAULT)
    if art_turn(kind, angle) % 180:
        w, h = h, w
    return (w * scale, h * scale)


def art_turn(kind: str, angle: float) -> int:
    """How far to turn a prop's art (pygame degrees, counter-clockwise on screen)
    so that its FRONT faces `angle` (the plan's facing, see `_face`).

    The plan measures a facing with y pointing down; pygame turns art counter-
    clockwise on screen. Passing one straight to the other, as the painter used to,
    turned no building's front toward its street: a square house hid it, and a
    long apartment slab or a parked car stood sideways to its kerb. Where the front
    of each picture is lives in `ART_FRONT`.
    """
    front = ART_FRONT.get(prop_art(kind), ART_FRONT_DEFAULT)
    return int(round((front - angle) / 90.0)) * 90 % 360


def _face(x: float, y: float, tx: float, ty: float) -> int:
    """The cardinal facing that points from (x, y) toward a target.

    Arbitrary angles made every building lean its own way - half of why a row of
    houses read as a pile rather than a lane - and a rotated footprint cannot be
    tested for overlap without rotating the test with it.
    """
    return int(round(math.degrees(math.atan2(ty - y, tx - x)) / 90.0) * 90) % 360


def _ink_rect(kind: str, x: float, y: float, scale: float, angle: float,
              pad: float = 0.0) -> tuple[float, float, float, float]:
    """The ground a prop covers, as ``(x0, y0, x1, y1)`` plus `pad` px of air."""
    w, h = ink_size(kind, scale, angle)
    return (x - w / 2.0 - pad, y - h / 2.0 - pad,
            x + w / 2.0 + pad, y + h / 2.0 + pad)
