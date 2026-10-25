"""Which prop art a kind of vegetation (or debris) is drawn with, where that
does not depend on the theme."""
from __future__ import annotations

COVER_PROPS: dict[str, tuple[str, ...]] = {
    "charred": ("tree_charred",),
}

__all__ = ["COVER_PROPS"]
