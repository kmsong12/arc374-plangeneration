"""
geometry_utils.py - Low-level geometry helpers.

Rectangle helpers (used by the dart-throwing packer):
    snap_to_grid, rect_overlap, overlaps_any, point_in_rect, rect_from_two_points

Polygon helpers (used by the final-modifications drag/snap-back):
    polygon_bbox, point_in_polygon, rotate_polygon, translate_polygon,
    polygons_overlap_sat
"""

from __future__ import annotations
import math
from typing import Iterable, List, Sequence, Tuple

Point = Tuple[float, float]
Polygon = Sequence[Point]


# ---------------------------------------------------------------------------
# Rectangle helpers
# ---------------------------------------------------------------------------

def snap_to_grid(v: float, g: int) -> int:
    return int(round(v / g)) * g


def rect_overlap(x1, y1, w1, h1, x2, y2, w2, h2) -> bool:
    return not (x1 + w1 <= x2 or x2 + w2 <= x1 or
                y1 + h1 <= y2 or y2 + h2 <= y1)


def overlaps_any(r, rooms, pad: int = 0) -> bool:
    x, y, w, h = r
    for rx, ry, rw, rh in rooms:
        if rect_overlap(x - pad, y - pad, w + 2 * pad, h + 2 * pad,
                        rx, ry, rw, rh):
            return True
    return False


def point_in_rect(px, py, rx, ry, rw, rh) -> bool:
    return rx <= px <= rx + rw and ry <= py <= ry + rh


def rect_from_two_points(x0, y0, x1, y1):
    x = min(x0, x1)
    y = min(y0, y1)
    return x, y, abs(x1 - x0), abs(y1 - y0)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def rooms_inside_zone(rooms, zone):
    """Return subset of rooms whose centre lies inside zone (x,y,w,h)."""
    zx, zy, zw, zh = zone
    result = []
    for r in rooms:
        cx = getattr(r, "cx", None)
        cy = getattr(r, "cy", None)
        if cx is None or cy is None:
            continue
        if zx <= cx <= zx + zw and zy <= cy <= zy + zh:
            result.append(r)
    return result


# ---------------------------------------------------------------------------
# Polygon helpers
# ---------------------------------------------------------------------------

def polygon_bbox(poly: Polygon) -> Tuple[float, float, float, float]:
    """Axis-aligned bounding box as (x, y, w, h)."""
    if not poly:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    return (x0, y0, x1 - x0, y1 - y0)


def polygon_centroid(poly: Polygon) -> Point:
    """Area-weighted centroid for a simple polygon; falls back to bbox centre."""
    n = len(poly)
    if n < 3:
        x, y, w, h = polygon_bbox(poly)
        return (x + w / 2.0, y + h / 2.0)
    a = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    a *= 0.5
    if abs(a) < 1e-9:
        x, y, w, h = polygon_bbox(poly)
        return (x + w / 2.0, y + h / 2.0)
    cx /= (6.0 * a)
    cy /= (6.0 * a)
    return (cx, cy)


def translate_polygon(poly: Polygon, dx: float, dy: float) -> List[Point]:
    return [(x + dx, y + dy) for x, y in poly]


def rotate_polygon(poly: Polygon, deg: float,
                   cx: float | None = None,
                   cy: float | None = None) -> List[Point]:
    """Rotate polygon by `deg` about (cx,cy). Defaults to centroid."""
    if cx is None or cy is None:
        ccx, ccy = polygon_centroid(poly)
        cx = ccx if cx is None else cx
        cy = ccy if cy is None else cy
    r = math.radians(deg)
    ca = math.cos(r)
    sa = math.sin(r)
    out: List[Point] = []
    for x, y in poly:
        dx = x - cx
        dy = y - cy
        out.append((cx + dx * ca - dy * sa, cy + dx * sa + dy * ca))
    return out


def point_in_polygon(p: Point, poly: Polygon) -> bool:
    """Standard even-odd ray cast."""
    x, y = p
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and \
                (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _project(poly: Polygon, axis: Point) -> Tuple[float, float]:
    ax, ay = axis
    dots = [x * ax + y * ay for x, y in poly]
    return (min(dots), max(dots))


def _edge_axes(poly: Polygon) -> List[Point]:
    """Outward (perpendicular to edge) axes, normalised."""
    axes: List[Point] = []
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        ex, ey = x1 - x0, y1 - y0
        length = math.hypot(ex, ey) or 1e-12
        # perpendicular
        axes.append((-ey / length, ex / length))
    return axes


def polygons_overlap_sat(a: Polygon, b: Polygon) -> bool:
    """
    Separating Axis Theorem overlap test for two CONVEX polygons.
    For concave polygons this is approximate (uses bounding convex-ish test);
    good enough for our "does this room's bbox-shape overlap another room"
    snap-back check, where polygons are generally convex or near-convex.
    """
    if not a or not b:
        return False
    for axis in list(_edge_axes(a)) + list(_edge_axes(b)):
        amin, amax = _project(a, axis)
        bmin, bmax = _project(b, axis)
        if amax < bmin or bmax < amin:
            return False
    return True


def polygon_overlaps_any(poly: Polygon,
                         others: Iterable[Polygon]) -> bool:
    for other in others:
        # cheap bbox reject first
        ax, ay, aw, ah = polygon_bbox(poly)
        bx, by, bw, bh = polygon_bbox(other)
        if not rect_overlap(ax, ay, aw, ah, bx, by, bw, bh):
            continue
        if polygons_overlap_sat(poly, other):
            return True
    return False


def rect_to_polygon(x: float, y: float, w: float, h: float) -> List[Point]:
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def regular_polygon(n: int,
                    bbox: Tuple[float, float, float, float],
                    grid: int = 1) -> List[Point]:
    """Regular N-gon inscribed in *bbox*.

    - N == 4 is a special case: an axis-aligned rectangle occupying the
      whole bbox (so the familiar "drag corners to resize" UX is kept).
    - For any other N >= 3 the polygon is inscribed in a circle centred
      in the bbox with radius ``min(W, H) / 2``. Odd N orients an apex
      upward; even N gives a flat top edge.
    - When ``grid >= 2`` each vertex is snapped to a multiple of
      ``grid``. If the snap would collapse two vertices onto the same
      point the unsnapped floats are returned instead.
    """
    n = max(3, int(n))
    bx, by, bw, bh = bbox
    if bw <= 0 or bh <= 0:
        bw = max(bw, 100.0)
        bh = max(bh, 100.0)

    if n == 4:
        verts = rect_to_polygon(bx, by, bw, bh)
    else:
        cx = bx + bw / 2.0
        cy = by + bh / 2.0
        r = min(bw, bh) / 2.0
        start = -math.pi / 2.0
        if n % 2 == 0:
            start += math.pi / n  # flat top edge for even N
        verts = []
        for k in range(n):
            theta = start + 2.0 * math.pi * k / n
            verts.append((cx + r * math.cos(theta),
                          cy + r * math.sin(theta)))

    if grid >= 2:
        snapped = [(float(snap_to_grid(x, grid)),
                    float(snap_to_grid(y, grid))) for x, y in verts]
        if len(set(snapped)) == len(snapped):
            return snapped
    return [(float(x), float(y)) for x, y in verts]


def closest_point_on_polygon(p: Point,
                             poly: Polygon
                             ) -> Tuple[float, float, int, float]:
    """Return the closest point on the *edges* of ``poly`` to ``p``.

    The polygon is treated as a closed ring so the last edge runs from
    ``poly[-1]`` back to ``poly[0]``.

    Returns ``(qx, qy, edge_idx, distance)`` where ``edge_idx`` indexes
    the edge starting at ``poly[edge_idx]``.  If the polygon is empty or
    degenerate the function returns ``(p.x, p.y, -1, 0.0)``.
    """
    px, py = float(p[0]), float(p[1])
    n = len(poly)
    if n < 2:
        return px, py, -1, 0.0
    best_q = (px, py)
    best_idx = -1
    best_d2 = float("inf")
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        dx = bx - ax
        dy = by - ay
        L2 = dx * dx + dy * dy
        if L2 <= 1e-12:
            qx, qy = ax, ay
        else:
            t = ((px - ax) * dx + (py - ay) * dy) / L2
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            qx = ax + t * dx
            qy = ay + t * dy
        d2 = (qx - px) ** 2 + (qy - py) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_q = (qx, qy)
            best_idx = i
    return float(best_q[0]), float(best_q[1]), best_idx, math.sqrt(best_d2)


# ---------------------------------------------------------------------------
# Room authoring: point / segment / rect tests (interior walls vs furniture)
# ---------------------------------------------------------------------------

def dist_point_to_segment_sq(px: float, py: float,
                             x0: float, y0: float,
                             x1: float, y1: float) -> float:
    """Squared distance from (px,py) to the closed segment (x0,y0)-(x1,y1)."""
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    if L2 < 1e-18:
        dpx, dpy = px - x0, py - y0
        return dpx * dpx + dpy * dpy
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L2))
    qx = x0 + t * dx
    qy = y0 + t * dy
    dpx, dpy = px - qx, py - qy
    return dpx * dpx + dpy * dpy


def aabb_too_close_to_poly_edges(
        fx: float, fy: float, fw: float, fh: float,
        poly: Polygon,
        min_dist: float) -> bool:
    """True if any corner (or the centre) of the axis-aligned box is within
    ``min_dist`` of any edge of ``poly`` (perpendicular distance in the
    plane). Used to keep furniture out of the outer-wall stroke region."""
    if not poly or len(poly) < 2 or min_dist <= 0:
        return False
    # conservative sample: corners + centre
    sample = [
        (fx, fy), (fx + fw, fy), (fx + fw, fy + fh), (fx, fy + fh),
        (fx + fw / 2, fy + fh / 2),
    ]
    for p in sample:
        _qx, _qy, _ei, d = closest_point_on_polygon(p, poly)
        if d < min_dist - 1e-9:
            return True
    return False


def thick_segment_overlaps_rect(
        sx: float, sy: float, ex: float, ey: float,
        half_width: float,
        rx: float, ry: float, rw: float, rh: float) -> bool:
    """True if the segment expanded by ``half_width`` (capsule) intersects
    the axis-aligned rectangle [rx,rx+rw]x[ry,ry+rh]."""
    if half_width <= 0 or rw <= 0 or rh <= 0:
        return False
    # Sample grid inside the rect: catches segment passing through the middle.
    hw2 = half_width * half_width
    for i in range(5):
        for j in range(5):
            px = rx + (i / 4.0) * rw
            py = ry + (j / 4.0) * rh
            if dist_point_to_segment_sq(px, py, sx, sy, ex, ey) <= hw2 * 1.0001:
                return True
    return False


def rotated_rect_corners(
        x: float, y: float, w: float, h: float, rot_deg: float) -> List[Point]:
    """Four world corners of axis-aligned rect (x,y,w,h) after rotation
    about its centre by ``rot_deg`` (degrees)."""
    if w <= 0 or h <= 0:
        return [(x, y), (x, y), (x, y), (x, y)]
    cx = x + w / 2.0
    cy = y + h / 2.0
    rad = math.radians(rot_deg)
    co = math.cos(rad)
    sn = math.sin(rad)
    local = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    out: List[Point] = []
    for hx, hy in local:
        rx = co * hx - sn * hy
        ry = sn * hx + co * hy
        out.append((cx + rx, cy + ry))
    return out


def rotated_rect_bounds(
        x: float, y: float, w: float, h: float, rot_deg: float
        ) -> Tuple[float, float, float, float]:
    """Tight axis-aligned bounds of a rectangle (top-left x,y, size w×h)
    rotated by ``rot_deg`` about its centre."""
    if w <= 0 or h <= 0:
        return (x, y, x, y)
    corners = rotated_rect_corners(x, y, w, h, rot_deg)
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def interior_wall_fully_inside_room(
        sx: float, sy: float, ex: float, ey: float,
        thickness: float, poly: Polygon) -> bool:
    """True if the full interior-wall slab (thickened segment) lies inside
    ``poly`` in template space. Uses corner points of the wall quad and
    samples along the centreline to reduce false positives in concave rooms.
    """
    if not poly or len(poly) < 3:
        return True
    dx = ex - sx
    dy = ey - sy
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return True
    half = max(0.0, float(thickness) / 2.0)
    nx = -dy / length
    ny = dx / length
    # Wall ribbon corners (match canvas wall quad winding).
    c1 = (sx + nx * half, sy + ny * half)
    c2 = (ex + nx * half, ey + ny * half)
    c3 = (ex - nx * half, ey - ny * half)
    c4 = (sx - nx * half, sy - ny * half)
    for p in (c1, c2, c3, c4):
        if not point_in_polygon(p, poly):
            return False
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        px = sx + t * (ex - sx)
        py = sy + t * (ey - sy)
        if not point_in_polygon((px, py), poly):
            return False
    return True
