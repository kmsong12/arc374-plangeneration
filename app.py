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
)
from hotel import Hotel
from packing import pack_rooms_into_hotel, pack_bushes
from canvas_renderer import CanvasRenderer
from geometry_utils import snap_to_grid, clamp
from rooms import ROOM_CLASSES
from llm_bridge import prompt_to_settings

# ── palette ───────────────────────────────────────────────────
C = {
    "bg":        "#F0EDE5",
    "panel":     "#FAFAF6",
    "panel_bdr": "#D8D5CC",
    "toolbar":   "#FFFFFF",
    "accent":    "#2D6A9F",
    "accent_lt": "#EBF3FB",
    "text":      "#2C2C2A",
    "text_dim":  "#888880",
    "sep":       "#E2DFD7",
    "warn_bg":   "#FFF8E1",
    "warn_fg":   "#8A6800",
    "metric_bg": "#F5F2EA",
    "bench":     "#9C8462",
    "path":      "#D4CCBA",
    "handle":    "#E85D24",
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

        # ── interaction state ──
        self.selected_room         = None
        self._drag_start           = None   # (room, mx, my) for move
        self._resize_start         = None   # (room, orig_w, orig_h, mx, my)
        self._zone_start           = None
        self._path_start           = None
        self._preview_id           = None
        self._spawning_room        = None   # room being dragged from library
        self._snap_on              = True
        self._bush_drag            = None   # (index, ox, oy)
        self._library_press_root   = None   # (x_root, y_root) for click vs drag
        self._room_preview         = None   # (label, rw, rh) while previewing

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

        # toolbar 
        tb = tk.Frame(root, bg=C["toolbar"], height=TOOLBAR_H,
                      highlightthickness=1, highlightbackground=C["sep"])
        tb.pack(side="top", fill="x")
        tb.pack_propagate(False)

        def _btn(text, cmd, primary=False, parent=tb):
            bg = C["accent_lt"] if primary else C["toolbar"]
            fg = C["accent"]    if primary else C["text"]
            b = tk.Label(parent, text=text, bg=bg, fg=fg,
                         font=("Helvetica", 10), padx=10, cursor="hand2")
            b.pack(side="left", padx=2, pady=5, ipady=3)
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>",    lambda e: b.config(bg=C["accent_lt"]))
            b.bind("<Leave>",    lambda e: b.config(bg=bg))
            return b

        _btn("↺  Regenerate", self._generate_manual, primary=True)
        self._vsep(tb)
        _btn("⎌  Undo",       self._undo)
        _btn("⎌  Redo",       self._redo)
        self._vsep(tb)

        # snap toggle
        self._snap_lbl = tk.Label(tb, text="Snap ✓", bg=C["toolbar"],
                                  fg=C["accent"], font=("Helvetica", 9),
                                  padx=8, cursor="hand2")
        self._snap_lbl.pack(side="left", padx=2, pady=5, ipady=3)
        self._snap_lbl.bind("<Button-1>", lambda e: self._toggle_snap())

        self._vsep(tb)
        _btn("Clear landscape", self._clear_landscape)
        self._vsep(tb)
        _btn("💾 Save",  self._save_layout)
        _btn("📂 Load",  self._load_layout)

        # seed label - click to enter specific seed
        tk.Frame(tb, bg=C["toolbar"]).pack(side="left", expand=True)
        self._seed_lbl = tk.Label(tb, text=f"seed  {self.seed}",
                                  bg=C["toolbar"], fg=C["text_dim"],
                                  font=("Courier", 9), cursor="hand2")
        self._seed_lbl.pack(side="left", padx=8)
        self._seed_lbl.bind("<Button-1>", lambda e: self._edit_seed())
        tk.Frame(tb, bg=C["toolbar"]).pack(side="left", expand=True)

        _btn("📷 Export PNG", self._export_png)

        # metrics bar
        mb = tk.Frame(root, bg=C["metric_bg"], height=METRICS_BAR_H,
                      highlightthickness=1, highlightbackground=C["sep"])
        mb.pack(side="bottom", fill="x")
        mb.pack_propagate(False)
        self._m = {}
        for key, label in (("total_rooms","Rooms"),("built_area","Built"),
                            ("open_area","Open"),("density","Density")):
            tk.Label(mb, text=label+":", bg=C["metric_bg"],
                     fg=C["text_dim"], font=("Helvetica", 9)).pack(
                side="left", padx=(12,2))
            v = tk.Label(mb, text="-", bg=C["metric_bg"],
                         fg=C["text"], font=("Helvetica", 9, "bold"))
            v.pack(side="left", padx=(0,10))
            self._m[key] = v
        # breakdown button
        tk.Label(mb, text="▸ breakdown", bg=C["metric_bg"],
                 fg=C["accent"], font=("Helvetica", 9),
                 cursor="hand2").pack(side="right", padx=12)

        # body
        body = tk.Frame(root, bg=C["bg"])
        body.pack(side="top", fill="both", expand=True)
        self._build_left(body)
        self._build_right(body)
        self._build_canvas(body)

        # bind breakdown click
        for w in mb.winfo_children():
            if isinstance(w, tk.Label) and "breakdown" in str(w.cget("text")):
                w.bind("<Button-1>", lambda e: self._show_breakdown())

    # left sidebar --------------------------------------------------------

    def _build_left(self, parent):
        f = tk.Frame(parent, bg=C["panel"], width=SIDEBAR_LEFT_W,
                     highlightthickness=1, highlightbackground=C["panel_bdr"])
        f.pack(side="left", fill="y")
        f.pack_propagate(False)

        self._sec(f, "MODE")
        for val, label in MODES:
            tk.Radiobutton(f, text=label, variable=self.mode, value=val,
                           command=self._on_mode_change,
                           bg=C["panel"], activebackground=C["accent_lt"],
                           selectcolor=C["accent_lt"],
                           fg=C["text"], font=("Helvetica", 10),
                           anchor="w", cursor="hand2").pack(
                fill="x", padx=12, pady=1)

        # zone pack button - only useful in zone mode
        self._zone_btn = tk.Label(f, text="  Pack into zones  →",
                                  bg=C["accent_lt"], fg=C["accent"],
                                  font=("Helvetica", 9), cursor="hand2",
                                  padx=6, pady=4)
        self._zone_btn.pack(fill="x", padx=12, pady=(4,0))
        self._zone_btn.bind("<Button-1>", lambda e: self._pack_zones())

        self._hsep(f)
        self._sec(f, "ROOM LIBRARY  (drag to place)")
        for lbl, col in ROOM_COLORS.items():
            row = tk.Frame(f, bg=C["panel"], cursor="hand2")
            row.pack(fill="x", padx=12, pady=2)
            chip = tk.Frame(row, bg=col, width=20, height=12,
                            highlightthickness=1,
                            highlightbackground=ROOM_BORDERS[lbl],
                            cursor="hand2")
            chip.pack(side="left", padx=(0,7))
            name_lbl = tk.Label(row, text=lbl, font=("Helvetica", 9),
                                bg=C["panel"], fg=C["text"], cursor="hand2")
            name_lbl.pack(side="left")
            # bind both chip and label for drag-to-canvas
            for w in (chip, name_lbl, row):
                w.bind("<ButtonPress-1>",
                       lambda e, l=lbl: self._library_press(e, l))
                w.bind("<B1-Motion>",   self._library_drag)
                w.bind("<ButtonRelease-1>", self._library_release)

        self._hsep(f)
        self._sec(f, "LANDSCAPE  (Bench / Path modes)")
        for chip_lbl, chip_col in (("Bench", C["bench"]),("Path", C["path"])):
            row = tk.Frame(f, bg=C["panel"])
            row.pack(fill="x", padx=12, pady=2)
            tk.Frame(row, bg=chip_col, width=20, height=12,
                     highlightthickness=1,
                     highlightbackground="#888").pack(side="left", padx=(0,7))
            tk.Label(row, text=chip_lbl, font=("Helvetica", 9),
                     bg=C["panel"], fg=C["text_dim"]).pack(side="left")

    # right sidebar -----------------------------------------------

    def _build_right(self, parent):
        f = tk.Frame(parent, bg=C["panel"], width=SIDEBAR_RIGHT_W,
                     highlightthickness=1, highlightbackground=C["panel_bdr"])
        f.pack(side="right", fill="y")
        f.pack_propagate(False)

        inn = tk.Frame(f, bg=C["panel"])
        inn.pack(fill="both", expand=True, padx=10, pady=10)

        self._sec(inn, "PARAMETERS")
        self._n_rooms_var  = tk.IntVar(value=10)
        self._pad_var      = tk.IntVar(value=30)
        self._bed_bias_var = tk.IntVar(value=50)
        self._margin_var   = tk.IntVar(value=SITE_MARGIN)

        self._slider(inn, "Room count",       self._n_rooms_var,  2, 24, 1)
        self._slider(inn, "Padding (px)",     self._pad_var,      0, 80, 5)
        self._slider(inn, "Bedroom bias (%)", self._bed_bias_var, 0, 100, 5,
                     cb=self._update_weights)
        self._slider(inn, "Site margin (px)", self._margin_var,   20, 120, 5)

        tk.Label(inn, text="Room filter", font=("Helvetica", 9),
                 bg=C["panel"], fg=C["text_dim"], anchor="w").pack(
            fill="x", pady=(8,2))
        self._constraint_var = tk.StringVar(value=CONSTRAINT_OPTIONS[0])
        ttk.Combobox(inn, textvariable=self._constraint_var,
                     values=CONSTRAINT_OPTIONS, state="readonly",
                     font=("Helvetica", 9)).pack(fill="x")

        self._hsep(inn)
        self._sec(inn, "DISPLAY")
        for text, var in (("Grid",         self._show_grid),
                           ("Room labels", self._show_labels),
                           ("Bushes",      self._show_bushes)):
            tk.Checkbutton(inn, text=text, variable=var,
                           command=self._redraw,
                           font=("Helvetica", 9), bg=C["panel"],
                           activebackground=C["panel"],
                           fg=C["text"], anchor="w",
                           cursor="hand2").pack(fill="x", pady=1)

        self._hsep(inn)

        # LLM section
        hdr = tk.Frame(inn, bg=C["panel"])
        hdr.pack(fill="x", pady=(0,4))
        tk.Label(hdr, text="LLM PROMPT", font=("Helvetica", 8, "bold"),
                 bg=C["panel"], fg=C["text_dim"]).pack(side="left")
        tk.Label(hdr, text=" beta", font=("Helvetica", 7),
                 bg=C["warn_bg"], fg=C["warn_fg"],
                 padx=3).pack(side="left", padx=4)

        self._llm_txt = tk.Text(inn, height=4, font=("Helvetica", 9),
                                relief="flat", bg="#F5F3EC", fg=C["text"],
                                highlightthickness=1,
                                highlightbackground=C["sep"],
                                wrap="word", bd=0)
        self._llm_txt.pack(fill="x", pady=(0,4))
        self._llm_txt.insert("end",
            "e.g. More bedrooms in the north, tea room near entrance")

        self._llm_btn = tk.Label(inn, text="Generate with prompt  ↗",
                                 bg=C["accent_lt"], fg=C["accent"],
                                 font=("Helvetica", 9), padx=8, pady=5,
                                 cursor="hand2")
        self._llm_btn.pack(fill="x")
        self._llm_btn.bind("<Button-1>", lambda e: self._llm_generate())

        # LLM status label (hidden until a call is in flight)
        self._llm_status = tk.Label(inn, text="", font=("Helvetica", 8),
                                    bg=C["panel"], fg=C["accent"])
        self._llm_status.pack(fill="x", pady=(2,0))

        self._hsep(inn)
        # Selected-room info
        self._sec(inn, "SELECTED ROOM")
        self._sel_lbl = tk.Label(inn, text="None", font=("Helvetica", 9),
                                 bg=C["panel"], fg=C["text_dim"], anchor="w")
        self._sel_lbl.pack(fill="x")

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

    def _handle_pos(self, room):
        """Bottom-right corner of selected room."""
        return room.x + room.w, room.y + room.h

    def _near_handle(self, mx, my, room) -> bool:
        hx, hy = self._handle_pos(room)
        return abs(mx-hx) <= HANDLE_R+4 and abs(my-hy) <= HANDLE_R+4

    def _clamp_to_site(self, room):
        """Push room back inside site boundaries."""
        sx, sy, sw, sh = self._site()
        room.x = clamp(room.x, sx, sx+sw-room.w)
        room.y = clamp(room.y, sy, sy+sh-room.h)

    # ------------------------------------------------------------------------
    #  Undo / Redo
    # ------------------------------------------------------------------------

    def _push_undo(self):
        self._undo_stack.append(self.hotel.snapshot())
        if len(self._undo_stack) > MAX_UNDO:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self, *_):
        if not self._undo_stack:
            return
        self._redo_stack.append(self.hotel.snapshot())
        self.hotel.restore(self._undo_stack.pop())
        self.selected_room = None
        self._update_metrics()
        self._redraw()

    def _redo(self, *_):
        if not self._redo_stack:
            return
        self._undo_stack.append(self.hotel.snapshot())
        self.hotel.restore(self._redo_stack.pop())
        self.selected_room = None
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

        self._push_undo()
        self.hotel = pack_rooms_into_hotel(
            site,
            n_rooms=self._n_rooms_var.get(),
            weights=self.weights,
            seed=self.seed,
            constraint=self._get_constraint(),
            zones=llm_zones,
            zone_weights=llm_zone_weights,
            pad=pad,
        )
        self.bushes = (pack_bushes(site, self.hotel, seed=self.seed, n_bushes=n_bushes)
                       if self._show_bushes.get() else [])
        self.selected_room = None
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
        )
        # draw resize handle if a room is selected
        if self.selected_room:
            hx, hy = self._handle_pos(self.selected_room)
            r = HANDLE_R
            self._canvas.create_oval(
                hx-r, hy-r, hx+r, hy+r,
                fill=C["handle"], outline="white", width=1.5)

    def _update_metrics(self):
        m = self.hotel.compute_metrics(self._site())
        self._m["total_rooms"].config(text=str(m["total_rooms"]))
        self._m["built_area"].config(text=f"{m['built_area']:,} px²")
        self._m["open_area"].config(text=f"{m['open_area']:,} px²")
        self._m["density"].config(text=f"{m['density']}%")

    def _update_sel_label(self):
        if self.selected_room:
            r = self.selected_room
            self._sel_lbl.config(
                text=f"{r.label}\n{r.w}x{r.h} px  @({r.x},{r.y})",
                fg=C["text"])
        else:
            self._sel_lbl.config(text="None", fg=C["text_dim"])

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

    def _library_press(self, event, label: str):
        """Record press position; spawn ghost room for drag-to-canvas."""
        self._library_press_root = (event.x_root, event.y_root)
        self.mode.set("drag")
        self._on_mode_change()
        from config import (A_SIZES,B_SIZES,C_SIZES,D_SIZES,
                            T1_SIZES,T2_SIZES,LIB_SIZES,RR_SIZES)
        size_map = {
            "BedroomA":A_SIZES,"BedroomB":B_SIZES,
            "BedroomC":C_SIZES,"BedroomD":D_SIZES,
            "TeaRoom1":T1_SIZES,"TeaRoom2":T2_SIZES,
            "Library":LIB_SIZES,"ReadingRoom":RR_SIZES,
        }
        rw, rh = size_map[label][0]
        cx = self._canvas.winfo_rootx()
        cy = self._canvas.winfo_rooty()
        mx = event.x_root - cx
        my = event.y_root - cy
        sx, sy = self._snapped(mx - rw/2), self._snapped(my - rh/2)
        room = ROOM_CLASSES[label](sx, sy, rw, rh)
        self._spawning_room = room
        self._push_undo()
        self.hotel.add_room(room)
        self.selected_room = room
        self._drag_start = (room, mx, my)
        self._redraw()

    def _library_drag(self, event):
        if not self._spawning_room:
            return
        cx = self._canvas.winfo_rootx()
        cy = self._canvas.winfo_rooty()
        mx = event.x_root - cx
        my = event.y_root - cy
        room, ox, oy = self._drag_start
        dx = self._snapped(mx - ox)
        dy = self._snapped(my - oy)
        room.move(dx, dy)
        self._drag_start = (room, mx, my)
        self._redraw()

    def _library_release(self, event):
        if self._spawning_room:
            # detect click (barely moved) vs actual drag
            if self._library_press_root:
                px, py = self._library_press_root
                dist = math.hypot(event.x_root - px, event.y_root - py)
                if dist < 5:
                    # treat as a click -> undo the add and show room preview
                    label = self._spawning_room.label
                    self.hotel.remove_room(self._spawning_room)
                    if self._undo_stack:
                        self._undo_stack.pop()
                    self._spawning_room = None
                    self._drag_start = None
                    self._library_press_root = None
                    self._show_room_preview(label)
                    return
            self._clamp_to_site(self._spawning_room)
            self._spawning_room = None
            self._drag_start = None
            self._library_press_root = None
            self._update_metrics()
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

        # Bush drag - works in all modes
        for i, (bx, by, br) in enumerate(self.bushes):
            if math.hypot(mx - bx, my - by) <= br:
                self._bush_drag = (i, mx, my)
                return

        if mode in ("random", "drag"):
            # check resize handle first
            if (self.selected_room and
                    self._near_handle(mx, my, self.selected_room)):
                r = self.selected_room
                self._resize_start = (r, r.w, r.h, mx, my)
                return
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

        # Bush drag - takes priority
        if self._bush_drag is not None:
            i, ox, oy = self._bush_drag
            bx, by, br = self.bushes[i]
            self.bushes[i] = (bx + mx - ox, by + my - oy, br)
            self._bush_drag = (i, mx, my)
            self._redraw()
            return

        # resize takes priority
        if self._resize_start:
            room, ow, oh, ox, oy = self._resize_start
            new_w = max(MIN_ROOM_DIM, self._snapped(ow + (mx - ox)))
            new_h = max(MIN_ROOM_DIM, self._snapped(oh + (my - oy)))
            # clamp to site
            sx, sy, sw, sh = self._site()
            new_w = min(new_w, sx+sw - room.x)
            new_h = min(new_h, sy+sh - room.y)
            room.w = new_w
            room.h = new_h
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

        if self._bush_drag is not None:
            self._bush_drag = None
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
        if self.selected_room:
            self._push_undo()
            self.hotel.remove_room(self.selected_room)
            self.selected_room = None
            self._update_sel_label()
            self._update_metrics()
            self._redraw()

    # ------------------------------------------------------------------------
    #  Toolbar callbacks
    # ------------------------------------------------------------------------

    def _on_mode_change(self):
        self._zone_start   = None
        self._path_start   = None
        self._drag_start   = None
        self._resize_start = None
        # don't clear zone_rects when leaving zone mode - user keeps them
        cursors = {"random":"fleur","drag":"hand2","zone":"crosshair",
                   "bench":"crosshair","path":"crosshair","llm":"arrow"}
        self._canvas.config(cursor=cursors.get(self.mode.get(),"crosshair"))
        self._redraw()

    def _toggle_snap(self):
        self._snap_on = not self._snap_on
        self._snap_lbl.config(
            text="Snap ✓" if self._snap_on else "Snap",
            fg=C["accent"] if self._snap_on else C["text_dim"])

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
            "hotel":           self.hotel.to_dict(),
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
            self.hotel           = Hotel.from_dict(data["hotel"])
            self.landscape_items = data.get("landscape_items", [])
            self._zone_rects     = data.get("zone_rects", [])
            self.selected_room   = None
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
