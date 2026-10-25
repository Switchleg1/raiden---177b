"""Which profile each ridge shape is drawn with."""
from __future__ import annotations

import random
from collections.abc import Callable

from .crests import (
    _crest_cone,
    _crest_domefield,
    _crest_hogback,
    _crest_massif,
    _crest_mesa,
    _crest_ridge,
    _crest_sawback,
)

CRESTS: dict[str, Callable[[int, random.Random], list[float]]] = {
    "sawback": _crest_sawback,
    "domefield": _crest_domefield,
    "mesa": _crest_mesa,
    "cone": _crest_cone,
    "hogback": _crest_hogback,
    "massif": _crest_massif,
    "ridge": _crest_ridge,
}

#: every shape a theme may name in `SiteSpec.ridge_shapes`
SHAPES = tuple(CRESTS)

#: how many spurs leave a ridge of each shape, (min, max): a ridge system, not a
#: line. Massifs and cones get the most; a mesa stands alone.
RIDGE_ARMS: dict[str, tuple[int, int]] = {
    "massif": (3, 6), "cone": (3, 5), "sawback": (1, 3), "domefield": (1, 3),
    "hogback": (1, 2), "mesa": (0, 1), "ridge": (1, 2),
}

__all__ = ["CRESTS", "RIDGE_ARMS", "SHAPES"]
