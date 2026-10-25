"""Laying a sector's places, in order."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .builders_table import BUILDERS
from .siting import _choose, _claim
from .vocabulary_table import VOCABULARY

if TYPE_CHECKING:
    from .claim import _Claim

import random

from ...plan.site_plan import SitePlan


def lay_places(plan: SitePlan, names: tuple[str, ...],
               rng: random.Random) -> dict[str, int]:
    """Lay the sector's places. Returns what was built, for the log and the tests.

    Order matters and is deliberate: the things that claim the most ground and
    decide the pattern (a highway's corridor, a neighborhood's lane) go first, and
    the small things that lean against them (a campground by the water) come after,
    because they are sited against what the earlier passes left.
    """
    if not names:
        return {}
    claims: list[_Claim] = []
    out: dict[str, int] = {}
    for name in sorted(names, key=lambda n: (VOCABULARY[n].order, n)):
        ps = VOCABULARY.get(name)
        if ps is None:
            raise KeyError(f"no blueprint for place {name!r}; "
                           f"known: {', '.join(sorted(VOCABULARY))}")
        want = max(1, int(round(plan.geom.screens
                                    / rng.uniform(ps.per[0], ps.per[1]))))
        made = 0
        tries = 0
        while made < want and tries < want * 4:
            # `want` is how many of these the sector SHOULD have, so it is the number
            # of successes, not the number of looks. A neighborhood asked once or
            # twice per sector, and when both anchors happened to fall on ground the
            # footprint rules refuse, the sector shipped with no settlement at all -
            # which is what the sector-level neighborhood test kept catching.
            tries += 1
            site = _choose(plan, claims, ps, rng)
            if site is None:
                continue
            # Claim AFTER building. Claiming first made a place stand inside its
            # own reservation: the blueprint's lane lay within its own disc, the
            # corridor test read that as someone else's ground, and the
            # neighborhood lost every lane it tried. Claims still happen on
            # failure (marked with what was tried) so the next attempt is not the
            # same anchor over and over.
            made_here = BUILDERS[name](plan, site, ps, rng)
            _claim(claims, plan, site, ps, name)
            # a PLACE was made if its builder put anything down. Adding the builder's
            # count of buildings here let one twenty-house estate stand in for the
            # two estates the sector asked for.
            made += 1 if made_here > 0 else 0
        out[name] = made
    return out
