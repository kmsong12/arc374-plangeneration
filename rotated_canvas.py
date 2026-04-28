"""
rotated_canvas.py - Rotate Tk Canvas drawing for furniture (Stage 1).

Draw routines emit primitives in an axis-aligned (w, h) box with top-left
(abs_x, abs_y). This proxy forwards create_* calls to a real tk.Canvas with
coordinates rotated about the box centre, matching
``geometry_utils.rotated_rect_corners`` (degrees CCW in the standard math
sense; y increases downward on the canvas, consistent with ``math.sin`` /
``math.cos`` used in ``rotated_rect_corners``).
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import Any, List, Tuple


class RotatedCanvasProxy:
    """Rotate all drawing about ``(cx, cy)`` in canvas pixels."""

    def __init__(
            self, canvas: tk.Canvas,
            cx: float, cy: float, cos_t: float, sin_t: float) -> None:
        self._c = canvas
        self._cx = cx
        self._cy = cy
        self._co = cos_t
        self._sn = sin_t

    def _map(self, x: float, y: float) -> Tuple[float, float]:
        hx = x - self._cx
        hy = y - self._cy
        rx = self._co * hx - self._sn * hy
        ry = self._sn * hx + self._co * hy
        return (self._cx + rx, self._cy + ry)

    def _map_flat(self, coords: List[float]) -> List[float]:
        out: List[float] = []
        for i in range(0, len(coords), 2):
            x, y = self._map(coords[i], coords[i + 1])
            out.extend((x, y))
        return out

    def create_line(self, *args, **kwargs) -> Any:
        flat = _take_leading_floats(args)
        if len(flat) < 4:
            return self._c.create_line(*args, **kwargs)
        m = self._map_flat(flat)
        return self._c.create_line(*m, **kwargs)

    def create_polygon(self, *args, **kwargs) -> Any:
        flat = _take_leading_floats(args)
        if len(flat) < 6:
            return self._c.create_polygon(*args, **kwargs)
        m = self._map_flat(flat)
        return self._c.create_polygon(*m, **kwargs)

    def create_rectangle(self, x0, y0, x1, y1, **kwargs) -> Any:
        a = self._map(float(x0), float(y0))
        b = self._map(float(x1), float(y0))
        c = self._map(float(x1), float(y1))
        d = self._map(float(x0), float(y1))
        flat = (a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1])
        return self._c.create_polygon(*flat, **kwargs)

    def create_oval(self, x0, y0, x1, y1, **kwargs) -> Any:
        x0f, y0f, x1f, y1f = float(x0), float(y0), float(x1), float(y1)
        cxb = 0.5 * (x0f + x1f)
        cyb = 0.5 * (y0f + y1f)
        a = abs(x1f - x0f) * 0.5
        b = abs(y1f - y0f) * 0.5
        if a < 1e-6 or b < 1e-6:
            p = self._map(cxb, cyb)
            return self._c.create_line(p[0], p[1], p[0], p[1], **kwargs)
        n = max(16, int(24 + (a + b) * 0.15))
        pts: List[float] = []
        for k in range(n + 1):
            t = 2.0 * math.pi * (k / n)
            px = cxb + a * math.cos(t)
            py = cyb + b * math.sin(t)
            m = self._map(px, py)
            pts.extend(m)
        fill = kwargs.get("fill", "")
        outline = kwargs.get("outline", "")
        width = kwargs.get("width", 1)
        if fill and str(fill) not in ("", "None"):
            return self._c.create_polygon(
                *pts, fill=fill, outline=outline or fill, width=width)
        return self._c.create_line(*pts, fill=outline or "#666", width=width)

    def create_arc(self, x0, y0, x1, y1, **kwargs) -> Any:
        x0f, y0f, x1f, y1f = float(x0), float(y0), float(x1), float(y1)
        start = float(kwargs.pop("start", 0) or 0)
        ext = float(kwargs.pop("extent", 90) or 0)
        style = kwargs.pop("style", tk.ARC)
        outline = kwargs.pop("outline", "#666")
        width = kwargs.pop("width", 1)
        cxb = 0.5 * (x0f + x1f)
        cyb = 0.5 * (y0f + y1f)
        a = abs(x1f - x0f) * 0.5
        b = abs(y1f - y0f) * 0.5
        # Tk: degrees from 3 o'clock, CCW; position on ellipse: x = cx + a*cos(θ), y = cy - b*sin(θ) (y down canvas).
        n = 24
        pts: List[float] = []
        for k in range(n + 1):
            tk_ang = start + ext * (k / n)
            tr = math.radians(tk_ang)
            px = cxb + a * math.cos(tr)
            py = cyb - b * math.sin(tr)
            m = self._map(px, py)
            pts.extend(m)
        if style == tk.ARC or style == "arc":
            return self._c.create_line(*pts, fill=outline, width=width)
        return self._c.create_line(*pts, **kwargs)


def _take_leading_floats(args: tuple) -> List[float]:
    out: List[float] = []
    for a in args:
        if isinstance(a, (int, float)):
            out.append(float(a))
        else:
            break
    return out
