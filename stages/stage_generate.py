"""
stages/stage_generate.py - Stage 2: three independent sub-modes.

Sub-modes are child frames instantiated on demand.  Switching sub-modes
throws away the current Plan; the user must click 'Send to Finalize' to
hand it off to Stage 3.

    RandomMode  : sliders for parameters; Generate button runs packing.
    ZoningMode  : step-by-step zone authoring; scrollable room list.
    LLMMode     : natural-language prompts via Claude → packing settings.
"""

from __future__ import annotations
import random
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, List, Optional, Tuple

from canvas_renderer import PlanCanvasRenderer
from config import SIDEBAR_LEFT_W, SIDEBAR_RIGHT_W, SITE_MARGIN, CANVAS_W, CANVAS_H
from model.plan import Plan, RoomInstance
from model.room_library import RoomLibrary
from packing import (
    pack_bushes,
    pack_bushes_for_llm,
    pack_from_llm_settings,
    random_pack,
    zone_pack,
)
from llm_bridge import prompt_to_settings
from theme import C, label_button, hsep, section, slider
from units import fmt_ft2


MODES = [
    ("random", "Random"),
    ("zoning", "Zoning"),
    ("llm",    "LLM"),
]


class GenerateStage(tk.Frame):
    def __init__(self, parent, shell):
        super().__init__(parent, bg=C["bg"])
        self.shell = shell
        self.library = shell.room_library

        # Top mode bar
        bar = tk.Frame(self, bg=C["panel"])
        bar.pack(side="top", fill="x")
        self._mode_buttons = {}
        for mid, lbl in MODES:
            b = tk.Label(bar, text=f"[{lbl}]", bg=C["panel"], fg=C["text_dim"],
                         font=("Helvetica", 10, "bold"),
                         padx=14, pady=8, cursor="hand2")
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, m=mid: self.switch_mode(m))
            self._mode_buttons[mid] = b
        tk.Frame(self, bg=C["sep"], height=1).pack(fill="x")

        self._body = tk.Frame(self, bg=C["bg"])
        self._body.pack(fill="both", expand=True)

        self._current_mode = None
        self._current_mode_frame: Optional[tk.Frame] = None
        self.switch_mode("random")
        self._install_toolbar()

    def _install_toolbar(self):
        tl = self.shell._toolbar_left
        tr = self.shell._toolbar_right
        label_button(tl, "Clear All",
                     self._clear_all).pack(side="left", padx=3)
        label_button(tl, "Clear Landscape",
                     self._clear_landscape).pack(side="left", padx=3)
        label_button(tr, "Send to Finalize \u2192",
                     self._send_to_finalize, primary=True).pack(
            side="right", padx=3)

    def switch_mode(self, mid: str):
        if mid == self._current_mode:
            return
        if self._current_mode_frame is not None:
            self._current_mode_frame.destroy()
            self._current_mode_frame = None
        for m, b in self._mode_buttons.items():
            b.config(fg=C["accent"] if m == mid else C["text_dim"],
                     bg=C["accent_lt"] if m == mid else C["panel"])
        if mid == "random":
            self._current_mode_frame = RandomMode(self._body, self.shell)
        elif mid == "zoning":
            self._current_mode_frame = ZoningMode(self._body, self.shell)
        elif mid == "llm":
            self._current_mode_frame = LLMMode(self._body, self.shell)
        self._current_mode_frame.pack(fill="both", expand=True)
        self._current_mode = mid

    def _clear_all(self):
        if self._current_mode_frame and hasattr(self._current_mode_frame, "clear_all"):
            self._current_mode_frame.clear_all()

    def _clear_landscape(self):
        if self._current_mode_frame and hasattr(self._current_mode_frame, "clear_landscape"):
            self._current_mode_frame.clear_landscape()

    def _send_to_finalize(self):
        if self._current_mode_frame and hasattr(self._current_mode_frame, "current_plan"):
            plan = self._current_mode_frame.current_plan()
            if plan is None or not plan.rooms:
                messagebox.showinfo("No plan",
                                    "Generate a plan first before sending to Finalize.")
                return
            self.shell.handoff_plan = plan
            self.shell.activate_stage("finalize")

    def teardown(self):
        if self._current_mode_frame is not None:
            try:
                self._current_mode_frame.destroy()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Helpers for sub-modes
# ---------------------------------------------------------------------------

def _make_site(canvas_w=CANVAS_W, canvas_h=CANVAS_H, margin=SITE_MARGIN):
    return (margin, margin, canvas_w - 2 * margin, canvas_h - 2 * margin)


def _scrollable(parent, width=SIDEBAR_LEFT_W - 30, height=None):
    wrap = tk.Frame(parent, bg=C["panel"])
    cvs = tk.Canvas(wrap, bg=C["panel"], highlightthickness=0, width=width,
                    height=height or 0)
    sb = tk.Scrollbar(wrap, orient="vertical", command=cvs.yview)
    cvs.configure(yscrollcommand=sb.set)
    inner = tk.Frame(cvs, bg=C["panel"])
    cvs.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
               lambda e: cvs.configure(scrollregion=cvs.bbox("all")))
    cvs.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    def _wheel(ev):
        cvs.yview_scroll(-int(ev.delta / 120), "units")
    cvs.bind_all("<MouseWheel>", _wheel)
    return wrap, inner


def _make_plan_canvas(parent):
    pw = tk.Frame(parent, bg=C["bg"])
    c = tk.Canvas(pw, bg=C["bg"], highlightthickness=1,
                  highlightbackground=C["panel_bdr"])
    c.pack(fill="both", expand=True, padx=8, pady=8)
    return pw, c


# ===========================================================================
# Random sub-mode
# ===========================================================================

class RandomMode(tk.Frame):
    def __init__(self, parent, shell):
        super().__init__(parent, bg=C["bg"])
        self.shell = shell
        self.library: RoomLibrary = shell.room_library
        self.plan = Plan()
        self.plan.site = _make_site()

        self._build_layout()
        self._install_help()
        self.renderer = PlanCanvasRenderer(self._canvas)
        self.after(30, self._redraw)

    def current_plan(self) -> Plan:
        return self.plan

    # --- layout ---------------------------------------------------------

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left sidebar - sliders
        self._left = tk.Frame(self, bg=C["panel"], width=SIDEBAR_LEFT_W)
        self._left.grid(row=0, column=0, sticky="ns")
        self._left.grid_propagate(False)
        self._build_controls()

        # Canvas
        cwrap, self._canvas = _make_plan_canvas(self)
        cwrap.grid(row=0, column=1, sticky="nsew")

        # Right sidebar - metrics
        self._right = tk.Frame(self, bg=C["panel"], width=SIDEBAR_RIGHT_W)
        self._right.grid(row=0, column=2, sticky="ns")
        self._right.grid_propagate(False)
        self._build_metrics()

    def _build_controls(self):
        tk.Label(self._left, text="Random Generation",
                 font=("Helvetica", 11, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(
            anchor="w", padx=10, pady=(10, 2))

        # Roomtype toggles
        section(self._left, "Room types")
        self._type_vars: Dict[str, tk.IntVar] = {}
        for rt in self.library.roomtypes():
            var = tk.IntVar(value=1)
            self._type_vars[rt] = var
            tk.Checkbutton(self._left, text=rt, variable=var,
                           bg=C["panel"], fg=C["text"],
                           font=("Helvetica", 9)).pack(anchor="w", padx=16)

        hsep(self._left)

        # Parameter sliders
        self._n_rooms = tk.IntVar(value=10)
        slider(self._left, "Total rooms", self._n_rooms, 1, 40, 1)
        self._pad = tk.IntVar(value=30)
        slider(self._left, "Padding (px)", self._pad, 0, 100, 5)
        self._bedroom_bias = tk.IntVar(value=50)
        slider(self._left, "Bedroom bias (%)", self._bedroom_bias, 0, 100, 5)
        self._bush_density = tk.IntVar(value=30)
        slider(self._left, "Bush count", self._bush_density, 0, 80, 2)
        self._seed = tk.IntVar(value=random.randint(1, 99999))
        slider(self._left, "Seed", self._seed, 0, 99999, 1)

        hsep(self._left)
        label_button(self._left, "Generate", self._generate,
                     primary=True).pack(fill="x", padx=10, pady=4)
        label_button(self._left, "Roll new seed",
                     lambda: self._seed.set(random.randint(1, 99999))).pack(
            fill="x", padx=10, pady=4)

    def _build_metrics(self):
        tk.Label(self._right, text="Metrics",
                 font=("Helvetica", 11, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(
            anchor="w", padx=10, pady=(10, 2))
        self._m_labels: Dict[str, tk.Label] = {}
        frm = tk.Frame(self._right, bg=C["panel"])
        frm.pack(fill="x", padx=10, pady=4)

        def _row(key, caption):
            r = tk.Frame(frm, bg=C["panel"]); r.pack(fill="x")
            tk.Label(r, text=caption, bg=C["panel"], fg=C["text_dim"],
                     font=("Helvetica", 9)).pack(side="left")
            l = tk.Label(r, text="-", bg=C["panel"], fg=C["text"],
                         font=("Helvetica", 9, "bold"))
            l.pack(side="right")
            self._m_labels[key] = l

        _row("rooms", "Rooms")
        _row("built", "Built")
        _row("open",  "Open")
        _row("density", "Density")

        hsep(self._right)
        tk.Label(self._right, text="Breakdown",
                 font=("Helvetica", 9, "bold"),
                 bg=C["panel"], fg=C["text_dim"]).pack(anchor="w", padx=10)
        self._breakdown = tk.Frame(self._right, bg=C["panel"])
        self._breakdown.pack(fill="both", expand=True, padx=10)

    def _install_help(self):
        pass

    # --- actions --------------------------------------------------------

    def _generate(self):
        enabled = [rt for rt, v in self._type_vars.items() if v.get()]
        weights: Dict[str, float] = {}
        bias = self._bedroom_bias.get() / 100.0
        weights["#bedroom"] = 0.2 + bias
        weights["#public room"] = 0.2 + (1 - bias) * 0.8
        plan = random_pack(
            self.library,
            site=self.plan.site,
            n_rooms=self._n_rooms.get(),
            enabled_types=enabled or None,
            weights=weights,
            seed=self._seed.get(),
            pad=self._pad.get(),
        )
        plan.site = self.plan.site
        plan.bushes = pack_bushes(plan.site, plan,
                                  seed=self._seed.get(),
                                  n_bushes=self._bush_density.get())
        self.plan = plan
        self._redraw()
        self._update_metrics()

    def clear_all(self):
        self.plan.clear()
        self._redraw()
        self._update_metrics()

    def clear_landscape(self):
        self.plan.clear_landscape()
        self._redraw()
        self._update_metrics()

    # --- draw -----------------------------------------------------------

    def _redraw(self):
        self.renderer.draw(self.plan, site=self.plan.site, show_grid=True,
                           show_labels=False)

    def _update_metrics(self):
        m = self.plan.compute_metrics()
        self._m_labels["rooms"].config(text=str(m["total_rooms"]))
        self._m_labels["built"].config(text=fmt_ft2(m["built_area_px"]))
        self._m_labels["open"].config(text=fmt_ft2(m["open_area_px"]))
        self._m_labels["density"].config(text=f"{m['density']:.1f}%")

        for child in list(self._breakdown.winfo_children()):
            child.destroy()
        for lab, cnt in m["counts"].items():
            area = m["avg_areas_px"].get(lab, 0)
            row = tk.Frame(self._breakdown, bg=C["panel"])
            row.pack(fill="x")
            tk.Label(row, text=f"{lab} \u00d7{cnt}",
                     bg=C["panel"], font=("Helvetica", 9)).pack(side="left")
            tk.Label(row, text=fmt_ft2(area) + " avg",
                     bg=C["panel"], fg=C["text_dim"],
                     font=("Helvetica", 8)).pack(side="right")


# ===========================================================================
# Zoning sub-mode
# ===========================================================================

class ZoningMode(tk.Frame):
    def __init__(self, parent, shell):
        super().__init__(parent, bg=C["bg"])
        self.shell = shell
        self.library = shell.room_library
        self.plan = Plan()
        self.plan.site = _make_site()
        self.zones: List[Tuple[int, int, int, int]] = []
        self.zone_specs: List[dict] = []   # per zone: {"label","max","weights","room_key_or_type"}
        self.active_zone: Optional[int] = None
        self._drag_start: Optional[Tuple[int, int]] = None
        self._drag_rect: Optional[Tuple[int, int, int, int]] = None

        self._build_layout()
        self.renderer = PlanCanvasRenderer(self._canvas)
        self.after(30, self._redraw)

    def current_plan(self) -> Plan:
        return self.plan

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left: scrollable room list
        self._left = tk.Frame(self, bg=C["panel"], width=SIDEBAR_LEFT_W)
        self._left.grid(row=0, column=0, sticky="ns")
        self._left.grid_propagate(False)
        self._build_room_list()

        cwrap, self._canvas = _make_plan_canvas(self)
        cwrap.grid(row=0, column=1, sticky="nsew")
        self._canvas.bind("<Button-1>", self._on_down)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_up)

        # Right: step-by-step panel
        self._right = tk.Frame(self, bg=C["panel"], width=SIDEBAR_RIGHT_W + 30)
        self._right.grid(row=0, column=2, sticky="ns")
        self._right.grid_propagate(False)
        self._build_steps()

    def _build_room_list(self):
        tk.Label(self._left, text="Rooms", font=("Helvetica", 11, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(
            anchor="w", padx=10, pady=(10, 2))
        tk.Label(self._left, text="Drag a room into a zone",
                 bg=C["panel"], fg=C["text_dim"],
                 font=("Helvetica", 8), wraplength=SIDEBAR_LEFT_W - 20).pack(
            anchor="w", padx=10)
        hsep(self._left)
        wrap, inner = _scrollable(self._left, width=SIDEBAR_LEFT_W - 30)
        wrap.pack(fill="both", expand=True, padx=4, pady=4)
        for key, tpl in self.library.all():
            self._make_room_row(inner, key, tpl)

    def _make_room_row(self, parent, key, tpl):
        row = tk.Frame(parent, bg=C["panel"], cursor="hand2")
        row.pack(fill="x", padx=4, pady=2)
        thumb = tk.Canvas(row, width=48, height=34,
                          bg=C["panel"], highlightthickness=0)
        thumb.pack(side="left", padx=(2, 6))
        _, _, bw, bh = tpl.bbox()
        s = min(40 / max(bw, 1), 28 / max(bh, 1))
        pts = []
        for x, y in tpl.polygon:
            pts += [4 + x * s, 3 + y * s]
        if pts:
            thumb.create_polygon(*pts, fill=tpl.fill_color,
                                 outline=tpl.border_color, width=1)
        info = tk.Frame(row, bg=C["panel"])
        info.pack(side="left", fill="x", expand=True)
        tk.Label(info, text=tpl.label, bg=C["panel"],
                 font=("Helvetica", 9, "bold"), anchor="w").pack(fill="x")
        tk.Label(info, text=tpl.roomtype, bg=C["panel"], fg=C["text_dim"],
                 font=("Helvetica", 8), anchor="w").pack(fill="x")

        def on_click(_e=None, k=key, t=tpl):
            if self.active_zone is None:
                self.shell.set_status("Pick a zone first, then click a room.")
                return
            zs = self.zone_specs[self.active_zone]
            zs["weights"] = {k: 1.0}
            zs["room_key_or_type"] = f"Room: {t.label}"
            self._refresh_step_panel()
            self.shell.set_status(f"Zone {self.active_zone + 1}: {t.label}.")
        row.bind("<Button-1>", on_click)
        thumb.bind("<Button-1>", on_click)
        for w in (row, thumb, info):
            w.bind("<Enter>", lambda e, r=row: r.config(bg=C["accent_lt"]))
            w.bind("<Leave>", lambda e, r=row: r.config(bg=C["panel"]))

    def _build_steps(self):
        tk.Label(self._right, text="Zoning Workflow",
                 font=("Helvetica", 11, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(
            anchor="w", padx=10, pady=(10, 2))
        tk.Label(self._right,
                 text="1) Drag on canvas to draw a zone  "
                      "2) Click a zone to select it  "
                      "3) Pick content on the left or choose a roomtype below  "
                      "4) Set max rooms  "
                      "5) Generate",
                 bg=C["panel"], fg=C["text_dim"],
                 font=("Helvetica", 8), wraplength=SIDEBAR_RIGHT_W + 10,
                 justify="left").pack(anchor="w", padx=10)
        hsep(self._right)

        # Roomtype picker
        rt_row = tk.Frame(self._right, bg=C["panel"])
        rt_row.pack(fill="x", padx=10, pady=2)
        tk.Label(rt_row, text="Type:", bg=C["panel"]).pack(side="left")
        self._roomtype_var = tk.StringVar(value=self.library.roomtypes()[0] if self.library.roomtypes() else "bedroom")
        cbo = ttk.Combobox(rt_row, textvariable=self._roomtype_var,
                           values=self.library.roomtypes(), width=14)
        cbo.pack(side="left", padx=4)
        label_button(rt_row, "Use type", self._assign_roomtype).pack(
            side="left", padx=3)

        # Max slider
        self._max_var = tk.IntVar(value=3)
        slider(self._right, "Max rooms in zone", self._max_var, 1, 20, 1,
               cb=self._update_max)

        self._rand_in_type = tk.IntVar(value=1)
        tk.Checkbutton(self._right, text="Random within type",
                       variable=self._rand_in_type,
                       bg=C["panel"]).pack(anchor="w", padx=10)

        hsep(self._right)

        # Zone list
        tk.Label(self._right, text="Zones",
                 bg=C["panel"], fg=C["text_dim"],
                 font=("Helvetica", 9, "bold")).pack(anchor="w", padx=10)
        self._zones_frame = tk.Frame(self._right, bg=C["panel"])
        self._zones_frame.pack(fill="x", padx=10)

        hsep(self._right)
        label_button(self._right, "Generate",
                     self._generate, primary=True).pack(fill="x", padx=10, pady=4)
        label_button(self._right, "Remove Zone",
                     self._remove_zone).pack(fill="x", padx=10, pady=2)

    def _refresh_step_panel(self):
        for child in self._zones_frame.winfo_children():
            child.destroy()
        for i, (z, s) in enumerate(zip(self.zones, self.zone_specs)):
            row = tk.Frame(self._zones_frame, bg=C["panel"], cursor="hand2")
            row.pack(fill="x", pady=1)
            desc = s.get("room_key_or_type") or "(empty)"
            max_n = s.get("max", 1)
            txt = f"Zone {i + 1}: {desc} \u00d7 up to {max_n}"
            lbl = tk.Label(row, text=txt, bg=C["panel"], anchor="w",
                           font=("Helvetica", 9))
            lbl.pack(fill="x")
            def on_click(_e=None, idx=i):
                self.active_zone = idx
                if self.zone_specs[idx]:
                    self._max_var.set(int(self.zone_specs[idx].get("max", 1)))
                self._refresh_step_panel()
                self._redraw()
            row.bind("<Button-1>", on_click)
            lbl.bind("<Button-1>", on_click)
            if i == self.active_zone:
                row.config(bg=C["accent_lt"])
                lbl.config(bg=C["accent_lt"])

    def _update_max(self):
        if self.active_zone is None:
            return
        self.zone_specs[self.active_zone]["max"] = int(self._max_var.get())
        self._refresh_step_panel()

    def _assign_roomtype(self):
        if self.active_zone is None:
            self.shell.set_status("Select a zone first.")
            return
        rt = self._roomtype_var.get().strip()
        if not rt:
            return
        zs = self.zone_specs[self.active_zone]
        zs["weights"] = {f"#{rt}": 1.0}
        zs["room_key_or_type"] = f"Type: {rt}"
        self._refresh_step_panel()
        self.shell.set_status(
            f"Zone {self.active_zone + 1}: any {rt} template.")

    # --- canvas events for zone drawing --------------------------------

    def _on_down(self, event):
        # Check if clicking an existing zone to select it
        for i, (zx, zy, zw, zh) in enumerate(self.zones):
            if zx <= event.x <= zx + zw and zy <= event.y <= zy + zh:
                self.active_zone = i
                self._max_var.set(int(self.zone_specs[i].get("max", 1)))
                self._refresh_step_panel()
                self._redraw()
                return
        self._drag_start = (event.x, event.y)
        self._drag_rect = None

    def _on_drag(self, event):
        if self._drag_start is None:
            return
        x0, y0 = self._drag_start
        x = min(x0, event.x); y = min(y0, event.y)
        w = abs(event.x - x0); h = abs(event.y - y0)
        self._drag_rect = (x, y, w, h)
        self._redraw()

    def _on_up(self, _event):
        if self._drag_start is None or self._drag_rect is None:
            self._drag_start = None
            self._drag_rect = None
            return
        x, y, w, h = self._drag_rect
        if w > 20 and h > 20:
            self.zones.append((x, y, w, h))
            self.zone_specs.append(
                {"max": int(self._max_var.get()), "weights": None,
                 "room_key_or_type": None})
            # Mirror into plan.zones so the renderer paints the box
            # immediately on release, before any generation runs.
            self.plan.zones.append((x, y, w, h))
            self.active_zone = len(self.zones) - 1
            self._refresh_step_panel()
        self._drag_start = None
        self._drag_rect = None
        self._redraw()

    def _remove_zone(self):
        if self.active_zone is None:
            return
        del self.zones[self.active_zone]
        del self.zone_specs[self.active_zone]
        if 0 <= self.active_zone < len(self.plan.zones):
            del self.plan.zones[self.active_zone]
        self.active_zone = None
        self._refresh_step_panel()
        self._redraw()

    # --- actions --------------------------------------------------------

    def _generate(self):
        if not self.zones:
            messagebox.showinfo("No zones",
                                "Draw at least one zone on the canvas first.")
            return
        # Default any empty zone spec to 'any roomtype' with weight 1
        zs = []
        for s in self.zone_specs:
            if not s.get("weights"):
                zs.append({"max": s.get("max", 1),
                           "weights": {f"#{rt}": 1.0
                                       for rt in self.library.roomtypes()}})
            else:
                zs.append({"max": s.get("max", 1),
                           "weights": dict(s["weights"])})
        plan = zone_pack(self.library, self.plan.site,
                         self.zones, zs, seed=random.randint(1, 99999),
                         pad=30)
        plan.site = self.plan.site
        # keep zones visible on the plan
        plan.zones = list(self.zones)
        self.plan = plan
        self._redraw()

    def clear_all(self):
        self.plan.clear()
        self.zones.clear()
        self.zone_specs.clear()
        self.active_zone = None
        self._refresh_step_panel()
        self._redraw()

    def clear_landscape(self):
        self.plan.clear_landscape()
        self._redraw()

    def _redraw(self):
        self.renderer.draw(
            self.plan, site=self.plan.site, show_grid=True,
            zone_preview=self._drag_rect,
            highlight_zone_idx=self.active_zone)


# ===========================================================================
# LLM sub-mode (Claude → packing settings)
# ===========================================================================

class LLMMode(tk.Frame):
    def __init__(self, parent, shell):
        super().__init__(parent, bg=C["bg"])
        self.shell = shell
        self.library: RoomLibrary = shell.room_library
        self.plan = Plan()
        self.plan.site = _make_site()
        self._build_layout()
        self.renderer = PlanCanvasRenderer(self._canvas)
        self.after(30, self._redraw)

    def current_plan(self) -> Plan:
        return self.plan

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Empty left side (can place future settings here)
        left = tk.Frame(self, bg=C["panel"], width=SIDEBAR_LEFT_W)
        left.grid(row=0, column=0, sticky="ns")
        left.grid_propagate(False)
        tk.Label(left, text="LLM Prompt",
                 font=("Helvetica", 11, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(
            anchor="w", padx=10, pady=(10, 2))
        tk.Label(left,
                 text=(
                     "Describe the hotel layout in plain English.\n"
                     "Generate calls Claude (needs anthropic package +\n"
                     "ANTHROPIC_API_KEY in .env or environment)."
                 ),
                 bg=C["panel"], fg=C["text_dim"], justify="left",
                 font=("Helvetica", 8),
                 wraplength=SIDEBAR_LEFT_W - 20).pack(
            anchor="w", padx=10, pady=4)

        # Canvas
        cwrap, self._canvas = _make_plan_canvas(self)
        cwrap.grid(row=0, column=1, sticky="nsew")

        # Right: prompt panel
        right = tk.Frame(self, bg=C["panel"], width=SIDEBAR_RIGHT_W + 40)
        right.grid(row=0, column=2, sticky="ns")
        right.grid_propagate(False)
        tk.Label(right, text="Prompt",
                 font=("Helvetica", 11, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(
            anchor="w", padx=10, pady=(10, 2))
        tk.Label(right,
                 text="Describe the layout you want in natural language.",
                 bg=C["panel"], fg=C["text_dim"],
                 font=("Helvetica", 8), wraplength=260,
                 justify="left").pack(anchor="w", padx=10)

        self._prompt = tk.Text(right, height=24, width=32, wrap="word",
                                bg="white", relief="solid", bd=1)
        self._prompt.pack(fill="both", expand=True, padx=10, pady=6)

        btnrow = tk.Frame(right, bg=C["panel"])
        btnrow.pack(fill="x", padx=10, pady=(0, 10))
        label_button(btnrow, "Generate from prompt",
                     self._run, primary=True).pack(side="left", padx=2)
        label_button(btnrow, "Clear",
                     lambda: self._prompt.delete("1.0", "end")).pack(
            side="left", padx=2)

    def _run(self):
        prompt = self._prompt.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning("Prompt", "Enter a description first.")
            return
        self.plan.title = prompt
        try:
            settings = prompt_to_settings(prompt)
        except RuntimeError as e:
            messagebox.showerror("LLM", str(e))
            return
        seed = random.randint(1, 999999)
        site = _make_site()
        try:
            plan = pack_from_llm_settings(
                self.library, site, settings, seed=seed)
        except Exception as e:
            messagebox.showerror("Packing", f"Could not build layout:\n{e}")
            return
        plan.title = prompt
        plan.bushes = pack_bushes_for_llm(site, plan, settings, seed=seed)
        self.plan = plan
        self._redraw()
        self.shell.set_status(
            f"LLM: {len(plan.rooms)} rooms (seed {seed}). "
            "Send to Finalize when ready."
        )

    def clear_all(self):
        self.plan.clear()
        self._redraw()

    def clear_landscape(self):
        self.plan.clear_landscape()
        self._redraw()

    def _redraw(self):
        self.renderer.draw(self.plan, site=self.plan.site)
