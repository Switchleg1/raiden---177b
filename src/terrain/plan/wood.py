"""A stand of props: trees, rocks, craters."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Wood:
    kind: str    # wood | copse | riparian | treeline | orchard | scree |
    #            outcrop
    items: list[tuple[float, float, float]]   # x, y, scale
