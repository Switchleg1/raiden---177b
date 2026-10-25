"""The planner's entry point: plan_site."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..plan.geom import SCREEN
from ..plan.site_plan import SitePlan
from .circulation import _add_decks, _bridge_spans, _circulation
from .cover import _cover
from .drainage import _drainage, _water_mark
from .fields import _fields
from .orogeny import _orogeny
from .settlement import _settlement
from .spec_table import SPEC

if TYPE_CHECKING:
    from ..plan.geom import Geom

import logging
import random
from dataclasses import replace

_LOG = logging.getLogger("raiden.terrain.design")


def _theme_index(theme: str) -> int:
    names = sorted(SPEC)
    try:
        return names.index(theme)
    except ValueError:
        return len(names)


def _rng(theme: str, seed: int) -> random.Random:
    """Deterministic per (seed, theme) - no ``hash()``, which salted per run."""
    return random.Random((seed * 1_000_003 + _theme_index(theme) * 7919)
                         & 0x7FFFFFFF)


def plan_site(theme: str, seed: int, geom: Geom | None = None,
              scars: float = 0.0) -> SitePlan:
    """Design a sector's ground. Deterministic from ``(seed, theme, geom)``.

    ``geom`` is the ground being designed: one screen by default, a longer strip
    for a streamed sector. Densities and the reach of a meander key off it, so a
    six-screen strip is a designed six screens and not one screen stretched.
    """
    g = geom or SCREEN
    if theme not in SPEC:
        # an unknown theme used to fall back to the default landscape, so a typo
        # in a level table silently painted rolling farmland where a glacier was
        # intended - and the picture looked plausible enough to ship
        raise KeyError(f"no site spec for theme {theme!r}; "
                       f"known: {', '.join(sorted(SPEC))}")
    spec = SPEC[theme]
    rng = _rng(theme, seed)
    if not g.cyclic:
        # more than one of everything a screen gets: a range, a hamlet, a
        # stand of woods per screen, each a local story the next one continues
        spec = replace(
            spec,
            ridge_count=(max(1, round(spec.ridge_count[0] * g.screens * 0.6)),
                         max(1, round(spec.ridge_count[1] * g.screens * 0.6))),
            woods=(max(1, round(spec.woods[0] * g.screens)),
                   max(1, round(spec.woods[1] * g.screens))))
    ridges, relief = _orogeny(g, spec, rng)
    # Normalise the height field. Raw orogeny peaks near 0.6, and the painter's
    # colour ramp, rock coverage and snowline are all calibrated 0..1 - so an
    # un-normalised plan paints a mountain range at two thirds of its own
    # possible contrast, which is what made reviewers write "no convincing
    # elevation" for every single theme.
    peak = max(max(row) for row in relief)
    if peak > 0.05:
        # normalise to the theme's own target, not always to full scale: a
        # canyon range and a village's low terrace are not the same kind of
        # ground, and the painter's rock and snow thresholds key off h
        gain = spec.relief_gain / peak
        relief = [[min(1.0, v * gain) for v in row] for row in relief]
    water = _drainage(g, spec, relief, rng)
    plan = SitePlan(theme=theme, seed=seed, ridges=ridges, water=water,
                    roads=[], buildings=[], fields=[], woods=[], greens=[],
                    relief=relief,
                    wet=[[False] * g.cols for _ in range(g.rows)],
                    built=[[False] * g.cols for _ in range(g.rows)], geom=g)
    _water_mark(plan)
    plan.roads = _circulation(g, spec, plan.relief, water, rng)
    # Settlement BEFORE fields, which is the order the module promises: the road
    # decides where the houses stand, and the flat dry ground the road and the
    # houses left over is what gets enclosed as fields. Run the other way round,
    # the parcels took the roadside and the frontage row was pushed into the
    # leftovers - which is part of why the houses looked put down at random.
    # Places first, then the frontage row, then the fields that enclose whatever
    # settled ground is left. Two orderings were wrong before this: fields claimed
    # the ground a blueprint was about to build on (a lane got laid and then lost
    # every house on it), and with settlement first the frontage row took the
    # roadside - which is where a neighborhood hangs its lane from - so the
    # neighborhood was sited onto ground the houses had already claimed and lost
    # every footprint to `built`. A place owns ground; a frontage house fills a
    # gap. That is the order that says so.
    from .places.lay import lay_places
    built = lay_places(plan, spec.places, rng)
    # Reconcile the roads with the water once, AFTER the vocabulary is down: a
    # lane laid before a lake can cross it, and a road standing in water with no
    # deck is the "road fords the river" artifact this project has already been
    # told about twice.
    for r in plan.roads:
        _add_decks(r, _bridge_spans(g, r.path, plan.water))
    if built:
        _LOG.debug("places for %s: %s", theme,
                   ", ".join(f"{k}={v}" for k, v in sorted(built.items())))
    _settlement(spec, plan, rng)
    _fields(spec, plan, rng)
    _cover(spec, plan, rng)
    # the war, last: the same ground, broken (a no-op at scars 0)
    from .war import scar
    scar(plan, scars)
    return plan
