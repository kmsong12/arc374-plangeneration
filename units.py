"""
units.py - pixel <-> feet conversion helpers.

Scale is anchored to a typical bed length:
    BED_LENGTH_FT   = 6.5 ft   (roughly a twin/queen mattress long side)
    BED_LENGTH_PX   = 100 px   (long side of the default Bed in the catalog)

=> PX_PER_FT = BED_LENGTH_PX / BED_LENGTH_FT ~= 15.38
"""

from __future__ import annotations

BED_LENGTH_FT = 6.5
BED_LENGTH_PX = 100

PX_PER_FT = BED_LENGTH_PX / BED_LENGTH_FT
FT_PER_PX = 1.0 / PX_PER_FT
PX2_PER_FT2 = PX_PER_FT * PX_PER_FT


def px_to_ft(px: float) -> float:
    return px * FT_PER_PX


def ft_to_px(ft: float) -> float:
    return ft * PX_PER_FT


def px2_to_ft2(area_px2: float) -> float:
    return area_px2 / PX2_PER_FT2


def fmt_ft(px: float, digits: int = 1) -> str:
    return f"{px_to_ft(px):.{digits}f} ft"


def fmt_ft2(area_px2: float, digits: int = 0) -> str:
    val = px2_to_ft2(area_px2)
    if digits == 0:
        return f"{int(round(val)):,} ft\u00b2"
    return f"{val:,.{digits}f} ft\u00b2"


def fmt_dims(w_px: float, h_px: float, digits: int = 1) -> str:
    return f"{px_to_ft(w_px):.{digits}f} x {px_to_ft(h_px):.{digits}f} ft"
