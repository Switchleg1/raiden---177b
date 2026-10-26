"""How the cover pass scatters what grows: the treeline belt."""

from __future__ import annotations

#: The treeline, as contour-parallel lines: (distance from the ridge spine, as a
#: fraction of the ridge's half-width, probability a spine point is SKIPPED, and
#: the tree's scale range). The high bands are the sparsest and the smallest: a
#: full crown does not stand on a cliff, and a belt that is uniform reads as a
#: texture, not as the place where the trees stop.
TREELINE_BANDS: tuple[tuple[float, float, tuple[float, float]], ...] = (
    (0.34, 0.70, (0.70, 1.05)),  # the foot of the slope: full trees
    (0.52, 0.78, (0.60, 0.92)),  # over the shoulder
    (0.70, 0.86, (0.48, 0.72)),  # the top: stunted and scattered
)
