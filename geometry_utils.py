"""
geometry_utils.py – Low-level geometry helpers.
Ported and extended from the Processing midterm version.
"""


def snap_to_grid(v: float, g: int) -> int:
    """Snap value v to the nearest multiple of g."""
    return int(round(v / g)) * g


def rect_overlap(x1, y1, w1, h1, x2, y2, w2, h2) -> bool:
    """Return True if two axis-aligned rectangles overlap (AABB test)."""
    return not (
        x1 + w1 <= x2
        or x2 + w2 <= x1
        or y1 + h1 <= y2
        or y2 + h2 <= y1
    )


def overlaps_any(r, rooms, pad: int = 0) -> bool:
    """
    Return True if rectangle r (x,y,w,h) overlaps any rectangle in rooms,
    with an optional outward padding applied to r.
    """
    x, y, w, h = r
    for rx, ry, rw, rh in rooms:
        if rect_overlap(x - pad, y - pad, w + 2 * pad, h + 2 * pad, rx, ry, rw, rh):
            return True
    return False


def point_in_rect(px, py, rx, ry, rw, rh) -> bool:
    """Return True if point (px, py) is inside rectangle (rx, ry, rw, rh)."""
    return rx <= px <= rx + rw and ry <= py <= ry + rh


def rect_from_two_points(x0, y0, x1, y1):
    """Return (x, y, w, h) from two corner points in any order."""
    x = min(x0, x1)
    y = min(y0, y1)
    w = abs(x1 - x0)
    h = abs(y1 - y0)
    return x, y, w, h
