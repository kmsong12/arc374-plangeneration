"""
furniture_lib.py - Built-in furniture catalog.

Every entry is a `FurnitureSpec` with a default size (px), a default fill
color, and a `draw(canvas, x, y, w, h, color)` function that paints the
item onto a Tkinter Canvas.

Size note (px -> ft, anchored by Bed = 6.5 ft @ 100 px):
    PX_PER_FT ~= 15.38
    1 ft  ~= 15 px
    2 ft  ~= 30 px
    6.5 ft ~= 100 px

The sizes below are chosen to roughly match real furniture:
    Twin bed  : 38" x 75" (~3.2 x 6.25 ft)  =>   50 x 95 px
    Queen bed : 60" x 80" (~5.0 x 6.7 ft)   =>   77 x 103 px
    King bed  : 76" x 80" (~6.3 x 6.7 ft)   =>   97 x 103 px
"""

from __future__ import annotations
import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Dict, List

from units import ft_to_px


def _px(ft: float) -> int:
    return max(1, int(round(ft_to_px(ft))))


# ---------------------------------------------------------------------------
# low level draw helpers
# ---------------------------------------------------------------------------

def _rect(c, x, y, w, h, fill, outline="#666", width=1.0):
    if w <= 0 or h <= 0:
        return
    c.create_rectangle(x, y, x + w, y + h,
                       fill=fill, outline=outline, width=width)


def _oval(c, x, y, w, h, fill, outline="#666", width=1.0):
    c.create_oval(x, y, x + w, y + h,
                  fill=fill, outline=outline, width=width)


def _line(c, x0, y0, x1, y1, fill="#666", width=1.0):
    c.create_line(x0, y0, x1, y1, fill=fill, width=width)


def _shade(color: str, darker: bool = True) -> str:
    """Return a slightly darker (or lighter) shade of `color`."""
    try:
        c = color.lstrip("#")
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except Exception:
        return "#666666"
    k = 0.75 if darker else 1.2
    r = max(0, min(255, int(r * k)))
    g = max(0, min(255, int(g * k)))
    b = max(0, min(255, int(b * k)))
    return f"#{r:02X}{g:02X}{b:02X}"


# ---------------------------------------------------------------------------
# drawing functions (each takes canvas, x, y, w, h, color)
# ---------------------------------------------------------------------------

def _draw_bed(c, x, y, w, h, color):
    border = _shade(color)
    _rect(c, x, y, w, h, color, border, 1.5)
    head_h = max(6, h // 8)
    _rect(c, x, y, w, head_h, border, border, 1)
    pw = int(w * 0.35)
    ph = max(6, int(h * 0.14))
    off = max(3, w // 16)
    _rect(c, x + off,           y + head_h + 4, pw, ph, "#FFFFFF", border, 1)
    _rect(c, x + w - off - pw,  y + head_h + 4, pw, ph, "#FFFFFF", border, 1)
    blanket_y = y + head_h + ph + 8
    if blanket_y < y + h - 4:
        _line(c, x + 3, blanket_y, x + w - 3, blanket_y, border, 1)


def _draw_cabinet(c, x, y, w, h, color):
    border = _shade(color)
    _rect(c, x, y, w, h, color, border, 1.5)
    _line(c, x + w / 2, y + 4, x + w / 2, y + h - 4, border, 1)
    r = 2
    cy = y + h / 2
    _oval(c, x + w / 4 - r, cy - r, 2 * r, 2 * r, border, border)
    _oval(c, x + 3 * w / 4 - r, cy - r, 2 * r, 2 * r, border, border)


def _draw_bookshelf(c, x, y, w, h, color):
    border = _shade(color)
    _rect(c, x, y, w, h, color, border, 1.5)
    shelves = 4
    for i in range(1, shelves):
        sy = y + h * i / shelves
        _line(c, x + 2, sy, x + w - 2, sy, border, 1)
    # book hints
    for i in range(shelves):
        sy = y + h * i / shelves + 2
        bw = max(3, w // 10)
        for j in range(1, int(w // bw) - 1):
            _line(c, x + j * bw, sy,
                  x + j * bw, sy + h / shelves - 4,
                  border, 0.8)


def _draw_table(c, x, y, w, h, color):
    border = _shade(color)
    _rect(c, x, y, w, h, color, border, 1.5)
    leg = max(3, min(w, h) // 8)
    for lx, ly in ((x, y), (x + w - leg, y),
                   (x, y + h - leg), (x + w - leg, y + h - leg)):
        _rect(c, lx, ly, leg, leg, border, border)


def _draw_chair_sq(c, x, y, w, h, color):
    border = _shade(color)
    _rect(c, x, y, w, h, color, border, 1.2)
    back_h = max(4, h // 3)
    _rect(c, x, y, w, back_h, border, border)


def _draw_chair_round(c, x, y, w, h, color):
    border = _shade(color)
    _oval(c, x, y, w, h, color, border, 1.2)
    inr = min(w, h) * 0.6
    ix = x + (w - inr) / 2
    iy = y + (h - inr) / 2
    _oval(c, ix, iy, inr, inr, _shade(color, darker=False), border, 0.8)


def _draw_tv(c, x, y, w, h, color):
    border = "#111111"
    _rect(c, x, y, w, h, "#222222", border, 1.5)
    inset = max(2, min(w, h) // 10)
    _rect(c, x + inset, y + inset, w - 2 * inset, h - 2 * inset,
          "#444444", "#111111", 0.5)
    _rect(c, x + w / 2 - 6, y + h - 2, 12, 2, border, border)


def _draw_window(c, x, y, w, h, color):
    border = _shade(color)
    _rect(c, x, y, w, h, color, border, 1.5)
    # double line window style
    if w >= h:
        _line(c, x, y + h / 2, x + w, y + h / 2, border, 1)
        for i in (1, 2, 3):
            lx = x + w * i / 4
            _line(c, lx, y, lx, y + h, border, 0.7)
    else:
        _line(c, x + w / 2, y, x + w / 2, y + h, border, 1)
        for i in (1, 2, 3):
            ly = y + h * i / 4
            _line(c, x, ly, x + w, ly, border, 0.7)


def _draw_door(c, x, y, w, h, color):
    border = _shade(color)
    _rect(c, x, y, w, h, color, border, 1.5)
    # Hinge on a short end of the slab; arc center on the opposite end of
    # the long side so the quarter-circle sweeps across the opening depth.
    if w >= h:
        long_r = w
        cx, cy = x + w, y + h
        c.create_arc(
            cx - long_r, cy - long_r, cx + long_r, cy + long_r,
            start=180, extent=-90,
            style=tk.ARC, outline=border, width=1)
        knob_x = x + w - 4
        knob_y = y + h / 2 - 2
    else:
        long_r = h
        cx, cy = x + w, y + h
        c.create_arc(
            cx - long_r, cy - long_r, cx + long_r, cy + long_r,
            start=90, extent=90,
            style=tk.ARC, outline=border, width=1)
        knob_x = x + w / 2 - 2
        knob_y = y + h - 4
    _oval(c, knob_x, knob_y, 3, 3, border, border)


def _draw_toilet(c, x, y, w, h, color):
    border = _shade(color)
    tank_h = h * 0.35
    bowl_h = h - tank_h
    _rect(c, x + w * 0.15, y, w * 0.70, tank_h, color, border, 1.2)
    _oval(c, x, y + tank_h, w, bowl_h, color, border, 1.2)


def _draw_sink(c, x, y, w, h, color):
    border = _shade(color)
    _rect(c, x, y, w, h, color, border, 1.2)
    margin_x = w * 0.15
    margin_y = h * 0.18
    _oval(c, x + margin_x, y + margin_y,
          w - 2 * margin_x, h - 2 * margin_y,
          "#FFFFFF", border, 1)
    _rect(c, x + w / 2 - 2, y + 1, 4, margin_y - 1, border, border)


def _draw_shower(c, x, y, w, h, color):
    border = _shade(color)
    _rect(c, x, y, w, h, color, border, 1.5)
    # X inside
    _line(c, x + 2, y + 2, x + w - 2, y + h - 2, border, 1.2)
    _line(c, x + 2, y + h - 2, x + w - 2, y + 2, border, 1.2)


def _draw_couch(n_cushions: int):
    def _draw(c, x, y, w, h, color):
        border = _shade(color)
        _rect(c, x, y, w, h, color, border, 1.5)
        arm = max(4, w // 10)
        back_h = max(6, h // 4)
        _rect(c, x, y, arm, h, border, border)
        _rect(c, x + w - arm, y, arm, h, border, border)
        _rect(c, x, y, w, back_h, border, border)
        # cushions
        ix0 = x + arm + 2
        iy0 = y + back_h + 2
        iw = w - 2 * arm - 4
        ih = h - back_h - 4
        if iw <= 0 or ih <= 0 or n_cushions < 1:
            return
        gap = 2
        cush_w = (iw - (n_cushions - 1) * gap) / n_cushions
        for i in range(n_cushions):
            cx = ix0 + i * (cush_w + gap)
            _rect(c, cx, iy0, cush_w, ih,
                  _shade(color, darker=False), border, 0.8)
    return _draw


def _draw_preset_bathroom(c, x, y, w, h, color):
    """Compact bathroom: toilet + sink + shower arranged left-to-right."""
    border = _shade(color)
    _rect(c, x, y, w, h, color, border, 1.5)
    pad = max(2, min(w, h) // 20)
    cell = (w - 4 * pad) / 3.0
    if cell <= 4 or h <= 4:
        return
    by = y + pad
    bh = h - 2 * pad
    _draw_toilet(c,
                 x + pad, by,
                 cell, bh, "#FFFFFF")
    _draw_sink(c,
               x + 2 * pad + cell, by,
               cell, bh, "#FFFFFF")
    _draw_shower(c,
                 x + 3 * pad + 2 * cell, by,
                 cell, bh, "#F6F6F6")


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

@dataclass
class FurnitureSpec:
    key: str
    label: str
    group: str            # Bedroom / Bath / Seating / Storage / Display / Openings / Preset
    w: int
    h: int
    color: str
    draw: Callable        # (canvas, x, y, w, h, color) -> None


def _spec(key, label, group, w_ft, h_ft, color, draw_fn) -> FurnitureSpec:
    return FurnitureSpec(
        key=key, label=label, group=group,
        w=_px(w_ft), h=_px(h_ft), color=color, draw=draw_fn,
    )


CATALOG: Dict[str, FurnitureSpec] = {}


def _register(spec: FurnitureSpec) -> None:
    CATALOG[spec.key] = spec


# --- Beds ---
_register(_spec("Bed_Twin",  "Twin Bed",  "Bedroom", 3.2, 6.25, "#E8E0D8", _draw_bed))
_register(_spec("Bed_Queen", "Queen Bed", "Bedroom", 5.0, 6.7,  "#E8E0D8", _draw_bed))
_register(_spec("Bed_King",  "King Bed",  "Bedroom", 6.3, 6.7,  "#E8E0D8", _draw_bed))

# --- Storage ---
_register(_spec("Cabinet",    "Cabinet",    "Storage", 3.0, 1.5, "#C8B898", _draw_cabinet))
_register(_spec("Bookshelf",  "Bookshelf",  "Storage", 3.5, 1.0, "#B08968", _draw_bookshelf))

# --- Seating ---
_register(_spec("Couch2",     "Couch (2-seat)", "Seating", 5.0, 2.8, "#B8A898", _draw_couch(2)))
_register(_spec("Couch3",     "Couch (3-seat)", "Seating", 7.0, 2.8, "#B8A898", _draw_couch(3)))
_register(_spec("ChairSquare","Square Chair",   "Seating", 1.8, 1.8, "#C4B5A0", _draw_chair_sq))
_register(_spec("ChairRound", "Round Chair",    "Seating", 2.0, 2.0, "#C4B5A0", _draw_chair_round))

# --- Tables ---
_register(_spec("Table",       "Table",         "Seating", 3.0, 4.5, "#D4C5A9", _draw_table))
_register(_spec("TableSmall",  "Small Table",   "Seating", 2.0, 2.0, "#D4C5A9", _draw_table))

# --- Display ---
_register(_spec("TV",          "TV",            "Display", 4.0, 0.6, "#222222", _draw_tv))

# --- Openings ---
_register(_spec("Window",      "Window",        "Openings", 3.0, 0.5, "#E3ECF5", _draw_window))
_register(_spec("Door",        "Door",          "Openings", 2.8, 0.3, "#B08968", _draw_door))

# --- Bath ---
_register(_spec("Toilet",      "Toilet",        "Bath",  1.5, 2.3, "#FFFFFF", _draw_toilet))
_register(_spec("Sink",        "Sink",          "Bath",  2.0, 1.4, "#FFFFFF", _draw_sink))
_register(_spec("Shower_S",    "Shower (small)","Bath",  2.8, 2.8, "#F6F6F6", _draw_shower))
_register(_spec("Shower_M",    "Shower (med)",  "Bath",  3.5, 3.5, "#F6F6F6", _draw_shower))
_register(_spec("Shower_L",    "Shower (large)","Bath",  4.5, 4.5, "#F6F6F6", _draw_shower))

# --- Preset groups ---
_register(_spec("PresetBathroom", "Preset Bathroom", "Preset", 8.0, 5.0, "#EFEAE0", _draw_preset_bathroom))


GROUPS: List[str] = [
    "Bedroom", "Bath", "Seating", "Storage", "Display", "Openings", "Preset",
]


def by_group() -> Dict[str, List[FurnitureSpec]]:
    """Return catalog entries grouped by `group`."""
    out: Dict[str, List[FurnitureSpec]] = {g: [] for g in GROUPS}
    for spec in CATALOG.values():
        out.setdefault(spec.group, []).append(spec)
    return out


def get(key: str) -> FurnitureSpec | None:
    return CATALOG.get(key)


def draw(canvas, item, abs_x: float, abs_y: float) -> None:
    """
    Draw a FurnitureItem (from room_template) at absolute canvas coords.

    Supports both catalog items and CustomFurniture (delegated to
    custom_furniture.draw_custom).
    """
    if item.type == "Custom":
        from model.custom_furniture import draw_custom  # lazy to avoid cycle
        draw_custom(canvas, item.custom_id, abs_x, abs_y, item.w, item.h,
                    item.color)
        return
    spec = CATALOG.get(item.type)
    if spec is None:
        # unknown - fall back to a neutral rectangle
        _rect(canvas, abs_x, abs_y, item.w, item.h,
              item.color or "#DDDDDD", "#888", 1)
        return
    color = item.color or spec.color
    spec.draw(canvas, abs_x, abs_y, item.w, item.h, color)
