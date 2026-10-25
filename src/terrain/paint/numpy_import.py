"""numpy, imported lazily: the painter runs without it (vector fallback)."""
from __future__ import annotations

from typing import Any


def _numpy() -> Any:
    try:
        import numpy as np
        return np
    except ImportError:                                   # pragma: no cover
        return None
