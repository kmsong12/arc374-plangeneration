"""
app.py - HotelApp: main Tkinter application.

Implemented features
------------------------------------------------------------------------
Modes
  * Random / Procedural  - dart-throwing packing with sliders
  * Drag & Drop          - click room in library to spawn, drag to place
  * Zoning               - draw zone rects, then "Pack into zones"
  * Bench / Path         - click-drag to draw landscape elements
  * LLM Prompt           - text prompt → weights → regenerate

Editing
  * Select + drag room to reposition (snap-to-grid optional)
  * Resize selected room by dragging the orange corner handle
  * Delete selected room (Delete / Backspace key)
  * Undo / Redo  (Cmd+Z / Cmd+Shift+Z  or  Ctrl+Z / Ctrl+Y)

File
  * Save layout to JSON  (Cmd/Ctrl+S)
  * Load layout from JSON (Cmd/Ctrl+O)
  * Export PNG screenshot

Display
  * Grid dots toggle
  * Room labels toggle
  * Bushes toggle
  * Snap-to-grid toggle (toolbar)
  * Per-room-type breakdown in expanded metrics tooltip

Keyboard shortcuts
  R        Regenerate
  G        Toggle grid
  L        Toggle labels
  Delete   Remove selected room
  Ctrl+Z   Undo
  Ctrl+Y / Ctrl+Shift+Z  Redo
  Ctrl+S   Save
  Ctrl+O   Load
"""

from __future__ import annotations
import copy
import json
import math
import os
import random
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from config import (
    CANVAS_W, CANVAS_H,
    SIDEBAR_LEFT_W, SIDEBAR_RIGHT_W, TOOLBAR_H, METRICS_BAR_H,
    SITE_MARGIN, GRID_SIZE, DEFAULT_WEIGHTS,
    ROOM_COLORS, ROOM_BORDERS,
    FURNITURE_ITEMS, FURNITURE_COLORS, FURNITURE_BORDERS,
)
from hotel import Hotel
from packing import pack_rooms_into_hotel, pack_bushes
from canvas_renderer import CanvasRenderer
from geometry_utils import snap_to_grid, clamp
from rooms import ROOM_CLASSES
from llm_bridge import prompt_to_settings

# ── palette ───────────────────────────────────────────────────
C = {
    "bg":          "#EDEBE6",    # warm canvas surround
    "panel":       "#FFFFFF",    # sidebar bg
    "panel_bdr":   "#E4E2DB",    # panel border
    "toolbar":     "#1C1C1E",    # dark toolbar
    "tb_text":     "#E4E4E7",    # toolbar primary text
    "tb_dim":      "#71717A",    # toolbar secondary text
    "tb_sep":      "#3F3F46",    # toolbar separator
    "accent":      "#4A80BE",    # blue accent
    "accent_lt":   "#EDF4FC",    # light accent bg
    "accent_dark": "#2E6BAA",    # dark accent (hover)
    "text":        "#18181B",    # primary text
    "text_dim":    "#6B7280",    # secondary text
    "text_xdim":   "#A1A1AA",    # tertiary / placeholder
    "sep":         "#F0EDE8",    # separator line
    "hover":       "#F5F4F1",    # list-item hover bg
    "warn_bg":     "#FEF3C7",
    "warn_fg":     "#92400E",
    "metric_bg":   "#1C1C1E",    # dark status bar
    "bench":       "#9C8462",
    "path":        "#D4CCBA",
    "handle":      "#F97316",
}

MODES = [
    ("random", "Random / Procedural"),
    ("drag",   "Drag & Drop"),
    ("zone",   "Zoning"),
    ("bench",  "Place Bench"),
    ("path",   "Draw Path"),
    ("llm",    "LLM Prompt"),
]

CONSTRAINT_OPTIONS = ["All rooms", "Bedrooms only", "Public rooms only"]

# minimum room dimension when resizing
MIN_ROOM_DIM = 60
# minimum dimension for furniture / landscape / bush resize
MIN_ITEM_DIM = 10
# handle size in px
HANDLE_R = 6
# max undo steps
MAX_UNDO = 40


class HotelApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Hotel Floor Plan Generator")
        root.configure(bg=C["bg"])
        root.minsize(920, 620)

        # ── model ──
        self.hotel:           Hotel = Hotel()
        self.bushes:          list  = []
        self.seed:            int   = random.randint(0, 10**9)
        self.weights:         dict  = DEFAULT_WEIGHTS.copy()
        self._llm_settings:   dict  = {}
        self.landscape_items: list  = []
        self._zone_rects:     list  = []   # drawn zone rectangles

        # ── undo / redo stacks ──
        self._undo_stack: list = []
        self._redo_stack: list = []

        # ── per-room furniture selection / drag ──
        self._sel_furn         = None   # (room_ref, idx) or None
        self._furn_drag_start  = None   # (room_ref, idx, ox, oy) while moving
        self._flib_hover_room  = None   # room highlighted during furniture lib drag

        # ── interaction state ──
        self.selected_room         = None
        self._drag_start           = None   # (room, mx, my) for move
        self._resize_start         = None   # (room, orig_w, orig_h, mx, my)
        self._zone_start           = None
        self._path_start           = None
        self._preview_id           = None
        self._spawning_room        = None   # room being dragged from library
        self._snap_on              = True
        self.selected_landscape    = -1     # index into landscape_items
        self.selected_bush         = -1     # index into bushes
        self._landscape_drag_start = None   # (idx, mx, my)
        self._bush_drag_start      = None   # (idx, mx, my)
        self._library_press_root   = None   # (x_root, y_root) for click vs drag
        self._room_preview         = None   # (label, rw, rh) while previewing
        self._ghost_window         = None   # floating drag-ghost Toplevel

        # ── tk vars ──
        self.mode          = tk.StringVar(value="random")
        self._show_grid    = tk.BooleanVar(value=True)
        self._show_labels  = tk.BooleanVar(value=False)
        self._show_bushes  = tk.BooleanVar(value=True)

        self._build_ui()

    # ------------------------------------------------------------------------
    #  UI construction
    # ------------------------------------------------------------------------

    def _build_ui(self):
        root = self.root

        # ── Toolbar (dark) ────────────────────────────────────────────────────
        tb = tk.Frame(root, bg=C["toolbar"], height=44)
        tb.pack(side="top", fill="x")
        tb.pack_propagate(False)

        def _tbtn(text, cmd, primary=False):
            if primary:
                bg, bgh, fg = C["accent"], C["accent_dark"], "#FFFFFF"
            else:
                bg, bgh, fg = C["toolbar"], "#2C2C2E", C["tb_text"]
            b = tk.Label(tb, text=text, bg=bg, fg=fg,
                         font=("Helvetica", 10), padx=12, cursor="hand2")
            b.pack(side="left", pady=8, ipady=2)
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>",    lambda e: b.config(bg=bgh))
            b.bind("<Leave>",    lambda e: b.config(bg=bg))
            return b

        def _tsep():
            tk.Frame(tb, bg=C["tb_sep"], width=1).pack(
                side="left", fill="y", pady=10, padx=4)

        _tbtn("↺  Regenerate", self._generate_manual, primary=True)
        _tsep()
        _tbtn("↩  Undo", self._undo)
        _tbtn("↪  Redo", self._redo)
        _tsep()

        self._snap_lbl = tk.Label(
            tb, text="⌗  Snap  ✓", bg=C["toolbar"],
            fg=C["accent"], font=("Helvetica", 9), padx=10, cursor="hand2")
        self._snap_lbl.pack(side="left", pady=8, ipady=2)
        self._snap_lbl.bind("<Button-1>", lambda e: self._toggle_snap())

        _tsep()
        _tbtn("Clear landscape", self._clear_landscape)
        _tsep()
        _tbtn("💾  Save", self._save_layout)
        _tbtn("📂  Load", self._load_layout)

        tk.Frame(tb, bg=C["toolbar"]).pack(side="left", expand=True)
        self._seed_lbl = tk.Label(
            tb, text=f"seed  {self.seed}",
            bg=C["toolbar"], fg=C["tb_dim"],
            font=("Courier", 8), cursor="hand2")
        self._seed_lbl.pack(side="left", padx=10)
        self._seed_lbl.bind("<Button-1>", lambda e: self._edit_seed())
        tk.Frame(tb, bg=C["toolbar"]).pack(side="left", expand=True)

        _tbtn("📷  Export", self._export_png)

        # ── Status / metrics bar (dark, bottom) ───────────────────────────────
        mb = tk.Frame(root, bg=C["metric_bg"], height=METRICS_BAR_H)
        mb.pack(side="bottom", fill="x")
        mb.pack_propagate(False)
        self._m = {}
        for key, lbl_text in (("total_rooms", "ROOMS"), ("built_area", "BUILT"),
                               ("open_area", "OPEN"), ("density", "DENSITY")):
            tk.Label(mb, text=lbl_text, bg=C["metric_bg"],
                     fg=C["tb_dim"], font=("Helvetica", 7, "bold")).pack(
                side="left", padx=(14, 3))
            v = tk.Label(mb, text="—", bg=C["metric_bg"],
                         fg=C["tb_text"], font=("Helvetica", 8, "bold"))
            v.pack(side="left", padx=(0, 12))
            self._m[key] = v

        bd_btn = tk.Label(mb, text="details  ›", bg=C["metric_bg"],
                          fg=C["accent"], font=("Helvetica", 8),
                          cursor="hand2", padx=14)
        bd_btn.pack(side="right")
        bd_btn.bind("<Button-1>", lambda e: self._show_breakdown())
        bd_btn.bind("<Enter>", lambda e: bd_btn.config(fg=C["tb_text"]))
        bd_btn.bind("<Leave>", lambda e: bd_btn.config(fg=C["accent"]))

        # ── Body ──────────────────────────────────────────────────────────────
        body = tk.Frame(root, bg=C["bg"])
        body.pack(side="top", fill="both", expand=True)
        self._build_left(body)
        self._build_right(body)
        self._build_canvas(body)

    # left sidebar --------------------------------------------------------

    def _build_left(self, parent):
        W = 206   # sidebar width

        f = tk.Frame(parent, bg=C["panel"], width=W)
        f.pack(side="left", fill="y")
        f.pack_propagate(False)

        # Right border line
        tk.Frame(parent, bg=C["panel_bdr"], width=1).pack(side="left", fill="y")

        # ── local helpers ──────────────────────────────────────────────────────
        def _sec(text):
            tk.Label(f, text=text, font=("Helvetica", 7, "bold"),
                     bg=C["panel"], fg=C["text_xdim"],
                     anchor="w", padx=16).pack(fill="x", pady=(14, 3))

        def _hsep():
            tk.Frame(f, bg=C["sep"], height=1).pack(fill="x", pady=3)

        def _lib_row(label_text, chip_color, chip_border,
                     press_cmd, motion_cmd, release_cmd):
            """One item row with full-width hover highlight."""
            row   = tk.Frame(f, bg=C["panel"], cursor="hand2")
            row.pack(fill="x")
            inner = tk.Frame(row, bg=C["panel"])
            inner.pack(fill="x", padx=16, pady=5)
            chip  = tk.Frame(inner, bg=chip_color, width=10, height=10,
                             highlightthickness=1,
                             highlightbackground=chip_border)
            chip.pack(side="left", padx=(0, 9))
            chip.pack_propagate(False)
            name_lbl = tk.Label(inner, text=label_text, font=("Helvetica", 9),
                                bg=C["panel"], fg=C["text"], cursor="hand2")
            name_lbl.pack(side="left")
            hw = [row, inner, name_lbl]

            def _e(e):
                for w in hw:
                    w.config(bg=C["hover"])
            def _l(e):
                for w in hw:
                    w.config(bg=C["panel"])

            for w in (row, inner, chip, name_lbl):
                w.bind("<Enter>",          _e)
                w.bind("<Leave>",          _l)
                w.bind("<ButtonPress-1>",  press_cmd)
                w.bind("<B1-Motion>",      motion_cmd)
                w.bind("<ButtonRelease-1>", release_cmd)

        # ── MODE ──────────────────────────────────────────────────────────────
        _sec("MODE")
        self._mode_btns = {}

        def _mode_item(val, text):
            row = tk.Frame(f, bg=C["panel"], cursor="hand2")
            row.pack(fill="x")
            ind = tk.Frame(row, bg=C["panel"], width=3)
            ind.pack(side="left", fill="y")
            lbl = tk.Label(row, text=text, font=("Helvetica", 9),
                           bg=C["panel"], fg=C["text_dim"],
                           anchor="w", padx=13, pady=5, cursor="hand2")
            lbl.pack(side="left", fill="x", expand=True)

            def _click(e=None):
                self.mode.set(val)
                self._on_mode_change()

            def _enter(e, r=row, l=lbl):
                if self.mode.get() != val:
                    r.config(bg=C["hover"])
                    l.config(bg=C["hover"])

            def _leave(e, v=val):
                self._refresh_mode_btns()

            for w in (row, lbl):
                w.bind("<Button-1>", _click)
                w.bind("<Enter>",    _enter)
                w.bind("<Leave>",    _leave)

            self._mode_btns[val] = (row, ind, lbl)

        for val, label in MODES:
            _mode_item(val, label)

        # Zone pack button
        self._zone_btn = tk.Label(
            f, text="Pack into zones  →",
            bg=C["accent"], fg="#FFFFFF",
            font=("Helvetica", 9), cursor="hand2",
            padx=16, pady=5)
        self._zone_btn.pack(fill="x", padx=16, pady=(4, 4))
        self._zone_btn.bind("<Button-1>", lambda e: self._pack_zones())
        self._zone_btn.bind("<Enter>",
                            lambda e: self._zone_btn.config(bg=C["accent_dark"]))
        self._zone_btn.bind("<Leave>",
                            lambda e: self._zone_btn.config(bg=C["accent"]))

        _hsep()

        # ── ROOM LIBRARY ──────────────────────────────────────────────────────
        _sec("ROOM LIBRARY")
        tk.Label(f, text="Drag to canvas  •  Click to preview",
                 font=("Helvetica", 7), bg=C["panel"], fg=C["text_xdim"],
                 anchor="w", padx=16).pack(fill="x", pady=(0, 4))

        for lbl, col in ROOM_COLORS.items():
            _lib_row(lbl, col, ROOM_BORDERS[lbl],
                     lambda e, l=lbl: self._library_press(e, l),
                     self._library_drag,
                     self._library_release)

        _hsep()

        # ── LANDSCAPE ─────────────────────────────────────────────────────────
        _sec("LANDSCAPE")
        tk.Label(f, text="Select Bench or Path mode above",
                 font=("Helvetica", 7), bg=C["panel"], fg=C["text_xdim"],
                 anchor="w", padx=16).pack(fill="x", pady=(0, 4))

        for chip_lbl, chip_col in (("Bench", C["bench"]), ("Path", C["path"])):
            row   = tk.Frame(f, bg=C["panel"])
            row.pack(fill="x")
            inner = tk.Frame(row, bg=C["panel"])
            inner.pack(fill="x", padx=16, pady=4)
            tk.Frame(inner, bg=chip_col, width=10, height=10,
                     highlightthickness=1,
                     highlightbackground="#999").pack(side="left", padx=(0, 9))
            tk.Label(inner, text=chip_lbl, font=("Helvetica", 9),
                     bg=C["panel"], fg=C["text_dim"]).pack(side="left")

        _hsep()

        # ── FURNITURE ─────────────────────────────────────────────────────────
        _sec("FURNITURE")
        tk.Label(f, text="Drag into a room  •  Right-click to pin",
                 font=("Helvetica", 7), bg=C["panel"], fg=C["text_xdim"],
                 anchor="w", padx=16).pack(fill="x", pady=(0, 4))

        for fname, finfo in FURNITURE_ITEMS.items():
            _lib_row(fname,
                     FURNITURE_COLORS[fname], FURNITURE_BORDERS[fname],
                     lambda e, n=fname, i=finfo: self._flib_press(e, n, i),
                     self._flib_drag,
                     self._flib_release)

        # set initial mode highlight
        self._refresh_mode_btns()

    # right sidebar -----------------------------------------------

    def _build_right(self, parent):
        W = 218   # sidebar width

        # Left border line
        tk.Frame(parent, bg=C["panel_bdr"], width=1).pack(side="right", fill="y")

        f = tk.Frame(parent, bg=C["panel"], width=W)
        f.pack(side="right", fill="y")
        f.pack_propagate(False)

        # Scrollable inner frame
        inn = tk.Frame(f, bg=C["panel"])
        inn.pack(fill="both", expand=True)

        # ── local helpers ──────────────────────────────────────────────────────
        def _sec(text):
            tk.Label(inn, text=text, font=("Helvetica", 7, "bold"),
                     bg=C["panel"], fg=C["text_xdim"],
                     anchor="w", padx=16).pack(fill="x", pady=(14, 3))

        def _hsep():
            tk.Frame(inn, bg=C["sep"], height=1).pack(fill="x", pady=4)

        def _slider(label, var, lo, hi, step, cb=None):
            row = tk.Frame(inn, bg=C["panel"])
            row.pack(fill="x", padx=16, pady=(5, 0))
            top = tk.Frame(row, bg=C["panel"])
            top.pack(fill="x")
            tk.Label(top, text=label, font=("Helvetica", 9),
                     bg=C["panel"], fg=C["text_dim"],
                     anchor="w").pack(side="left")
            val_lbl = tk.Label(top, text=str(var.get()),
                               font=("Helvetica", 9, "bold"),
                               bg=C["panel"], fg=C["text"])
            val_lbl.pack(side="right")
            def _tr(*_):
                val_lbl.config(text=str(var.get()))
                if cb: cb()
            var.trace_add("write", _tr)
            tk.Scale(row, variable=var, from_=lo, to=hi, resolution=step,
                     orient="horizontal", bg=C["panel"],
                     troughcolor=C["sep"], highlightthickness=0,
                     sliderrelief="flat", activebackground=C["accent"],
                     showvalue=False, sliderlength=14, bd=0,
                     length=185).pack(fill="x", pady=(2, 0))

        def _toggle_row(text, var, cmd):
            row = tk.Frame(inn, bg=C["panel"], cursor="hand2")
            row.pack(fill="x")
            lbl = tk.Label(row, text=text, font=("Helvetica", 9),
                           bg=C["panel"], fg=C["text"],
                           anchor="w", padx=16, pady=5, cursor="hand2")
            lbl.pack(side="left", fill="x", expand=True)
            dot = tk.Label(row, font=("Helvetica", 11),
                           bg=C["panel"], padx=12, cursor="hand2")
            dot.pack(side="right")

            def _refresh():
                dot.config(text="●" if var.get() else "○",
                           fg=C["accent"] if var.get() else C["text_xdim"])
            _refresh()

            def _toggle(e=None):
                var.set(not var.get())
                _refresh()
                cmd()

            def _ent(e, r=row, l=lbl, d=dot):
                for w in (r, l, d): w.config(bg=C["hover"])
            def _lv(e, r=row, l=lbl, d=dot):
                for w in (r, l, d): w.config(bg=C["panel"])

            for w in (row, lbl, dot):
                w.bind("<Button-1>", _toggle)
                w.bind("<Enter>",    _ent)
                w.bind("<Leave>",    _lv)

        # ── PARAMETERS ────────────────────────────────────────────────────────
        _sec("PARAMETERS")
        self._n_rooms_var  = tk.IntVar(value=10)
        self._pad_var      = tk.IntVar(value=30)
        self._bed_bias_var = tk.IntVar(value=50)
        self._margin_var   = tk.IntVar(value=SITE_MARGIN)

        _slider("Room count",       self._n_rooms_var,  2, 24, 1)
        _slider("Padding (px)",     self._pad_var,      0, 80, 5)
        _slider("Bedroom bias (%)", self._bed_bias_var, 0, 100, 5,
                cb=self._update_weights)
        _slider("Site margin (px)", self._margin_var,   20, 120, 5)

        tk.Label(inn, text="Room filter", font=("Helvetica", 9),
                 bg=C["panel"], fg=C["text_dim"],
                 anchor="w", padx=16).pack(fill="x", pady=(10, 2))
        self._constraint_var = tk.StringVar(value=CONSTRAINT_OPTIONS[0])
        ttk.Combobox(inn, textvariable=self._constraint_var,
                     values=CONSTRAINT_OPTIONS, state="readonly",
                     font=("Helvetica", 9)).pack(fill="x", padx=16)

        _hsep()

        # ── DISPLAY ───────────────────────────────────────────────────────────
        _sec("DISPLAY")
        _toggle_row("Grid dots",   self._show_grid,   self._redraw)
        _toggle_row("Room labels", self._show_labels, self._redraw)
        _toggle_row("Bushes",      self._show_bushes, self._redraw)

        _hsep()

        # ── LLM PROMPT ────────────────────────────────────────────────────────
        hdr = tk.Frame(inn, bg=C["panel"])
        hdr.pack(fill="x", padx=16, pady=(0, 4))
        tk.Label(hdr, text="LLM PROMPT", font=("Helvetica", 7, "bold"),
                 bg=C["panel"], fg=C["text_xdim"]).pack(side="left")
        tk.Label(hdr, text="beta", font=("Helvetica", 7),
                 bg=C["warn_bg"], fg=C["warn_fg"],
                 padx=4, pady=1).pack(side="left", padx=6)

        self._llm_txt = tk.Text(inn, height=3, font=("Helvetica", 9),
                                relief="flat", bg=C["hover"], fg=C["text"],
                                highlightthickness=1,
                                highlightbackground=C["sep"],
                                wrap="word", bd=0, padx=8, pady=6)
        self._llm_txt.pack(fill="x", padx=16, pady=(0, 6))
        self._llm_txt.insert("end",
            "e.g. More bedrooms in the north, tea room near entrance")

        self._llm_btn = tk.Label(
            inn, text="Generate with prompt  ↗",
            bg=C["accent"], fg="#FFFFFF",
            font=("Helvetica", 9), padx=8, pady=6, cursor="hand2")
        self._llm_btn.pack(fill="x", padx=16)
        self._llm_btn.bind("<Button-1>", lambda e: self._llm_generate())
        self._llm_btn.bind("<Enter>",
                           lambda e: self._llm_btn.config(bg=C["accent_dark"]))
        self._llm_btn.bind("<Leave>",
                           lambda e: self._llm_btn.config(bg=C["accent"]))

        self._llm_status = tk.Label(inn, text="", font=("Helvetica", 8),
                                    bg=C["panel"], fg=C["accent"])
        self._llm_status.pack(fill="x", padx=16, pady=(4, 0))

        _hsep()

        # ── SELECTED ROOM ─────────────────────────────────────────────────────
        _sec("SELECTED ROOM")
        self._sel_lbl = tk.Label(
            inn, text="None", font=("Helvetica", 9),
            bg=C["panel"], fg=C["text_xdim"],
            anchor="w", padx=16, pady=2,
            wraplength=W - 32, justify="left")
        self._sel_lbl.pack(fill="x")

        self._reset_furn_btn = tk.Label(
            inn, text="Reset furniture",
            bg=C["sep"], fg=C["text_dim"],
            font=("Helvetica", 8), padx=16, pady=5,
            cursor="arrow", anchor="w")
        self._reset_furn_btn.pack(fill="x", padx=16, pady=(6, 0))
        self._reset_furn_btn.bind("<Button-1>",
                                  lambda e: self._reset_room_furniture())

    # canvas ------------------------------------------------------------

    def _build_canvas(self, parent):
        self._canvas = tk.Canvas(parent, bg=C["bg"],
                                 width=CANVAS_W, height=CANVAS_H,
                                 bd=0, highlightthickness=0,
                                 cursor="crosshair")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._renderer = CanvasRenderer(self._canvas)

        cv = self._canvas
        cv.bind("<Button-1>",        self._on_click)
        cv.bind("<B1-Motion>",       self._on_drag)
        cv.bind("<ButtonRelease-1>", self._on_release)
        cv.bind("<Button-2>",        self._on_right_click)   # macOS two-finger / middle
        cv.bind("<Button-3>",        self._on_right_click)   # right-click
        cv.bind("<Configure>",
                lambda e: self._redraw() if self.hotel.rooms else None)

        # Only bind Cmd/Ctrl shortcuts - single-letter shortcuts removed
        # entirely because they conflict with the LLM text box on macOS.
        # Use the toolbar buttons to regenerate, toggle grid, etc.
        mod = "Command" if self.root.tk.call("tk", "windowingsystem") == "aqua" else "Control"
        root = self.root
        root.bind(f"<{mod}-z>", lambda e: self._undo())
        root.bind(f"<{mod}-Z>", lambda e: self._redo())
        root.bind(f"<{mod}-y>", lambda e: self._redo())
        root.bind(f"<{mod}-s>", lambda e: self._save_layout())
        root.bind(f"<{mod}-o>", lambda e: self._load_layout())
        # Delete selected room only when canvas has focus
        cv.config(takefocus=True)
        cv.bind("<Delete>",    self._delete_selected)
        cv.bind("<BackSpace>", self._delete_selected)

    # widget helpers --------------------------------------------------------

    def _sec(self, parent, text):
        tk.Label(parent, text=text, font=("Helvetica", 8, "bold"),
                 bg=C["panel"], fg=C["text_dim"], anchor="w").pack(
            fill="x", pady=(8,3))

    def _hsep(self, parent):
        tk.Frame(parent, bg=C["sep"], height=1).pack(fill="x", pady=6)

    def _vsep(self, parent):
        tk.Frame(parent, bg=C["sep"], width=1).pack(
            side="left", fill="y", pady=6, padx=4)

    def _slider(self, parent, label, var, lo, hi, step, cb=None):
        row = tk.Frame(parent, bg=C["panel"])
        row.pack(fill="x", pady=(4,0))
        tk.Label(row, text=label, font=("Helvetica", 9),
                 bg=C["panel"], fg=C["text_dim"], anchor="w").pack(side="left")
        val_lbl = tk.Label(row, text=str(var.get()),
                           font=("Helvetica", 9, "bold"),
                           bg=C["panel"], fg=C["text"])
        val_lbl.pack(side="right")
        def _tr(*_):
            val_lbl.config(text=str(var.get()))
            if cb:
                cb()
        var.trace_add("write", _tr)
        tk.Scale(parent, variable=var, from_=lo, to=hi, resolution=step,
                 orient="horizontal", bg=C["panel"], troughcolor=C["sep"],
                 sliderrelief="flat", highlightthickness=0,
                 showvalue=False, length=175).pack(fill="x")

    # ------------------------------------------------------------------------
    #  Site / geometry
    # ------------------------------------------------------------------------

    def _site(self):
        m = self._margin_var.get()
        w = self._canvas.winfo_width()  or CANVAS_W
        h = self._canvas.winfo_height() or CANVAS_H
        return (m, m, w-2*m, h-2*m)

    def _get_constraint(self) -> int:
        return CONSTRAINT_OPTIONS.index(self._constraint_var.get())

    def _snapped(self, v):
        return snap_to_grid(v, GRID_SIZE) if self._snap_on else int(v)

    # ── four-corner resize helpers ────────────────────────────────────────────

    @staticmethod
    def _corner_positions(x, y, w, h) -> dict:
        """Return {corner_name: (cx, cy)} for all four corners."""
        return {
            "TL": (x,     y),
            "TR": (x + w, y),
            "BL": (x,     y + h),
            "BR": (x + w, y + h),
        }

    def _nearest_corner(self, mx, my, x, y, w, h):
        """Return the corner name within HANDLE_R+4 px of (mx,my), or None."""
        threshold = HANDLE_R + 4
        for name, (cx, cy) in self._corner_positions(x, y, w, h).items():
            if abs(mx - cx) <= threshold and abs(my - cy) <= threshold:
                return name
        return None

    def _obj_xywh(self, obj):
        """Return (x, y, w, h) for a room or furniture dict."""
        if isinstance(obj, dict):
            return obj["x"], obj["y"], obj["w"], obj["h"]
        return obj.x, obj.y, obj.w, obj.h

    def _apply_corner_resize(self, obj, corner, orig, mx, my,
                             min_dim=None):
        """
        Resize from orig=(ox,oy,ow,oh,mx0,my0) using given corner.
        min_dim: floor for width/height.  Defaults to MIN_ROOM_DIM for
        Room objects, MIN_ITEM_DIM for furniture/landscape/bushes.
        Returns new (x, y, w, h).
        """
        from rooms import Room as _Room
        if min_dim is None:
            min_dim = MIN_ROOM_DIM if isinstance(obj, _Room) else MIN_ITEM_DIM
        ox, oy, ow, oh, mx0, my0 = orig
        ddx = self._snapped(mx - mx0)
        ddy = self._snapped(my - my0)

        if corner == "BR":
            nx, ny = ox, oy
            nw = max(min_dim, ow + ddx)
            nh = max(min_dim, oh + ddy)
        elif corner == "BL":
            nw = max(min_dim, ow - ddx)
            nh = max(min_dim, oh + ddy)
            nx = ox + ow - nw
            ny = oy
        elif corner == "TR":
            nw = max(min_dim, ow + ddx)
            nh = max(min_dim, oh - ddy)
            nx = ox
            ny = oy + oh - nh
        else:   # TL
            nw = max(min_dim, ow - ddx)
            nh = max(min_dim, oh - ddy)
            nx = ox + ow - nw
            ny = oy + oh - nh

        # clamp within site
        sx, sy, sw, sh = self._site()
        nx = clamp(nx, sx, sx + sw - nw)
        ny = clamp(ny, sy, sy + sh - nh)
        nw = min(nw, sx + sw - nx)
        nh = min(nh, sy + sh - ny)
        return int(nx), int(ny), int(nw), int(nh)

    def _draw_corner_handles(self, x, y, w, h):
        """Draw four filled circles at each corner of the bounding box."""
        r = HANDLE_R
        cv = self._canvas
        for cx, cy in self._corner_positions(x, y, w, h).values():
            cv.create_oval(cx - r, cy - r, cx + r, cy + r,
                           fill=C["handle"], outline="white", width=1.5)

    def _clamp_to_site(self, room):
        """Push room back inside site boundaries."""
        sx, sy, sw, sh = self._site()
        room.x = clamp(room.x, sx, sx+sw-room.w)
        room.y = clamp(room.y, sy, sy+sh-room.h)

    # ------------------------------------------------------------------------
    #  Undo / Redo
    # ------------------------------------------------------------------------

    def _push_undo(self):
        # Hotel snapshot now includes per-room furniture; landscape stored separately
        self._undo_stack.append(
            (self.hotel.snapshot(), copy.deepcopy(self.landscape_items)))
        if len(self._undo_stack) > MAX_UNDO:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self, *_):
        if not self._undo_stack:
            return
        self._redo_stack.append(
            (self.hotel.snapshot(), copy.deepcopy(self.landscape_items)))
        hotel_snap, landscape_snap = self._undo_stack.pop()
        self.hotel.restore(hotel_snap)
        self.landscape_items  = landscape_snap
        self.selected_room    = None
        self._sel_furn        = None
        self._update_metrics()
        self._redraw()

    def _redo(self, *_):
        if not self._redo_stack:
            return
        self._undo_stack.append(
            (self.hotel.snapshot(), copy.deepcopy(self.landscape_items)))
        hotel_snap, landscape_snap = self._redo_stack.pop()
        self.hotel.restore(hotel_snap)
        self.landscape_items  = landscape_snap
        self.selected_room    = None
        self._sel_furn        = None
        self._update_metrics()
        self._redraw()

    # ------------------------------------------------------------------------
    #  Generation
    # ------------------------------------------------------------------------

    def _generate(self):
        # If user manually regenerates, go back to slider-based weights
        if not getattr(self, "_llm_weights_active", False):
            self._update_weights()
        self.seed = random.randint(0, 10**9)
        self._seed_lbl.config(text=f"seed  {self.seed}")
        self._run_packing()

    def _generate_manual(self):
        """Called by the Regenerate button - clears LLM weights."""
        self._llm_weights_active = False
        self._llm_settings = {}
        self._llm_status.config(text="")
        self._generate()

    def _run_packing(self, zones=None, zone_weights=None):
        self._room_preview = None   # exit preview mode whenever packing runs
        import config as cfg
        cfg.PAD = self._pad_var.get()
        site = self._site()
        sx, sy, sw, sh = site

        # LLM spatial layout -> auto-generate zones with per-zone weights
        llm_zones = zones
        llm_zone_weights = zone_weights
        if getattr(self, "_llm_weights_active", False) and not zones:
            spatial = self._llm_settings.get("spatial", "mixed")
            if spatial != "mixed":
                bedroom_w = {k: v for k, v in self.weights.items()
                             if k in ("BedroomA","BedroomB","BedroomC","BedroomD")}
                public_w  = {k: v for k, v in self.weights.items()
                             if k in ("TeaRoom1","TeaRoom2","Library","ReadingRoom")}
                half_h = sh // 2
                half_w = sw // 2
                if spatial == "bedrooms_bottom":
                    llm_zones = [(sx, sy, sw, half_h), (sx, sy+half_h, sw, half_h)]
                    llm_zone_weights = [public_w, bedroom_w]
                elif spatial == "bedrooms_top":
                    llm_zones = [(sx, sy, sw, half_h), (sx, sy+half_h, sw, half_h)]
                    llm_zone_weights = [bedroom_w, public_w]
                elif spatial == "bedrooms_left":
                    llm_zones = [(sx, sy, half_w, sh), (sx+half_w, sy, half_w, sh)]
                    llm_zone_weights = [bedroom_w, public_w]
                elif spatial == "bedrooms_right":
                    llm_zones = [(sx, sy, half_w, sh), (sx+half_w, sy, half_w, sh)]
                    llm_zone_weights = [public_w, bedroom_w]

        pad = self._llm_settings.get("pad") if getattr(self, "_llm_weights_active", False) else None
        n_bushes = self._llm_settings.get("n_bushes") if getattr(self, "_llm_weights_active", False) else None

        # Collect pinned rooms before replacing the hotel
        pinned_rooms = [r for r in self.hotel.rooms if getattr(r, "pinned", False)]

        self._push_undo()
        self.hotel = pack_rooms_into_hotel(
            site,
            n_rooms=max(0, self._n_rooms_var.get() - len(pinned_rooms)),
            weights=self.weights,
            seed=self.seed,
            constraint=self._get_constraint(),
            zones=llm_zones,
            zone_weights=llm_zone_weights,
            pad=pad,
        )
        # Re-add pinned rooms so they persist across generation
        for r in pinned_rooms:
            self.hotel.add_room(r)

        self.bushes = (pack_bushes(site, self.hotel, seed=self.seed, n_bushes=n_bushes)
                       if self._show_bushes.get() else [])
        self.selected_room = None
        self._sel_furn     = None
        self._update_sel_label()
        self._redraw()
        self._update_metrics()

    def _pack_zones(self):
        """Pack rooms constrained to drawn zone rectangles."""
        if not self._zone_rects:
            messagebox.showinfo("No zones",
                "Draw at least one zone rectangle on the canvas first,\n"
                "then click this button.")
            return
        self._run_packing(zones=self._zone_rects)

    def _llm_generate(self):
        prompt = self._llm_txt.get("1.0","end").strip()
        if not prompt:
            return
        self._llm_btn.config(fg=C["text_dim"])
        self._llm_status.config(text="Calling API...")
        self.root.update_idletasks()

        def _worker():
            err_msg = None
            settings = None
            try:
                settings = prompt_to_settings(prompt)
            except Exception as e:
                err_msg = str(e)
            if err_msg:
                self.root.after(0, lambda msg=err_msg: messagebox.showerror(
                    "LLM Error", msg))
            else:
                self._llm_settings = settings
                self.weights = settings["weights"]
                # apply slider-compatible settings immediately
                if "n_rooms" in settings:
                    self.root.after(0, lambda v=settings["n_rooms"]:
                                    self._n_rooms_var.set(v))
                if "pad" in settings:
                    self.root.after(0, lambda v=settings["pad"]:
                                    self._pad_var.set(v))
            self.root.after(0, self._on_llm_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_llm_done(self):
        self._llm_weights_active = True
        self._llm_status.config(text="LLM weights active")
        self._llm_btn.config(fg=C["accent"])
        self.root.after(3000, lambda: self._llm_status.config(text=""))
        self._generate()

    # ------------------------------------------------------------------------
    #  Redraw / metrics
    # ------------------------------------------------------------------------

    def _redraw(self, *_):
        if not hasattr(self, "_renderer"):
            return
        if self._room_preview:
            label, rw, rh = self._room_preview
            self._renderer.draw_preview(label, rw, rh)
            return
        if not self._show_bushes.get():
            self.bushes = []
        self._renderer.draw(
            site=self._site(),
            hotel=self.hotel,
            bushes=self.bushes,
            landscape_items=self.landscape_items,
            show_grid=self._show_grid.get(),
            show_labels=self._show_labels.get(),
            selected_room=self.selected_room,
            zone_rects=self._zone_rects if self.mode.get()=="zone" else None,
            sel_furn=self._sel_furn,
        )
        cv = self._canvas
        # Selected room — four corner handles
        if self.selected_room:
            rm = self.selected_room
            self._draw_corner_handles(rm.x, rm.y, rm.w, rm.h)

        # Selected furniture — four corner handles (furniture drawn by renderer)
        if self._sel_furn is not None:
            sel_room, sel_idx = self._sel_furn
            if sel_room in self.hotel.rooms and \
                    0 <= sel_idx < len(sel_room.furniture):
                fi = sel_room.furniture[sel_idx]
                ax = sel_room.x + fi["x"]
                ay = sel_room.y + fi["y"]
                self._draw_corner_handles(ax, ay, fi["w"], fi["h"])

        # Hover highlight during furniture library drag
        if self._flib_hover_room is not None:
            r = self._flib_hover_room
            cv.create_rectangle(r.x, r.y, r.x + r.w, r.y + r.h,
                                outline="#2D9F6A", width=3, fill="")

        # Selected landscape item — dashed selection rect + four corner handles
        if 0 <= self.selected_landscape < len(self.landscape_items):
            li = self.landscape_items[self.selected_landscape]
            pad = 3
            cv.create_rectangle(
                li["x"]-pad, li["y"]-pad,
                li["x"]+li["w"]+pad, li["y"]+li["h"]+pad,
                outline=C["handle"], width=2, fill="", dash=(5, 3))
            self._draw_corner_handles(li["x"], li["y"], li["w"], li["h"])

        # Selected bush (tree) — dashed circle + corner handles on bounding box
        if 0 <= self.selected_bush < len(self.bushes):
            bx, by, br = self.bushes[self.selected_bush]
            pad = 4
            cv.create_oval(
                bx-br-pad, by-br-pad, bx+br+pad, by+br+pad,
                outline=C["handle"], width=2, fill="", dash=(5, 3))
            self._draw_corner_handles(bx-br, by-br, 2*br, 2*br)

    def _update_metrics(self):
        m = self.hotel.compute_metrics(self._site())
        self._m["total_rooms"].config(text=str(m["total_rooms"]))
        self._m["built_area"].config(text=f"{m['built_area']:,} px²")
        self._m["open_area"].config(text=f"{m['open_area']:,} px²")
        self._m["density"].config(text=f"{m['density']}%")

    def _update_sel_label(self):
        reset_active = False
        reset_room   = None

        if self._sel_furn is not None:
            sel_room, sel_idx = self._sel_furn
            if sel_room in self.hotel.rooms and \
                    0 <= sel_idx < len(sel_room.furniture):
                fi = sel_room.furniture[sel_idx]
                self._sel_lbl.config(
                    text=f"{fi['type']} in {sel_room.label}\n"
                         f"{fi['w']}x{fi['h']} px",
                    fg=C["text"])
                reset_active = True
                reset_room   = sel_room
            else:
                self._sel_furn = None
        elif self.selected_room:
            r = self.selected_room
            pin_tag  = "  [PINNED]" if getattr(r, "pinned", False) else ""
            n_furn   = len(r.furniture)
            furn_tag = f"  •{n_furn} furn." if n_furn else ""
            self._sel_lbl.config(
                text=f"{r.label}{pin_tag}{furn_tag}\n"
                     f"{r.w}x{r.h} px  @({r.x},{r.y})",
                fg=C["text"])
            if n_furn:
                reset_active = True
                reset_room   = r
        elif 0 <= self.selected_landscape < len(self.landscape_items):
            li = self.landscape_items[self.selected_landscape]
            self._sel_lbl.config(
                text=f"{li['type'].capitalize()}\n"
                     f"{li['w']}x{li['h']} px  @({li['x']},{li['y']})",
                fg=C["text"])
        elif 0 <= self.selected_bush < len(self.bushes):
            bx, by, br = self.bushes[self.selected_bush]
            self._sel_lbl.config(
                text=f"Tree  r={br} px\n@({bx},{by})",
                fg=C["text"])
        else:
            self._sel_lbl.config(text="None", fg=C["text_dim"])

        # Update Reset furniture button appearance
        if reset_active and reset_room is not None:
            n = len(reset_room.furniture)
            self._reset_furn_btn.config(
                bg=C["warn_bg"], fg="#C44444", cursor="hand2",
                text=f"Reset furniture ({n})")
        else:
            self._reset_furn_btn.config(
                bg=C["sep"], fg=C["text_dim"], cursor="arrow",
                text="Reset furniture")

    def _show_breakdown(self):
        """Pop-up window showing per-type room count and average area."""
        m = self.hotel.compute_metrics(self._site())
        if not m["counts"]:
            messagebox.showinfo("Breakdown", "No rooms placed yet.")
            return
        win = tk.Toplevel(self.root)
        win.title("Room Breakdown")
        win.configure(bg=C["panel"])
        win.resizable(False, False)
        tk.Label(win, text="Room Breakdown", font=("Helvetica", 12, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(padx=20, pady=(14,6))
        for rtype in sorted(m["counts"]):
            n   = m["counts"][rtype]
            avg = int(m["avg_areas"][rtype])
            row = tk.Frame(win, bg=C["panel"])
            row.pack(fill="x", padx=20, pady=2)
            col = ROOM_COLORS.get(rtype, "#eee")
            tk.Frame(row, bg=col, width=16, height=10,
                     highlightthickness=1,
                     highlightbackground=ROOM_BORDERS.get(rtype,"#888")
                     ).pack(side="left", padx=(0,8))
            tk.Label(row, text=f"{rtype}:  {n}  (avg {avg:,} px²)",
                     font=("Helvetica", 9), bg=C["panel"],
                     fg=C["text"], anchor="w").pack(side="left")
        tk.Button(win, text="Close", command=win.destroy,
                  font=("Helvetica", 9), relief="flat",
                  bg=C["accent_lt"], fg=C["accent"],
                  padx=12, pady=4).pack(pady=(10,14))

    # ------------------------------------------------------------------------
    #  Room preview
    # ------------------------------------------------------------------------

    def _show_room_preview(self, label):
        from config import (A_SIZES, B_SIZES, C_SIZES, D_SIZES,
                            T1_SIZES, T2_SIZES, LIB_SIZES, RR_SIZES)
        size_map = {
            "BedroomA": A_SIZES, "BedroomB": B_SIZES,
            "BedroomC": C_SIZES, "BedroomD": D_SIZES,
            "TeaRoom1": T1_SIZES, "TeaRoom2": T2_SIZES,
            "Library":  LIB_SIZES, "ReadingRoom": RR_SIZES,
        }
        rw, rh = size_map[label][0]
        self._room_preview = (label, rw, rh)
        self._renderer.draw_preview(label, rw, rh)

    def _exit_room_preview(self):
        if self._room_preview:
            self._room_preview = None
            self._redraw()

    # ------------------------------------------------------------------------
    #  Library drag-to-canvas
    # ------------------------------------------------------------------------

    # ── ghost-window helpers ─────────────────────────────────────────────────

    def _start_drag_ghost(self, x_root, y_root, gw, gh, color, label):
        """Spawn a small floating Toplevel that follows the cursor."""
        try:
            ghost = tk.Toplevel(self.root)
            ghost.overrideredirect(True)
            ghost.attributes("-topmost", True)
            ghost.attributes("-alpha", 0.70)
            ghost.geometry(f"{gw}x{gh}+{x_root - gw//2}+{y_root - gh//2}")
            frame = tk.Frame(ghost, bg=color, highlightthickness=1,
                             highlightbackground="#888888")
            frame.pack(fill="both", expand=True)
            short = label[:3] if len(label) > 3 else label
            tk.Label(frame, text=short, bg=color, fg="#333333",
                     font=("Helvetica", 7)).pack(expand=True)
            self._ghost_window = ghost
            self._ghost_gw = gw
            self._ghost_gh = gh
        except Exception:
            self._ghost_window = None

    def _move_drag_ghost(self, x_root, y_root):
        if self._ghost_window:
            try:
                gw = getattr(self, "_ghost_gw", 60)
                gh = getattr(self, "_ghost_gh", 36)
                self._ghost_window.geometry(
                    f"+{x_root - gw//2}+{y_root - gh//2}")
            except Exception:
                pass

    def _destroy_drag_ghost(self):
        if self._ghost_window:
            try:
                self._ghost_window.destroy()
            except Exception:
                pass
            self._ghost_window = None

    # ── library drag (room types) ─────────────────────────────────────────────

    def _library_press(self, event, label: str):
        """Record press; show ghost window. Room is created when cursor enters canvas."""
        self._library_press_root = (event.x_root, event.y_root)
        self._library_drag_label = label
        self.mode.set("drag")
        self._on_mode_change()
        from config import (A_SIZES, B_SIZES, C_SIZES, D_SIZES,
                            T1_SIZES, T2_SIZES, LIB_SIZES, RR_SIZES)
        size_map = {
            "BedroomA": A_SIZES, "BedroomB": B_SIZES,
            "BedroomC": C_SIZES, "BedroomD": D_SIZES,
            "TeaRoom1": T1_SIZES, "TeaRoom2": T2_SIZES,
            "Library":  LIB_SIZES, "ReadingRoom": RR_SIZES,
        }
        rw, rh = size_map[label][0]
        self._library_drag_size = (rw, rh)
        self._spawning_room = None
        color = ROOM_COLORS.get(label, "#EBF3FB")
        gw = min(80, max(40, rw // 2))
        gh = min(50, max(25, rh // 2))
        self._start_drag_ghost(event.x_root, event.y_root, gw, gh, color, label)

    def _library_drag(self, event):
        self._move_drag_ghost(event.x_root, event.y_root)
        cx = self._canvas.winfo_rootx()
        cy = self._canvas.winfo_rooty()
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        mx = event.x_root - cx
        my = event.y_root - cy
        rw, rh = self._library_drag_size
        label = self._library_drag_label
        if 0 <= mx <= cw and 0 <= my <= ch:
            if self._spawning_room is None:
                # Cursor just entered canvas — create the room here
                sx = self._snapped(mx - rw / 2)
                sy = self._snapped(my - rh / 2)
                room = ROOM_CLASSES[label](sx, sy, rw, rh)
                room.pinned = True          # library-placed rooms are pinned
                self._spawning_room = room
                self._push_undo()
                self.hotel.add_room(room)
                self.selected_room = room
                self._drag_start = (room, mx, my)
            else:
                room, ox, oy = self._drag_start
                dx = self._snapped(mx - ox)
                dy = self._snapped(my - oy)
                room.move(dx, dy)
                self._drag_start = (room, mx, my)
            self._redraw()

    def _library_release(self, event):
        self._destroy_drag_ghost()
        label = getattr(self, "_library_drag_label", None)

        # Detect click (barely moved) regardless of whether room was spawned.
        # The cursor may never have crossed into the canvas, so _spawning_room
        # can still be None on a plain click.
        if self._library_press_root and label:
            px, py = self._library_press_root
            dist = math.hypot(event.x_root - px, event.y_root - py)
            if dist < 5:
                # plain click → undo any partially-spawned room, show preview
                if self._spawning_room:
                    self.hotel.remove_room(self._spawning_room)
                    if self._undo_stack:
                        self._undo_stack.pop()
                self._spawning_room = None
                self._drag_start = None
                self._library_press_root = None
                self._show_room_preview(label)
                return

        if self._spawning_room:
            self._clamp_to_site(self._spawning_room)
            self._update_metrics()
        self._spawning_room = None
        self._drag_start = None
        self._library_press_root = None
        self._redraw()

    # ── furniture library drag ─────────────────────────────────────────────────

    def _flib_press(self, event, fname: str, finfo: dict):
        """Press on a furniture item in the library — show ghost, start tracking."""
        self._library_press_root = (event.x_root, event.y_root)
        self._flib_name = fname
        self._flib_size = (finfo["w"], finfo["h"])
        self._flib_hover_room = None
        color = FURNITURE_COLORS.get(fname, "#D4C5A9")
        gw = min(70, max(36, finfo["w"]))
        gh = min(50, max(24, finfo["h"]))
        self._start_drag_ghost(event.x_root, event.y_root, gw, gh, color, fname)

    def _flib_drag(self, event):
        """Move ghost; track which room the cursor is hovering over."""
        self._move_drag_ghost(event.x_root, event.y_root)
        cx = self._canvas.winfo_rootx()
        cy = self._canvas.winfo_rooty()
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        mx = event.x_root - cx
        my = event.y_root - cy
        if 0 <= mx <= cw and 0 <= my <= ch:
            hover = self.hotel.room_at(int(mx), int(my))
        else:
            hover = None
        if hover is not self._flib_hover_room:
            self._flib_hover_room = hover
            self._redraw()

    def _flib_release(self, event):
        """Drop furniture into the hovered room, or discard if not over a room."""
        self._destroy_drag_ghost()
        hover_room = self._flib_hover_room
        self._flib_hover_room = None

        # Detect plain click (barely moved) — do nothing
        if self._library_press_root:
            px, py = self._library_press_root
            if math.hypot(event.x_root - px, event.y_root - py) < 5:
                self._library_press_root = None
                self._redraw()
                return

        # Find drop target
        cx = self._canvas.winfo_rootx()
        cy = self._canvas.winfo_rooty()
        mx = event.x_root - cx
        my = event.y_root - cy
        target = hover_room or self.hotel.room_at(int(mx), int(my))

        if target is not None:
            fw, fh = self._flib_size
            # Clamp furniture size to room if room is very small
            fw = min(fw, target.w)
            fh = min(fh, target.h)
            # Room-relative position centred on cursor
            rx = max(0, min(int(mx) - target.x - fw // 2, target.w - fw))
            ry = max(0, min(int(my) - target.y - fh // 2, target.h - fh))
            self._push_undo()
            item = {"type": self._flib_name, "x": rx, "y": ry, "w": fw, "h": fh}
            target.furniture.append(item)
            self._sel_furn    = (target, len(target.furniture) - 1)
            self.selected_room = target
            self._update_sel_label()

        self._library_press_root = None
        self._redraw()

    # ------------------------------------------------------------------------
    #  Canvas mouse handlers
    # ------------------------------------------------------------------------

    def _on_click(self, event):
        # Give the canvas keyboard focus so single-key shortcuts work
        self._canvas.focus_set()
        mx, my = event.x, event.y
        mode   = self.mode.get()

        # Exit room preview on any canvas click
        if self._room_preview:
            self._exit_room_preview()
            return

        # ── Corner resize handles (check selected-item handles first) ─────────
        # Furniture handles
        if self._sel_furn is not None:
            sel_room, sel_idx = self._sel_furn
            if sel_room in self.hotel.rooms and \
                    0 <= sel_idx < len(sel_room.furniture):
                fi = sel_room.furniture[sel_idx]
                ax = sel_room.x + fi["x"]
                ay = sel_room.y + fi["y"]
                corner = self._nearest_corner(mx, my, ax, ay, fi["w"], fi["h"])
                if corner:
                    self._push_undo()
                    self._resize_start = ("furn", sel_room, sel_idx, corner,
                                          ax, ay, fi["w"], fi["h"], mx, my)
                    return

        # Landscape handles (bench / path)
        if 0 <= self.selected_landscape < len(self.landscape_items):
            li = self.landscape_items[self.selected_landscape]
            corner = self._nearest_corner(mx, my,
                                          li["x"], li["y"], li["w"], li["h"])
            if corner:
                self._push_undo()
                self._resize_start = ("landscape", self.selected_landscape,
                                      corner,
                                      li["x"], li["y"], li["w"], li["h"],
                                      mx, my)
                return

        # Bush handles (4 corners of bounding box)
        if 0 <= self.selected_bush < len(self.bushes):
            bx, by, br = self.bushes[self.selected_bush]
            corner = self._nearest_corner(mx, my, bx-br, by-br, 2*br, 2*br)
            if corner:
                self._push_undo()
                self._resize_start = ("bush", self.selected_bush, corner,
                                      bx-br, by-br, 2*br, 2*br, mx, my)
                return

        # Room handles
        if self.selected_room and mode in ("random", "drag"):
            r = self.selected_room
            corner = self._nearest_corner(mx, my, r.x, r.y, r.w, r.h)
            if corner:
                self._push_undo()
                self._resize_start = ("room", r, corner,
                                      r.x, r.y, r.w, r.h, mx, my)
                return

        # ── Body hit-tests (select & start drag) ─────────────────────────────
        # Furniture (check each room's furniture list, top room first)
        for room in reversed(self.hotel.rooms):
            for i in range(len(room.furniture) - 1, -1, -1):
                fi = room.furniture[i]
                ax = room.x + fi["x"]
                ay = room.y + fi["y"]
                if ax <= mx <= ax + fi["w"] and ay <= my <= ay + fi["h"]:
                    self._push_undo()
                    self._sel_furn          = (room, i)
                    self.selected_room      = None
                    self.selected_landscape = -1
                    self.selected_bush      = -1
                    self._furn_drag_start   = (room, i, mx, my)
                    self._update_sel_label()
                    self._redraw()
                    return

        # Landscape items (bench / path)
        for i in range(len(self.landscape_items) - 1, -1, -1):
            li = self.landscape_items[i]
            if (li["x"] <= mx <= li["x"]+li["w"] and
                    li["y"] <= my <= li["y"]+li["h"]):
                self._push_undo()
                self.selected_landscape    = i
                self._sel_furn             = None
                self.selected_room         = None
                self.selected_bush         = -1
                self._landscape_drag_start = (i, mx, my)
                self._update_sel_label()
                self._redraw()
                return

        # Bushes (trees)
        for i, (bx, by, br) in enumerate(self.bushes):
            if math.hypot(mx - bx, my - by) <= br:
                self.selected_bush         = i
                self._sel_furn             = None
                self.selected_room         = None
                self.selected_landscape    = -1
                self._bush_drag_start      = (i, mx, my)
                self._update_sel_label()
                self._redraw()
                return

        # Deselect landscape / bush / furniture if nothing above was hit
        self._sel_furn          = None
        self.selected_landscape = -1
        self.selected_bush      = -1

        if mode in ("random", "drag"):
            hit = self._renderer.hit_test(mx, my, self.hotel)
            if hit is not self.selected_room:
                self.selected_room = hit
                self._update_sel_label()
            if hit:
                self._push_undo()
                self._drag_start = (hit, mx, my)
            else:
                self._drag_start = None
            self._redraw()

        elif mode == "zone":
            self._zone_start = (mx, my)

        elif mode in ("bench", "path"):
            self._path_start = (mx, my)

    def _on_drag(self, event):
        mx, my = event.x, event.y
        mode   = self.mode.get()

        # Furniture drag (per-room, room-relative coordinates)
        if self._furn_drag_start is not None:
            room_ref, idx, ox, oy = self._furn_drag_start
            if room_ref in self.hotel.rooms and \
                    0 <= idx < len(room_ref.furniture):
                fi = room_ref.furniture[idx]
                dx = self._snapped(mx - ox)
                dy = self._snapped(my - oy)
                fi["x"] = max(0, min(fi["x"] + dx, room_ref.w - fi["w"]))
                fi["y"] = max(0, min(fi["y"] + dy, room_ref.h - fi["h"]))
                self._furn_drag_start = (room_ref, idx, mx, my)
                self._update_sel_label()
                self._redraw()
            return

        # Landscape item drag (bench / path)
        if self._landscape_drag_start is not None:
            idx, ox, oy = self._landscape_drag_start
            if 0 <= idx < len(self.landscape_items):
                li = self.landscape_items[idx]
                li["x"] += self._snapped(mx - ox)
                li["y"] += self._snapped(my - oy)
                self._landscape_drag_start = (idx, mx, my)
                self._update_sel_label()
                self._redraw()
            return

        # Bush (tree) drag
        if self._bush_drag_start is not None:
            idx, ox, oy = self._bush_drag_start
            if 0 <= idx < len(self.bushes):
                bx, by, br = self.bushes[idx]
                self.bushes[idx] = (bx + mx - ox, by + my - oy, br)
                self._bush_drag_start = (idx, mx, my)
                self._redraw()
            return

        # Corner resize (all item types)
        if self._resize_start:
            rs = self._resize_start
            kind = rs[0]
            if kind == "room":
                _, room, corner, ox, oy, ow, oh, mx0, my0 = rs
                nx, ny, nw, nh = self._apply_corner_resize(
                    room, corner, (ox, oy, ow, oh, mx0, my0), mx, my)
                room.x, room.y, room.w, room.h = nx, ny, nw, nh
            elif kind == "furn":
                _, room_ref, fidx, corner, ox, oy, ow, oh, mx0, my0 = rs
                if room_ref in self.hotel.rooms and \
                        0 <= fidx < len(room_ref.furniture):
                    fi = room_ref.furniture[fidx]
                    nx, ny, nw, nh = self._apply_corner_resize(
                        None, corner, (ox, oy, ow, oh, mx0, my0), mx, my)
                    # Convert absolute → room-relative, clamp within room
                    fi["x"] = max(0, min(nx - room_ref.x, room_ref.w - nw))
                    fi["y"] = max(0, min(ny - room_ref.y, room_ref.h - nh))
                    fi["w"] = nw
                    fi["h"] = nh
            elif kind == "landscape":
                _, lidx, corner, ox, oy, ow, oh, mx0, my0 = rs
                if 0 <= lidx < len(self.landscape_items):
                    li = self.landscape_items[lidx]
                    nx, ny, nw, nh = self._apply_corner_resize(
                        None, corner, (ox, oy, ow, oh, mx0, my0), mx, my)
                    li["x"], li["y"], li["w"], li["h"] = nx, ny, nw, nh
                    if li["type"] == "bench":
                        li["orient"] = "h" if nw >= nh else "v"
            elif kind == "bush":
                _, bidx, corner, ox, oy, ow, oh, mx0, my0 = rs
                if 0 <= bidx < len(self.bushes):
                    nx, ny, nw, nh = self._apply_corner_resize(
                        None, corner, (ox, oy, ow, oh, mx0, my0), mx, my)
                    new_br = max(8, (nw + nh) // 4)
                    self.bushes[bidx] = (nx + nw//2, ny + nh//2, new_br)
            self._update_sel_label()
            self._redraw()
            return

        if mode in ("random","drag") and self._drag_start:
            room, ox, oy = self._drag_start
            dx = self._snapped(mx - ox)
            dy = self._snapped(my - oy)
            room.move(dx, dy)
            self._clamp_to_site(room)
            self._drag_start = (room, mx, my)
            self._update_sel_label()
            self._redraw()

        elif mode == "zone" and self._zone_start:
            from geometry_utils import rect_from_two_points
            sx, sy = self._zone_start
            self._zone_rects_preview = [rect_from_two_points(sx, sy, mx, my)]
            self._redraw()
            # draw live preview rect
            cv = self._canvas
            if self._preview_id:
                cv.delete(self._preview_id)
            x0,y0,x1,y1 = min(sx,mx),min(sy,my),max(sx,mx),max(sy,my)
            self._preview_id = cv.create_rectangle(
                x0,y0,x1,y1, outline="#BA7517", fill="#FFF3CD",
                dash=(5,3), width=1, stipple="gray25")

        elif mode in ("bench","path") and self._path_start:
            cv = self._canvas
            if self._preview_id:
                cv.delete(self._preview_id)
            sx, sy = self._path_start
            x0,y0,x1,y1 = min(sx,mx),min(sy,my),max(sx,mx),max(sy,my)
            col = C["bench"] if mode=="bench" else C["path"]
            self._preview_id = cv.create_rectangle(
                x0,y0,x1,y1, outline=col, fill=col, dash=(4,3), width=1)

    def _on_release(self, event):
        mx, my = event.x, event.y
        mode   = self.mode.get()

        sx, sy, sw, sh = self._site()

        # Furniture drag finalise (coordinates already clamped during drag)
        if self._furn_drag_start is not None:
            self._furn_drag_start = None
            self._update_sel_label()
            self._redraw()
            return

        # Landscape drag finalise
        if self._landscape_drag_start is not None:
            idx = self._landscape_drag_start[0]
            if 0 <= idx < len(self.landscape_items):
                li = self.landscape_items[idx]
                li["x"] = max(sx, min(li["x"], sx + sw - li["w"]))
                li["y"] = max(sy, min(li["y"], sy + sh - li["h"]))
            self._landscape_drag_start = None
            self._update_sel_label()
            self._redraw()
            return

        # Bush drag finalise
        if self._bush_drag_start is not None:
            self._bush_drag_start = None
            self._redraw()
            return

        if self._preview_id:
            self._canvas.delete(self._preview_id)
            self._preview_id = None

        if self._resize_start:
            self._resize_start = None
            self._update_metrics()
            self._redraw()
            return

        if mode in ("bench","path") and self._path_start:
            sx, sy = self._path_start
            x0 = self._snapped(min(sx,mx)); y0 = self._snapped(min(sy,my))
            x1 = self._snapped(max(sx,mx)); y1 = self._snapped(max(sy,my))
            w = x1-x0; h = y1-y0
            if w > 8 and h > 8:
                if mode == "path":
                    self.landscape_items.append(
                        {"type":"path","x":x0,"y":y0,"w":w,"h":h})
                else:
                    orient = "h" if w >= h else "v"
                    self.landscape_items.append(
                        {"type":"bench","x":x0,"y":y0,"w":w,"h":h,
                         "orient":orient})
            self._path_start = None

        elif mode == "zone" and self._zone_start:
            from geometry_utils import rect_from_two_points
            sx, sy = self._zone_start
            x0 = self._snapped(min(sx,mx)); y0 = self._snapped(min(sy,my))
            x1 = self._snapped(max(sx,mx)); y1 = self._snapped(max(sy,my))
            w = x1-x0; h = y1-y0
            if w > 20 and h > 20:
                self._zone_rects.append(
                    rect_from_two_points(x0,y0,x1,y1))
            self._zone_start = None

        self._drag_start = None
        self._redraw()

    def _delete_selected(self, event=None):
        if self._sel_furn is not None:
            room_ref, idx = self._sel_furn
            if room_ref in self.hotel.rooms and \
                    0 <= idx < len(room_ref.furniture):
                self._push_undo()
                room_ref.furniture.pop(idx)
            self._sel_furn = None
            self._update_sel_label()
            self._redraw()
            return
        if 0 <= self.selected_landscape < len(self.landscape_items):
            self._push_undo()
            self.landscape_items.pop(self.selected_landscape)
            self.selected_landscape = -1
            self._update_sel_label()
            self._redraw()
            return
        if 0 <= self.selected_bush < len(self.bushes):
            self._push_undo()
            self.bushes.pop(self.selected_bush)
            self.selected_bush = -1
            self._update_sel_label()
            self._redraw()
            return
        if self.selected_room:
            self._push_undo()
            self.hotel.remove_room(self.selected_room)
            self.selected_room = None
            self._update_sel_label()
            self._update_metrics()
            self._redraw()

    def _reset_room_furniture(self):
        """Clear all furniture from the currently referenced room."""
        room = None
        if self._sel_furn is not None:
            room = self._sel_furn[0]
        elif self.selected_room:
            room = self.selected_room
        if room and room in self.hotel.rooms and room.furniture:
            self._push_undo()
            room.furniture.clear()
            self._sel_furn = None
            self._update_sel_label()
            self._redraw()

    def _on_right_click(self, event):
        """Right-click on a room toggles its pinned state."""
        mx, my = event.x, event.y
        hit = self._renderer.hit_test(mx, my, self.hotel)
        if hit:
            self._push_undo()
            hit.pinned = not hit.pinned
            self.selected_room = hit
            self._update_sel_label()
            self._redraw()

    # ------------------------------------------------------------------------
    #  Toolbar callbacks
    # ------------------------------------------------------------------------

    def _on_mode_change(self):
        self._zone_start          = None
        self._path_start          = None
        self._drag_start          = None
        self._resize_start        = None
        self._landscape_drag_start = None
        self._bush_drag_start     = None
        self._furn_drag_start     = None
        self._flib_hover_room     = None
        # don't clear zone_rects when leaving zone mode - user keeps them
        cursors = {"random":"fleur","drag":"hand2","zone":"crosshair",
                   "bench":"crosshair","path":"crosshair","llm":"arrow"}
        self._canvas.config(cursor=cursors.get(self.mode.get(),"crosshair"))
        self._refresh_mode_btns()
        self._redraw()

    def _refresh_mode_btns(self):
        """Update mode button highlight to match self.mode."""
        if not hasattr(self, "_mode_btns"):
            return
        cur = self.mode.get()
        for val, (row, ind, lbl) in self._mode_btns.items():
            if val == cur:
                row.config(bg=C["accent_lt"])
                ind.config(bg=C["accent"])
                lbl.config(bg=C["accent_lt"], fg=C["accent"])
            else:
                row.config(bg=C["panel"])
                ind.config(bg=C["panel"])
                lbl.config(bg=C["panel"], fg=C["text_dim"])

    def _toggle_snap(self):
        self._snap_on = not self._snap_on
        self._snap_lbl.config(
            text="⌗  Snap  ✓" if self._snap_on else "⌗  Snap",
            fg=C["accent"] if self._snap_on else C["tb_dim"])

    def _update_weights(self):
        # Don't override weights if LLM just set them
        if getattr(self, "_llm_weights_active", False):
            return
        bias = self._bed_bias_var.get()/100.0; pub = 1.0-bias
        bs = bias/4; ps = pub/4
        self.weights = {
            "BedroomA":bs,"BedroomB":bs,"BedroomC":bs,"BedroomD":bs,
            "TeaRoom1":ps,"TeaRoom2":ps,"Library":ps,"ReadingRoom":ps,
        }

    def _clear_landscape(self):
        self.landscape_items = []
        self._redraw()

    def _edit_seed(self):
        val = simpledialog.askinteger(
            "Set Seed", "Enter a seed integer:",
            parent=self.root,
            initialvalue=self.seed, minvalue=0, maxvalue=10**9)
        if val is not None:
            self.seed = val
            self._seed_lbl.config(text=f"seed  {self.seed}")
            self._run_packing()

    # ------------------------------------------------------------------------
    #  Save / Load
    # ------------------------------------------------------------------------

    def _save_layout(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("Hotel layout", "*.json"), ("All files", "*.*")],
            title="Save layout")
        if not path:
            return
        data = {
            "seed":            self.seed,
            "hotel":           self.hotel.to_dict(),  # furniture embedded per-room
            "landscape_items": self.landscape_items,
            "zone_rects":      self._zone_rects,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        messagebox.showinfo("Saved", f"Layout saved to:\n{path}")

    def _load_layout(self):
        path = filedialog.askopenfilename(
            filetypes=[("Hotel layout", "*.json"), ("All files", "*.*")],
            title="Load layout")
        if not path:
            return
        try:
            with open(path) as f:
                data = json.load(f)
            self._push_undo()
            self.seed = data.get("seed", self.seed)
            self._seed_lbl.config(text=f"seed  {self.seed}")
            self.hotel            = Hotel.from_dict(data["hotel"])
            self.landscape_items  = data.get("landscape_items", [])
            self._zone_rects      = data.get("zone_rects", [])
            self.selected_room    = None
            self._sel_furn        = None
            self._update_sel_label()
            self._update_metrics()
            if self._show_bushes.get():
                self.bushes = pack_bushes(self._site(), self.hotel,
                                          seed=self.seed)
            self._redraw()
        except Exception as e:
            messagebox.showerror("Load Error", str(e))

    # ------------------------------------------------------------------------
    #  Export PNG
    # ------------------------------------------------------------------------

    def _export_png(self):
        try:
            from PIL import ImageGrab
            import datetime
            default = f"hotel_plan_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
            path = filedialog.asksaveasfilename(
                defaultextension=".png",
                initialfile=default,
                filetypes=[("PNG image","*.png"),("All files","*.*")],
                title="Export PNG")
            if not path:
                return
            x = self._canvas.winfo_rootx()
            y = self._canvas.winfo_rooty()
            w = self._canvas.winfo_width()
            h = self._canvas.winfo_height()
            ImageGrab.grab(bbox=(x,y,x+w,y+h)).save(path)
            messagebox.showinfo("Exported", f"Saved as:\n{path}")
        except ImportError:
            messagebox.showwarning("Export","Run: pip install pillow")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))
