"""
canvas_renderer.py – Draws the hotel plan onto a Tkinter Canvas.

Responsibilities:
  • Site boundary & grid
  • Rooms (filled rect + label + simple interior sketch)
  • Bushes
  • Selection highlight

All drawing uses Tkinter canvas primitives (create_rectangle,
create_oval, create_text, …) with integer-pixel coordinates.
"""

from __future__ import annotations
import tkinter as tk
from typing import List, Tuple, Optional

from config import (
    GRID_SIZE, SITE_BORDER, SITE_BG,
    ROOM_COLORS, ROOM_BORDERS, BUSH_COLOR, LABEL_COLOR,
)
from hotel import Hotel
from rooms import Room


class CanvasRenderer:
    """Stateless helper: call draw() whenever the model changes."""

    def __init__(self, canvas: tk.Canvas):
        self.canvas = canvas
        self._room_item_map: dict[int, Room] = {}   # canvas item id → Room

    # ── Public API ─────────────────────────────────────────────

    def draw(
        self,
        site: Tuple[int, int, int, int],
        hotel: Hotel,
        bushes: List[Tuple[int, int, int]],
        show_grid: bool = True,
        show_labels: bool = False,
        selected_room: Optional[Room] = None,
        zone_rects: Optional[List[Tuple[int, int, int, int]]] = None,
    ):
        """Full redraw."""
        c = self.canvas
        c.delete("all")
        self._room_item_map.clear()

        sx, sy, sw, sh = site

        # 1. Background
        c.create_rectangle(0, 0, c.winfo_width() or 2000, c.winfo_height() or 2000,
                           fill="#F5F4EE", outline="")

        # 2. Grid
        if show_grid:
            self._draw_grid(site)

        # 3. Site border
        c.create_rectangle(sx, sy, sx + sw, sy + sh,
                           outline=SITE_BORDER, width=2, fill=SITE_BG)

        # 4. Zone overlays (semi-transparent, drawn before rooms)
        if zone_rects:
            for zx, zy, zw, zh in zone_rects:
                c.create_rectangle(zx, zy, zx + zw, zy + zh,
                                   fill="#FFF3CD", outline="#BA7517",
                                   width=1, dash=(4, 3), stipple="gray25")

        # 5. Bushes (drawn before rooms so they appear underneath)
        self._draw_bushes(bushes)

        # 6. Rooms
        for room in hotel.rooms:
            self._draw_room(room, selected=(room is selected_room),
                            show_label=show_labels)

    def hit_test(self, px: int, py: int, hotel: Hotel) -> Optional[Room]:
        """Return the room under pixel (px, py)."""
        return hotel.room_at(px, py)

    # ── Private helpers ────────────────────────────────────────

    def _draw_grid(self, site: Tuple[int, int, int, int]):
        sx, sy, sw, sh = site
        c = self.canvas
        step = GRID_SIZE
        for gy in range(sy, sy + sh + 1, step):
            for gx in range(sx, sx + sw + 1, step):
                c.create_oval(gx - 1, gy - 1, gx + 1, gy + 1,
                              fill="#cccccc", outline="")

    def _draw_bushes(self, bushes: List[Tuple[int, int, int]]):
        c = self.canvas
        for bx, by, br in bushes:
            offsets = [
                (0, -br * 0.75), (br * 0.75, 0), (0, br * 0.75), (-br * 0.75, 0),
                (-br * 0.5, -br * 0.5), (br * 0.5, -br * 0.5),
                (br * 0.5, br * 0.5), (-br * 0.5, br * 0.5), (0, 0),
            ]
            for ox, oy in offsets:
                cx, cy = bx + ox, by + oy
                c.create_oval(cx - br / 2, cy - br / 2,
                              cx + br / 2, cy + br / 2,
                              fill=BUSH_COLOR, outline="")

    def _draw_room(self, room: Room, selected: bool, show_label: bool):
        c   = self.canvas
        lbl = room.label
        fill    = ROOM_COLORS.get(lbl, "#EEEEEE")
        outline = ROOM_BORDERS.get(lbl, "#888888")
        width   = 3 if selected else 1.5

        # Outer rect
        item_id = c.create_rectangle(
            room.x, room.y, room.x + room.w, room.y + room.h,
            fill=fill, outline=outline, width=width,
        )
        self._room_item_map[item_id] = room

        # Selection highlight
        if selected:
            c.create_rectangle(
                room.x - 3, room.y - 3,
                room.x + room.w + 3, room.y + room.h + 3,
                outline="#FF6B00", width=2, fill="", dash=(4, 2),
            )

        # Simple interior sketch (minimal, so it reads at small sizes)
        self._draw_interior(room)

        # Label (optional)
        if show_label:
            c.create_text(
                room.cx, room.cy,
                text=lbl, font=("Helvetica", 8), fill=LABEL_COLOR,
                anchor="center",
            )

    def _draw_interior(self, room: Room):
        """Draw a minimal interior hint matching the room type."""
        c   = self.canvas
        lbl = room.label
        x, y, w, h = room.x, room.y, room.w, room.h
        col = ROOM_BORDERS.get(lbl, "#888888")

        if lbl in ("BedroomA", "BedroomB", "BedroomC", "BedroomD"):
            # Bed rectangle
            bw, bh = w * 0.45, h * 0.35
            bx = x + (w - bw) / 2
            by = y + h * 0.15
            c.create_rectangle(bx, by, bx + bw, by + bh,
                               outline=col, fill="", width=1)
            # Two pillows
            pw, ph = bw * 0.22, bh * 0.22
            c.create_rectangle(bx + bw * 0.10, by + bh * 0.08,
                               bx + bw * 0.10 + pw, by + bh * 0.08 + ph,
                               outline=col, fill="", width=0.5)
            c.create_rectangle(bx + bw * 0.68, by + bh * 0.08,
                               bx + bw * 0.68 + pw, by + bh * 0.08 + ph,
                               outline=col, fill="", width=0.5)

        elif lbl in ("TeaRoom1", "TeaRoom2"):
            # Two circular tables
            for tx_frac in (0.30, 0.68):
                ty_frac = 0.45
                tr = min(w, h) * 0.10
                cx = x + w * tx_frac
                cy = y + h * ty_frac
                c.create_oval(cx - tr, cy - tr, cx + tr, cy + tr,
                              outline=col, fill="", width=1)

        elif lbl == "Library":
            # Three vertical bookshelf lines
            bx = x + w * 0.08
            for i in range(3):
                lx = bx + i * w * 0.06
                c.create_rectangle(lx, y + h * 0.10, lx + w * 0.02, y + h * 0.80,
                                   outline=col, fill="", width=0.5)

        elif lbl == "ReadingRoom":
            # Small desk rect
            dw, dh = w * 0.40, h * 0.20
            dx = x + (w - dw) / 2
            dy = y + h * 0.20
            c.create_rectangle(dx, dy, dx + dw, dy + dh,
                               outline=col, fill="", width=1)
