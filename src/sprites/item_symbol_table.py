"""Which icon each pickup kind is drawn with. A kind not listed is a mine."""
from __future__ import annotations

from collections.abc import Callable

from .item_symbols import (
    symbol_bomb,
    symbol_extra_life,
    symbol_flame,
    symbol_jammer,
    symbol_medal,
    symbol_mine,
    symbol_missile,
    symbol_moon,
    symbol_shield,
    symbol_weapon,
    symbol_whip,
)

ITEM_SYMBOLS: dict[str, Callable[..., None]] = {
    "weapon": symbol_weapon,
    "missile": symbol_missile,
    "bomb": symbol_bomb,
    "shield": symbol_shield,
    "medal": symbol_medal,
    "extra_life": symbol_extra_life,
    "whip": symbol_whip,
    "moon": symbol_moon,
    "flame": symbol_flame,
    "jammer": symbol_jammer,
    "mine": symbol_mine,
}

__all__ = ["ITEM_SYMBOLS"]
