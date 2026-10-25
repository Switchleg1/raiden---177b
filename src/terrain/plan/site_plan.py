"""A designed sector: everything planned, and the grids that answer
"what is here"."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..design.geometry import _in_poly, _near_path
from .geom import SCREEN

if TYPE_CHECKING:
    from .building import Building
    from .field import Field
    from .geom import Geom
    from .green import Green
    from .ridge import Ridge
    from .road import Road
    from .water import Water
    from .wood import Wood

from dataclasses import dataclass
from typing import Any


def _y_extent(f: Any) -> tuple[float, float]:
    """The y-range a planned feature occupies, before its reach is added."""
    pts = getattr(f, "path", None)
    if pts is None:
        poly = getattr(f, "poly", None)
        if poly is not None:
            ys = [p[1] for p in poly]
        elif hasattr(f, "items"):
            ys = [p[1] for p in f.items]
        elif hasattr(f, "spine"):
            # a ridge: its points are the spine, and its flanks hang off them.
            # Missing this case put every ridge on a strip at y 0..0, so the
            # slice cull dropped the ridges out of every window but the first -
            # and the spatial index answered "no ridges here" to everything.
            ys = [p[1] for p in f.spine]
            for spur in getattr(f, "spurs", ()):
                ys += [p[1] for p in spur]
        elif hasattr(f, "y"):
            ys = [f.y - getattr(f, "radius", 0.0),
                  f.y + getattr(f, "radius", 0.0)]
        else:                        # pragma: no cover - a new feature kind
            return (0.0, 0.0)
    else:
        ys = [p[1] for p in pts]
    drive = getattr(f, "drive", None)
    if drive:
        ys += [p[1] for p in drive]
    if not ys:
        # An item list emptied by a later pass (a building cleared the growth it
        # stands on) has no extent, and `min()` of nothing is a crash inside the
        # paint worker. A range no window can intersect is the honest answer.
        return (1.0e18, -1.0e18)
    return (min(ys), max(ys))


@dataclass
class SitePlan:
    theme: str
    seed: int
    ridges: list[Ridge]
    water: list[Water]
    roads: list[Road]
    buildings: list[Building]
    fields: list[Field]
    woods: list[Wood]
    greens: list[Green]
    relief: list[list[float]]         # [row][col], 0..1
    wet: list[list[bool]]
    built: list[list[bool]]
    #: ground a PLACE owns: its lane, its clearing, its highway corridor. Kept
    #: separate from `built` on purpose - `built` means "a footprint stands here",
    #: and a place must be able to build on the ground it reserved. Using one grid
    #: for both made every blueprint block its own buildings: the neighborhood
    #: claimed its disc, then refused every house in it.
    place: list[list[bool]] | None = None
    geom: Geom = SCREEN
    #: how fought-over this ground is, 0..1 (see `terrain.design.war`)
    scars: float = 0.0
    _bands: dict | None = None
    # (y_lo, y_hi, corridor half-width, path) per road, rebuilt when roads change
    _road_box: list | None = None
    _road_n: int = -1

    # ------------------------------------------------------------- windowing
    # How far a feature of each kind reaches beyond its own y-range. The painter
    # used to walk every feature of the plan for every window - 357 houses and
    # 2700 wood stamps per slice, each rotated and blitted and thrown away. On a
    # thirty-screen strip that is the difference between painting a slice in a
    # second and in half a minute.
    # How far past its own anchor a feature of this kind can paint, in bake px: a
    # window that cannot see a feature's anchor must still paint the part of it that
    # reaches into the kept band, or a house ends up cut in half along a boundary -
    # and no overlap test can see that, because both neighbours dropped it happily.
    # These values were raised once on a hunch (320/90/260/160) and measured: the
    # slice-vs-one-window difference did not move at all (0.04% either way), so the
    # clipped-feature explanation was wrong and the extra reach is only extra work.
    # Lowered numbers are guarded by `scripts/study_slice_seams.py`; if a theme ever
    # grows a sprite that paints past these, that measurement moves first.
    _REACH = {"ridges": 0.0, "water": 0.0, "roads": 0.0, "buildings": 130.0,
              "fields": 30.0, "woods": 150.0, "greens": 70.0}

    def band(self, kind: str, y0: float, y1: float) -> list[int]:
        """Indices of the features of `kind` that can appear in a y-range.

        Indices, not features: the painter's jitter is keyed to the feature's
        index in the plan, and a window that saw a renumbered neighbourhood
        would grow different hedges than the window next door.

        A wrapping (one-screen) plan answers with everything: its features wrap
        across the seam, so culling by y would drop the seam copies and change
        the baked maps.
        """
        attr = {"ridges": "ridges", "water": "water", "roads": "roads",
                "buildings": "buildings", "fields": "fields",
                "woods": "woods", "greens": "greens"}[kind]
        feats = getattr(self, attr)
        if self.geom.cyclic:
            return list(range(len(feats)))
        self._bands = self._bands or {}
        ranges = self._bands.get(kind)
        if ranges is None:
            reach = self._REACH[kind]
            ranges = []
            for i, f in enumerate(feats):
                lo, hi = _y_extent(f)
                if kind == "ridges":
                    reach = f.width * 3.4 + 40.0
                elif kind == "water":
                    reach = max(f.flood, f.half * 2.0) + 60.0
                elif kind == "roads":
                    reach = f.width * 2.0 + 90.0
                elif kind == "buildings":
                    # A building is not its footprint. It stamps a prop sprite
                    # (256 px of art at `scale`, so it overhangs 128*scale either
                    # way) and splats a yard (art scaled by radius/60, so about
                    # 2.1 radii beyond the yard's own edge). The constant 130 was a
                    # guess at the sprite and covered neither, so a neighbour's yard
                    # appeared in the window that happened to include it and not in
                    # the one painting the ground under it - measured as one compact
                    # 100x100 px blob of differently-shaded ground at a slice
                    # boundary, present in a one-window reference and absent from the
                    # slice. Reach is what the feature DRAWS, not what it IS.
                    spread = 128.0 * float(getattr(f, "scale", 1.0)) + 40.0
                    if getattr(f, "yard", None):
                        spread = max(spread, 2.2 * float(f.yard[2]) + 40.0)
                    reach = max(reach, spread)
                elif kind == "woods":
                    # The stand's trees are its own props, up to 256*scale wide,
                    # and its edge is the outermost crown, not the stand's points.
                    reach = max(reach, 128.0 + 40.0)
                elif kind == "greens":
                    # A green draws its lanes too, and they run out to the houses
                    # around it - a window that saw the anchor but not the lane end
                    # (or the reverse) painted half a lane, which is the same
                    # half-a-house artifact at a slice boundary wearing a different
                    # hat. Reach is what the feature DRAWS.
                    lanes = getattr(f, "lanes", None) or []
                    far = max((max(abs(p2[1] - f.y) for p2 in lane)
                               for lane in lanes), default=0.0)
                    reach = max(reach, far + 20.0)
                ranges.append((lo - reach, hi + reach, i))
            self._bands[kind] = ranges
        return [i for lo, hi, i in ranges if hi >= y0 and lo <= y1]

    # ------------------------------------------------------------------ asks
    def relief_at(self, x: float, y: float) -> float:
        return self.relief[self.geom.row(y)][self.geom.col(x)]

    def is_wet(self, x: float, y: float) -> bool:
        return self.wet[self.geom.row(y)][self.geom.col(x)]

    def is_built(self, x: float, y: float) -> bool:
        return self.built[self.geom.row(y)][self.geom.col(x)]

    def in_road_corridor(self, x: float, y: float,
                         margin: float = 30.0) -> bool:
        """Is this point inside a road's cleared corridor?

        Every road is tested - not just the one a building faces - because a
        building set back from its own lane can still be standing on a highway the
        lane runs beside.

        Cheap by bounding box first: roads are indexed once per plan by the y they
        span, and a point outside that span plus the corridor cannot be in it.
        Without that prefilter the check walked every segment of every road for
        every candidate building, and planning a 24-screen strip went from seconds
        to two minutes.
        """
        if self._road_box is None or self._road_n != len(self.roads):
            self._road_n = len(self.roads)
            self._road_box = [(min(p[1] for p in r.path),
                               max(p[1] for p in r.path),
                               r.width * 0.5 + margin, r.path)
                              for r in self.roads]
        for lo, hi, half, path in self._road_box:
            if not (lo - half <= y <= hi + half):
                continue
            if _near_path(self.geom, x, y, path, half):
                return True
        return False

    def is_place(self, x: float, y: float) -> bool:
        """Is this ground owned by a place (a lane, a clearing, a road corridor)?

        Vegetation and parcels stay out of it. Buildings may stand in it - they are
        the place.
        """
        return bool(self.place) and             self.place[self.geom.row(y)][self.geom.col(x)]

    def near_water(self, x: float, y: float, dist: float) -> bool:
        for w in self.water:
            # A CLOSED body is a region, and being inside it is closer to water than
            # any distance test against its outline can say. `_near_path` measures to
            # the shoreline, and a lake's `half` is its MINOR radius: a point deep in
            # the middle of a wide lake is further from the outline than `half`, so
            # every guard of the form `near_water(x, y, 70)` - scree, outcrops,
            # vegetation - read the middle of a lake as dry ground and dropped rocks
            # in it.
            if w.closed and _in_poly(x, y, w.path):
                return True
            if _near_path(self.geom, x, y, w.path, dist):
                return True
        return False

    def near_road(self, x: float, y: float, dist: float) -> bool:
        return any(_near_path(self.geom, x, y, r.path, dist)
                   for r in self.roads)
