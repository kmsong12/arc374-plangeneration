"""
furniture_geometry.py - Resize helpers for placed furniture (unrotated w×h, rot°).
"""

from __future__ import annotations

import math
from typing import List, Tuple

from geometry_utils import rotated_rect_corners

MIN_FURN_W = 12.0
MIN_FURN_H = 12.0


def world_to_local(rot_deg: float, dwx: float, dwy: float) -> Tuple[float, float]:
    r = math.radians(rot_deg)
    co, sn = math.cos(r), math.sin(r)
    return (co * dwx + sn * dwy, -sn * dwx + co * dwy)


def topleft_from_center(cx: float, cy: float, w: float, h: float) -> Tuple[float, float]:
    return (cx - w * 0.5, cy - h * 0.5)


def R(rot_deg: float, lx: float, ly: float) -> Tuple[float, float]:
    r = math.radians(rot_deg)
    co, sn = math.cos(r), math.sin(r)
    return (co * lx - sn * ly, sn * lx + co * ly)


def furniture_handle_positions(
        x: float, y: float, w: float, h: float, rot_deg: float) -> List[Tuple[str, float, float]]:
    """Eight handle ids with world (wx, wy) for resize hit-testing and drawing."""
    corn = rotated_rect_corners(x, y, w, h, rot_deg)
    nw, ne, se, sw = corn[0], corn[1], corn[2], corn[3]

    def m(a, b):
        return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)

    return [
        ("nw", nw[0], nw[1]), ("ne", ne[0], ne[1]),
        ("se", se[0], se[1]), ("sw", sw[0], sw[1]),
        ("n", m(nw, ne)[0], m(nw, ne)[1]), ("e", m(ne, se)[0], m(ne, se)[1]),
        ("s", m(se, sw)[0], m(se, sw)[1]), ("w", m(sw, nw)[0], m(sw, nw)[1]),
    ]


def apply_resize(
        x0: float, y0: float, w0: float, h0: float, rot0: float,
        handle: str, mouse_wx: float, mouse_wy: float) -> Tuple[float, float, float, float] | None:
    """Return new (x, y, w, h) in template space, or None."""
    corners = rotated_rect_corners(x0, y0, w0, h0, rot0)
    nw, ne, se, sw = corners[0], corners[1], corners[2], corners[3]
    th = float(rot0)
    Mx, My = float(mouse_wx), float(mouse_wy)

    if handle == "se":
        dlx, dly = world_to_local(th, Mx - nw[0], My - nw[1])
        w1 = max(MIN_FURN_W, dlx)
        h1 = max(MIN_FURN_H, dly)
        cx, cy = nw[0] + R(th, w1 * 0.5, h1 * 0.5)[0], nw[1] + R(th, w1 * 0.5, h1 * 0.5)[1]
    elif handle == "nw":
        dlx, dly = world_to_local(th, Mx - se[0], My - se[1])
        w1 = max(MIN_FURN_W, -dlx)
        h1 = max(MIN_FURN_H, -dly)
        cx, cy = se[0] + R(th, -w1 * 0.5, -h1 * 0.5)[0], se[1] + R(th, -w1 * 0.5, -h1 * 0.5)[1]
    elif handle == "ne":
        dlx, dly = world_to_local(th, Mx - sw[0], My - sw[1])
        w1 = max(MIN_FURN_W, dlx)
        h1 = max(MIN_FURN_H, -dly)
        cx, cy = sw[0] + R(th, w1 * 0.5, h1 * 0.5)[0], sw[1] + R(th, w1 * 0.5, h1 * 0.5)[1]
    elif handle == "sw":
        dlx, dly = world_to_local(th, Mx - ne[0], My - ne[1])
        w1 = max(MIN_FURN_W, -dlx)
        h1 = max(MIN_FURN_H, dly)
        cx, cy = ne[0] + R(th, -w1 * 0.5, h1 * 0.5)[0], ne[1] + R(th, -w1 * 0.5, h1 * 0.5)[1]
    elif handle == "e":
        wmid = ((nw[0] + sw[0]) * 0.5, (nw[1] + sw[1]) * 0.5)
        dlx, dly = world_to_local(th, Mx - wmid[0], My - wmid[1])
        w1 = max(MIN_FURN_W, dlx)
        h1 = h0
        cx, cy = wmid[0] + R(th, w1 * 0.5, 0.0)[0], wmid[1] + R(th, w1 * 0.5, 0.0)[1]
    elif handle == "w":
        wmid = ((ne[0] + se[0]) * 0.5, (ne[1] + se[1]) * 0.5)
        dlx, dly = world_to_local(th, Mx - wmid[0], My - wmid[1])
        w1 = max(MIN_FURN_W, -dlx)
        h1 = h0
        cx, cy = wmid[0] + R(th, -w1 * 0.5, 0.0)[0], wmid[1] + R(th, -w1 * 0.5, 0.0)[1]
    elif handle == "n":
        # Drag top edge: keep bottom (S) side fixed.
        smid = ((sw[0] + se[0]) * 0.5, (sw[1] + se[1]) * 0.5)
        dlx, dly = world_to_local(th, Mx - smid[0], My - smid[1])
        w1 = w0
        h1 = max(MIN_FURN_H, -dly)
        cx, cy = smid[0] - R(th, 0.0, h1 * 0.5)[0], smid[1] - R(th, 0.0, h1 * 0.5)[1]
    elif handle == "s":
        nmid = ((nw[0] + ne[0]) * 0.5, (nw[1] + ne[1]) * 0.5)
        dlx, dly = world_to_local(th, Mx - nmid[0], My - nmid[1])
        w1 = w0
        h1 = max(MIN_FURN_H, dly)
        cx, cy = nmid[0] + R(th, 0.0, h1 * 0.5)[0], nmid[1] + R(th, 0.0, h1 * 0.5)[1]
    else:
        return None
    x1, y1 = topleft_from_center(cx, cy, w1, h1)
    return (x1, y1, w1, h1)
