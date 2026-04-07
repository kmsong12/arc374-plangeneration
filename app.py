"""
app.py – HotelApp: the main Tkinter window and interaction logic.

Layout (left → right):
  ┌─────────────────────────────────────────────────────────────────┐
  │  [toolbar: Regenerate | Grid | Snap | seed label | Export]      │
  ├────────────┬───────────────────────────────────────┬────────────┤
  │ Left panel │         Canvas                        │ Right panel│
  │ (modes +   │  (Tkinter Canvas widget)              │ (sliders + │
  │  library)  │                                       │  LLM box)  │
  ├────────────┴───────────────────────────────────────┴────────────┤
  │  [metrics bar: built area | open area | density | rooms]        │
  └─────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations
import random
import tkinter as tk
from tkinter import ttk, messagebox

from config import (
    CANVAS_W, CANVAS_H,
    SIDEBAR_LEFT_W, SIDEBAR_RIGHT_W, TOOLBAR_H, METRICS_BAR_H,
    SITE_MARGIN, GRID_SIZE, DEFAULT_WEIGHTS,
)
from hotel import Hotel
from packing import pack_rooms_into_hotel, pack_bushes
from canvas_renderer import CanvasRenderer
from llm_bridge import prompt_to_weights


class HotelApp:
    """Top-level application class."""

    # ── Init ──────────────────────────────────────────────────

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Hotel Floor Plan Generator – ARC374")
        root.configure(bg="#F5F4EE")

        # Model state
        self.hotel:   Hotel            = Hotel()
        self.bushes:  list             = []
        self.seed:    int              = random.randint(0, 10 ** 9)
        self.weights: dict             = DEFAULT_WEIGHTS.copy()

        # Interaction state
        self.selected_room             = None
        self._drag_start               = None   # (room, mouse_x, mouse_y)
        self._zone_start               = None   # for zoning drag
        self._zone_rects: list         = []
        self._show_grid:  bool         = True
        self._show_labels: bool        = False
        self._snap_on:    bool         = True

        # Generation mode: "random" | "drag" | "zone" | "llm"
        self.mode = tk.StringVar(value="random")

        self._build_ui()
        self._generate()

    # ── UI Construction ───────────────────────────────────────

    def _build_ui(self):
        root = self.root

        # ── Toolbar (top) ──────────────────────────────────────
        toolbar = tk.Frame(root, bg="#FFFFFF", height=TOOLBAR_H,
                           bd=0, relief="flat")
        toolbar.pack(side="top", fill="x")
        toolbar.pack_propagate(False)

        tk.Button(toolbar, text="↺  Regenerate", command=self._generate,
                  font=("Helvetica", 10), bg="#EBF4FF", fg="#185FA5",
                  relief="flat", padx=10, pady=3,
                  cursor="hand2").pack(side="left", padx=(8, 4), pady=5)

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y",
                                                       padx=4, pady=6)

        self._grid_btn = tk.Button(toolbar, text="Grid ✓", command=self._toggle_grid,
                                   font=("Helvetica", 9), relief="flat", padx=8,
                                   cursor="hand2")
        self._grid_btn.pack(side="left", padx=2, pady=5)

        self._snap_btn = tk.Button(toolbar, text="Snap ✓", command=self._toggle_snap,
                                   font=("Helvetica", 9), relief="flat", padx=8,
                                   cursor="hand2")
        self._snap_btn.pack(side="left", padx=2, pady=5)

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y",
                                                       padx=4, pady=6)

        self._seed_label = tk.Label(toolbar, text=f"Seed: {self.seed}",
                                    font=("Helvetica", 9), bg="#FFFFFF", fg="#888")
        self._seed_label.pack(side="left", padx=6)

        tk.Button(toolbar, text="💾  Export PNG", command=self._export_png,
                  font=("Helvetica", 9), relief="flat", padx=8, pady=3,
                  cursor="hand2").pack(side="right", padx=8, pady=5)

        # ── Metrics bar (bottom) ───────────────────────────────
        self._metrics_bar = tk.Frame(root, bg="#F0EFE7", height=METRICS_BAR_H)
        self._metrics_bar.pack(side="bottom", fill="x")
        self._metrics_bar.pack_propagate(False)
        self._metrics_labels: dict[str, tk.Label] = {}
        for key in ("total_rooms", "built_area", "open_area", "density"):
            lbl = tk.Label(self._metrics_bar, text="—", font=("Helvetica", 9),
                           bg="#F0EFE7", fg="#666")
            lbl.pack(side="left", padx=14)
            self._metrics_labels[key] = lbl

        # ── Body row ───────────────────────────────────────────
        body = tk.Frame(root, bg="#F5F4EE")
        body.pack(side="top", fill="both", expand=True)

        self._build_left_sidebar(body)
        self._build_right_sidebar(body)
        self._build_canvas(body)

    def _build_left_sidebar(self, parent):
        frame = tk.Frame(parent, bg="#FFFFFF", width=SIDEBAR_LEFT_W,
                         bd=0, relief="flat",
                         highlightthickness=1,
                         highlightbackground="#E0DFD5")
        frame.pack(side="left", fill="y")
        frame.pack_propagate(False)

        # Mode section
        tk.Label(frame, text="GENERATION MODE", font=("Helvetica", 8, "bold"),
                 bg="#FFFFFF", fg="#999", anchor="w").pack(
            fill="x", padx=12, pady=(10, 4))

        modes = [
            ("random", "Random / Procedural"),
            ("drag",   "Drag & Drop"),
            ("zone",   "Zoning"),
            ("llm",    "LLM Prompt"),
        ]
        for val, label in modes:
            rb = tk.Radiobutton(frame, text=label, variable=self.mode,
                                value=val, command=self._on_mode_change,
                                font=("Helvetica", 10), bg="#FFFFFF",
                                activebackground="#EBF4FF",
                                selectcolor="#EBF4FF", fg="#333",
                                anchor="w", cursor="hand2")
            rb.pack(fill="x", padx=10, pady=1)

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=8)

        # Room library
        tk.Label(frame, text="ROOM LIBRARY", font=("Helvetica", 8, "bold"),
                 bg="#FFFFFF", fg="#999", anchor="w").pack(
            fill="x", padx=12, pady=(0, 4))

        from config import ROOM_COLORS, ROOM_BORDERS
        for lbl, color in ROOM_COLORS.items():
            row = tk.Frame(frame, bg="#FFFFFF", cursor="fleur")
            row.pack(fill="x", padx=10, pady=2)
            tk.Frame(row, bg=color, width=22, height=14,
                     highlightthickness=1,
                     highlightbackground=ROOM_BORDERS[lbl]).pack(
                side="left", padx=(0, 6))
            tk.Label(row, text=lbl, font=("Helvetica", 9),
                     bg="#FFFFFF", fg="#444").pack(side="left")

    def _build_right_sidebar(self, parent):
        frame = tk.Frame(parent, bg="#FFFFFF", width=SIDEBAR_RIGHT_W,
                         highlightthickness=1, highlightbackground="#E0DFD5")
        frame.pack(side="right", fill="y")
        frame.pack_propagate(False)

        inner = tk.Frame(frame, bg="#FFFFFF")
        inner.pack(fill="both", expand=True, padx=8, pady=8)

        tk.Label(inner, text="PARAMETERS", font=("Helvetica", 8, "bold"),
                 bg="#FFFFFF", fg="#999", anchor="w").pack(fill="x", pady=(0, 6))

        # ── Room count ──────────────────────────────────────────
        self._n_rooms_var = tk.IntVar(value=10)
        self._add_slider(inner, "Room count", self._n_rooms_var, 2, 24, 1)

        # ── Padding ─────────────────────────────────────────────
        self._pad_var = tk.IntVar(value=30)
        self._add_slider(inner, "Padding (px)", self._pad_var, 0, 80, 5)

        # ── Bedroom bias ────────────────────────────────────────
        self._bed_bias_var = tk.IntVar(value=50)
        self._add_slider(inner, "Bedroom bias (%)", self._bed_bias_var, 0, 100, 5,
                         callback=self._update_weights_from_sliders)

        # ── Site margin ─────────────────────────────────────────
        self._margin_var = tk.IntVar(value=SITE_MARGIN)
        self._add_slider(inner, "Site margin (px)", self._margin_var, 20, 120, 5)

        # ── Room constraint ─────────────────────────────────────
        tk.Label(inner, text="Room filter", font=("Helvetica", 9),
                 bg="#FFFFFF", fg="#666", anchor="w").pack(fill="x", pady=(8, 2))
        self._constraint_var = tk.StringVar(value="All rooms")
        constraint_cb = ttk.Combobox(inner, textvariable=self._constraint_var,
                                     values=["All rooms", "Bedrooms only", "Public rooms only"],
                                     state="readonly", font=("Helvetica", 9))
        constraint_cb.pack(fill="x")

        ttk.Separator(inner, orient="horizontal").pack(fill="x", pady=10)

        # ── Show/Hide ───────────────────────────────────────────
        tk.Label(inner, text="DISPLAY", font=("Helvetica", 8, "bold"),
                 bg="#FFFFFF", fg="#999", anchor="w").pack(fill="x", pady=(0, 4))

        self._grid_check_var   = tk.BooleanVar(value=True)
        self._labels_check_var = tk.BooleanVar(value=False)
        self._bushes_check_var = tk.BooleanVar(value=True)

        for text, var, cb in [
            ("Show grid",       self._grid_check_var,   self._toggle_grid_check),
            ("Show room labels",self._labels_check_var, self._toggle_labels_check),
            ("Show bushes",     self._bushes_check_var, self._redraw),
        ]:
            tk.Checkbutton(inner, text=text, variable=var, command=cb,
                           font=("Helvetica", 9), bg="#FFFFFF",
                           activebackground="#FFFFFF",
                           anchor="w", cursor="hand2").pack(fill="x")

        ttk.Separator(inner, orient="horizontal").pack(fill="x", pady=10)

        # ── LLM prompt ──────────────────────────────────────────
        row_llm = tk.Frame(inner, bg="#FFFFFF")
        row_llm.pack(fill="x")
        tk.Label(row_llm, text="LLM PROMPT", font=("Helvetica", 8, "bold"),
                 bg="#FFFFFF", fg="#999", anchor="w").pack(side="left")
        tk.Label(row_llm, text="beta", font=("Helvetica", 7),
                 bg="#FFF3CD", fg="#856404", padx=4, pady=1,
                 relief="flat").pack(side="left", padx=4)

        self._llm_text = tk.Text(inner, height=4, font=("Helvetica", 9),
                                 relief="solid", bd=1, wrap="word",
                                 fg="#333", bg="#F9F9F5")
        self._llm_text.pack(fill="x", pady=(6, 4))
        self._llm_text.insert("end",
            "e.g. More bedrooms near north, tea room near entrance")

        tk.Button(inner, text="Generate with prompt ↗",
                  command=self._llm_generate,
                  font=("Helvetica", 9), bg="#EBF4FF", fg="#185FA5",
                  relief="flat", padx=6, pady=4,
                  cursor="hand2").pack(fill="x")

    def _add_slider(self, parent, label_text, var, from_, to, tick,
                    callback=None):
        lbl_row = tk.Frame(parent, bg="#FFFFFF")
        lbl_row.pack(fill="x", pady=(6, 0))
        tk.Label(lbl_row, text=label_text, font=("Helvetica", 9),
                 bg="#FFFFFF", fg="#666", anchor="w").pack(side="left")
        val_lbl = tk.Label(lbl_row, text=str(var.get()),
                           font=("Helvetica", 9, "bold"),
                           bg="#FFFFFF", fg="#333")
        val_lbl.pack(side="right")

        def _trace(*_):
            val_lbl.config(text=str(var.get()))
            if callback:
                callback()

        var.trace_add("write", _trace)
        tk.Scale(parent, variable=var, from_=from_, to=to,
                 resolution=tick, orient="horizontal",
                 bg="#FFFFFF", highlightthickness=0,
                 showvalue=False, sliderrelief="flat",
                 troughcolor="#E5E4DC", length=160).pack(fill="x")

    def _build_canvas(self, parent):
        self._canvas = tk.Canvas(parent, bg="#F5F4EE",
                                 width=CANVAS_W, height=CANVAS_H,
                                 bd=0, highlightthickness=0, cursor="crosshair")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._renderer = CanvasRenderer(self._canvas)

        # Bind mouse events
        self._canvas.bind("<Button-1>",        self._on_click)
        self._canvas.bind("<B1-Motion>",       self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Configure>",       lambda e: self._redraw())

    # ── Site geometry ─────────────────────────────────────────

    def _site(self):
        m = self._margin_var.get()
        w = self._canvas.winfo_width()  or CANVAS_W
        h = self._canvas.winfo_height() or CANVAS_H
        return (m, m, w - 2 * m, h - 2 * m)

    # ── Generation ────────────────────────────────────────────

    def _generate(self):
        """Full regeneration with current settings."""
        self.seed = random.randint(0, 10 ** 9)
        self._seed_label.config(text=f"Seed: {self.seed}")
        self._run_packing()

    def _run_packing(self):
        site = self._site()
        pad  = self._pad_var.get()

        # Temporarily override module-level PAD via config
        import config as cfg
        cfg.PAD = pad

        self.hotel = pack_rooms_into_hotel(
            site,
            n_rooms=self._n_rooms_var.get(),
            weights=self.weights,
            seed=self.seed,
        )
        self.bushes = pack_bushes(site, self.hotel, seed=self.seed) \
            if self._bushes_check_var.get() else []

        self.selected_room = None
        self._redraw()
        self._update_metrics()

    def _llm_generate(self):
        prompt = self._llm_text.get("1.0", "end").strip()
        if not prompt:
            return
        # Briefly disable the button to prevent double-clicks
        self.mode.set("llm")
        try:
            self.weights = prompt_to_weights(prompt)
        except Exception as e:
            messagebox.showerror("LLM Error", str(e))
            self.weights = DEFAULT_WEIGHTS.copy()
        self._generate()

    # ── Redraw / metrics ──────────────────────────────────────

    def _redraw(self, *_):
        site = self._site()
        self._renderer.draw(
            site=site,
            hotel=self.hotel,
            bushes=self.bushes if self._bushes_check_var.get() else [],
            show_grid=self._grid_check_var.get(),
            show_labels=self._labels_check_var.get(),
            selected_room=self.selected_room,
            zone_rects=self._zone_rects if self.mode.get() == "zone" else None,
        )

    def _update_metrics(self):
        m = self.hotel.compute_metrics(self._site())
        self._metrics_labels["total_rooms"].config(
            text=f"Rooms: {m['total_rooms']}")
        self._metrics_labels["built_area"].config(
            text=f"Built: {m['built_area']:,} px²")
        self._metrics_labels["open_area"].config(
            text=f"Open: {m['open_area']:,} px²")
        self._metrics_labels["density"].config(
            text=f"Density: {m['density']}%")

    # ── Mouse interaction ─────────────────────────────────────

    def _on_click(self, event):
        mx, my = event.x, event.y
        mode   = self.mode.get()

        if mode == "random":
            hit = self._renderer.hit_test(mx, my, self.hotel)
            self.selected_room = hit
            if hit:
                self._drag_start = (hit, mx, my)
            self._redraw()

        elif mode == "drag":
            hit = self._renderer.hit_test(mx, my, self.hotel)
            if hit:
                self.selected_room = hit
                self._drag_start   = (hit, mx, my)
            else:
                # TODO: spawn new room from library (Week 3+)
                self.selected_room = None
            self._redraw()

        elif mode == "zone":
            self._zone_start = (mx, my)

    def _on_drag(self, event):
        mx, my = event.x, event.y
        mode   = self.mode.get()

        if mode in ("random", "drag") and self._drag_start:
            room, ox, oy = self._drag_start
            dx = mx - ox
            dy = my - oy
            if self._snap_on:
                dx = round(dx / GRID_SIZE) * GRID_SIZE
                dy = round(dy / GRID_SIZE) * GRID_SIZE
            room.move(dx, dy)
            self._drag_start = (room, mx, my)
            self._redraw()

        elif mode == "zone" and self._zone_start:
            sx, sy = self._zone_start
            from geometry_utils import rect_from_two_points
            self._zone_rects = [rect_from_two_points(sx, sy, mx, my)]
            self._redraw()

    def _on_release(self, event):
        self._drag_start = None
        if self.mode.get() == "zone" and self._zone_start:
            # Zone rect committed; could trigger zone-aware packing here
            self._zone_start = None
            # Future: pass zone_rects as spatial constraints to packing
            self._redraw()

    # ── Toolbar callbacks ─────────────────────────────────────

    def _toggle_grid(self):
        self._show_grid = not self._show_grid
        self._grid_check_var.set(self._show_grid)
        txt = "Grid ✓" if self._show_grid else "Grid"
        self._grid_btn.config(text=txt)
        self._redraw()

    def _toggle_snap(self):
        self._snap_on = not self._snap_on
        txt = "Snap ✓" if self._snap_on else "Snap"
        self._snap_btn.config(text=txt)

    def _toggle_grid_check(self):
        self._show_grid = self._grid_check_var.get()
        self._redraw()

    def _toggle_labels_check(self):
        self._redraw()

    def _on_mode_change(self):
        self._zone_rects = []
        self.selected_room = None
        self._drag_start   = None
        self._zone_start   = None
        self._redraw()

    def _update_weights_from_sliders(self):
        """Adjust bedroom vs public room weights based on the bias slider."""
        bias = self._bed_bias_var.get() / 100.0    # 0.0 – 1.0
        pub  = 1.0 - bias

        bed_share = bias / 4   # split evenly among 4 bedroom types
        pub_share = pub  / 4   # split evenly among 4 public types

        self.weights = {
            "BedroomA":    bed_share,
            "BedroomB":    bed_share,
            "BedroomC":    bed_share,
            "BedroomD":    bed_share,
            "TeaRoom1":    pub_share,
            "TeaRoom2":    pub_share,
            "Library":     pub_share,
            "ReadingRoom": pub_share,
        }

    def _export_png(self):
        """Save the current canvas to a PNG file via PIL/Pillow."""
        try:
            from PIL import ImageGrab
            import os, datetime
            fname = f"hotel_plan_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
            x = self._canvas.winfo_rootx()
            y = self._canvas.winfo_rooty()
            w = self._canvas.winfo_width()
            h = self._canvas.winfo_height()
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            img.save(fname)
            messagebox.showinfo("Exported", f"Saved as {os.path.abspath(fname)}")
        except ImportError:
            messagebox.showwarning("Export",
                "Pillow not installed. Run: pip install pillow")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))
