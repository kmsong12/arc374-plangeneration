"""
geometry_utils.py – Low-level geometry helpers.
"""


def snap_to_grid(v: float, g: int) -> int:
    return int(round(v / g)) * g


def rect_overlap(x1, y1, w1, h1, x2, y2, w2, h2) -> bool:
    return not (x1+w1 <= x2 or x2+w2 <= x1 or y1+h1 <= y2 or y2+h2 <= y1)


def overlaps_any(r, rooms, pad: int = 0) -> bool:
    x, y, w, h = r
    for rx, ry, rw, rh in rooms:
        if rect_overlap(x-pad, y-pad, w+2*pad, h+2*pad, rx, ry, rw, rh):
            return True
    return False


def point_in_rect(px, py, rx, ry, rw, rh) -> bool:
    return rx <= px <= rx+rw and ry <= py <= ry+rh


def rect_from_two_points(x0, y0, x1, y1):
    x = min(x0, x1); y = min(y0, y1)
    return x, y, abs(x1-x0), abs(y1-y0)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def rooms_inside_zone(rooms, zone):
    """Return subset of rooms whose centre lies inside zone (x,y,w,h)."""
    zx, zy, zw, zh = zone
    return [r for r in rooms
            if zx <= r.cx <= zx+zw and zy <= r.cy <= zy+zh]