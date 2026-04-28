"""
canvas_renderer.py - Two small renderers that paint on a Tk Canvas.

    RoomCanvasRenderer  : Stage 1 (authoring) - single room, local grid.
    PlanCanvasRenderer  : Stage 2/3 - site, rooms, landscape, bushes, zones.
"""

from __future__ import annotations
import math
import tkinter as tk
from typing import Iterable, List, Optional, Tuple

from model.room_template import RoomTemplate, FurnitureItem, Wall
from model.plan import Plan, RoomInstance
from model import furniture_lib
from presets import PRESET_RENDERERS
from config import room_polygon_outline_screen_px
from geometry_utils import rotated_rect_corners
from units import fmt_ft, fmt_ft2
from rotated_canvas import RotatedCanvasProxy
from furniture_geometry import furniture_handle_positions

GRID_SIZE = 10


# ---------------------------------------------------------------------------
# Shared palette
# ---------------------------------------------------------------------------
C_SEL = "#E85D24"
C_HANDLE = "#E85D24"
C_TEMPLATE_GRID = "#D0CDC3"
C_SITE_GRID = "#C4C2BA"

# Shared selection style for furniture / rooms / landscape.
# High-contrast bright blue, solid 3-px outline.
C_SELECT = "#1E90FF"
SEL_WIDTH = 3
SEL_PAD = 4


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _polygon_to_flat(poly) -> List[float]:
    out: List[float] = []
    for x, y in poly:
        out.append(x)
        out.append(y)
    return out


def draw_furniture_item_local(c, item: FurnitureItem, ox: float, oy: float):
    """Draw a FurnitureItem at absolute canvas coords (ox,oy) + item local."""
    ax = ox + item.x
    ay = oy + item.y
    _draw_furniture_scaled_rotated(c, item, ax, ay, item.w, item.h)


def _draw_furniture_scaled_rotated(
        c: tk.Canvas, fi: FurnitureItem,
        ax: float, ay: float, sw: float, sh: float) -> None:
    """Draw catalog/custom furniture with full rotation of internal detail."""
    rot = float(fi.rotation) % 360.0
    if abs(rot) < 0.08:
        item = FurnitureItem(
            type=fi.type, x=0, y=0, w=sw, h=sh,
            color=fi.color, rotation=0.0, custom_id=fi.custom_id, label=fi.label)
        furniture_lib.draw(c, item, ax, ay)
        return
    cx = ax + sw * 0.5
    cy = ay + sh * 0.5
    rad = math.radians(rot)
    proxy = RotatedCanvasProxy(c, cx, cy, math.cos(rad), math.sin(rad))
    item = FurnitureItem(
        type=fi.type, x=0, y=0, w=sw, h=sh,
        color=fi.color, rotation=0.0, custom_id=fi.custom_id, label=fi.label)
    furniture_lib.draw(proxy, item, ax, ay)


def _draw_bench(c, x, y, w, h, orient="h"):
    seat = "#9C8462"; leg = "#6B5740"; back = "#7A6248"
    if orient == "h":
        c.create_rectangle(x, y + h * 0.1, x + w * 0.10, y + h, fill=leg, outline="")
        c.create_rectangle(x + w * 0.90, y + h * 0.1, x + w, y + h, fill=leg, outline="")
        c.create_rectangle(x + w * 0.05, y + h * 0.35, x + w * 0.95, y + h * 0.80,
                           fill=seat, outline=leg, width=1)
        c.create_rectangle(x + w * 0.05, y, x + w * 0.95, y + h * 0.30,
                           fill=back, outline=leg, width=1)
    else:
        c.create_rectangle(x + w * 0.1, y, x + w * 0.9, y + h * 0.10, fill=leg, outline="")
        c.create_rectangle(x + w * 0.1, y + h * 0.90, x + w * 0.9, y + h, fill=leg, outline="")
        c.create_rectangle(x + w * 0.35, y + h * 0.05, x + w * 0.80, y + h * 0.95,
                           fill=seat, outline=leg, width=1)
        c.create_rectangle(x, y + h * 0.05, x + w * 0.30, y + h * 0.95,
                           fill=back, outline=leg, width=1)


def _draw_path(c, x, y, w, h):
    c.create_rectangle(x, y, x + w, y + h,
                       fill="#D4CCBA", outline="#B0A898", width=1)
    if w >= h:
        step = max(24, w // 6)
        for px in range(int(x + step), int(x + w), step):
            c.create_line(px, y + 2, px, y + h - 2, fill="#C0B8A4")
        c.create_line(x + 2, y + h / 2, x + w - 2, y + h / 2, fill="#C0B8A4")
    else:
        step = max(24, h // 6)
        for py in range(int(y + step), int(y + h), step):
            c.create_line(x + 2, py, x + w - 2, py, fill="#C0B8A4")
        c.create_line(x + w / 2, y + 2, x + w / 2, y + h - 2, fill="#C0B8A4")


def _draw_bush(c, bx, by, br):
    for ox, oy in [(0, -br * .75), (br * .75, 0), (0, br * .75), (-br * .75, 0),
                   (-br * .5, -br * .5), (br * .5, -br * .5), (br * .5, br * .5),
                   (-br * .5, br * .5), (0, 0)]:
        r = br / 2
        c.create_oval(bx + ox - r, by + oy - r, bx + ox + r, by + oy + r,
                      fill="#1A8A60", outline="#0A5C40", width=0.5)


def _lighter_shade(hex_color: str) -> str:
    """Mix ``hex_color`` 55% with white for a translucent-looking tint.

    Falls back to ``#E8E8E8`` if the input can't be parsed.
    """
    try:
        s = hex_color.lstrip("#")
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        if len(s) != 6:
            return "#E8E8E8"
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
        mix = 0.55
        nr = int(r + (255 - r) * mix)
        ng = int(g + (255 - g) * mix)
        nb = int(b + (255 - b) * mix)
        return f"#{nr:02X}{ng:02X}{nb:02X}"
    except Exception:
        return "#E8E8E8"


def _rotation_bbox(w: float, h: float, rot: float
                   ) -> Tuple[float, float, float, float]:
    """Return ``(draw_w, draw_h, dx, dy)`` for drawing a furniture bbox at a
    cardinal ``rot`` (0/90/180/270) degrees while keeping the visual bbox
    centred over the original ``(w, h)`` footprint.

    Non-cardinal rotations fall through as 0 degrees.
    """
    r = int(round(rot)) % 360
    if r == 90 or r == 270:
        draw_w, draw_h = h, w
    else:
        draw_w, draw_h = w, h
    dx = (w - draw_w) / 2.0
    dy = (h - draw_h) / 2.0
    return draw_w, draw_h, dx, dy


def _draw_wall_scaled(c, w: Wall, ox: float, oy: float, scale: float) -> None:
    """Render an interior wall as a thickened rectangle with round end-caps.

    ``ox``/``oy`` are the template origin in canvas space (already includes
    any outer offset); ``scale`` is applied to both endpoints and thickness.
    """
    x0 = ox + w.x0 * scale
    y0 = oy + w.y0 * scale
    x1 = ox + w.x1 * scale
    y1 = oy + w.y1 * scale
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    t = max(1.0, w.thickness * scale) / 2.0
    nx = -dy / length
    ny = dx / length
    corners = [
        x0 + nx * t, y0 + ny * t,
        x1 + nx * t, y1 + ny * t,
        x1 - nx * t, y1 - ny * t,
        x0 - nx * t, y0 - ny * t,
    ]
    c.create_polygon(*corners, fill=w.color, outline="#3C3C3A", width=1)
    # Rounded end-caps so diagonal walls look clean at the joints.
    c.create_oval(x0 - t, y0 - t, x0 + t, y0 + t,
                  fill=w.color, outline="")
    c.create_oval(x1 - t, y1 - t, x1 + t, y1 + t,
                  fill=w.color, outline="")


def _draw_wall_selection_highlight(
        c, w: Wall, ox: float, oy: float, scale: float) -> None:
    """Draw a bright centerline stroke on an interior wall (author selection)."""
    x0 = ox + w.x0 * scale
    y0 = oy + w.y0 * scale
    x1 = ox + w.x1 * scale
    y1 = oy + w.y1 * scale
    dx, dy = x1 - x0, y1 - y0
    if (dx * dx + dy * dy) < 1e-6:
        return
    c.create_line(x0, y0, x1, y1, fill=C_SELECT, width=5, capstyle=tk.ROUND)


def _draw_handles(c, points, color=C_HANDLE, r=5):
    for px, py in points:
        c.create_oval(px - r, py - r, px + r, py + r,
                      fill=color, outline="white", width=1.2)


def _draw_template_body(c, template: RoomTemplate, ox: float, oy: float,
                        fill_override: Optional[str] = None,
                        border_override: Optional[str] = None,
                        draw_interior: bool = True) -> None:
    """Draw a RoomTemplate at absolute offset (ox,oy)."""
    fill = fill_override or template.fill_color
    border = border_override or template.border_color

    # Polygon outline
    flat = _polygon_to_flat([(ox + x, oy + y) for x, y in template.polygon])
    if flat:
        c.create_polygon(*flat, fill=fill, outline=border, width=1.5)

    # Preset interior (only for seeded rooms)
    if draw_interior and template.preset_id:
        renderer = PRESET_RENDERERS.get(template.preset_id)
        if renderer:
            bx, by, bw, bh = template.bbox()
            try:
                renderer(c, ox + bx, oy + by, bw, bh)
            except Exception:
                pass

    # Inner walls (drawn between polygon outline and furniture).
    if draw_interior:
        for w in getattr(template, "walls", []):
            _draw_wall_scaled(c, w, ox, oy, 1.0)

    # Furniture items (room-relative)
    if draw_interior:
        for fi in template.furniture:
            draw_furniture_item_local(c, fi, ox, oy)


# ---------------------------------------------------------------------------
# Stage 1: RoomCanvasRenderer
# ---------------------------------------------------------------------------

class RoomCanvasRenderer:
    """Stage 1 — draws a single RoomTemplate centred in its own canvas."""

    ZOOM_MIN = 0.3
    ZOOM_MAX = 3.0

    def __init__(self, canvas: tk.Canvas):
        self.canvas = canvas
        # transform: template-local -> canvas pixels
        self.origin: Tuple[float, float] = (0.0, 0.0)
        self.scale: float = 1.0
        # Split scale into (auto-fit) * (user zoom) so refits preserve zoom.
        self._base_scale: float = 1.0
        self._zoom: float = 1.0
        # Track the canvas size the last fit() was computed for, so we
        # can detect when we need to refit (e.g. first real <Configure>).
        self._fit_size: Tuple[int, int] = (0, 0)

    def _canvas_size(self) -> Tuple[int, int]:
        """Return the canvas's actual pixel size (after layout).

        Tk returns 1x1 for a widget that hasn't been mapped yet; in that
        case force an idle-task pump so the geometry manager has a
        chance to assign a real size.
        """
        c = self.canvas
        cw = c.winfo_width()
        ch = c.winfo_height()
        if cw <= 1 or ch <= 1:
            try:
                c.update_idletasks()
                cw = c.winfo_width()
                ch = c.winfo_height()
            except Exception:
                pass
        if cw <= 1:
            cw = int(c.winfo_reqwidth()) or 800
        if ch <= 1:
            ch = int(c.winfo_reqheight()) or 560
        return cw, ch

    def fit(self, template: RoomTemplate, pad: int = 80) -> None:
        """Centre the template in the current canvas size.

        Stores the auto-fit factor in ``_base_scale`` and multiplies by the
        current user ``_zoom``; this way a window resize or new template
        re-fits while preserving the user's zoom level.
        """
        cw, ch = self._canvas_size()
        _, _, w, h = template.bbox()
        if w <= 0 or h <= 0:
            w = h = 100
        sx = (cw - 2 * pad) / max(1.0, w)
        sy = (ch - 2 * pad) / max(1.0, h)
        self._base_scale = max(0.25, min(1.8, min(sx, sy)))
        self.scale = self._base_scale * self._zoom
        tw = w * self.scale
        th = h * self.scale
        self.origin = ((cw - tw) / 2, (ch - th) / 2)
        self._fit_size = (cw, ch)

    def needs_refit(self) -> bool:
        """True when the canvas has been resized since the last fit()."""
        cw, ch = self._canvas_size()
        fw, fh = self._fit_size
        return abs(cw - fw) > 2 or abs(ch - fh) > 2

    # ------------------------------------------------------------------
    # Zoom controls
    # ------------------------------------------------------------------

    def set_zoom(self, z: float) -> None:
        """Set the user zoom multiplier (clamped) and refresh ``scale``."""
        self._zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, float(z)))
        self.scale = self._base_scale * self._zoom

    def zoom_by(self, factor: float,
                pivot_canvas: Optional[Tuple[float, float]] = None) -> None:
        """Multiply the user zoom by ``factor`` (clamped).

        If ``pivot_canvas`` is given we translate ``origin`` so that the
        world point currently under that canvas coordinate remains under
        it after the zoom (cursor-anchored zoom).
        """
        old_scale = self.scale
        new_zoom = max(self.ZOOM_MIN,
                       min(self.ZOOM_MAX, self._zoom * float(factor)))
        if new_zoom == self._zoom:
            return
        if pivot_canvas is not None and old_scale > 0:
            px, py = pivot_canvas
            wx = (px - self.origin[0]) / old_scale
            wy = (py - self.origin[1]) / old_scale
            self._zoom = new_zoom
            self.scale = self._base_scale * self._zoom
            self.origin = (px - wx * self.scale, py - wy * self.scale)
        else:
            self._zoom = new_zoom
            self.scale = self._base_scale * self._zoom

    def reset_zoom(self) -> None:
        """Reset the user zoom to 1.0. Caller should re-fit() afterwards."""
        self._zoom = 1.0
        self.scale = self._base_scale

    @property
    def zoom(self) -> float:
        return self._zoom

    def world_to_canvas(self, x: float, y: float) -> Tuple[float, float]:
        ox, oy = self.origin
        return ox + x * self.scale, oy + y * self.scale

    def canvas_to_world(self, cx: float, cy: float) -> Tuple[float, float]:
        ox, oy = self.origin
        return (cx - ox) / self.scale, (cy - oy) / self.scale

    def draw(self, template: RoomTemplate,
             show_grid: bool = True,
             selected_vertex: Optional[int] = None,
             selected_furniture: Optional[int] = None,
             selected_wall: Optional[int] = None,
             hover_edge: Optional[int] = None,
             show_handles: bool = True,
             invalid_furniture: Optional[int] = None,
             drag_preview: Optional[Tuple[int, float, float, bool]] = None,
             place_preview: Optional[Tuple] = None,
             wall_mode: bool = False,
             furniture_resize: Optional[int] = None,
             opening_edge_glow:
                 Optional[Tuple[Tuple[str, int], bool]] = None) -> None:
        c = self.canvas
        c.delete("all")
        cw, ch = self._canvas_size()
        c.create_rectangle(0, 0, cw, ch, fill="#F5F3EC", outline="")
        dim_center_y = 22.0
        if wall_mode:
            # Subtle full-canvas tint in wall-drawing mode.
            c.create_rectangle(0, 0, cw, ch, fill="#F2EDD8", outline="")
            dim_center_y = 56.0

        # Local grid (template coordinates)
        if show_grid:
            self._draw_local_grid(template)

        # Template polygon + furniture (scaled)
        self._draw_template_scaled(
            template, selected_furniture,
            selected_wall=selected_wall,
            invalid_furniture=invalid_furniture,
            furniture_resize=furniture_resize)

        if opening_edge_glow is not None:
            glow_key, ok = opening_edge_glow
            self._draw_opening_edge_glow(template, glow_key, ok)

        # Drag-ghost footprint (rendered above furniture, below handles).
        if drag_preview is not None:
            self._draw_drag_ghost(template, drag_preview)

        # Placement-shadow ghost (cursor preview for armed brush).
        if place_preview is not None:
            self._draw_place_ghost(place_preview)

        # Vertex handles
        if show_handles:
            handle_points = [self.world_to_canvas(x, y)
                             for x, y in template.polygon]
            if hover_edge is not None and 0 <= hover_edge < len(template.polygon):
                n = len(template.polygon)
                ax, ay = template.polygon[hover_edge]
                bx, by = template.polygon[(hover_edge + 1) % n]
                mx, my = self.world_to_canvas((ax + bx) / 2, (ay + by) / 2)
                c.create_oval(mx - 4, my - 4, mx + 4, my + 4,
                              fill="", outline="#2D9F6A", width=2)
            for i, (px, py) in enumerate(handle_points):
                is_sel = (selected_vertex == i)
                fill = "#FFCB5C" if is_sel else C_HANDLE
                c.create_oval(px - 5, py - 5, px + 5, py + 5,
                              fill=fill, outline="white", width=1.5)

        # Prominent dimension read-out (top-centre)
        _, _, bw, bh = template.bbox()
        area_lbl = fmt_ft2(bw * bh)
        dim_lbl = f"{fmt_ft(bw)}  \u00d7  {fmt_ft(bh)}"
        badge_text = f"{dim_lbl}   \u2022   {area_lbl}"
        # A soft badge behind the text so it reads even over the grid
        _ = c.create_text(
            cw / 2, dim_center_y,
            text=badge_text,
            font=("Helvetica", 12, "bold"),
            fill="#2C2C2A",
            tags=("dim_header",))
        bbox = c.bbox("dim_header")
        if bbox:
            x0, y0, x1, y1 = bbox
            pad_x, pad_y = 14, 4
            c.create_rectangle(x0 - pad_x, y0 - pad_y,
                               x1 + pad_x, y1 + pad_y,
                               fill="#FFFFFF", outline="#D8D5CC",
                               width=1)
            c.tag_raise("dim_header")

        # Wall-mode banner (top strip, on top of scene)
        if wall_mode:
            bar_h = 36.0
            c.create_rectangle(0, 0, cw, bar_h, fill="#FFF0C6",
                               outline="#C4A000", width=1, tags=("wall_mode_layer",))
            c.create_text(
                cw / 2, bar_h / 2,
                text="INTERIOR WALL MODE  \u2014  only wall drawing. "
                     "Furniture/room tools disabled until you exit (Esc or Exit).",
                font=("Helvetica", 10, "bold"),
                fill="#5A4A00",
                tags=("wall_mode_layer",))
            c.tag_raise("wall_mode_layer")
            c.tag_raise("dim_header")

        # Small faded footer with instructions
        foot = (
            "wall mode: click-drag to add walls, Esc to finish"
            if wall_mode else
            "vertex handles: reshape room  \u00b7  "
            "furniture: select, drag, white handles to resize, rt-click for rotate  \u00b7  "
            "dbl-click edge: add vertex  \u00b7  rt-click vertex: remove")
        c.create_text(
            cw / 2, ch - 14,
            text=foot,
            font=("Helvetica", 8),
            fill="#888880")
        if wall_mode:
            c.tag_raise("wall_mode_layer")

    def _draw_local_grid(self, template: RoomTemplate) -> None:
        c = self.canvas
        cw, ch = self._canvas_size()
        ox, oy = self.origin
        s = self.scale
        _, _, bw, bh = template.bbox()
        # extend grid past the template for visual context
        ext_w = bw + 200
        ext_h = bh + 200
        # anchor grid at template's (0,0) shifted to canvas
        step = GRID_SIZE * s
        if step < 4:
            step = 4
        x0 = ox - 100 * s
        y0 = oy - 100 * s
        x1 = ox + ext_w * s
        y1 = oy + ext_h * s
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(cw, x1)
        y1 = min(ch, y1)
        gx = x0
        while gx <= x1:
            gy = y0
            while gy <= y1:
                c.create_oval(gx - 1, gy - 1, gx + 1, gy + 1,
                              fill=C_TEMPLATE_GRID, outline="")
                gy += step
            gx += step

    def _draw_opening_edge_glow(
            self, template: RoomTemplate,
            glow_key: Tuple[str, int], valid: bool) -> None:
        """Highlight a room polygon edge or interior wall while placing."""
        col = "#00B4D8" if valid else "#C24141"
        kind, ix = glow_key[0], glow_key[1]
        if kind == "poly":
            poly = template.polygon
            n = len(poly)
            if not (0 <= ix < n):
                return
            ax, ay = poly[ix]
            bx, by = poly[(ix + 1) % n]
        else:
            walls = template.walls
            if not (0 <= ix < len(walls)):
                return
            w = walls[ix]
            ax, ay, bx, by = w.x0, w.y0, w.x1, w.y1
        acx, acy = self.world_to_canvas(ax, ay)
        bcx, bcy = self.world_to_canvas(bx, by)
        self.canvas.create_line(
            acx, acy, bcx, bcy, fill=col, width=5,
            capstyle=tk.ROUND, joinstyle=tk.ROUND)

    def _draw_place_ghost(
            self,
            place_preview: Tuple
            ) -> None:
        """Draw a semi-transparent footprint following the cursor for the
        currently armed furniture brush.

        ``place_preview`` is either a 7-tuple ``(canvas_cx, canvas_cy,
        world_w, world_h, color, is_valid, rot_deg)`` or a 10-tuple with
        optional world ``(ghost_x, ghost_y, ghost_rot)`` for wall-snapped
        openings; when those are non-``None``, the ghost uses that pose."""
        c = self.canvas
        if len(place_preview) >= 10:
            (cx, cy, ww, wh, color, is_valid, rot, gx0, gy0, gro
             ) = place_preview[:10]
            if gx0 is not None and gy0 is not None and gro is not None:
                x0, y0 = float(gx0), float(gy0)
                rot = float(gro)
            else:
                wx, wy = self.canvas_to_world(cx, cy)
                x0 = wx - ww / 2.0
                y0 = wy - wh / 2.0
        else:
            cx, cy, ww, wh, color, is_valid, rot = place_preview[:7]
            wx, wy = self.canvas_to_world(cx, cy)
            x0 = wx - ww / 2.0
            y0 = wy - wh / 2.0
        wpts = rotated_rect_corners(x0, y0, ww, wh, rot)
        flat: List[float] = []
        for p in wpts:
            px, py = self.world_to_canvas(p[0], p[1])
            flat.extend([px, py])
        base_color = color or "#A0A0A0"
        if is_valid:
            fill = _lighter_shade(base_color)
            outline = "#666666"
        else:
            fill = "#E66A6A"
            outline = "#C24141"
        c.create_polygon(
            *flat, fill=fill, outline=outline, width=2, dash=(2, 2),
            stipple="gray50")
        r = 5
        c.create_line(cx - r, cy, cx + r, cy, fill=outline, width=1)
        c.create_line(cx, cy - r, cx, cy + r, fill=outline, width=1)

    def _draw_drag_ghost(self, template: RoomTemplate,
                          drag_preview: Tuple[int, float, float, bool]
                          ) -> None:
        c = self.canvas
        idx, wx, wy, is_valid = drag_preview
        if not (0 <= idx < len(template.furniture)):
            return
        fi = template.furniture[idx]
        sw = fi.w * self.scale
        sh = fi.h * self.scale
        ax, ay = self.world_to_canvas(wx, wy)
        # Validity-aware tint: red ghost when the drop would be rejected.
        base_color = fi.color or "#A0A0A0"
        if is_valid:
            fill = _lighter_shade(base_color)
            outline = "#666666"
        else:
            fill = "#E66A6A"
            outline = "#C24141"
        c.create_rectangle(ax, ay, ax + sw, ay + sh,
                           fill=fill, outline=outline,
                           width=2, dash=(2, 2), stipple="gray50")
        # Small crosshair at the candidate centre so the user can align.
        mx = ax + sw / 2.0
        my = ay + sh / 2.0
        r = 5
        c.create_line(mx - r, my, mx + r, my, fill=outline, width=1)
        c.create_line(mx, my - r, mx, my + r, fill=outline, width=1)

    def _draw_template_scaled(self, template: RoomTemplate,
                              selected_furniture: Optional[int],
                              selected_wall: Optional[int] = None,
                              invalid_furniture: Optional[int] = None,
                              furniture_resize: Optional[int] = None) -> None:
        c = self.canvas

        # polygon (scaled)
        pts: List[float] = []
        for x, y in template.polygon:
            cx, cy = self.world_to_canvas(x, y)
            pts += [cx, cy]
        if pts:
            outline_w = room_polygon_outline_screen_px(self.scale)
            c.create_polygon(*pts,
                             fill=template.fill_color,
                             outline=template.border_color,
                             width=outline_w)

        # preset interior in scaled local space (only meaningful for preset_id)
        if template.preset_id:
            renderer = PRESET_RENDERERS.get(template.preset_id)
            if renderer:
                bx, by, bw, bh = template.bbox()
                cx0, cy0 = self.world_to_canvas(bx, by)
                scaled_w = bw * self.scale
                scaled_h = bh * self.scale
                try:
                    renderer(c, cx0, cy0, scaled_w, scaled_h)
                except Exception:
                    pass

        # inner walls (scaled; drawn below furniture, above polygon fill)
        ox, oy = self.origin
        wall_list = getattr(template, "walls", [])
        for w in wall_list:
            _draw_wall_scaled(c, w, ox, oy, self.scale)
        if selected_wall is not None and 0 <= selected_wall < len(wall_list):
            _draw_wall_selection_highlight(
                c, wall_list[selected_wall], ox, oy, self.scale)

        # furniture items scaled
        for i, fi in enumerate(template.furniture):
            ax, ay = self.world_to_canvas(fi.x, fi.y)
            sw = fi.w * self.scale
            sh = fi.h * self.scale
            _draw_furniture_scaled_rotated(
                c, fi, ax, ay, sw, sh)
            if invalid_furniture == i:
                self._furniture_sel_outline(
                    c, fi, outline="#D04A4A", width=2, pad=3)
            elif selected_furniture == i:
                self._furniture_sel_outline(
                    c, fi, outline=C_SELECT, width=SEL_WIDTH, pad=SEL_PAD)
            if furniture_resize is not None and furniture_resize == i:
                self._draw_furniture_resize_handles(c, fi)

    def _furniture_sel_outline(
            self, c: tk.Canvas, fi: FurnitureItem, outline: str, width: float,
            pad: float) -> None:
        """Outline the rotated furniture footprint (``pad`` kept for API compat)."""
        _ = pad
        corners = rotated_rect_corners(
            fi.x, fi.y, fi.w, fi.h, float(fi.rotation))
        flat: List[float] = []
        for wx, wy in corners:
            flat.extend(self.world_to_canvas(wx, wy))
        flat.extend(flat[:2])
        c.create_line(*flat, fill=outline, width=width)

    def _draw_furniture_resize_handles(self, c: tk.Canvas, fi: FurnitureItem) -> None:
        """Corner + edge handles on the rotated rectangle in world space."""
        r = 5.0
        for _h, wx, wy in furniture_handle_positions(
                fi.x, fi.y, fi.w, fi.h, float(fi.rotation)):
            cx, cy = self.world_to_canvas(wx, wy)
            c.create_rectangle(
                cx - r, cy - r, cx + r, cy + r,
                fill="#FFFFFF", outline=C_SELECT, width=2)


# ---------------------------------------------------------------------------
# Stage 2/3: PlanCanvasRenderer
# ---------------------------------------------------------------------------

class PlanCanvasRenderer:
    """Draws the full site + plan.

    World coordinates (``plan.site``, room poses, etc.) are unchanged; the
    canvas applies a uniform **view scale** so the site and content fit the
    visible widget with padding (no 1:1 pixel assumption on screen).
    """

    _VIEW_PAD = 24.0

    def __init__(self, canvas: tk.Canvas):
        self.canvas = canvas
        # Last draw viewport: world px -> screen px
        self._plan_view_s: float = 1.0
        self._plan_view_ox: float = 0.0
        self._plan_view_oy: float = 0.0

    def screen_to_world(self, sx: float, sy: float) -> Tuple[float, float]:
        """Canvas pixel (after ``canvasx`` / ``canvasy``) → world / site px."""
        s = self._plan_view_s
        if abs(s) < 1e-12:
            s = 1.0
        return (
            (sx - self._plan_view_ox) / s,
            (sy - self._plan_view_oy) / s,
        )

    def _w2s(self, wx: float, wy: float) -> Tuple[float, float]:
        return (
            self._plan_view_ox + wx * self._plan_view_s,
            self._plan_view_oy + wy * self._plan_view_s,
        )

    def _lw(self, w: float) -> float:
        """Scale cosmetic line/outline width toward readability."""
        return max(1.0, min(8.0, w * self._plan_view_s))

    @staticmethod
    def _world_content_bounds(
            plan: Plan,
            site: Tuple[int, int, int, int],
            zone_preview: Optional[Tuple[int, int, int, int]],
            ) -> Tuple[float, float, float, float]:
        """Bounding box (minx, miny, maxx, maxy) in world pixels."""
        sx, sy, sw, sh = site
        minx = float(sx)
        miny = float(sy)
        maxx = float(sx + sw)
        maxy = float(sy + sh)
        for r in plan.rooms:
            bx, by, bw, bh = r.world_bbox()
            minx = min(minx, bx)
            miny = min(miny, by)
            maxx = max(maxx, bx + bw)
            maxy = max(maxy, by + bh)
        for zx, zy, zw, zh in plan.zones:
            minx = min(minx, float(zx))
            miny = min(miny, float(zy))
            maxx = max(maxx, float(zx + zw))
            maxy = max(maxy, float(zy + zh))
        for item in plan.landscape:
            ix = float(item["x"])
            iy = float(item["y"])
            iw = float(item["w"])
            ih = float(item["h"])
            minx = min(minx, ix)
            miny = min(miny, iy)
            maxx = max(maxx, ix + iw)
            maxy = max(maxy, iy + ih)
        for bx, by, br in plan.bushes:
            r = float(br)
            minx = min(minx, bx - r)
            miny = min(miny, by - r)
            maxx = max(maxx, bx + r)
            maxy = max(maxy, by + r)
        if zone_preview is not None:
            zx0, zy0, zw0, zh0 = zone_preview
            minx = min(minx, float(zx0))
            miny = min(miny, float(zy0))
            maxx = max(maxx, float(zx0 + zw0))
            maxy = max(maxy, float(zy0 + zh0))
        return (minx, miny, maxx, maxy)

    def _setup_view(self, plan: Plan,
                    site: Tuple[int, int, int, int],
                    zone_preview: Optional[Tuple[int, int, int, int]],
                    cw: int, ch: int) -> None:
        minx, miny, maxx, maxy = self._world_content_bounds(
            plan, site, zone_preview)
        content_w = max(maxx - minx, 1.0)
        content_h = max(maxy - miny, 1.0)
        pad = self._VIEW_PAD
        avail_w = max(50.0, float(cw) - 2.0 * pad)
        avail_h = max(50.0, float(ch) - 2.0 * pad)
        self._plan_view_s = min(avail_w / content_w, avail_h / content_h)
        drawn_w = content_w * self._plan_view_s
        drawn_h = content_h * self._plan_view_s
        ox = pad + (avail_w - drawn_w) / 2.0
        oy = pad + (avail_h - drawn_h) / 2.0
        self._plan_view_ox = ox - minx * self._plan_view_s
        self._plan_view_oy = oy - miny * self._plan_view_s

    def draw(self, plan: Plan,
             site: Optional[Tuple[int, int, int, int]] = None,
             show_grid: bool = True,
             show_labels: bool = False,
             selected_room: Optional[RoomInstance] = None,
             zone_preview: Optional[Tuple[int, int, int, int]] = None,
             drop_preview_poly: Optional[list] = None,
             drop_preview_valid: bool = True,
             highlight_zone_idx: Optional[int] = None,
             selected_landscape: Optional[int] = None,
             selected_bush: Optional[int] = None) -> None:
        c = self.canvas
        c.delete("all")
        cw = c.winfo_width() or 1000
        ch = c.winfo_height() or 640
        if site is None:
            site = plan.site
        sx, sy, sw, sh = site
        self._setup_view(plan, site, zone_preview, cw, ch)
        vp = self._plan_view_s

        # Background
        c.create_rectangle(0, 0, cw, ch, fill="#E8E6DE", outline="")

        if show_grid:
            self._draw_site_grid(site)

        # Site border
        x0, y0 = self._w2s(float(sx), float(sy))
        x1, y1 = self._w2s(float(sx + sw), float(sy + sh))
        c.create_rectangle(
            min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1),
            fill="#FAFAF6", outline="#1a1a1a",
            width=self._lw(2.0))

        # Zones
        for i, (zx, zy, zw, zh) in enumerate(plan.zones):
            is_hl = (highlight_zone_idx == i)
            zx0, zy0 = self._w2s(float(zx), float(zy))
            zx1, zy1 = self._w2s(float(zx + zw), float(zy + zh))
            c.create_rectangle(
                min(zx0, zx1), min(zy0, zy1), max(zx0, zx1), max(zy0, zy1),
                fill="#FFF3CD" if not is_hl else "#FFE49C",
                outline="#BA7517",
                width=self._lw(2.0 if is_hl else 1.0),
                dash=(4, 3),
                stipple="gray25")
            tx, ty = self._w2s(float(zx) + 6.0, float(zy) + 6.0)
            c.create_text(tx, ty, anchor="nw",
                          text=f"Zone {i + 1}",
                          font=("Helvetica", 8, "bold"),
                          fill="#8a5800")

        # Landscape: paths drawn below rooms
        for item in plan.landscape:
            if item["type"] == "path":
                self._draw_path_w(item["x"], item["y"], item["w"], item["h"])

        # Bushes
        for bx, by, br in plan.bushes:
            self._draw_bush_w(bx, by, br)

        # Rooms
        for room in plan.rooms:
            self._draw_room(room, selected=(room is selected_room),
                            show_label=show_labels)

        # Landscape: benches on top
        for item in plan.landscape:
            if item["type"] == "bench":
                self._draw_bench_w(
                    item["x"], item["y"], item["w"], item["h"],
                    item.get("orient", "h"))

        # Landscape selection highlight (rectangle)
        if (selected_landscape is not None
                and 0 <= selected_landscape < len(plan.landscape)):
            it = plan.landscape[selected_landscape]
            lx = it["x"]; ly = it["y"]
            lw = it["w"]; lh = it["h"]
            lx0, ly0 = self._w2s(lx - SEL_PAD, ly - SEL_PAD)
            lx1, ly1 = self._w2s(lx + lw + SEL_PAD, ly + lh + SEL_PAD)
            c.create_rectangle(
                lx0, ly0, lx1, ly1,
                outline=C_SELECT, width=self._lw(SEL_WIDTH), fill="")

        # Bush selection highlight (circle)
        if (selected_bush is not None
                and 0 <= selected_bush < len(plan.bushes)):
            bx, by, br = plan.bushes[selected_bush]
            pad_r = (br + SEL_PAD) * vp
            sx_c, sy_c = self._w2s(bx, by)
            c.create_oval(sx_c - pad_r, sy_c - pad_r, sx_c + pad_r, sy_c + pad_r,
                          outline=C_SELECT, width=self._lw(SEL_WIDTH), fill="")

        # Zone preview (currently dragging)
        if zone_preview:
            zx0, zy0, zw, zh = zone_preview
            ax0, ay0 = self._w2s(float(zx0), float(zy0))
            ax1, ay1 = self._w2s(float(zx0 + zw), float(zy0 + zh))
            c.create_rectangle(
                min(ax0, ax1), min(ay0, ay1), max(ax0, ax1), max(ay0, ay1),
                outline="#BA7517", fill="#FFF3CD",
                dash=(5, 3), stipple="gray25", width=self._lw(1.0))

        # Drop preview polygon (dragging a room from a library)
        if drop_preview_poly:
            fp0 = drop_preview_poly[0]
            if isinstance(fp0, (list, tuple)) and len(fp0) >= 2:
                flat_w = _polygon_to_flat(drop_preview_poly)
            else:
                flat_w = list(drop_preview_poly)
            if len(flat_w) >= 4:
                flat_out: List[float] = []
                for i in range(0, len(flat_w), 2):
                    wx = float(flat_w[i])
                    wy = float(flat_w[i + 1])
                    fx, fy = self._w2s(wx, wy)
                    flat_out.extend((fx, fy))
                fill = "#BEE8C2" if drop_preview_valid else "#F7C3C3"
                border = "#2D9F6A" if drop_preview_valid else "#C44444"
                c.create_polygon(*flat_out, fill=fill, outline=border,
                                 width=self._lw(2.0), stipple="gray25")

    def _draw_site_grid(self, site: Tuple[int, int, int, int]) -> None:
        sx, sy, sw, sh = site
        c = self.canvas
        vp = self._plan_view_s
        need = max(float(GRID_SIZE), 14.0 / max(vp, 1e-6))
        step = int(GRID_SIZE * max(1, math.ceil(need / float(GRID_SIZE))))
        rad = max(1.0, self._lw(1.0))
        gx = int(math.floor(float(sx) / step) * step)
        gx_max = sx + sw
        gy_max = sy + sh
        while gx <= gx_max:
            gy = int(math.floor(float(sy) / step) * step)
            while gy <= gy_max:
                if sx <= gx <= gx_max and sy <= gy <= gy_max:
                    cx, cy = self._w2s(float(gx), float(gy))
                    c.create_oval(cx - rad, cy - rad, cx + rad, cy + rad,
                                  fill=C_SITE_GRID, outline="")
                gy += step
            gx += step

    def _draw_path_w(self, x: float, y: float, w: float, h: float) -> None:
        x0, y0 = self._w2s(x, y)
        x1, y1 = self._w2s(x + w, y + h)
        _draw_path(self.canvas, x0, y0, x1 - x0, y1 - y0)

    def _draw_bench_w(self, x: float, y: float, w: float, h: float,
                      orient: str = "h") -> None:
        x0, y0 = self._w2s(x, y)
        x1, y1 = self._w2s(x + w, y + h)
        _draw_bench(self.canvas, x0, y0, x1 - x0, y1 - y0, orient)

    def _draw_bush_w(self, bx: float, by: float, br: float) -> None:
        _draw_bush(self.canvas, self._w2s(bx, by)[0], self._w2s(bx, by)[1],
                   br * self._plan_view_s)

    def _draw_room(self, room: RoomInstance, selected: bool, show_label: bool):
        c = self.canvas
        poly = room.world_polygon()
        fill = room.fill_override or room.template_snapshot.fill_color
        border = room.template_snapshot.border_color

        flat = []
        for px, py in poly:
            flat.extend(self._w2s(float(px), float(py)))
        vp = self._plan_view_s
        if flat:
            c.create_polygon(
                *flat, fill=fill, outline=border,
                width=self._lw(2.2 if room.pinned else 1.5))

        tpl = room.template_snapshot

        rot_deg = float(room.rotation) % 360.0
        if tpl.preset_id:
            bx, by, bw, bh = room.world_bbox()
            sbx, sby = self._w2s(bx, by)
            sw = bw * vp
            sh = bh * vp
            renderer = PRESET_RENDERERS.get(tpl.preset_id)
            if renderer:
                try:
                    if abs(rot_deg) < 0.08 or abs(rot_deg - 360.0) < 0.08:
                        renderer(c, sbx, sby, sw, sh)
                    else:
                        rad = math.radians(rot_deg)
                        scx = sbx + sw * 0.5
                        scy = sby + sh * 0.5
                        proxy = RotatedCanvasProxy(
                            c, scx, scy, math.cos(rad), math.sin(rad))
                        renderer(proxy, sbx, sby, sw, sh)
                except Exception:
                    pass

        wall_list = getattr(tpl, "walls", None) or []
        for wi in wall_list:
            xa, ya = room.template_point_to_world(wi.x0, wi.y0)
            xb, yb = room.template_point_to_world(wi.x1, wi.y1)
            w_world = Wall(
                x0=xa, y0=ya, x1=xb, y1=yb,
                thickness=float(wi.thickness),
                color=wi.color,
            )
            _draw_wall_scaled(
                c, w_world,
                self._plan_view_ox, self._plan_view_oy, self._plan_view_s)

        bx, by, _, _ = room.world_bbox()
        for fi in tpl.furniture:
            fx, fy, fw, fh = fi.x, fi.y, fi.w, fi.h
            rot = int(room.rotation) % 360
            tbbx, tbby, tbw, tbh = tpl.bbox()
            ix = fx - tbbx
            iy = fy - tbby
            if rot == 0:
                nx, ny, nw, nh = ix, iy, fw, fh
            elif rot == 90:
                nx = tbh - iy - fh
                ny = ix
                nw, nh = fh, fw
            elif rot == 180:
                nx = tbw - ix - fw
                ny = tbh - iy - fh
                nw, nh = fw, fh
            elif rot == 270:
                nx = iy
                ny = tbw - ix - fw
                nw, nh = fh, fw
            else:
                nx, ny, nw, nh = ix, iy, fw, fh
            placed = FurnitureItem(
                type=fi.type, x=0, y=0, w=nw, h=nh,
                color=fi.color, rotation=fi.rotation, custom_id=fi.custom_id)
            ax, ay = self._w2s(bx + nx, by + ny)
            _draw_furniture_scaled_rotated(
                c, placed, ax, ay, float(nw) * vp, float(nh) * vp)

        if room.pinned:
            bx, by, bw, bh = room.world_bbox()
            ox0, oy0 = self._w2s(bx + bw - 14, by + 2)
            ox1, oy1 = self._w2s(bx + bw - 2, by + 14)
            c.create_oval(
                min(ox0, ox1), min(oy0, oy1), max(ox0, ox1), max(oy0, oy1),
                fill="#E85D24", outline="white",
                width=self._lw(1.5))

        if show_label:
            bx, by, bw, bh = room.world_bbox()
            tx, ty = self._w2s(bx + bw / 2.0, by + bh - 10.0)
            c.create_text(tx, ty,
                          text=tpl.label, font=("Helvetica", 8),
                          fill="#444")

        if selected:
            cx_, cy_, bw, bh = room.world_bbox()
            ax0, ay0 = self._w2s(cx_ - SEL_PAD, cy_ - SEL_PAD)
            ax1, ay1 = self._w2s(cx_ + bw + SEL_PAD, cy_ + bh + SEL_PAD)
            c.create_rectangle(ax0, ay0, ax1, ay1,
                               outline=C_SELECT,
                               width=self._lw(SEL_WIDTH), fill="")

    def hit_test(self, px: float, py: float, plan: Plan) -> Optional[RoomInstance]:
        """``px``, ``py`` must be **world** coordinates."""
        return plan.room_at(px, py)
