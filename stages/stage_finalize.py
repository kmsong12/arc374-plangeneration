"""
stages/stage_finalize.py - Stage 3: finalise the plan and export.

Features
--------
- Drag room -> snap back if polygon-SAT overlap with any other room.
- Place benches, paths, trees; reject if overlaps any room.
- Rotate selected room by 90° around centroid.
- Color picker for selected room.
- Delete / pin selected room.
- Save plan to PlanLibrary; export PNG (via Tk PostScript) or JSON.
- Load a previously saved plan.
"""

from __future__ import annotations
import copy
import json
import os
import random
import tkinter as tk
import tkinter.colorchooser
import tkinter.filedialog
import tkinter.simpledialog
from tkinter import messagebox
from typing import Any, List, Optional, Tuple

from canvas_renderer import PlanCanvasRenderer
from config import SIDEBAR_LEFT_W, SIDEBAR_RIGHT_W, SITE_MARGIN, CANVAS_W, CANVAS_H

from stages.stage_generate import (
    bind_plan_canvas_autoresize,
    make_scrollable_plan_canvas,
    update_plan_canvas_scrollregion,
)
from geometry_utils import (
    polygon_bbox, polygon_overlaps_any, polygons_overlap_sat, rect_to_polygon,
    translate_polygon,
)
from model.plan import Plan, RoomInstance
from model.room_library import RoomLibrary
from theme import C, label_button, hsep, section, slider
from units import fmt_ft2


def _make_site():
    return (SITE_MARGIN, SITE_MARGIN,
            CANVAS_W - 2 * SITE_MARGIN, CANVAS_H - 2 * SITE_MARGIN)


class FinalizeStage(tk.Frame):
    def __init__(self, parent, shell):
        super().__init__(parent, bg=C["bg"])
        self.shell = shell
        self.library: RoomLibrary = shell.room_library
        self.plan_library = shell.plan_library

        # Adopt handoff plan if available; otherwise empty
        if shell.handoff_plan is not None:
            self.plan = copy.deepcopy(shell.handoff_plan)
            shell.handoff_plan = None
        else:
            self.plan = Plan()
            self.plan.site = _make_site()
        if not self.plan.site:
            self.plan.site = _make_site()

        self.selected: Optional[RoomInstance] = None
        self._drag_start: Optional[tuple] = None   # (orig_x, orig_y)
        self._drag_offset: Optional[tuple] = None  # (dx, dy)
        self._armed_landscape: Optional[str] = None  # "bench"|"path"|"tree"

        # Landscape selection / drag state.
        self.selected_landscape: Optional[int] = None  # index into plan.landscape
        self.selected_bush: Optional[int] = None       # index into plan.bushes
        self._drag_landscape_start: Optional[tuple] = None  # (orig_x, orig_y)
        self._drag_landscape_offset: Optional[tuple] = None # (dx, dy)
        self._drag_bush_start: Optional[tuple] = None       # (orig_x, orig_y)
        self._drag_bush_offset: Optional[tuple] = None      # (dx, dy)

        self._undo_stack: List[Any] = []  # Plan snapshots via plan.snapshot()
        self._undo_drag_anchor: Optional[Any] = None

        self._build_layout()
        self._install_toolbar()
        self.renderer = PlanCanvasRenderer(self._canvas)
        bind_plan_canvas_autoresize(self._canvas, self._redraw)
        self.after(30, self._redraw)

    def teardown(self):
        try:
            self.unbind_all("<Delete>")
            self.unbind_all("<BackSpace>")
            self.unbind_all("r")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = tk.Frame(self, bg=C["panel"], width=SIDEBAR_LEFT_W)
        left.grid(row=0, column=0, sticky="ns")
        left.grid_propagate(False)
        self._build_left(left)

        cwrap, self._canvas = make_scrollable_plan_canvas(self)
        cwrap.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        self._canvas.bind("<Button-1>", self._on_down)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_up)
        self.bind_all("<Delete>", self._on_delete)
        self.bind_all("<BackSpace>", self._on_delete)
        self.bind_all("r", lambda e: self._rotate_selected())

        right = tk.Frame(self, bg=C["panel"], width=SIDEBAR_RIGHT_W)
        right.grid(row=0, column=2, sticky="ns")
        right.grid_propagate(False)
        self._build_right(right)

    def _cw_xy(self, event) -> Tuple[float, float]:
        """Canvas pixel coordinates → world / site px (fit-to-view inverse)."""
        cx = float(self._canvas.canvasx(event.x))
        cy = float(self._canvas.canvasy(event.y))
        return self.renderer.screen_to_world(cx, cy)

    def _build_left(self, parent):
        tk.Label(parent, text="Saved Plans", font=("Helvetica", 11, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(
            anchor="w", padx=10, pady=(10, 2))
        self._plans_frame = tk.Frame(parent, bg=C["panel"])
        self._plans_frame.pack(fill="x", padx=6)
        self._refresh_plan_list()

        hsep(parent)
        section(parent, "Landscape")
        for label, key in (("Bench (h)", "bench_h"), ("Bench (v)", "bench_v"),
                           ("Path (h)", "path_h"), ("Path (v)", "path_v"),
                           ("Tree", "tree")):
            def arm(k=key, lbl=label):
                self._armed_landscape = k
                self.shell.set_status(
                    f"Armed: {lbl} — click on empty space to place.")
            label_button(parent, label, arm).pack(fill="x", padx=10, pady=1)
        label_button(parent, "Disarm", lambda: self._disarm()).pack(
            fill="x", padx=10, pady=(6, 0))

    def _build_right(self, parent):
        tk.Label(parent, text="Selected Room", font=("Helvetica", 11, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(
            anchor="w", padx=10, pady=(10, 2))
        self._sel_info = tk.Label(parent, text="(none)",
                                  bg=C["panel"], fg=C["text_dim"],
                                  font=("Helvetica", 9), wraplength=SIDEBAR_RIGHT_W - 20,
                                  justify="left")
        self._sel_info.pack(anchor="w", padx=10)

        hsep(parent)
        label_button(parent, "Rotate 90°",
                     self._rotate_selected).pack(fill="x", padx=10, pady=2)
        label_button(parent, "Change Color",
                     self._recolor_selected).pack(fill="x", padx=10, pady=2)
        label_button(parent, "Toggle Pin",
                     self._pin_selected).pack(fill="x", padx=10, pady=2)
        label_button(parent, "Delete Room",
                     self._delete_selected).pack(fill="x", padx=10, pady=2)

        hsep(parent)
        tk.Label(parent, text="Metrics",
                 font=("Helvetica", 9, "bold"),
                 bg=C["panel"], fg=C["text_dim"]).pack(
            anchor="w", padx=10)
        self._met_frame = tk.Frame(parent, bg=C["panel"])
        self._met_frame.pack(fill="x", padx=10)

    def _install_toolbar(self):
        tl = self.shell._toolbar_left
        tr = self.shell._toolbar_right
        label_button(tl, "Clear All", self._clear_all).pack(side="left", padx=3)
        label_button(tl, "Clear Landscape",
                     self._clear_landscape).pack(side="left", padx=3)
        self._undo_btn = label_button(tl, "Undo", self._undo)
        self._undo_btn.pack(side="left", padx=3)
        self._sync_undo_btn()

        label_button(tr, "Save to Library", self._save_plan,
                     primary=True).pack(side="right", padx=3)
        label_button(tr, "Export JSON",
                     self._export_json).pack(side="right", padx=3)
        label_button(tr, "Export PNG",
                     self._export_png).pack(side="right", padx=3)

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        snap = self._undo_stack.pop()
        self.plan.restore(snap)
        self.selected = None
        self._clear_landscape_selection()
        self._sync_undo_btn()
        self._redraw()
        self._update_metrics()
        self._update_selection_info()
        self.shell.set_status("Undid last change.")

    def _sync_undo_btn(self) -> None:
        en = bool(self._undo_stack)
        fg = C["accent"] if en else C["text_dim"]
        try:
            self._undo_btn.config(fg=fg, cursor=("hand2" if en else "arrow"))
        except Exception:
            pass

    def _push_undo_capture(self, snap: Any) -> None:
        self._undo_stack.append(snap)
        while len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._sync_undo_btn()

    # ------------------------------------------------------------------
    # Plan list
    # ------------------------------------------------------------------

    def _refresh_plan_list(self):
        for child in self._plans_frame.winfo_children():
            child.destroy()
        if not self.plan_library.all():
            tk.Label(self._plans_frame, text="(empty)",
                     bg=C["panel"], fg=C["text_dim"],
                     font=("Helvetica", 9)).pack(anchor="w", padx=4)
            return
        for key, plan in self.plan_library.all():
            row = tk.Frame(self._plans_frame, bg=C["panel"])
            row.pack(fill="x", padx=2, pady=1)
            lbl = tk.Label(row, text=plan.title or "(untitled)",
                           bg=C["panel"], fg=C["text"],
                           font=("Helvetica", 9, "bold"), cursor="hand2",
                           anchor="w")
            lbl.pack(side="left", fill="x", expand=True)
            lbl.bind("<Button-1>",
                     lambda e, k=key: self._load_plan(k))
            tk.Label(row, text=f"{len(plan.rooms)} rms",
                     bg=C["panel"], fg=C["text_dim"],
                     font=("Helvetica", 8)).pack(side="left", padx=3)
            dbtn = tk.Label(row, text="del", bg=C["panel"], fg=C["bad"],
                            font=("Helvetica", 8, "underline"),
                            cursor="hand2")
            dbtn.pack(side="right", padx=2)
            dbtn.bind("<Button-1>",
                      lambda e, k=key: self._delete_plan(k))

    def _load_plan(self, key):
        plan = self.plan_library.get(key)
        if not plan:
            return
        self.plan = copy.deepcopy(plan)
        if not self.plan.site:
            self.plan.site = _make_site()
        self.selected = None
        self._undo_stack.clear()
        self._sync_undo_btn()
        self._redraw()
        self._update_metrics()

    def _delete_plan(self, key):
        if messagebox.askyesno("Delete plan", "Remove this plan?"):
            self.plan_library.remove(key)
            self._refresh_plan_list()

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _disarm(self):
        self._armed_landscape = None
        self.shell.set_status("Disarmed.")

    def _hit_landscape(self, cx, cy) -> Optional[int]:
        """Return index into plan.landscape if (cx,cy) is inside an item bbox."""
        for i in range(len(self.plan.landscape) - 1, -1, -1):
            it = self.plan.landscape[i]
            ix, iy, iw, ih = it["x"], it["y"], it["w"], it["h"]
            if ix <= cx <= ix + iw and iy <= cy <= iy + ih:
                return i
        return None

    def _hit_bush(self, cx, cy) -> Optional[int]:
        """Return index into plan.bushes if (cx,cy) is within bush radius."""
        for i in range(len(self.plan.bushes) - 1, -1, -1):
            bx, by, br = self.plan.bushes[i]
            if (cx - bx) ** 2 + (cy - by) ** 2 <= (br + 4) ** 2:
                return i
        return None

    def _clear_landscape_selection(self):
        self.selected_landscape = None
        self.selected_bush = None
        self._drag_landscape_start = None
        self._drag_landscape_offset = None
        self._drag_bush_start = None
        self._drag_bush_offset = None

    def _on_down(self, event):
        cx, cy = self._cw_xy(event)
        if self._armed_landscape is not None:
            self._place_landscape(cx, cy)
            return
        hit = self.plan.room_at(cx, cy)
        if hit is not None:
            self.selected = hit
            self._clear_landscape_selection()
            if not hit.pinned:
                self._undo_drag_anchor = self.plan.snapshot()
                self._drag_start = (hit.x, hit.y)
                bx, by, _, _ = hit.world_bbox()
                self._drag_offset = (cx - bx, cy - by)
            else:
                self._drag_start = None
                self._drag_offset = None
            self._update_selection_info()
            self._redraw()
            return

        # No room hit -> try landscape items, then bushes
        l_idx = self._hit_landscape(cx, cy)
        if l_idx is not None:
            self.selected = None
            self._drag_start = None
            self._drag_offset = None
            self.selected_bush = None
            self.selected_landscape = l_idx
            it = self.plan.landscape[l_idx]
            self._drag_landscape_start = (it["x"], it["y"])
            self._drag_landscape_offset = (cx - it["x"], cy - it["y"])
            self._update_selection_info()
            self._redraw()
            return

        b_idx = self._hit_bush(cx, cy)
        if b_idx is not None:
            self.selected = None
            self._drag_start = None
            self._drag_offset = None
            self.selected_landscape = None
            self.selected_bush = b_idx
            bx, by, _br = self.plan.bushes[b_idx]
            self._drag_bush_start = (bx, by)
            self._drag_bush_offset = (cx - bx, cy - by)
            self._update_selection_info()
            self._redraw()
            return

        # Nothing hit -> clear all selections
        self.selected = None
        self._clear_landscape_selection()
        self._drag_start = None
        self._drag_offset = None
        self._update_selection_info()
        self._redraw()

    def _on_drag(self, event):
        cx, cy = self._cw_xy(event)
        # Room drag
        if self.selected is not None and self._drag_offset is not None:
            ox, oy = self._drag_offset
            new_bx = cx - ox
            new_by = cy - oy
            bx0, by0, bw, bh = self.selected.world_bbox()
            dx = new_bx - bx0
            dy = new_by - by0
            self.selected.x += dx
            self.selected.y += dy
            self._redraw()
            return
        # Landscape item drag
        if (self.selected_landscape is not None
                and self._drag_landscape_offset is not None):
            ox, oy = self._drag_landscape_offset
            it = self.plan.landscape[self.selected_landscape]
            it["x"] = cx - ox
            it["y"] = cy - oy
            self._redraw()
            return
        # Bush drag
        if (self.selected_bush is not None
                and self._drag_bush_offset is not None):
            ox, oy = self._drag_bush_offset
            bx_old, by_old, br = self.plan.bushes[self.selected_bush]
            self.plan.bushes[self.selected_bush] = (
                cx - ox, cy - oy, br)
            self._redraw()
            return

    def _on_up(self, _event):
        # Room release
        if self.selected is not None and self._drag_start is not None:
            sx0, sy0 = self._drag_start
            drag_anchor = self._undo_drag_anchor
            if self._overlaps_other(self.selected):
                self.selected.x, self.selected.y = self._drag_start
                self.shell.set_status("Overlap detected — snapped back.")
            sx, sy, sw, sh = self.plan.site
            bx, by, bw, bh = self.selected.world_bbox()
            if bx < sx or by < sy or bx + bw > sx + sw or by + bh > sy + sh:
                self.selected.x, self.selected.y = self._drag_start
                self.shell.set_status("Out of bounds — snapped back.")
            if drag_anchor is not None:
                moved = (
                    abs(self.selected.x - sx0) > 1e-3
                    or abs(self.selected.y - sy0) > 1e-3)
                if moved:
                    self._push_undo_capture(drag_anchor)
            self._undo_drag_anchor = None
            self._drag_start = None
            self._drag_offset = None
            self._redraw()
            self._update_metrics()
            return
        # Landscape release - clear drag state (no overlap restriction here)
        if (self.selected_landscape is not None
                and self._drag_landscape_offset is not None):
            self._drag_landscape_start = None
            self._drag_landscape_offset = None
            self._redraw()
            return
        if (self.selected_bush is not None
                and self._drag_bush_offset is not None):
            self._drag_bush_start = None
            self._drag_bush_offset = None
            self._redraw()
            return
        self._drag_start = None
        self._drag_offset = None

    def _overlaps_other(self, room: RoomInstance) -> bool:
        poly = room.world_polygon()
        others = [r.world_polygon() for r in self.plan.rooms if r is not room]
        return polygon_overlaps_any(poly, others)

    def _on_delete(self, _event):
        if self.selected is not None:
            snap = self.plan.snapshot()
            self.plan.remove_room(self.selected)
            self.selected = None
            self._push_undo_capture(snap)
            self._update_selection_info()
            self._redraw()
            self._update_metrics()
            return
        if self.selected_landscape is not None:
            snap = self.plan.snapshot()
            idx = self.selected_landscape
            if 0 <= idx < len(self.plan.landscape):
                self.plan.landscape.pop(idx)
            self._clear_landscape_selection()
            self._push_undo_capture(snap)
            self._update_selection_info()
            self._redraw()
            self._update_metrics()
            return
        if self.selected_bush is not None:
            snap = self.plan.snapshot()
            idx = self.selected_bush
            if 0 <= idx < len(self.plan.bushes):
                self.plan.bushes.pop(idx)
            self._clear_landscape_selection()
            self._push_undo_capture(snap)
            self._update_selection_info()
            self._redraw()
            self._update_metrics()

    def _delete_selected(self):
        self._on_delete(None)

    def _rotate_selected(self):
        if self.selected is None:
            return
        snap = self.plan.snapshot()
        before = (self.selected.rotation, self.selected.x, self.selected.y)
        self.selected.rotate_90()
        if self._overlaps_other(self.selected):
            self.selected.rotation, self.selected.x, self.selected.y = before
            self.shell.set_status("Rotation would overlap — cancelled.")
            return
        sx, sy, sw, sh = self.plan.site
        bx, by, bw, bh = self.selected.world_bbox()
        if bx < sx or by < sy or bx + bw > sx + sw or by + bh > sy + sh:
            self.selected.rotation, self.selected.x, self.selected.y = before
            self.shell.set_status("Rotation would leave site — cancelled.")
            return
        self._push_undo_capture(snap)
        self._redraw()

    def _recolor_selected(self):
        if self.selected is None:
            return
        init = (self.selected.fill_override or
                self.selected.template_snapshot.fill_color)
        c = tkinter.colorchooser.askcolor(initialcolor=init)
        if c and c[1]:
            self.selected.fill_override = c[1]
            self._redraw()

    def _pin_selected(self):
        if self.selected is None:
            return
        self.selected.pinned = not self.selected.pinned
        self._redraw()

    def _update_selection_info(self):
        if self.selected is not None:
            r = self.selected
            bx, by, bw, bh = r.world_bbox()
            info = (f"{r.label} [{r.roomtype}]\n"
                    f"rot: {int(r.rotation)}°\n"
                    f"size: {fmt_ft2(bw * bh)}\n"
                    f"pinned: {'yes' if r.pinned else 'no'}")
            self._sel_info.config(text=info)
            return
        if self.selected_landscape is not None:
            it = self.plan.landscape[self.selected_landscape]
            self._sel_info.config(
                text=f"Landscape: {it.get('type', '?')}\n"
                     f"size: {int(it['w'])}x{int(it['h'])} px")
            return
        if self.selected_bush is not None:
            bx, by, br = self.plan.bushes[self.selected_bush]
            self._sel_info.config(
                text=f"Tree (bush)\nradius: {int(br)} px")
            return
        self._sel_info.config(text="(none)")

    # ------------------------------------------------------------------
    # Landscape placement
    # ------------------------------------------------------------------

    def _place_landscape(self, cx, cy):
        snap = self.plan.snapshot()
        kind = self._armed_landscape
        placed = False
        if kind == "tree":
            r = random.randint(8, 16)
            box = rect_to_polygon(cx - r * 2, cy - r * 2, 4 * r, 4 * r)
            if not self._overlaps_any_room_poly(box):
                self.plan.bushes.append((cx, cy, r))
                placed = True
            else:
                self.shell.set_status("Overlaps a room — not placed.")
        else:
            orient = "h" if kind.endswith("_h") else "v"
            base = kind.split("_")[0]
            if base == "bench":
                w, h = (80, 24) if orient == "h" else (24, 80)
            else:  # path
                w, h = (120, 30) if orient == "h" else (30, 120)
            box = rect_to_polygon(cx - w / 2, cy - h / 2, w, h)
            if not self._overlaps_any_room_poly(box):
                self.plan.landscape.append({
                    "type": base, "x": cx - w / 2, "y": cy - h / 2,
                    "w": w, "h": h, "orient": orient,
                })
                placed = True
            else:
                self.shell.set_status("Overlaps a room — not placed.")
        if placed:
            self._push_undo_capture(snap)
        self._redraw()

    def _overlaps_any_room_poly(self, poly) -> bool:
        others = [r.world_polygon() for r in self.plan.rooms]
        return polygon_overlaps_any(poly, others)

    # ------------------------------------------------------------------
    # Top-level actions
    # ------------------------------------------------------------------

    def _clear_all(self):
        if (
                not self.plan.rooms and not self.plan.landscape
                and not self.plan.bushes):
            return
        snap = self.plan.snapshot()
        self.plan.clear()
        self.selected = None
        self._push_undo_capture(snap)
        self._redraw()
        self._update_metrics()
        self._update_selection_info()

    def _clear_landscape(self):
        self.plan.clear_landscape()
        self._redraw()
        self._update_metrics()

    def _save_plan(self):
        if not self.plan.rooms:
            messagebox.showwarning("Empty plan", "Nothing to save.")
            return
        title = tkinter.simpledialog.askstring(
            "Save plan", "Plan title:",
            initialvalue=self.plan.title or "My Plan",
            parent=self)
        if not title:
            return
        self.plan.title = title
        self.plan_library.add(self.plan, title=title)
        self._refresh_plan_list()
        self.shell.set_status(f"Saved plan '{title}'.")

    def _export_json(self):
        path = tkinter.filedialog.asksaveasfilename(
            parent=self, defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
            initialfile=(self.plan.title or "plan") + ".json",
            title="Export plan as JSON")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.plan.to_dict(), f, indent=2)
            self.shell.set_status(f"Wrote {path}.")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def _export_png(self):
        path = tkinter.filedialog.asksaveasfilename(
            parent=self, defaultextension=".ps",
            filetypes=[("PostScript", "*.ps"), ("All", "*.*")],
            initialfile=(self.plan.title or "plan") + ".ps",
            title="Export canvas (PostScript)")
        if not path:
            return
        try:
            cw = self._canvas.winfo_width() or 1000
            ch = self._canvas.winfo_height() or 640
            self._canvas.postscript(
                file=path,
                colormode="color",
                width=float(cw),
                height=float(ch))
            self.shell.set_status(f"Wrote {path}. Convert to PNG via ImageMagick.")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def _redraw(self):
        update_plan_canvas_scrollregion(self._canvas, self.plan.site)
        self.renderer.draw(
            self.plan, site=self.plan.site,
            show_grid=True, show_labels=False,
            selected_room=self.selected,
            selected_landscape=self.selected_landscape,
            selected_bush=self.selected_bush)

    def _update_metrics(self):
        for child in list(self._met_frame.winfo_children()):
            child.destroy()
        m = self.plan.compute_metrics()
        def _add(k, v):
            row = tk.Frame(self._met_frame, bg=C["panel"])
            row.pack(fill="x")
            tk.Label(row, text=k, bg=C["panel"], fg=C["text_dim"],
                     font=("Helvetica", 9)).pack(side="left")
            tk.Label(row, text=v, bg=C["panel"], fg=C["text"],
                     font=("Helvetica", 9, "bold")).pack(side="right")
        _add("Rooms", str(m["total_rooms"]))
        _add("Built", fmt_ft2(m["built_area_px"]))
        _add("Open",  fmt_ft2(m["open_area_px"]))
        _add("Density", f"{m['density']:.1f}%")
