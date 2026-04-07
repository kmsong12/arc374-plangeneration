"""
app.py – HotelApp: main Tkinter window.
Fixes:
  - Grid toggle now actually redraws
  - Room filter dropdown wired to ROOM_CONSTRAINT (0/1/2)
  - No stray canvas items before first generate
  - Landscape items (bench/path) draw/drag working
"""

from __future__ import annotations
import random
import tkinter as tk
from tkinter import ttk, messagebox

from config import (
    CANVAS_W, CANVAS_H,
    SIDEBAR_LEFT_W, SIDEBAR_RIGHT_W, TOOLBAR_H, METRICS_BAR_H,
    SITE_MARGIN, GRID_SIZE, DEFAULT_WEIGHTS,
    ROOM_COLORS, ROOM_BORDERS,
)
from hotel import Hotel
from packing import pack_rooms_into_hotel, pack_bushes
from canvas_renderer import CanvasRenderer
from llm_bridge import prompt_to_weights


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
    "bench_chip":"#9C8462",
    "path_chip": "#D4CCBA",
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


class HotelApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Hotel Floor Plan Generator")
        root.configure(bg=C["bg"])
        root.minsize(900, 600)

        self.hotel:   Hotel = Hotel()
        self.bushes:  list  = []
        self.seed:    int   = random.randint(0, 10**9)
        self.weights: dict  = DEFAULT_WEIGHTS.copy()
        self.landscape_items: list = []

        self.selected_room  = None
        self._drag_start    = None
        self._zone_start    = None
        self._path_start    = None
        self._preview_id    = None
        self._zone_rects: list = []

        self.mode         = tk.StringVar(value="random")
        self._show_grid   = tk.BooleanVar(value=True)
        self._show_labels = tk.BooleanVar(value=False)
        self._show_bushes = tk.BooleanVar(value=True)

        self._build_ui()
        # Don't draw anything until generate runs
        self._generate()

    # ══════════════════════════════════════════════════════════
    #  UI
    # ══════════════════════════════════════════════════════════

    def _build_ui(self):
        root = self.root

        # toolbar
        tb = tk.Frame(root, bg=C["toolbar"], height=TOOLBAR_H,
                      highlightthickness=1, highlightbackground=C["sep"])
        tb.pack(side="top", fill="x")
        tb.pack_propagate(False)

        def _tb(text, cmd, primary=False):
            bg = C["accent_lt"] if primary else C["toolbar"]
            fg = C["accent"]    if primary else C["text"]
            lbl = tk.Label(tb, text=text, bg=bg, fg=fg,
                           font=("Helvetica", 10), padx=12, cursor="hand2")
            lbl.pack(side="left", padx=2, pady=6, ipady=3)
            lbl.bind("<Button-1>", lambda e: cmd())
            lbl.bind("<Enter>",    lambda e: lbl.config(bg=C["accent_lt"]))
            lbl.bind("<Leave>",    lambda e: lbl.config(bg=bg))

        _tb("↺  Regenerate",    self._generate, primary=True)
        tk.Frame(tb, bg=C["sep"], width=1).pack(side="left", fill="y", pady=6, padx=4)
        _tb("Clear landscape",  self._clear_landscape)
        tk.Frame(tb, bg=C["toolbar"]).pack(side="left", expand=True)
        self._seed_lbl = tk.Label(tb, text=f"seed  {self.seed}",
                                  bg=C["toolbar"], fg=C["text_dim"],
                                  font=("Courier", 9))
        self._seed_lbl.pack(side="left", padx=8)
        tk.Frame(tb, bg=C["toolbar"]).pack(side="left", expand=True)
        _tb("💾  Export PNG", self._export_png)

        # metrics bar
        mb = tk.Frame(root, bg=C["metric_bg"], height=METRICS_BAR_H,
                      highlightthickness=1, highlightbackground=C["sep"])
        mb.pack(side="bottom", fill="x")
        mb.pack_propagate(False)
        self._m = {}
        for key, lbl in (("total_rooms","Rooms"),("built_area","Built"),
                         ("open_area","Open"),("density","Density")):
            tk.Label(mb, text=lbl+":", bg=C["metric_bg"],
                     fg=C["text_dim"], font=("Helvetica", 9)).pack(
                side="left", padx=(12,2))
            v = tk.Label(mb, text="—", bg=C["metric_bg"],
                         fg=C["text"], font=("Helvetica", 9, "bold"))
            v.pack(side="left", padx=(0,12))
            self._m[key] = v

        body = tk.Frame(root, bg=C["bg"])
        body.pack(side="top", fill="both", expand=True)
        self._build_left(body)
        self._build_right(body)
        self._build_canvas(body)

    # ── left sidebar ──────────────────────────────────────────

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

        self._hsep(f)
        self._sec(f, "ROOM LIBRARY")
        for lbl, col in ROOM_COLORS.items():
            row = tk.Frame(f, bg=C["panel"])
            row.pack(fill="x", padx=12, pady=2)
            tk.Frame(row, bg=col, width=20, height=12,
                     highlightthickness=1,
                     highlightbackground=ROOM_BORDERS[lbl]).pack(
                side="left", padx=(0,7))
            tk.Label(row, text=lbl, font=("Helvetica", 9),
                     bg=C["panel"], fg=C["text"]).pack(side="left")

        self._hsep(f)
        self._sec(f, "LANDSCAPE")
        for chip_lbl, chip_col in (("Bench", C["bench_chip"]),
                                    ("Path",  C["path_chip"])):
            row = tk.Frame(f, bg=C["panel"])
            row.pack(fill="x", padx=12, pady=2)
            tk.Frame(row, bg=chip_col, width=20, height=12,
                     highlightthickness=1, highlightbackground="#888").pack(
                side="left", padx=(0,7))
            tk.Label(row, text=chip_lbl+" — select mode →",
                     font=("Helvetica", 8), bg=C["panel"],
                     fg=C["text_dim"]).pack(side="left")

    # ── right sidebar ─────────────────────────────────────────

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

        # Room filter — mirrors original ROOM_CONSTRAINT 0/1/2
        tk.Label(inn, text="Room filter", font=("Helvetica", 9),
                 bg=C["panel"], fg=C["text_dim"], anchor="w").pack(
            fill="x", pady=(8,2))
        self._constraint_var = tk.StringVar(value=CONSTRAINT_OPTIONS[0])
        ttk.Combobox(inn, textvariable=self._constraint_var,
                     values=CONSTRAINT_OPTIONS,
                     state="readonly",
                     font=("Helvetica", 9)).pack(fill="x")

        self._hsep(inn)
        self._sec(inn, "DISPLAY")
        for text, var in (("Grid",          self._show_grid),
                           ("Room labels",  self._show_labels),
                           ("Bushes",       self._show_bushes)):
            tk.Checkbutton(inn, text=text, variable=var,
                           command=self._redraw,       # ← direct redraw
                           font=("Helvetica", 9), bg=C["panel"],
                           activebackground=C["panel"],
                           fg=C["text"], anchor="w",
                           cursor="hand2").pack(fill="x", pady=1)

        self._hsep(inn)
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

        llm_btn = tk.Label(inn, text="Generate with prompt  ↗",
                           bg=C["accent_lt"], fg=C["accent"],
                           font=("Helvetica", 9), padx=8, pady=5,
                           cursor="hand2")
        llm_btn.pack(fill="x")
        llm_btn.bind("<Button-1>", lambda e: self._llm_generate())

    def _sec(self, parent, text):
        tk.Label(parent, text=text, font=("Helvetica", 8, "bold"),
                 bg=C["panel"], fg=C["text_dim"], anchor="w").pack(
            fill="x", pady=(8,3))

    def _hsep(self, parent):
        tk.Frame(parent, bg=C["sep"], height=1).pack(fill="x", pady=6)

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
                 showvalue=False, length=170).pack(fill="x")

    # ── canvas ────────────────────────────────────────────────

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
        # Configure fires on resize — only redraw if hotel exists
        cv.bind("<Configure>",
                lambda e: self._redraw() if self.hotel.rooms else None)

        self.root.bind("<r>", lambda e: self._generate())
        self.root.bind("<R>", lambda e: self._generate())
        self.root.bind("<s>", lambda e: self._export_png())
        self.root.bind("<S>", lambda e: self._export_png())
        self.root.bind("<g>", lambda e: (
            self._show_grid.set(not self._show_grid.get()),
            self._redraw()))
        self.root.bind("<l>", lambda e: (
            self._show_labels.set(not self._show_labels.get()),
            self._redraw()))
        self.root.bind("<Delete>",    self._delete_selected)
        self.root.bind("<BackSpace>", self._delete_selected)

    # ══════════════════════════════════════════════════════════
    #  Site helpers
    # ══════════════════════════════════════════════════════════

    def _site(self):
        m = self._margin_var.get()
        w = self._canvas.winfo_width()  or CANVAS_W
        h = self._canvas.winfo_height() or CANVAS_H
        return (m, m, w-2*m, h-2*m)

    def _get_constraint(self) -> int:
        idx = CONSTRAINT_OPTIONS.index(self._constraint_var.get())
        return idx   # 0, 1, or 2

    # ══════════════════════════════════════════════════════════
    #  Generation
    # ══════════════════════════════════════════════════════════

    def _generate(self):
        self.seed = random.randint(0, 10**9)
        self._seed_lbl.config(text=f"seed  {self.seed}")
        self._run_packing()

    def _run_packing(self):
        import config as cfg
        cfg.PAD = self._pad_var.get()
        site = self._site()
        self.hotel = pack_rooms_into_hotel(
            site,
            n_rooms=self._n_rooms_var.get(),
            weights=self.weights,
            seed=self.seed,
            constraint=self._get_constraint(),
        )
        if self._show_bushes.get():
            self.bushes = pack_bushes(site, self.hotel, seed=self.seed)
        else:
            self.bushes = []
        self.selected_room = None
        self._redraw()
        self._update_metrics()

    def _llm_generate(self):
        prompt = self._llm_txt.get("1.0","end").strip()
        if not prompt:
            return
        self.mode.set("llm")
        try:
            self.weights = prompt_to_weights(prompt)
        except Exception as e:
            messagebox.showerror("LLM Error", str(e))
            self.weights = DEFAULT_WEIGHTS.copy()
        self._generate()

    def _clear_landscape(self):
        self.landscape_items = []
        self._redraw()

    # ══════════════════════════════════════════════════════════
    #  Redraw / metrics
    # ══════════════════════════════════════════════════════════

    def _redraw(self, *_):
        if not hasattr(self, '_renderer'):
            return
        # Bushes: regenerate if toggle changed since last draw
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

    def _update_metrics(self):
        m = self.hotel.compute_metrics(self._site())
        self._m["total_rooms"].config(text=str(m["total_rooms"]))
        self._m["built_area"].config(text=f"{m['built_area']:,} px²")
        self._m["open_area"].config(text=f"{m['open_area']:,} px²")
        self._m["density"].config(text=f"{m['density']}%")

    # ══════════════════════════════════════════════════════════
    #  Mouse
    # ══════════════════════════════════════════════════════════

    def _on_click(self, event):
        mx,my = event.x, event.y
        mode  = self.mode.get()
        if mode in ("random","drag"):
            hit = self._renderer.hit_test(mx, my, self.hotel)
            self.selected_room = hit
            self._drag_start   = (hit, mx, my) if hit else None
            self._redraw()
        elif mode == "zone":
            self._zone_start = (mx, my)
        elif mode in ("bench","path"):
            self._path_start = (mx, my)

    def _on_drag(self, event):
        mx,my = event.x, event.y
        mode  = self.mode.get()
        if mode in ("random","drag") and self._drag_start:
            room,ox,oy = self._drag_start
            dx = round((mx-ox)/GRID_SIZE)*GRID_SIZE
            dy = round((my-oy)/GRID_SIZE)*GRID_SIZE
            room.move(dx, dy)
            self._drag_start = (room, mx, my)
            self._redraw()
        elif mode == "zone" and self._zone_start:
            from geometry_utils import rect_from_two_points
            sx,sy = self._zone_start
            self._zone_rects = [rect_from_two_points(sx,sy,mx,my)]
            self._redraw()
        elif mode in ("bench","path") and self._path_start:
            cv = self._canvas
            if self._preview_id:
                cv.delete(self._preview_id)
            sx,sy = self._path_start
            x0,y0,x1,y1 = min(sx,mx),min(sy,my),max(sx,mx),max(sy,my)
            col = "#9C8462" if mode=="bench" else "#D4CCBA"
            self._preview_id = cv.create_rectangle(
                x0,y0,x1,y1, outline=col, fill=col, dash=(4,3), width=1)

    def _on_release(self, event):
        mx,my = event.x, event.y
        mode  = self.mode.get()
        if self._preview_id:
            self._canvas.delete(self._preview_id)
            self._preview_id = None
        if mode in ("bench","path") and self._path_start:
            sx,sy = self._path_start
            x0=round(min(sx,mx)/GRID_SIZE)*GRID_SIZE
            y0=round(min(sy,my)/GRID_SIZE)*GRID_SIZE
            x1=round(max(sx,mx)/GRID_SIZE)*GRID_SIZE
            y1=round(max(sy,my)/GRID_SIZE)*GRID_SIZE
            w=x1-x0; h=y1-y0
            if w>8 and h>8:
                if mode=="path":
                    self.landscape_items.append(
                        {"type":"path","x":x0,"y":y0,"w":w,"h":h})
                else:
                    orient = "h" if w>=h else "v"
                    self.landscape_items.append(
                        {"type":"bench","x":x0,"y":y0,"w":w,"h":h,"orient":orient})
            self._path_start = None
        elif mode == "zone":
            self._zone_start = None
        self._drag_start = None
        self._redraw()

    def _delete_selected(self, event=None):
        if self.selected_room:
            self.hotel.remove_room(self.selected_room)
            self.selected_room = None
            self._update_metrics()
            self._redraw()

    # ══════════════════════════════════════════════════════════
    #  Callbacks
    # ══════════════════════════════════════════════════════════

    def _on_mode_change(self):
        self._zone_rects   = []
        self._drag_start   = None
        self._zone_start   = None
        self._path_start   = None
        self.selected_room = None
        cursors = {"random":"fleur","drag":"hand2","zone":"crosshair",
                   "bench":"crosshair","path":"crosshair","llm":"arrow"}
        self._canvas.config(cursor=cursors.get(self.mode.get(),"crosshair"))
        self._redraw()

    def _update_weights(self):
        bias=self._bed_bias_var.get()/100.0; pub=1.0-bias
        bs=bias/4; ps=pub/4
        self.weights={
            "BedroomA":bs,"BedroomB":bs,"BedroomC":bs,"BedroomD":bs,
            "TeaRoom1":ps,"TeaRoom2":ps,"Library":ps,"ReadingRoom":ps,
        }

    def _export_png(self):
        try:
            from PIL import ImageGrab
            import datetime, os
            fname=f"hotel_plan_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
            x=self._canvas.winfo_rootx(); y=self._canvas.winfo_rooty()
            w=self._canvas.winfo_width(); h=self._canvas.winfo_height()
            ImageGrab.grab(bbox=(x,y,x+w,y+h)).save(fname)
            messagebox.showinfo("Exported",
                                f"Saved as:\n{os.path.abspath(fname)}")
        except ImportError:
            messagebox.showwarning("Export","Run: pip install pillow")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))