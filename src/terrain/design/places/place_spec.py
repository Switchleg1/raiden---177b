"""What a kind of place is: how many, where, what it claims."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlaceSpec:
    """What a kind of place IS: how many, where it sits, and what it claims."""

    name: str
    #: how much strip ONE instance wants, in screens. Counted this way because the
    #: old "per screen" reading made a 4-screen sector ask for 4-8 woodlands and 4-8
    #: lakes: measured, 6-9 closed water bodies and 1300 trees in one sector, i.e. a
    #: map that is water and forest with nowhere for a lane. A woodland is a landmark
    #: every two or three screens, not a texture on every screen.
    per: tuple[float, float] = (2.0, 3.0)
    #: the ground it claims around its anchor, bake px. Two places may not overlap
    #: discs, which is what stops a campground standing inside a neighborhood.
    reach: float = 260.0
    #: the ground it actually OCCUPIES - what gets painted into the `place` grid.
    #: Kept separate from `reach` because one number cannot do both jobs: at
    #: reach x 0.62 a neighborhood's reservation is a 534 px disc in a 1460 px-wide
    #: sector, so three of them cover the map end to end, and every lane the next
    #: neighborhood tries crosses someone's reservation and is refused. Measured:
    #: four sites chosen, thirty-six lanes refused, zero houses built.
    keep: float = 150.0
    #: siting rules, all must hold: "flat" (low relief), "dry" (not wet ground),
    #: "offroad" (not on a carriageway)
    needs: tuple[str, ...] = ("flat", "dry", "offroad")
    #: what it leans against, and how far it will walk to find it
    against: str = ""             # "road" | "water" | "wood" | ""
    against_max: float = 420.0
    #: prop kinds it is allowed to build with (theme-free: these are plan kinds)
    kinds: tuple[str, ...] = ()
    #: how many candidate anchors to score before giving up on one
    tries: int = 24
    #: kinds of place this one keeps away from, and by how far beyond their own
    #: ground (bake px). A lake does not belong in a subdivision: the estate is
    #: houses facing streets, and still water inside it read as a park pond at
    #: best and as a flooded estate at worst.
    shun: tuple[tuple[str, float], ...] = ()
    #: if non-zero, a road must be within this many px: a place sited against
    #: something else (a camp against water) is still reached by a road, and
    #: siting it without asking put camps 600 px from any track, which the builder
    #: then refused - every camp in a sector, every time
    road_max: float = 0.0
    #: how far "offroad" is, px from a carriageway: at least the place's own
    #: footprint, or its clearing is laid across the road and refused
    offroad: float = 70.0
    #: who lays first. A neighborhood needs the roadside more than a campground
    #: needs a clearing, so it asks first; sorted (order, name) keeps that
    #: deterministic instead of dependent on dict or theme-tuple order.
    order: int = 1
