"""
stages/stage_author.py - Stage 1: Room Authoring.

Layout:
    +----------+---------------------------+---------------------+
    | Left:    |                           | Right:              |
    | furnit.  |      Room Canvas          | room-template       |
    | catalog  |     (own local grid)      | library             |
    |          |                           |                     |
    +----------+---------------------------+---------------------+

Interaction:
    * Drag orange vertex handles to reshape the polygon.
    * Double-click an edge to insert a vertex at the midpoint.
    * Right-click a vertex to delete it (minimum 3 remain).
    * Click a furniture item in the left list -> arms it as the active
      "brush"; click on the canvas to drop it.  Click a placed item to
      select it (blue outline); drag to move; Delete to remove.
    * Click an interior wall to select (blue centerline); drag to move;
      Delete to remove. Not available while the wall-drawing tool is on
      or while a furniture brush is armed. New walls must stay inside the
      room; the wall preview turns red if the segment would leave the room
      or cross furniture.
    * [ / ] : rotate the selected piece by \u221290° / +90° (when one is
      selected; not in wall mode).
    * R: add 30° to the armed brush rotation or to the selected piece (if
      the new angle would be invalid, the rotation is refused).
    * 'Save Room...' button opens a dialog for title + roomtype, then
      writes the authored template into `RoomLibrary`.
    * 'Reset' clears the canvas to a blank rectangle.
"""

from __future__ import annotations
import math
import sys
import tkinter as tk
import tkinter.colorchooser
import tkinter.simpledialog
from tkinter import messagebox, ttk
from typing import List, Optional, Tuple

from canvas_renderer import RoomCanvasRenderer
from config import (
    GRID_SIZE, SIDEBAR_LEFT_W, SIDEBAR_RIGHT_W, CANVAS_W, CANVAS_H,
    ROOM_POLYGON_OUTLINE_PX, room_outline_thickness_template,
)
from geometry_utils import (
    point_in_polygon,
    regular_polygon, snap_to_grid,
    aabb_too_close_to_poly_edges,
    thick_segment_overlaps_rect,
    rotated_rect_bounds,
    rotated_rect_corners,
    interior_wall_fully_inside_room,
)
from model import furniture_lib
from model.custom_furniture import (
    BASE_W, BASE_H, CustomFurniture, Primitive,
    get_store as get_cf_store,
)
from model.room_template import FurnitureItem, RoomTemplate, Wall
from theme import C, label_button, section, hsep
from units import fmt_ft, ft_to_px, px_to_ft
from furniture_geometry import apply_resize, furniture_handle_positions

FURN_HANDLE_PX = 9.0

DEFAULT_ROOMTYPES = ["bedroom", "public room", "bathroom", "kitchen", "other"]


def _hl_cat_cell(fr, on: bool) -> None:
    try:
        fr.config(
            highlightbackground=(C["accent"] if on else C["panel_bdr"]),
            highlightthickness=2 if on else 1)
    except tk.TclError:
        pass


class AuthorStage(tk.Frame):
    def __init__(self, parent, shell):
        super().__init__(parent, bg=C["bg"])
        self.shell = shell
        self.library = shell.room_library

        # --- working template ---
        self._new_blank_template()

        # interaction state
        self._armed_furniture_key: Optional[str] = None
        self._armed_custom_id: Optional[str] = None
        self._armed_color: str = "#D9C7A3"
        self._armed_rotation: float = 0.0
        self._drag_vertex: Optional[int] = None
        self._drag_furniture: Optional[int] = None
        self._drag_offset: Tuple[float, float] = (0, 0)
        # Last known "valid" position for the item being dragged; if the
        # user moves it into an illegal spot we freeze at this position
        # and snap back to it on release.
        self._drag_last_valid: Optional[Tuple[float, float]] = None
        # Position when the drag started, used as an ultimate fallback.
        self._drag_start_pos: Optional[Tuple[float, float]] = None
        self._drag_invalid: bool = False
        self._selected_vertex: Optional[int] = None
        self._selected_furniture: Optional[int] = None
        self._selected_wall: Optional[int] = None
        self._editing_key: Optional[str] = None  # library key of template being edited

        # Interior wall translate (click wall to select + drag)
        self._drag_wall: Optional[int] = None
        self._drag_wall_anchor: Optional[Tuple[float, float]] = None
        self._wall_drag_start: Optional[Tuple[float, float, float, float]] = None
        self._drag_wall_last_valid: Optional[Tuple[float, float, float, float]] = None
        self._drag_wall_start_pos: Optional[Tuple[float, float, float, float]] = None
        self._drag_wall_invalid: bool = False
        self._drag_wall_undo_pushed: bool = False

        # Undo / redo stacks hold RoomTemplate.to_dict() snapshots.
        self._undo_stack: List[dict] = []
        self._redo_stack: List[dict] = []
        self._undo_cap: int = 80
        # Set to True on the first B1-Motion after grabbing a vertex or
        # furniture item, so we push exactly one undo frame per drag.
        self._drag_undo_pushed: bool = False

        # --- wall-drawing tool state ---
        self._wall_mode: bool = False
        # Matches `ROOM_POLYGON_OUTLINE_PX` at a nominal scale; updated on each wall op.
        self._pending_wall_thickness_px: float = room_outline_thickness_template(1.0)
        self._wall_start: Optional[Tuple[float, float]] = None
        self._wall_preview_id: Optional[int] = None

        # --- drag ghost preview (furniture) ---
        # (furniture_index, world_x, world_y, is_valid)
        self._drag_preview: Optional[Tuple[int, float, float, bool]] = None

        # --- placement shadow (armed brush following the cursor) ---
        # last canvas coords of the mouse over the room canvas, or None.
        self._place_preview: Optional[Tuple[float, float]] = None

        # (furniture index, 'nw'|'n'|...) while dragging a resize handle
        self._resize_furniture: Optional[Tuple[int, str]] = None
        self._resize_drag_started: bool = False

        # Stack of (template dict snapshot, library editing key) for Back.
        self._template_stack: List[Tuple[dict, Optional[str]]] = []
        # First (snapshot, editing_key) before any library drill-down (Home).
        self._browse_home_snapshot: Optional[Tuple[dict, Optional[str]]] = None
        # Door/Window placement: highlight polygon edge (index, valid) in canvas.
        self._opening_edge_glow: Optional[Tuple[int, bool]] = None

        self._build_layout()
        self._install_toolbar()
        self._bind_canvas()
        # Defer the first fit until after Tk has assigned a real size;
        # refit() will re-trigger from the <Configure> binding below as
        # soon as the canvas has a real allocation.
        self.after(50, self._first_draw)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left sidebar
        self.left = tk.Frame(self, bg=C["panel"], width=SIDEBAR_LEFT_W)
        self.left.grid(row=0, column=0, sticky="ns")
        self.left.grid_propagate(False)
        self._build_left_sidebar()

        # Center canvas
        center = tk.Frame(self, bg=C["bg"])
        center.grid(row=0, column=1, sticky="nsew")
        self.canvas = tk.Canvas(center, bg="#F5F3EC",
                                highlightthickness=1,
                                highlightbackground=C["panel_bdr"])
        self.canvas.pack(fill="both", expand=True, padx=8, pady=8)

        # Right sidebar
        self.right = tk.Frame(self, bg=C["panel"], width=SIDEBAR_RIGHT_W)
        self.right.grid(row=0, column=2, sticky="ns")
        self.right.grid_propagate(False)
        self._build_right_sidebar()

        # Renderer
        self.renderer = RoomCanvasRenderer(self.canvas)

    def _install_toolbar(self):
        tl = self.shell._toolbar_left
        tr = self.shell._toolbar_right

        label_button(tl, "New Room", self._new_blank_and_draw,
                     primary=True).pack(side="left", padx=3)
        self._undo_btn = label_button(tl, "\u238c Undo", self._undo)
        self._undo_btn.pack(side="left", padx=3)
        self._redo_btn = label_button(tl, "Redo \u21aa", self._redo)
        self._redo_btn.pack(side="left", padx=3)
        label_button(tl, "Reset Shape", self._reset_shape).pack(side="left", padx=3)
        label_button(tl, "Recenter",  self._recenter).pack(side="left", padx=3)
        label_button(tl, "\u2212 Zoom", self._zoom_out).pack(side="left", padx=3)
        label_button(tl, "+ Zoom",  self._zoom_in).pack(side="left", padx=3)
        label_button(tl, "1x",      self._zoom_reset).pack(side="left", padx=3)
        label_button(tl, "Delete Selection",
                     self._delete_selection).pack(side="left", padx=3)
        # Interior wall drawing is in the right sidebar (Current Room).
        # Initial dimmed state until something mutable happens.
        self._sync_undo_button()

        label_button(tr, "Save Room...",
                     self._save_room_dialog, primary=True).pack(
            side="right", padx=3)
        tk.Label(tr, text="Drag orange handles to reshape · dbl-click edge to add · rt-click vertex to remove",
                 bg=C["toolbar"], fg=C["text_dim"],
                 font=("Helvetica", 9)).pack(side="right", padx=10)

    # ------------------------------------------------------------------
    # Left sidebar - furniture catalog
    # ------------------------------------------------------------------

    def _bind_wheel_scroll(self, cvs: tk.Canvas):
        """Let the mouse wheel scroll ``cvs`` while the pointer is over it.

        We use bind_all on Enter and unbind_all on Leave so the event
        reaches the sidebar canvas even when the cursor hovers over an
        inner row (Tk delivers wheel events to the widget under the
        cursor, which for nested frames is often the child).  The room
        canvas uses a local bind and does not touch the global binding,
        so the two do not fight each other.
        """
        def on_wheel(e):
            num = getattr(e, "num", 0)
            if num == 4:
                step = -1
            elif num == 5:
                step = 1
            else:
                delta = getattr(e, "delta", 0)
                step = -1 if delta > 0 else 1
            cvs.yview_scroll(step * 3, "units")
            return "break"

        def on_enter(_e):
            cvs.bind_all("<MouseWheel>", on_wheel)
            cvs.bind_all("<Button-4>", on_wheel)
            cvs.bind_all("<Button-5>", on_wheel)

        def on_leave(_e):
            cvs.unbind_all("<MouseWheel>")
            cvs.unbind_all("<Button-4>")
            cvs.unbind_all("<Button-5>")

        cvs.bind("<Enter>", on_enter)
        cvs.bind("<Leave>", on_leave)

    def _build_left_sidebar(self):
        top = tk.Frame(self.left, bg=C["panel"])
        top.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(top, text="Furniture", font=("Helvetica", 11, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(anchor="w")
        tk.Label(top, text="Click an item, then click on the canvas.",
                 font=("Helvetica", 8), bg=C["panel"],
                 fg=C["text_dim"], wraplength=SIDEBAR_LEFT_W - 20,
                 justify="left").pack(anchor="w")

        color_row = tk.Frame(self.left, bg=C["panel"])
        color_row.pack(fill="x", padx=10, pady=4)
        tk.Label(color_row, text="Color: ", bg=C["panel"],
                 fg=C["text_dim"], font=("Helvetica", 9)).pack(side="left")
        self._color_swatch = tk.Label(color_row, text=" ", width=3,
                                      bg=self._armed_color,
                                      relief="solid", bd=1, cursor="hand2")
        self._color_swatch.pack(side="left", padx=4)
        self._color_swatch.bind("<Button-1>",
                                lambda e: self._pick_color())
        label_button(color_row, "Pick", self._pick_color).pack(
            side="left", padx=3)
        self._placement_cancel_btn = label_button(
            color_row, "Cancel placement", self._disarm_furniture)
        self._placement_cancel_btn.pack(side="right", padx=2)
        self._sync_cancel_placement_button()

        hsep(self.left)

        # Scrollable list
        scroll_frame = tk.Frame(self.left, bg=C["panel"])
        scroll_frame.pack(fill="both", expand=True, padx=6)
        cvs = tk.Canvas(scroll_frame, bg=C["panel"], highlightthickness=0,
                        width=SIDEBAR_LEFT_W - 30)
        cvs.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(scroll_frame, orient="vertical", command=cvs.yview)
        sb.pack(side="right", fill="y")
        cvs.configure(yscrollcommand=sb.set)
        inner = tk.Frame(cvs, bg=C["panel"])
        cvs.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: cvs.configure(scrollregion=cvs.bbox("all")))
        self._cat_inner = inner
        self._cat_canvas = cvs

        self._render_catalog()
        self._bind_wheel_scroll(self._cat_canvas)

        hsep(self.left)
        label_button(self.left, "+ New Furniture...",
                     self._new_custom_dialog).pack(fill="x", padx=10, pady=(4, 4))
        label_button(self.left, "Manage Custom...",
                     self._manage_custom).pack(fill="x", padx=10, pady=(0, 8))

    def _render_catalog(self):
        for child in self._cat_inner.winfo_children():
            child.destroy()
        col_w = max(1, (SIDEBAR_LEFT_W - 40) // 2)
        groups = furniture_lib.by_group()
        for group in furniture_lib.GROUPS:
            items = groups.get(group) or []
            if not items:
                continue
            tk.Label(self._cat_inner, text=group.upper(),
                     bg=C["panel"], fg=C["text_dim"],
                     font=("Helvetica", 8, "bold")).pack(
                anchor="w", padx=4, pady=(6, 2))
            grid = tk.Frame(self._cat_inner, bg=C["panel"])
            grid.pack(fill="x", padx=2)
            r, c_ = 0, 0
            for spec in items:
                self._make_cat_tile(grid, spec, col_w, r, c_)
                c_ += 1
                if c_ >= 2:
                    c_ = 0
                    r += 1

        cf_items = get_cf_store().all()
        if cf_items:
            tk.Label(self._cat_inner, text="CUSTOM",
                     bg=C["panel"], fg=C["text_dim"],
                     font=("Helvetica", 8, "bold")).pack(
                anchor="w", padx=4, pady=(6, 2))
            gridc = tk.Frame(self._cat_inner, bg=C["panel"])
            gridc.pack(fill="x", padx=2)
            r, c_ = 0, 0
            for cf in cf_items:
                self._make_custom_tile(gridc, cf, col_w, r, c_)
                c_ += 1
                if c_ >= 2:
                    c_ = 0
                    r += 1

    def _make_cat_tile(self, grid, spec, col_w, row, col):
        cell = tk.Frame(
            grid, bg=C["good_lt"], padx=4, pady=4, cursor="hand2",
            highlightthickness=1, highlightbackground=C["panel_bdr"])
        cell.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")
        grid.grid_columnconfigure(0, weight=1, uniform="cat")
        grid.grid_columnconfigure(1, weight=1, uniform="cat")
        ph = 52
        swatch = tk.Canvas(
            cell, width=col_w - 4, height=ph, bg="#FAFAF6",
            highlightthickness=0)
        swatch.pack()
        try:
            spec.draw(
                swatch, 3, 3, col_w - 10, ph - 6, spec.color)
        except Exception:
            swatch.create_rectangle(
                3, 3, col_w - 4, ph - 3,
                fill=spec.color, outline="#666")
        sub = tk.Label(
            cell, text=spec.label, bg=C["good_lt"], fg=C["text"],
            font=("Helvetica", 8), wraplength=col_w, justify="center")
        sub.pack(pady=(2, 0))
        dim = tk.Label(
            cell, text=f"{int(spec.w)}\u00d7{int(spec.h)}", bg=C["good_lt"],
            fg=C["text_dim"], font=("Helvetica", 7))
        dim.pack()

        def on_click(_e, key=spec.key, color=spec.color, lab=spec.label):
            if self._wall_mode:
                self.canvas.bell()
                self.shell.set_status(
                    "Exit wall mode (Esc or Exit wall mode) to arm furniture.")
                return
            self._armed_furniture_key = key
            self._armed_custom_id = None
            self._armed_rotation = 0.0
            self._armed_color = color
            self._color_swatch.config(bg=color)
            self._sync_cancel_placement_button()
            self.shell.set_status(
                f"Armed: {lab} — click on the canvas to place.")

        for w in (cell, swatch, sub, dim):
            w.bind("<Button-1>", on_click)
        for w in (cell, swatch, sub, dim):
            w.bind(
                "<Enter>", lambda e, fr=cell: _hl_cat_cell(fr, True))
            w.bind(
                "<Leave>", lambda e, fr=cell: _hl_cat_cell(fr, False))

    def _make_custom_tile(self, grid, cf, col_w, row, col):
        from model.custom_furniture import draw_custom
        cell = tk.Frame(
            grid, bg=C["good_lt"], padx=4, pady=4, cursor="hand2",
            highlightthickness=1, highlightbackground=C["panel_bdr"])
        cell.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")
        ph = 52
        swatch = tk.Canvas(
            cell, width=col_w - 4, height=ph, bg="#FAFAF6",
            highlightthickness=0)
        swatch.pack()
        draw_custom(swatch, cf.id, 3, 3, col_w - 10, ph - 6, None)
        sub = tk.Label(
            cell, text=cf.label, bg=C["good_lt"], fg=C["text"],
            font=("Helvetica", 8), wraplength=col_w, justify="center")
        sub.pack(pady=(2, 0))

        def on_click(_e, cfid=cf.id, lab=cf.label):
            if self._wall_mode:
                self.canvas.bell()
                self.shell.set_status(
                    "Exit wall mode (Esc or Exit wall mode) to arm furniture.")
                return
            self._armed_furniture_key = "Custom"
            self._armed_custom_id = cfid
            self._armed_rotation = 0.0
            self._sync_cancel_placement_button()
            self.shell.set_status(f"Armed: {lab} — click on canvas.")
        for w in (cell, swatch, sub):
            w.bind("<Button-1>", on_click)
        for w in (cell, swatch, sub):
            w.bind("<Enter>", lambda e, fr=cell: _hl_cat_cell(fr, True))
            w.bind("<Leave>", lambda e, fr=cell: _hl_cat_cell(fr, False))

    def _pick_color(self):
        c = tkinter.colorchooser.askcolor(initialcolor=self._armed_color,
                                          title="Furniture color")
        if c and c[1]:
            self._armed_color = c[1]
            self._color_swatch.config(bg=self._armed_color)

    # ------------------------------------------------------------------
    # Right sidebar - template library
    # ------------------------------------------------------------------

    def _build_right_sidebar(self):
        top = tk.Frame(self.right, bg=C["panel"])
        top.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(top, text="Room Library", font=("Helvetica", 11, "bold"),
                 bg=C["panel"], fg=C["text"]).pack(anchor="w")
        tk.Label(top, text="Click a template to open it. Use Save to add or update the library file.",
                 font=("Helvetica", 8), bg=C["panel"],
                 fg=C["text_dim"], wraplength=SIDEBAR_RIGHT_W - 20,
                 justify="left").pack(anchor="w")

        nav1 = tk.Frame(top, bg=C["panel"]); nav1.pack(fill="x", pady=(4, 2))
        self._back_btn = label_button(
            nav1, "\u2190 Back to previous", self._pop_template_stack)
        self._back_btn.pack(side="left", padx=(0, 4))
        self._back_btn.config(state="disabled")
        self._home_btn = label_button(
            nav1, "\u2302 Home", self._return_to_active_editing)
        self._home_btn.pack(side="left", padx=(0, 4))
        self._home_btn.config(state="disabled")

        nav2 = tk.Frame(top, bg=C["panel"]); nav2.pack(fill="x", pady=(0, 2))
        label_button(
            nav2, "+ New room template",
            self._new_room_from_sidebar, primary=True).pack(side="left", padx=(0, 4))

        # Appearance controls for the current room
        apbox = tk.LabelFrame(self.right, text="Current Room",
                              bg=C["panel"], fg=C["text"],
                              font=("Helvetica", 9, "bold"), bd=1, relief="flat")
        apbox.pack(fill="x", padx=10, pady=4)

        row1 = tk.Frame(apbox, bg=C["panel"]); row1.pack(fill="x", pady=2)
        tk.Label(row1, text="Fill", bg=C["panel"],
                 font=("Helvetica", 9)).pack(side="left")
        self._fill_swatch = tk.Label(row1, text="  ", bg=self.template.fill_color,
                                      relief="solid", bd=1, cursor="hand2", width=4)
        self._fill_swatch.pack(side="left", padx=4)
        self._fill_swatch.bind("<Button-1>", lambda e: self._pick_fill())

        row2 = tk.Frame(apbox, bg=C["panel"]); row2.pack(fill="x", pady=2)
        tk.Label(row2, text="Border", bg=C["panel"],
                 font=("Helvetica", 9)).pack(side="left")
        self._border_swatch = tk.Label(row2, text="  ",
                                        bg=self.template.border_color,
                                        relief="solid", bd=1, cursor="hand2", width=4)
        self._border_swatch.pack(side="left", padx=4)
        self._border_swatch.bind("<Button-1>", lambda e: self._pick_border())

        # Interior walls (color matches room border; thickness 6" template px).
        wall_row = tk.Frame(apbox, bg=C["panel"]); wall_row.pack(fill="x", pady=(6, 2))
        tk.Label(wall_row, text="Interior walls", bg=C["panel"],
                 font=("Helvetica", 9, "bold")).pack(side="left")
        wbtn = tk.Frame(wall_row, bg=C["panel"]); wbtn.pack(side="right")
        self._draw_wall_btn = label_button(
            wbtn, "Draw interior walls", self._enter_wall_mode, primary=True)
        self._draw_wall_btn.pack(side="left", padx=1)
        self._exit_wall_btn = label_button(
            wbtn, "Exit wall mode", self._cancel_wall_mode)
        self._exit_wall_btn.pack(side="left", padx=1)
        self._exit_wall_btn.pack_forget()
        self._wall_mode_badge = tk.Label(
            wall_row, text=" WALL MODE ", bg=C["warn_bg"], fg=C["warn_fg"],
            font=("Helvetica", 8, "bold"), padx=4, pady=1, relief="solid", bd=1)
        # Shown in _sync_wall_mode_ui while wall-drawing.
        self._wall_mode_badge.pack(side="left", padx=(8, 0))
        self._wall_mode_badge.pack_forget()
        tk.Label(apbox, text="Click-drag on canvas. Color matches Border above. Esc or Exit to stop.",
                 bg=C["panel"], fg=C["text_dim"],
                 font=("Helvetica", 8), wraplength=SIDEBAR_RIGHT_W - 24,
                 justify="left").pack(anchor="w", padx=0, pady=(0, 2))

        # Shape controls: vertex-count slider + Reshape button.
        row3 = tk.Frame(apbox, bg=C["panel"]); row3.pack(fill="x", pady=(6, 2))
        tk.Label(row3, text="Shape", bg=C["panel"],
                 font=("Helvetica", 9)).pack(side="left")
        initial_n = max(3, min(24, len(self.template.polygon) or 4))
        self._vertex_var = tk.IntVar(value=initial_n)
        self._vertex_scale = tk.Scale(
            row3, from_=3, to=24, orient="horizontal",
            variable=self._vertex_var,
            length=SIDEBAR_RIGHT_W - 130,
            showvalue=True, resolution=1,
            bg=C["panel"], fg=C["text"],
            troughcolor=C.get("toolbar", "#DDD"),
            highlightthickness=0, bd=0,
        )
        self._vertex_scale.pack(side="left", padx=(4, 4))

        row4 = tk.Frame(apbox, bg=C["panel"]); row4.pack(fill="x", pady=(0, 4))
        tk.Label(row4, text="(reshape replaces the current polygon)",
                 bg=C["panel"], fg=C["text_dim"],
                 font=("Helvetica", 8)).pack(side="left")
        label_button(row4, "Reshape", self._on_reshape_clicked,
                     primary=True).pack(side="right", padx=2)

        # --- Base Size (Author-only) ---
        bs_row1 = tk.Frame(apbox, bg=C["panel"]); bs_row1.pack(fill="x", pady=(8, 2))
        tk.Label(bs_row1, text="Base Size", bg=C["panel"],
                 font=("Helvetica", 9, "bold")).pack(side="left")

        # Uniform scale slider + Apply button
        bs_row2 = tk.Frame(apbox, bg=C["panel"]); bs_row2.pack(fill="x", pady=2)
        tk.Label(bs_row2, text="Scale", bg=C["panel"],
                 font=("Helvetica", 9)).pack(side="left")
        self._scale_var = tk.DoubleVar(value=1.0)
        self._scale_slider = tk.Scale(
            bs_row2, from_=0.25, to=3.0, resolution=0.05,
            orient="horizontal", variable=self._scale_var,
            length=SIDEBAR_RIGHT_W - 150,
            showvalue=True,
            bg=C["panel"], fg=C["text"],
            troughcolor=C.get("toolbar", "#DDD"),
            highlightthickness=0, bd=0,
        )
        self._scale_slider.pack(side="left", padx=(4, 4))
        label_button(bs_row2, "Apply", self._on_apply_scale_clicked,
                     primary=True).pack(side="right", padx=2)

        # Width / Height numeric entries (in feet) + Resize button
        bs_row3 = tk.Frame(apbox, bg=C["panel"]); bs_row3.pack(fill="x", pady=2)
        tk.Label(bs_row3, text="W (ft)", bg=C["panel"],
                 font=("Helvetica", 9)).pack(side="left")
        self._size_w_var = tk.StringVar(value="")
        tk.Entry(bs_row3, textvariable=self._size_w_var, width=6).pack(
            side="left", padx=(2, 6))
        tk.Label(bs_row3, text="H (ft)", bg=C["panel"],
                 font=("Helvetica", 9)).pack(side="left")
        self._size_h_var = tk.StringVar(value="")
        tk.Entry(bs_row3, textvariable=self._size_h_var, width=6).pack(
            side="left", padx=(2, 6))
        label_button(bs_row3, "Resize", self._on_resize_clicked,
                     primary=True).pack(side="right", padx=2)

        # Sync the W/H entries with the current bbox initially.
        self._sync_size_entries_to_bbox()

        sel_rot_fr = tk.Frame(apbox, bg=C["panel"])
        sel_rot_fr.pack(fill="x", pady=(8, 2))
        tk.Label(sel_rot_fr, text="Furniture rotation",
                 bg=C["panel"], font=("Helvetica", 9, "bold")).pack(anchor="w")
        sel_rot_r2 = tk.Frame(sel_rot_fr, bg=C["panel"])
        sel_rot_r2.pack(fill="x", pady=(2, 0))
        self._sel_rot_lbl = tk.Label(
            sel_rot_r2, text="\u2014", bg=C["panel"], fg=C["text"],
            font=("Helvetica", 9), width=14, anchor="w")
        self._sel_rot_lbl.pack(side="left")
        sbx = tk.Frame(sel_rot_r2, bg=C["panel"])
        sbx.pack(side="right")
        self._sel_rot_ccw_btn = label_button(
            sbx, "\u27f2 \u221290\u00b0", self._on_sidebar_rotate_ccw)
        self._sel_rot_ccw_btn.pack(side="left", padx=1)
        self._sel_rot_cw_btn = label_button(
            sbx, "\u27f3 +90\u00b0", self._on_sidebar_rotate_cw)
        self._sel_rot_cw_btn.pack(side="left", padx=1)
        tk.Label(
            sel_rot_fr,
            text="[ / ] cardinal rotate when a piece is selected (R: 30\u00b0).",
            bg=C["panel"], fg=C["text_dim"], font=("Helvetica", 8),
            wraplength=SIDEBAR_RIGHT_W - 24, justify="left").pack(
                anchor="w", pady=(2, 0))

        save_row = tk.Frame(apbox, bg=C["panel"]); save_row.pack(fill="x", pady=(8, 2))
        label_button(save_row, "Save to library...",
                     self._save_room_dialog, primary=True).pack(fill="x")

        hsep(self.right)

        scroll_frame = tk.Frame(self.right, bg=C["panel"])
        scroll_frame.pack(fill="both", expand=True, padx=6)
        cvs = tk.Canvas(scroll_frame, bg=C["panel"], highlightthickness=0,
                        width=SIDEBAR_RIGHT_W - 30)
        cvs.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(scroll_frame, orient="vertical", command=cvs.yview)
        sb.pack(side="right", fill="y")
        cvs.configure(yscrollcommand=sb.set)
        inner = tk.Frame(cvs, bg=C["panel"])
        cvs.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: cvs.configure(scrollregion=cvs.bbox("all")))
        self._tpl_inner = inner
        self._tpl_canvas = cvs
        self._render_library()
        self._sync_home_button()
        self._bind_wheel_scroll(self._tpl_canvas)

    def _render_library(self):
        for child in self._tpl_inner.winfo_children():
            child.destroy()
        for key, tpl in self.library.all():
            self._make_tpl_item(self._tpl_inner, key, tpl)

    def _sync_back_button(self) -> None:
        if hasattr(self, "_back_btn"):
            self._back_btn.config(
                state=("normal" if self._template_stack else "disabled"))

    def _sync_home_button(self) -> None:
        if not hasattr(self, "_home_btn"):
            return
        can_home = self._browse_home_snapshot is not None
        try:
            self._home_btn.config(state=("normal" if can_home else "disabled"))
        except tk.TclError:
            pass

    def _return_to_active_editing(self) -> None:
        if self._browse_home_snapshot is None:
            return
        if self._wall_mode:
            self._cancel_wall_mode()
        snap, ekey = self._browse_home_snapshot
        self._template_stack.clear()
        self._browse_home_snapshot = None
        self._editing_key = ekey
        self._apply_snapshot(snap)
        if hasattr(self, "_fill_swatch"):
            self._fill_swatch.config(bg=self.template.fill_color)
        if hasattr(self, "_border_swatch"):
            self._border_swatch.config(bg=self.template.border_color)
        if hasattr(self, "_vertex_var"):
            self._vertex_var.set(max(3, min(24, len(self.template.polygon) or 4)))
        self._sync_size_entries_to_bbox()
        self.renderer.reset_zoom()
        self.renderer.fit(self.template)
        self._sync_back_button()
        self._sync_home_button()
        self.shell.set_status("Returned to editing (\u2302 Home).")
        self._redraw()

    def _new_room_from_sidebar(self) -> None:
        if self._wall_mode:
            self._cancel_wall_mode()
        self._new_blank_and_draw()
        self.shell.set_status("New room template — edit and use Save to library when ready.")

    def _pop_template_stack(self) -> None:
        if not self._template_stack:
            return
        if self._wall_mode:
            self._cancel_wall_mode()
        snap, ekey = self._template_stack.pop()
        self._editing_key = ekey
        self._apply_snapshot(snap)
        if hasattr(self, "_fill_swatch"):
            self._fill_swatch.config(bg=self.template.fill_color)
        if hasattr(self, "_border_swatch"):
            self._border_swatch.config(bg=self.template.border_color)
        if hasattr(self, "_vertex_var"):
            self._vertex_var.set(max(3, min(24, len(self.template.polygon) or 4)))
        self._sync_size_entries_to_bbox()
        self.renderer.reset_zoom()
        self.renderer.fit(self.template)
        self._sync_back_button()
        self._sync_home_button()
        self.shell.set_status("Restored previous room from stack.")
        self._redraw()

    def _sync_wall_mode_ui(self) -> None:
        if not hasattr(self, "_draw_wall_btn"):
            return
        if self._wall_mode:
            try:
                self._draw_wall_btn.pack_forget()
            except Exception:
                pass
            self._exit_wall_btn.pack(side="left", padx=1)
            if hasattr(self, "_wall_mode_badge"):
                try:
                    self._wall_mode_badge.pack(side="left", padx=(8, 0))
                except Exception:
                    pass
        else:
            try:
                self._exit_wall_btn.pack_forget()
            except Exception:
                pass
            self._draw_wall_btn.pack(side="left", padx=1)
            if hasattr(self, "_wall_mode_badge"):
                try:
                    self._wall_mode_badge.pack_forget()
                except Exception:
                    pass

    def _make_tpl_item(self, parent, key, tpl):
        outer = tk.Frame(parent, bg=C["panel"])
        outer.pack(fill="x", padx=2, pady=2)
        row = tk.Frame(outer, bg=C["panel"], cursor="hand2")
        row.pack(fill="x")
        thumb = tk.Canvas(row, width=60, height=42,
                          bg=C["panel"], highlightthickness=0)
        thumb.pack(side="left", padx=(2, 4))
        _, _, bw, bh = tpl.bbox()
        pad = 3
        sx = (60 - 2 * pad) / max(1.0, bw)
        sy = (42 - 2 * pad) / max(1.0, bh)
        s = min(sx, sy, 0.4)
        fw = bw * s
        fh = bh * s
        ox = (60 - fw) / 2
        oy = (42 - fh) / 2
        pts: List[float] = []
        for x, y in tpl.polygon:
            pts += [ox + x * s, oy + y * s]
        if pts:
            thumb.create_polygon(*pts, fill=tpl.fill_color,
                                 outline=tpl.border_color, width=1)

        info = tk.Frame(row, bg=C["panel"])
        info.pack(side="left", fill="x", expand=True)
        tk.Label(info, text=tpl.label, bg=C["panel"],
                 font=("Helvetica", 9, "bold"), anchor="w").pack(fill="x")
        tk.Label(info, text=f"[{tpl.roomtype}]",
                 bg=C["panel"], fg=C["text_dim"],
                 font=("Helvetica", 8), anchor="w").pack(fill="x")

        def on_load(_e=None, tkey=key):
            self._load_from_library(tkey, edit=True)

        for w in (row, thumb, info):
            w.bind("<Button-1>", on_load)
            w.bind("<Enter>", lambda e, r=row: r.config(bg=C["accent_lt"]))
            w.bind("<Leave>", lambda e, r=row: r.config(bg=C["panel"]))

        if tpl.furniture:
            furn = tk.Frame(outer, bg=C["panel"])
            furn.pack(fill="x", padx=(66, 2), pady=(2, 0))
            for i, fi in enumerate(tpl.furniture):
                cell = tk.Frame(furn, bg=C["good_lt"], highlightthickness=1,
                                highlightbackground=C["panel_bdr"])
                cell.pack(fill="x", pady=1)
                sw = tk.Label(
                    cell, text="  ", width=2,
                    bg=fi.color or "#CCCCCC", relief="solid", bd=1)
                sw.pack(side="left", padx=4, pady=2)
                txt = f"{i + 1}. {fi.type}  {fi.w:.1f}\u00d7{fi.h:.1f}"
                tk.Label(cell, text=txt, bg=C["good_lt"], fg=C["text"],
                         font=("Helvetica", 8), anchor="w").pack(
                    side="left", fill="x", expand=True)
                del_btn = label_button(
                    cell, "Del", lambda k=key, idx=i: self._delete_furniture_from_library_slot(k, idx))
                del_btn.pack(side="right", padx=2, pady=1)

    def _delete_furniture_from_library_slot(self, key: str, idx: int) -> None:
        tpl = self.library.get(key)
        if tpl is None or not (0 <= idx < len(tpl.furniture)):
            return
        label = tpl.label
        desc = tpl.furniture[idx].type
        if key == self._editing_key:
            self._push_undo()
            del self.template.furniture[idx]
            self.library.update(key, self.template.copy())
            if self._selected_furniture is not None:
                if self._selected_furniture == idx:
                    self._selected_furniture = None
                elif self._selected_furniture > idx:
                    self._selected_furniture -= 1
        else:
            new_tpl = tpl.copy()
            del new_tpl.furniture[idx]
            self.library.update(key, new_tpl)
        self._render_library()
        self.shell.set_status(f"Deleted {desc} from \u2018{label}\u2019.")
        self._redraw()

    def _load_from_library(self, key: str, edit: bool):
        tpl = self.library.get(key)
        if tpl is None:
            return
        if self._wall_mode:
            self._cancel_wall_mode()
        if self._browse_home_snapshot is None:
            self._browse_home_snapshot = (self._snapshot(), self._editing_key)
        self._template_stack.append((self._snapshot(), self._editing_key))
        self._sync_back_button()
        self._sync_home_button()
        self.template = tpl.copy()
        self._editing_key = key if edit else None
        self._selected_furniture = None
        self._selected_vertex = None
        self._selected_wall = None
        self._fill_swatch.config(bg=self.template.fill_color)
        self._border_swatch.config(bg=self.template.border_color)
        if hasattr(self, "_vertex_var"):
            self._vertex_var.set(max(3, min(24, len(self.template.polygon) or 4)))
        self._sync_size_entries_to_bbox()
        self._clear_history()
        self.renderer.reset_zoom()
        self.renderer.fit(self.template)
        self.shell.set_status(
            f"{'Editing' if edit else 'Copied'} \u2018{tpl.label}\u2019 — make changes, then Save Room.")
        self._redraw()

    # ------------------------------------------------------------------
    # Color pickers
    # ------------------------------------------------------------------

    def _pick_fill(self):
        c = tkinter.colorchooser.askcolor(initialcolor=self.template.fill_color,
                                          title="Room fill")
        if c and c[1]:
            self._push_undo()
            self.template.fill_color = c[1]
            self._fill_swatch.config(bg=c[1])
            self._redraw()

    def _pick_border(self):
        c = tkinter.colorchooser.askcolor(initialcolor=self.template.border_color,
                                          title="Room border")
        if c and c[1]:
            self._push_undo()
            self.template.border_color = c[1]
            self._border_swatch.config(bg=c[1])
            self._redraw()

    # ------------------------------------------------------------------
    # Canvas events
    # ------------------------------------------------------------------

    def _bind_canvas(self):
        c = self.canvas
        c.bind("<Button-1>", self._on_click)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Double-Button-1>", self._on_dbl_click)
        c.bind("<Button-3>", self._on_rclick)
        c.bind("<Configure>", self._on_canvas_configure)
        c.bind("<Motion>", self._on_motion)
        c.bind("<Leave>", self._on_canvas_leave)
        c.bind("<Escape>", self._on_author_escape)
        self.bind("<Escape>", self._on_author_escape)
        # Wheel = zoom on the room canvas only (local bind, no bind_all).
        c.bind("<MouseWheel>", self._on_canvas_wheel)       # Windows / macOS
        c.bind("<Button-4>", self._on_canvas_wheel)         # Linux (scroll up)
        c.bind("<Button-5>", self._on_canvas_wheel)         # Linux (scroll down)
        self.bind_all("<Delete>", self._on_delete_key)
        self.bind_all("<BackSpace>", self._on_delete_key)
        # Undo / redo shortcuts (also catch the Shift+Ctrl+Z variant).
        self.bind_all("<Control-z>", self._undo)
        self.bind_all("<Control-Z>", self._undo)
        self.bind_all("<Control-y>", self._redo)
        self.bind_all("<Control-Y>", self._redo)
        self.bind_all("<Control-Shift-z>", self._redo)
        self.bind_all("<Control-Shift-Z>", self._redo)
        # Flip key: f rotates selected Door/Window by 90; Shift+f by 180.
        self.bind_all("<KeyPress-f>", self._on_flip)
        self.bind_all("<KeyPress-F>", self._on_flip)
        self.bind_all("<KeyPress-r>", self._on_rotate_30)
        self.bind_all("<KeyPress-R>", self._on_rotate_30)
        self.bind_all("<KeyPress-bracketleft>", self._on_bracket_rotate_ccw)
        self.bind_all("<KeyPress-bracketright>", self._on_bracket_rotate_cw)

    def _nudge_furniture_rotation(self, idx: int, delta_deg: float) -> bool:
        """Add ``delta_deg`` to furniture ``idx`` rotation if the result is
        valid. On failure (collision / room), sets status and rings the bell.
        """
        if self._wall_mode or self._drag_furniture is not None:
            return False
        if not (0 <= idx < len(self.template.furniture)):
            return False
        fi = self.template.furniture[idx]
        new_r = (float(fi.rotation) + float(delta_deg)) % 360.0
        if not self._is_furniture_placement_valid(
                fi.x, fi.y, fi.w, fi.h, rotation=new_r,
                exclude_idx=idx):
            self.shell.set_status(
                "Can't rotate there — would hit a wall or leave the room.")
            self.canvas.bell()
            return False
        self._push_undo()
        fi.rotation = new_r
        self._redraw()
        return True

    def _on_rotate_30(self, _event=None):
        """R: add 30° to armed placement rotation or to selected furniture."""
        if self._wall_mode or self._drag_furniture is not None:
            return
        if self._selected_furniture is not None:
            idx = self._selected_furniture
            if not (0 <= idx < len(self.template.furniture)):
                return
            if not self._nudge_furniture_rotation(idx, 30.0):
                return "break"
            fi = self.template.furniture[idx]
            self.shell.set_status(
                f"Rotation: {int(fi.rotation)}\u00b0  (R adds 30\u00b0)")
            return "break"
        if self._armed_furniture_key is not None:
            self._armed_rotation = (self._armed_rotation + 30.0) % 360.0
            self.shell.set_status(
                f"Brush rotation: {int(self._armed_rotation)}\u00b0  "
                f"(R adds 30\u00b0; click to place)")
            self._redraw()
            return "break"
        return None

    def _on_author_escape(self, _event=None):
        """Single Escape handler: exit wall mode first, else disarm furniture."""
        if self._wall_mode:
            self._end_wall_mode_internal()
            return "break"
        if self._armed_furniture_key is not None:
            self._disarm_furniture()
            return "break"
        return None

    def _disarm_furniture(self) -> None:
        if self._armed_furniture_key is None:
            return
        self._armed_furniture_key = None
        self._armed_custom_id = None
        self._armed_rotation = 0.0
        self._place_preview = None
        self._opening_edge_glow = None
        self._sync_cancel_placement_button()
        self._redraw()
        self.shell.set_status("Placement mode off. Click a catalog item to arm again.")

    def _sync_cancel_placement_button(self) -> None:
        if not hasattr(self, "_placement_cancel_btn"):
            return
        try:
            st = "normal" if self._armed_furniture_key is not None else "disabled"
            self._placement_cancel_btn.config(state=st)
        except tk.TclError:
            pass

    def _end_wall_mode_internal(self) -> None:
        """Clear wall-drawing state (shared by Exit button, Escape, snapshot)."""
        self._wall_mode = False
        self._wall_start = None
        try:
            self.canvas.config(cursor="")
        except tk.TclError:
            pass
        if self._wall_preview_id is not None:
            try:
                self.canvas.delete(self._wall_preview_id)
            except Exception:
                pass
            self._wall_preview_id = None
        if hasattr(self, "_draw_wall_btn"):
            self._sync_wall_mode_ui()
        self.shell.set_status("Wall mode off. You can place furniture again.")

    def _on_canvas_configure(self, _event):
        # Refit whenever the canvas has been resized (including the
        # first real size allocation after the widget is mapped).
        if self.renderer.needs_refit():
            self.renderer.fit(self.template)
        self._redraw()

    def _first_draw(self):
        self.renderer.fit(self.template)
        self._redraw()

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------

    def _zoom_in(self):
        self.renderer.zoom_by(1.1)
        self._redraw()
        self.shell.set_status(f"Zoom: {int(self.renderer.zoom * 100)}%")

    def _zoom_out(self):
        self.renderer.zoom_by(1.0 / 1.1)
        self._redraw()
        self.shell.set_status(f"Zoom: {int(self.renderer.zoom * 100)}%")

    def _zoom_reset(self):
        self.renderer.reset_zoom()
        self.renderer.fit(self.template)
        self._redraw()
        self.shell.set_status("Zoom: 100%")

    def _on_canvas_wheel(self, event):
        num = getattr(event, "num", 0)
        if num == 4:
            factor = 1.1
        elif num == 5:
            factor = 1.0 / 1.1
        else:
            delta = getattr(event, "delta", 0)
            # Windows: +/-120 per notch; macOS: small signed ints.
            factor = 1.1 if delta > 0 else 1.0 / 1.1
        self.renderer.zoom_by(factor, pivot_canvas=(event.x, event.y))
        self._redraw()
        self.shell.set_status(f"Zoom: {int(self.renderer.zoom * 100)}%")
        return "break"

    def _redraw(self):
        invalid_idx = (self._drag_furniture
                       if (self._drag_furniture is not None and self._drag_invalid)
                       else None)
        place_preview = self._build_place_preview()
        fr = None
        if (self._selected_furniture is not None
                and not self._wall_mode
                and self._armed_furniture_key is None
                and self._drag_furniture is None
                and self._drag_vertex is None):
            fr = self._selected_furniture
        self.renderer.draw(
            self.template,
            selected_vertex=self._selected_vertex,
            selected_furniture=self._selected_furniture,
            selected_wall=self._selected_wall,
            invalid_furniture=invalid_idx,
            drag_preview=self._drag_preview,
            place_preview=place_preview,
            wall_mode=self._wall_mode,
            furniture_resize=fr,
            opening_edge_glow=self._opening_edge_glow,
        )
        self._sync_selection_rotation_sidebar()

    # ------------------------------------------------------------------
    # Placement shadow (armed-brush cursor preview)
    # ------------------------------------------------------------------

    def _armed_dimensions(self) -> Optional[Tuple[float, float, str]]:
        """Return ``(w_world, h_world, color)`` for the currently armed
        brush, or ``None`` if nothing is armed."""
        if self._armed_furniture_key is None:
            return None
        if self._armed_furniture_key == "Custom":
            return (60.0, 60.0, self._armed_color)
        spec = furniture_lib.get(self._armed_furniture_key)
        if spec is None:
            return None
        color = self._armed_color or getattr(spec, "color", "#A0A0A0")
        return (float(spec.w), float(spec.h), color)

    def _build_place_preview(self):
        """Build the ``place_preview`` tuple consumed by the renderer.

        Returns ``(canvas_cx, canvas_cy, w_world, h_world, color, is_valid,
        rot_deg, ghost_x0, ghost_y0, ghost_rot)`` where the last three are
        ``(None, None, None)`` unless a Door/Window snap supplies world
        top-left and rotation for the ghost outline."""
        if self._wall_mode:
            return None
        if self._armed_furniture_key is None or self._place_preview is None:
            return None
        if self._drag_furniture is not None or self._drag_vertex is not None:
            return None
        dims = self._armed_dimensions()
        if dims is None:
            return None
        w, h, color = dims
        cx, cy = self._place_preview
        wx, wy = self.renderer.canvas_to_world(cx, cy)
        x0 = wx - w / 2.0
        y0 = wy - h / 2.0
        rot = self._armed_rotation
        ogx: Optional[float] = None
        ogy: Optional[float] = None
        ogrot: Optional[float] = None
        key = self._armed_furniture_key
        if key in self._EDGE_SNAP_TYPES:
            spec = furniture_lib.get(key)
            if spec is not None:
                fi = FurnitureItem(
                    type=key,
                    x=x0, y=y0, w=spec.w, h=spec.h,
                    color=color, rotation=rot)
                got = self._try_snap_opening(fi, fi.x, fi.y)
                if got is not None:
                    nx, ny, nrot, _e = got
                    rot = nrot
                    ogx, ogy, ogrot = nx, ny, nrot
                    is_valid = True
                else:
                    is_valid = False
            else:
                is_valid = self._is_furniture_placement_valid(
                    x0, y0, w, h, rotation=rot)
        else:
            is_valid = self._is_furniture_placement_valid(
                x0, y0, w, h, rotation=rot)
        return (cx, cy, w, h, color, is_valid, rot, ogx, ogy, ogrot)

    def _on_motion(self, event):
        """Track the cursor for the placement-shadow preview."""
        if self._wall_mode:
            if self._hit_furniture(event.x, event.y) is not None:
                self.canvas.config(cursor="no")
            else:
                self.canvas.config(cursor="crosshair")
            return
        if self._armed_furniture_key is None:
            if self._place_preview is not None:
                self._place_preview = None
                self._opening_edge_glow = None
                self._redraw()
            return
        self._place_preview = (event.x, event.y)
        key = self._armed_furniture_key
        if key in self._EDGE_SNAP_TYPES:
            spec = furniture_lib.get(key)
            if spec is not None:
                fi = FurnitureItem(
                    type=key, x=0, y=0, w=spec.w, h=spec.h,
                    color=self._armed_color, rotation=self._armed_rotation)
                self._opening_edge_glow_from_cursor(fi)
            else:
                self._opening_edge_glow = None
        else:
            self._opening_edge_glow = None
        self._redraw()

    def _on_canvas_leave(self, _event):
        if self._wall_mode:
            self.canvas.config(cursor="crosshair")
        if self._place_preview is not None:
            self._place_preview = None
            self._opening_edge_glow = None
            self._redraw()

    # ------------------------------------------------------------------
    # Undo / redo
    # ------------------------------------------------------------------

    def _snapshot(self) -> dict:
        return self.template.to_dict()

    def _push_undo(self, clear_redo: bool = True) -> None:
        """Record the current template state as an undo checkpoint."""
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > self._undo_cap:
            self._undo_stack.pop(0)
        if clear_redo:
            self._redo_stack.clear()
        self._sync_undo_button()

    def _sync_selection_rotation_sidebar(self) -> None:
        if not hasattr(self, "_sel_rot_lbl"):
            return
        dis = (
            self._wall_mode
            or self._selected_furniture is None
            or self._armed_furniture_key is not None
            or self._drag_furniture is not None
            or not (0 <= self._selected_furniture < len(self.template.furniture))
        )
        if dis:
            self._sel_rot_lbl.config(text="\u2014")
            try:
                self._sel_rot_ccw_btn.config(state="disabled")
                self._sel_rot_cw_btn.config(state="disabled")
            except tk.TclError:
                pass
            return
        fi = self.template.furniture[self._selected_furniture]
        self._sel_rot_lbl.config(text=f"{int(fi.rotation)}\u00b0")
        try:
            self._sel_rot_ccw_btn.config(state="normal")
            self._sel_rot_cw_btn.config(state="normal")
        except tk.TclError:
            pass

    def _rotate_selected_furniture_cardinal(self, delta: int) -> bool:
        if self._wall_mode or self._drag_furniture is not None:
            return False
        if self._selected_furniture is None:
            return False
        idx = self._selected_furniture
        if not (0 <= idx < len(self.template.furniture)):
            return False
        if not self._nudge_furniture_rotation(idx, float(delta)):
            return False
        fi = self.template.furniture[idx]
        self.shell.set_status(
            f"Rotation: {int(fi.rotation)}\u00b0  "
            f"([ / ] \u00b190\u00b0, R +30\u00b0)")
        return True

    def _on_sidebar_rotate_ccw(self, _event=None) -> None:
        self._rotate_selected_furniture_cardinal(-90)

    def _on_sidebar_rotate_cw(self, _event=None) -> None:
        self._rotate_selected_furniture_cardinal(90)

    def _on_bracket_rotate_ccw(self, _event=None) -> Optional[str]:
        if (self._wall_mode or self._drag_furniture is not None
                or self._selected_furniture is None):
            return None
        idx = self._selected_furniture
        if not (0 <= idx < len(self.template.furniture)):
            return None
        self._rotate_selected_furniture_cardinal(-90)
        return "break"

    def _on_bracket_rotate_cw(self, _event=None) -> Optional[str]:
        if (self._wall_mode or self._drag_furniture is not None
                or self._selected_furniture is None):
            return None
        idx = self._selected_furniture
        if not (0 <= idx < len(self.template.furniture)):
            return None
        self._rotate_selected_furniture_cardinal(90)
        return "break"

    def _clear_history(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._sync_undo_button()

    def _apply_snapshot(self, snap: dict) -> None:
        self.template = RoomTemplate.from_dict(snap)
        # Any active drag / selection references indices of the old
        # template list and is no longer valid.
        self._selected_vertex = None
        self._selected_furniture = None
        self._selected_wall = None
        self._drag_vertex = None
        self._drag_furniture = None
        self._drag_wall = None
        self._drag_wall_anchor = None
        self._wall_drag_start = None
        self._drag_wall_last_valid = None
        self._drag_wall_start_pos = None
        self._drag_wall_invalid = False
        self._drag_wall_undo_pushed = False
        self._drag_last_valid = None
        self._drag_start_pos = None
        self._drag_invalid = False
        self._drag_undo_pushed = False
        self._drag_preview = None
        # Cancel wall-draw state if an undo lands in the middle of one.
        self._wall_mode = False
        self._wall_start = None
        if self._wall_preview_id is not None:
            try:
                self.canvas.delete(self._wall_preview_id)
            except Exception:
                pass
            self._wall_preview_id = None
        if hasattr(self, "_draw_wall_btn"):
            self._sync_wall_mode_ui()
        if hasattr(self, "_fill_swatch"):
            self._fill_swatch.config(bg=self.template.fill_color)
        if hasattr(self, "_border_swatch"):
            self._border_swatch.config(bg=self.template.border_color)
        if hasattr(self, "_vertex_var"):
            try:
                n = max(3, min(24, len(self.template.polygon) or 4))
                self._vertex_var.set(n)
            except Exception:
                pass
        self._sync_size_entries_to_bbox()

    def _undo(self, _event=None):
        if not self._undo_stack:
            self.shell.set_status("Nothing to undo.")
            return "break"
        self._redo_stack.append(self._snapshot())
        if len(self._redo_stack) > self._undo_cap:
            self._redo_stack.pop(0)
        self._apply_snapshot(self._undo_stack.pop())
        self._sync_undo_button()
        self._redraw()
        self.shell.set_status(f"Undo \u2713  ({len(self._undo_stack)} left)")
        return "break"

    def _redo(self, _event=None):
        if not self._redo_stack:
            self.shell.set_status("Nothing to redo.")
            return "break"
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > self._undo_cap:
            self._undo_stack.pop(0)
        self._apply_snapshot(self._redo_stack.pop())
        self._sync_undo_button()
        self._redraw()
        self.shell.set_status(f"Redo \u2713  ({len(self._redo_stack)} left)")
        return "break"

    def _sync_undo_button(self) -> None:
        btn = getattr(self, "_undo_btn", None)
        if btn is not None:
            try:
                btn.config(state=("normal" if self._undo_stack else "disabled"))
            except tk.TclError:
                pass
        btn = getattr(self, "_redo_btn", None)
        if btn is not None:
            try:
                btn.config(state=("normal" if self._redo_stack else "disabled"))
            except tk.TclError:
                pass

    # ------------------------------------------------------------------
    # Validity helpers (Issues 2 & 3)
    # ------------------------------------------------------------------

    def _furniture_inside_room(self, x: float, y: float,
                                w: float, h: float,
                                rotation: float = 0.0) -> bool:
        """True when the rotated furniture footprint sits fully inside
        the current room polygon."""
        poly = self.template.polygon
        if not poly or len(poly) < 3:
            return True
        corners = rotated_rect_corners(x, y, w, h, rotation)
        cx = x + w / 2.0
        cy = y + h / 2.0
        samples = list(corners) + [(cx, cy)]
        return all(point_in_polygon(p, poly) for p in samples)

    def _furniture_overlaps_others(
            self, x: float, y: float, w: float, h: float,
            rotation: float = 0.0,
            exclude_idx: Optional[int] = None) -> bool:
        """True when the rotated footprint overlaps another piece's (rotated)
        axis-aligned bounds. Uses tight AABBs in world space so 90° rotations
        are not compared using stale unrotated boxes."""
        minx, miny, maxx, maxy = rotated_rect_bounds(x, y, w, h, rotation)
        for i, fi in enumerate(self.template.furniture):
            if i == exclude_idx:
                continue
            om, oy, oX, oY = rotated_rect_bounds(
                fi.x, fi.y, fi.w, fi.h, float(fi.rotation))
            if not (maxx <= om or oX <= minx or maxy <= oy or oY <= miny):
                return True
        return False

    def _outer_wall_buffer_world(self) -> float:
        """Half of the outer stroke in template space: matches inner half of
        ``ROOM_POLYGON_OUTLINE_PX`` at the current zoom."""
        sc = max(0.01, self.renderer.scale)
        return 0.5 * ROOM_POLYGON_OUTLINE_PX / sc

    def _furniture_hits_walls(
            self, x: float, y: float, w: float, h: float,
            rotation: float = 0.0) -> bool:
        """Rotated furniture footprint: too close to the outer edge or
        intersecting a thickened interior wall (tight AABB vs wall slab)."""
        buf = self._outer_wall_buffer_world()
        minx, miny, maxx, maxy = rotated_rect_bounds(x, y, w, h, rotation)
        rw = maxx - minx
        rh = maxy - miny
        if aabb_too_close_to_poly_edges(
                minx, miny, rw, rh, self.template.polygon, buf):
            return True
        for wall in self.template.walls:
            if thick_segment_overlaps_rect(
                    wall.x0, wall.y0, wall.x1, wall.y1,
                    max(0.0, float(wall.thickness) / 2.0),
                    minx, miny, rw, rh):
                return True
        return False

    def _wall_segment_hits_furniture(
            self, sx: float, sy: float, ex: float, ey: float,
            thickness: float) -> bool:
        half = max(0.0, float(thickness) / 2.0)
        for fi in self.template.furniture:
            minx, miny, maxx, maxy = rotated_rect_bounds(
                fi.x, fi.y, fi.w, fi.h, float(fi.rotation))
            rw = maxx - minx
            rh = maxy - miny
            if thick_segment_overlaps_rect(
                    sx, sy, ex, ey, half, minx, miny, rw, rh):
                return True
        return False

    def _interior_wall_placement_valid(
            self, sx: float, sy: float, ex: float, ey: float,
            thickness: float) -> bool:
        """Wall slab fully inside room polygon and not through furniture."""
        if not interior_wall_fully_inside_room(
                sx, sy, ex, ey, thickness, self.template.polygon):
            return False
        if self._wall_segment_hits_furniture(sx, sy, ex, ey, thickness):
            return False
        return True

    def _is_furniture_placement_valid(self, x: float, y: float,
                                       w: float, h: float,
                                       rotation: float = 0.0,
                                       exclude_idx: Optional[int] = None) -> bool:
        if not self._furniture_inside_room(x, y, w, h, rotation):
            return False
        if self._furniture_hits_walls(x, y, w, h, rotation):
            return False
        if self._furniture_overlaps_others(
                x, y, w, h, rotation=rotation, exclude_idx=exclude_idx):
            return False
        return True

    def _hit_vertex(self, cx, cy) -> Optional[int]:
        for i, (x, y) in enumerate(self.template.polygon):
            px, py = self.renderer.world_to_canvas(x, y)
            if (px - cx) ** 2 + (py - cy) ** 2 <= 8 * 8:
                return i
        return None

    def _hit_edge(self, cx, cy) -> Optional[int]:
        """Return edge index if click is close to an edge."""
        poly = self.template.polygon
        n = len(poly)
        for i in range(n):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % n]
            ax, ay = self.renderer.world_to_canvas(x0, y0)
            bx, by = self.renderer.world_to_canvas(x1, y1)
            # distance from (cx,cy) to segment
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy or 1e-6
            t = max(0.0, min(1.0, ((cx - ax) * dx + (cy - ay) * dy) / L2))
            px = ax + t * dx
            py = ay + t * dy
            if (cx - px) ** 2 + (cy - py) ** 2 <= 6 * 6:
                return i
        return None

    def _hit_furniture(self, cx, cy) -> Optional[int]:
        for i, fi in enumerate(self.template.furniture):
            ax, ay = self.renderer.world_to_canvas(fi.x, fi.y)
            bx = ax + fi.w * self.renderer.scale
            by = ay + fi.h * self.renderer.scale
            if ax <= cx <= bx and ay <= cy <= by:
                return i
        return None

    def _hit_furniture_resize_handle(self, cx, cy) -> Optional[Tuple[int, str]]:
        if self._wall_mode or self._armed_furniture_key is not None:
            return None
        r2 = FURN_HANDLE_PX * FURN_HANDLE_PX
        for i in range(len(self.template.furniture) - 1, -1, -1):
            fi = self.template.furniture[i]
            for hname, wx, wy in furniture_handle_positions(
                    fi.x, fi.y, fi.w, fi.h, float(fi.rotation)):
                pxc, pyc = self.renderer.world_to_canvas(wx, wy)
                if (cx - pxc) ** 2 + (cy - pyc) ** 2 <= r2:
                    return (i, hname)
        return None

    def _hit_wall(self, cx: float, cy: float) -> Optional[int]:
        """Return the topmost interior wall index if (cx,cy) is near its
        centreline in screen space."""
        walls = self.template.walls
        s = self.renderer.scale
        for i in range(len(walls) - 1, -1, -1):
            w = walls[i]
            ax, ay = self.renderer.world_to_canvas(w.x0, w.y0)
            bx, by = self.renderer.world_to_canvas(w.x1, w.y1)
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            if l2 < 1e-6:
                continue
            t = max(0.0, min(1.0, ((cx - ax) * dx + (cy - ay) * dy) / l2))
            px = ax + t * dx
            py = ay + t * dy
            dist = math.hypot(cx - px, cy - py)
            half = max(1.0, float(w.thickness) * s) / 2.0
            if dist <= max(8.0, half + 3.0):
                return i
        return None

    # ------------------------------------------------------------------
    # Snap helpers
    # ------------------------------------------------------------------

    def _snap_world_point(self, world_pt: Tuple[float, float]
                          ) -> Tuple[float, float]:
        """Snap a world point to the nearest polygon vertex (if within
        10 screen-px), else to the global grid."""
        wx, wy = world_pt
        scale = max(0.01, self.renderer.scale)
        thresh2_world = (10.0 / scale) ** 2
        best = None
        best_d2 = thresh2_world
        for vx, vy in self.template.polygon:
            d2 = (vx - wx) ** 2 + (vy - wy) ** 2
            if d2 <= best_d2:
                best_d2 = d2
                best = (float(vx), float(vy))
        if best is not None:
            return best
        return (float(snap_to_grid(wx, GRID_SIZE)),
                float(snap_to_grid(wy, GRID_SIZE)))

    # ------------------------------------------------------------------
    # Door / Window — mandatory wall-edge placement
    # ------------------------------------------------------------------

    _EDGE_SNAP_TYPES = {"Door", "Window"}
    _OPENING_EDGE_INSET = 1.0
    _OPENING_WALL_MAGNET_PX = 20.0
    _OPENING_WALL_NORMAL_EPS = 1.0

    def _opening_edges_by_distance(
            self, cx: float, cy: float,
            ) -> List[Tuple[float, int]]:
        """Edges ``(distance_to_centre, edge_idx)`` sorted nearest first."""
        poly = self.template.polygon
        n = len(poly)
        scored: List[Tuple[float, int]] = []
        for i in range(n):
            ax, ay = poly[i]
            bx, by = poly[(i + 1) % n]
            ddx, ddy = bx - ax, by - ay
            L2 = ddx * ddx + ddy * ddy
            if L2 < 1e-12:
                continue
            t = max(0.0, min(1.0, ((cx - ax) * ddx + (cy - ay) * ddy) / L2))
            qx = ax + t * ddx
            qy = ay + t * ddy
            d = math.hypot(qx - cx, qy - cy)
            scored.append((d, i))
        scored.sort(key=lambda t: t[0])
        return scored

    def _try_snap_opening(self, fi: FurnitureItem, x: float, y: float
                          ) -> Optional[Tuple[float, float, float, int]]:
        """Snap Door/Window to the best valid polygon edge. Returns
        ``(new_x, new_y, rotation, edge_idx)`` or ``None``."""
        poly = self.template.polygon
        if len(poly) < 2 or fi.type not in self._EDGE_SNAP_TYPES:
            return None
        cx = x + fi.w / 2.0
        cy = y + fi.h / 2.0
        scale = max(0.01, self.renderer.scale)
        scored_edges = self._opening_edges_by_distance(cx, cy)
        if not scored_edges:
            return None
        if scored_edges[0][0] * scale > self._OPENING_WALL_MAGNET_PX:
            return None
        margin = self._OPENING_EDGE_INSET
        bbx, bby, bbw, bbh = self.template.bbox()
        poly_cx = bbx + bbw / 2.0
        poly_cy = bby + bbh / 2.0
        for _dist, edge_idx in scored_edges:
            ax, ay = poly[edge_idx]
            bx, by = poly[(edge_idx + 1) % len(poly)]
            dx, dy = (bx - ax), (by - ay)
            L = math.hypot(dx, dy)
            if L < 1e-6:
                continue
            tx, ty = dx / L, dy / L
            nx, ny = -ty, tx
            theta = math.degrees(math.atan2(dy, dx)) % 360.0
            candidates = [0, 90, 180, 270]
            best_rot = float(min(
                candidates,
                key=lambda c: min(abs((theta - c) % 360),
                                 abs((c - theta) % 360))))
            if best_rot in (90.0, 270.0):
                eff_w, eff_h = fi.h, fi.w
            else:
                eff_w, eff_h = fi.w, fi.h
            if L + 1e-6 < eff_w + 2 * margin:
                continue
            t = max(0.0, min(1.0, ((cx - ax) * dx + (cy - ay) * dy) / (L * L)))
            qx = ax + t * dx
            qy = ay + t * dy
            if (poly_cx - qx) * nx + (poly_cy - qy) * ny < 0:
                nx, ny = -nx, -ny
            s_raw = (qx - ax) * tx + (qy - ay) * ty
            s_raw = max(0.0, min(L, s_raw))
            lo = eff_w / 2.0 + margin
            hi = L - eff_w / 2.0 - margin
            if lo > hi + 1e-6:
                continue
            s = max(lo, min(hi, s_raw))
            base_cx = ax + tx * s
            base_cy = ay + ty * s
            for inset in (0.0, self._OPENING_WALL_NORMAL_EPS):
                new_cx = base_cx + nx * inset
                new_cy = base_cy + ny * inset
                new_x = new_cx - fi.w / 2.0
                new_y = new_cy - fi.h / 2.0
                if self._is_furniture_placement_valid(
                        new_x, new_y, fi.w, fi.h, rotation=best_rot):
                    return (new_x, new_y, best_rot, edge_idx)
        return None

    def _maybe_snap_to_edge(self, fi: FurnitureItem, x: float, y: float
                            ) -> Tuple[float, float, float]:
        """Door/Window: snap to a wall edge or keep position if none fits."""
        if fi.type not in self._EDGE_SNAP_TYPES:
            return x, y, fi.rotation
        got = self._try_snap_opening(fi, x, y)
        if got is None:
            return x, y, fi.rotation
        return got[0], got[1], got[2]

    def _opening_edge_glow_from_cursor(self, fi: FurnitureItem) -> None:
        """Set ``_opening_edge_glow`` for hover feedback while armed."""
        poly = self.template.polygon
        if (self._place_preview is None or len(poly) < 2
                or fi.type not in self._EDGE_SNAP_TYPES):
            self._opening_edge_glow = None
            return
        cx_canvas, cy_canvas = self._place_preview
        wx, wy = self.renderer.canvas_to_world(cx_canvas, cy_canvas)
        x0 = wx - fi.w / 2.0
        y0 = wy - fi.h / 2.0
        got = self._try_snap_opening(fi, x0, y0)
        if got is not None:
            self._opening_edge_glow = (got[3], True)
            return
        scored = self._opening_edges_by_distance(wx, wy)
        if not scored:
            self._opening_edge_glow = None
        else:
            self._opening_edge_glow = (scored[0][1], False)

    # ------------------------------------------------------------------
    # Wall tool (interior walls; see right sidebar: Draw interior walls)
    # ------------------------------------------------------------------

    def _enter_wall_mode(self):
        """Start wall-drawing: thickness matches outer polygon stroke at this zoom."""
        if self._wall_mode:
            return
        self._armed_furniture_key = None
        self._armed_custom_id = None
        self._armed_rotation = 0.0
        self._place_preview = None
        self._opening_edge_glow = None
        self._sync_cancel_placement_button()
        self._selected_wall = None
        self._drag_wall = None
        self._drag_wall_anchor = None
        self._wall_drag_start = None
        self._drag_wall_last_valid = None
        self._drag_wall_start_pos = None
        self._drag_wall_invalid = False
        self._drag_wall_undo_pushed = False
        self._selected_furniture = None
        self._selected_vertex = None
        self._resize_furniture = None
        self._resize_drag_started = False
        self._pending_wall_thickness_px = room_outline_thickness_template(
            self.renderer.scale)
        self._wall_mode = True
        self._wall_start = None
        self.focus_set()
        try:
            self.canvas.config(cursor="crosshair")
        except tk.TclError:
            pass
        self._redraw()  # clear placement shadow
        self._sync_wall_mode_ui()
        self.shell.set_status(
            "INTERIOR WALL MODE \u2014 draw segments on the canvas. "
            "Furniture and most room tools are off until you exit (Esc, Exit, or the sidebar).")

    def _cancel_wall_mode(self, _event=None):
        self._end_wall_mode_internal()
        return "break"

    def _on_click(self, event):
        cx, cy = event.x, event.y

        if self._wall_mode:
            if self._hit_furniture(cx, cy) is not None:
                self.canvas.bell()
                self.shell.set_status(
                    "Exit wall mode to select or place furniture. "
                    "You cannot use furniture while drawing walls.")
                return
            wx, wy = self.renderer.canvas_to_world(cx, cy)
            self._wall_start = self._snap_world_point((wx, wy))
            return

        # Prioritise vertex handle
        v = self._hit_vertex(cx, cy)
        if v is not None:
            self._drag_vertex = v
            self._drag_undo_pushed = False
            self._selected_vertex = v
            self._selected_furniture = None
            self._selected_wall = None
            self._redraw()
            return

        # Furniture resize handle (8-way)
        rh = self._hit_furniture_resize_handle(cx, cy)
        if rh is not None and self._armed_furniture_key is None:
            ridx, hname = rh
            self._selected_furniture = ridx
            self._selected_vertex = None
            self._selected_wall = None
            self._resize_furniture = (ridx, hname)
            self._resize_drag_started = False
            self._redraw()
            return

        # Furniture hit?
        fi_idx = self._hit_furniture(cx, cy)
        if fi_idx is not None and self._armed_furniture_key is None:
            self._drag_furniture = fi_idx
            self._selected_furniture = fi_idx
            self._selected_vertex = None
            self._selected_wall = None
            # grip offset relative to item
            fi = self.template.furniture[fi_idx]
            ax, ay = self.renderer.world_to_canvas(fi.x, fi.y)
            self._drag_offset = (cx - ax, cy - ay)
            # Remember starting / last-valid position for Issues 2 & 3.
            self._drag_start_pos = (fi.x, fi.y)
            self._drag_last_valid = (fi.x, fi.y)
            self._drag_invalid = False
            self._drag_undo_pushed = False
            self._redraw()
            return

        # Interior wall (select + drag) when not placing from catalog
        wi = self._hit_wall(cx, cy)
        if wi is not None and self._armed_furniture_key is None:
            self._drag_wall = wi
            self._selected_wall = wi
            self._selected_vertex = None
            self._selected_furniture = None
            w = self.template.walls[wi]
            wx, wy = self.renderer.canvas_to_world(cx, cy)
            self._drag_wall_anchor = (wx, wy)
            self._wall_drag_start = (w.x0, w.y0, w.x1, w.y1)
            self._drag_wall_last_valid = (
                w.x0, w.y0, w.x1, w.y1)
            self._drag_wall_start_pos = (
                w.x0, w.y0, w.x1, w.y1)
            self._drag_wall_invalid = False
            self._drag_wall_undo_pushed = False
            self.shell.set_status(
                "Wall selected. Drag to move, Delete to remove.")
            self._redraw()
            return

        # Armed to place furniture?
        if self._armed_furniture_key is not None:
            wx, wy = self.renderer.canvas_to_world(cx, cy)
            key = self._armed_furniture_key
            if key == "Custom":
                fi = FurnitureItem(
                    type="Custom", x=wx - 30, y=wy - 30, w=60, h=60,
                    color=self._armed_color, custom_id=self._armed_custom_id,
                    rotation=self._armed_rotation)
            else:
                spec = furniture_lib.get(key)
                if spec is None:
                    return
                fi = FurnitureItem(
                    type=key,
                    x=wx - spec.w / 2, y=wy - spec.h / 2,
                    w=spec.w, h=spec.h,
                    color=self._armed_color,
                    rotation=self._armed_rotation)
            if fi.type in self._EDGE_SNAP_TYPES:
                got = self._try_snap_opening(fi, fi.x, fi.y)
                if got is None:
                    ccx = fi.x + fi.w / 2.0
                    ccy = fi.y + fi.h / 2.0
                    sc = max(0.01, self.renderer.scale)
                    near = self._opening_edges_by_distance(ccx, ccy)
                    if near and near[0][0] * sc > self._OPENING_WALL_MAGNET_PX:
                        self.shell.set_status(
                            "Windows/doors must be placed ON walls.")
                    else:
                        self.shell.set_status(
                            "Door/Window must go on a wall edge; segment too "
                            "short or no valid spot against interior walls / "
                            "overlap.")
                    self.canvas.bell()
                    return
                fi.x, fi.y, fi.rotation = got[0], got[1], got[2]
            # Validate placement: reject if outside room, walls, or overlapping.
            if not self._furniture_inside_room(
                    fi.x, fi.y, fi.w, fi.h, fi.rotation):
                self.shell.set_status(
                    "Can't place there — furniture must sit inside the room.")
                self.canvas.bell()
                return
            if self._furniture_hits_walls(
                    fi.x, fi.y, fi.w, fi.h, fi.rotation):
                self.shell.set_status(
                    "Can't place there — too close to the outer wall or overlapping "
                    "an interior wall.")
                self.canvas.bell()
                return
            if self._furniture_overlaps_others(
                    fi.x, fi.y, fi.w, fi.h, rotation=fi.rotation):
                self.shell.set_status(
                    "Can't place there — it would overlap another item.")
                self.canvas.bell()
                return
            self._push_undo()
            self.template.furniture.append(fi)
            self._selected_furniture = len(self.template.furniture) - 1
            self._selected_vertex = None
            self._selected_wall = None
            self._redraw()
            return

        # Nothing hit: clear selection
        self._selected_vertex = None
        self._selected_furniture = None
        self._selected_wall = None
        self._redraw()

    def _on_drag(self, event):
        cx, cy = event.x, event.y

        if self._resize_furniture is not None:
            idx, hname = self._resize_furniture
            if not (0 <= idx < len(self.template.furniture)):
                return
            if not self._resize_drag_started:
                self._push_undo()
                self._resize_drag_started = True
            fi = self.template.furniture[idx]
            wx, wy = self.renderer.canvas_to_world(cx, cy)
            wx = float(snap_to_grid(wx, GRID_SIZE))
            wy = float(snap_to_grid(wy, GRID_SIZE))
            out = apply_resize(
                fi.x, fi.y, fi.w, fi.h, float(fi.rotation), hname, wx, wy)
            if out is not None:
                nx, ny, nw, nh = out
                if self._is_furniture_placement_valid(
                        nx, ny, nw, nh, rotation=fi.rotation,
                        exclude_idx=idx):
                    fi.x, fi.y, fi.w, fi.h = nx, ny, nw, nh
            self._redraw()
            return

        if self._wall_mode and self._wall_start is not None:
            wx, wy = self.renderer.canvas_to_world(cx, cy)
            sx, sy = self._snap_world_point((wx, wy))
            if self._wall_preview_id is not None:
                try:
                    self.canvas.delete(self._wall_preview_id)
                except Exception:
                    pass
                self._wall_preview_id = None
            a_cx, a_cy = self.renderer.world_to_canvas(*self._wall_start)
            b_cx, b_cy = self.renderer.world_to_canvas(sx, sy)
            wx0, wy0 = self._wall_start
            thw = room_outline_thickness_template(self.renderer.scale)
            w_ok = self._interior_wall_placement_valid(
                wx0, wy0, sx, sy, thw)
            line_fill = "#6E6E6A" if w_ok else "#C24141"
            self._wall_preview_id = self.canvas.create_line(
                a_cx, a_cy, b_cx, b_cy,
                fill=line_fill, width=2, dash=(5, 3))
            return

        if self._drag_vertex is not None:
            if not self._drag_undo_pushed:
                self._push_undo()
                self._drag_undo_pushed = True
            wx, wy = self.renderer.canvas_to_world(cx, cy)
            self.template.polygon[self._drag_vertex] = (
                float(snap_to_grid(wx, GRID_SIZE)),
                float(snap_to_grid(wy, GRID_SIZE)),
            )
            self._redraw()
            return
        if self._drag_furniture is not None:
            if not self._drag_undo_pushed:
                self._push_undo()
                self._drag_undo_pushed = True
            wx, wy = self.renderer.canvas_to_world(
                cx - self._drag_offset[0], cy - self._drag_offset[1])
            fi = self.template.furniture[self._drag_furniture]
            new_x = round(wx / 5) * 5
            new_y = round(wy / 5) * 5
            new_rot = fi.rotation
            # Door/Window: edge snap while dragging.
            if fi.type in self._EDGE_SNAP_TYPES:
                new_x, new_y, new_rot = self._maybe_snap_to_edge(
                    fi, new_x, new_y)
            is_valid = self._is_furniture_placement_valid(
                new_x, new_y, fi.w, fi.h, rotation=new_rot,
                exclude_idx=self._drag_furniture)
            if is_valid:
                fi.x = new_x
                fi.y = new_y
                fi.rotation = new_rot
                self._drag_last_valid = (new_x, new_y)
                self._drag_invalid = False
            else:
                # Freeze the item at its last valid position and show a
                # red outline as feedback.
                if self._drag_last_valid is not None:
                    fi.x, fi.y = self._drag_last_valid
                self._drag_invalid = True
            # Ghost preview at the candidate (unclamped) position.
            self._drag_preview = (self._drag_furniture,
                                   new_x, new_y, is_valid)
            self._redraw()
            return
        if self._drag_wall is not None:
            if not self._drag_wall_undo_pushed:
                self._push_undo()
                self._drag_wall_undo_pushed = True
            idx = self._drag_wall
            w = self.template.walls[idx]
            awx, awy = self._drag_wall_anchor
            cur = self.renderer.canvas_to_world(cx, cy)
            ddx = cur[0] - awx
            ddy = cur[1] - awy
            s0x, s0y, s1x, s1y = self._wall_drag_start
            n0x = float(snap_to_grid(s0x + ddx, GRID_SIZE))
            n0y = float(snap_to_grid(s0y + ddy, GRID_SIZE))
            n1x = float(snap_to_grid(s1x + ddx, GRID_SIZE))
            n1y = float(snap_to_grid(s1y + ddy, GRID_SIZE))
            th = float(w.thickness)
            if self._interior_wall_placement_valid(
                    n0x, n0y, n1x, n1y, th):
                w.x0, w.y0, w.x1, w.y1 = n0x, n0y, n1x, n1y
                self._drag_wall_last_valid = (n0x, n0y, n1x, n1y)
                self._drag_wall_invalid = False
            else:
                if self._drag_wall_last_valid is not None:
                    lv = self._drag_wall_last_valid
                    w.x0 = lv[0]
                    w.y0 = lv[1]
                    w.x1 = lv[2]
                    w.y1 = lv[3]
                self._drag_wall_invalid = True
            self._redraw()
            return

    def _on_release(self, event):
        if self._resize_furniture is not None:
            self._resize_furniture = None
            self._resize_drag_started = False
            self._redraw()
            return
        if self._wall_mode and self._wall_start is not None:
            cx, cy = event.x, event.y
            wx, wy = self.renderer.canvas_to_world(cx, cy)
            ex, ey = self._snap_world_point((wx, wy))
            sx, sy = self._wall_start
            # clear the preview
            if self._wall_preview_id is not None:
                try:
                    self.canvas.delete(self._wall_preview_id)
                except Exception:
                    pass
                self._wall_preview_id = None
            # only commit if there's actual length
            if (abs(ex - sx) > 1e-3 or abs(ey - sy) > 1e-3):
                th = room_outline_thickness_template(self.renderer.scale)
                if not interior_wall_fully_inside_room(
                        sx, sy, ex, ey, th, self.template.polygon):
                    self.shell.set_status(
                        "Wall must stay inside the room — not placed.")
                    self.canvas.bell()
                elif self._wall_segment_hits_furniture(sx, sy, ex, ey, th):
                    self.shell.set_status(
                        "Wall would cross furniture — not placed.")
                    self.canvas.bell()
                else:
                    self._push_undo()
                    self.template.walls.append(Wall(
                        x0=sx, y0=sy, x1=ex, y1=ey,
                        thickness=th,
                        color=self.template.border_color,
                    ))
                    self._pending_wall_thickness_px = th
                    self.shell.set_status(
                        f"Wall added. {len(self.template.walls)} wall(s) total. "
                        f"Use Exit wall mode or Esc to finish drawing walls.")
            self._wall_start = None
            self._redraw()
            return

        if self._drag_vertex is not None:
            self.template.normalise()
        if self._drag_furniture is not None:
            fi = self.template.furniture[self._drag_furniture]
            # Defensive snap-back: ensure final position is valid.
            if not self._is_furniture_placement_valid(
                    fi.x, fi.y, fi.w, fi.h, rotation=fi.rotation,
                    exclude_idx=self._drag_furniture):
                target = self._drag_last_valid or self._drag_start_pos
                if target is not None:
                    fi.x, fi.y = target
        if self._drag_wall is not None:
            idx = self._drag_wall
            if 0 <= idx < len(self.template.walls):
                w = self.template.walls[idx]
                if self._drag_wall_invalid:
                    lv = self._drag_wall_last_valid or self._drag_wall_start_pos
                    if lv is not None:
                        w.x0, w.y0, w.x1, w.y1 = lv[0], lv[1], lv[2], lv[3]
                self._selected_wall = idx
            else:
                self._selected_wall = None
            self._drag_wall = None
            self._drag_wall_anchor = None
            self._wall_drag_start = None
            self._drag_wall_last_valid = None
            self._drag_wall_start_pos = None
            self._drag_wall_invalid = False
            self._drag_wall_undo_pushed = False
        self._drag_vertex = None
        self._drag_furniture = None
        self._drag_last_valid = None
        self._drag_start_pos = None
        self._drag_invalid = False
        self._drag_undo_pushed = False
        self._drag_preview = None
        self._redraw()

    def _on_dbl_click(self, event):
        if self._wall_mode:
            self.canvas.bell()
            self.shell.set_status(
                "Exit wall mode to add vertices, edit furniture, or use other tools.")
            return
        cx, cy = event.x, event.y
        edge = self._hit_edge(cx, cy)
        if edge is not None:
            self._push_undo()
            poly = self.template.polygon
            n = len(poly)
            x0, y0 = poly[edge]
            x1, y1 = poly[(edge + 1) % n]
            mid = (float(snap_to_grid((x0 + x1) / 2.0, GRID_SIZE)),
                   float(snap_to_grid((y0 + y1) / 2.0, GRID_SIZE)))
            poly.insert(edge + 1, mid)
            self.template.polygon = poly
            self._selected_vertex = edge + 1
            self._selected_furniture = None
            self._selected_wall = None
            self._redraw()
            return
        fi_idx = self._hit_furniture(cx, cy)
        if fi_idx is not None:
            self._edit_furniture_size(fi_idx)

    def _edit_furniture_size(self, idx):
        fi = self.template.furniture[idx]
        dlg = tk.Toplevel(self)
        dlg.title("Furniture size")
        dlg.configure(bg=C["panel"])
        dlg.transient(self)
        frm = tk.Frame(dlg, bg=C["panel"], padx=12, pady=10)
        frm.pack()
        ws = tk.DoubleVar(value=fi.w); hs = tk.DoubleVar(value=fi.h)
        tk.Label(frm, text="Width (px)", bg=C["panel"]).grid(row=0, column=0, sticky="w")
        tk.Entry(frm, textvariable=ws, width=8).grid(row=0, column=1, padx=4)
        tk.Label(frm, text="Height (px)", bg=C["panel"]).grid(row=1, column=0, sticky="w")
        tk.Entry(frm, textvariable=hs, width=8).grid(row=1, column=1, padx=4)
        def apply_():
            self._push_undo()
            try:
                fi.w = float(ws.get()); fi.h = float(hs.get())
            except Exception:
                pass
            dlg.destroy()
            self._redraw()
        label_button(frm, "Apply", apply_, primary=True).grid(
            row=2, column=0, columnspan=2, pady=8)

    def _on_furniture_context_rotate_45(self, fi_idx: int) -> None:
        """Context menu: add 45° clockwise per use."""
        if not self._nudge_furniture_rotation(fi_idx, 45.0):
            return
        fi = self.template.furniture[fi_idx]
        self.shell.set_status(
            f"Rotation: {int(fi.rotation)}\u00b0  (right-click: +45\u00b0 each time)")

    def _on_rclick(self, event):
        if self._wall_mode:
            self.canvas.bell()
            self.shell.set_status(
                "Exit wall mode to remove vertices or use other context actions.")
            return
        if self._armed_furniture_key is not None:
            self._disarm_furniture()
            return
        if self._drag_furniture is not None:
            return
        fi_idx = self._hit_furniture(event.x, event.y)
        if fi_idx is not None:
            self._selected_furniture = fi_idx
            self._selected_vertex = None
            self._selected_wall = None
            self._redraw()
            # Toplevel parent avoids some Windows/Win32 cases where a Frame-owned
            # menu fails to run commands; grab_release only if the menu held grab.
            top = self.winfo_toplevel()
            m = tk.Menu(top, tearoff=0)
            m.add_command(
                label="Rotate 45\u00b0 clockwise",
                command=lambda i=fi_idx: self._on_furniture_context_rotate_45(i))
            try:
                self.update_idletasks()
                m.tk_popup(event.x_root, event.y_root)
            finally:
                try:
                    m.grab_release()
                except tk.TclError:
                    pass
            return
        v = self._hit_vertex(event.x, event.y)
        if v is not None and len(self.template.polygon) > 3:
            self._push_undo()
            del self.template.polygon[v]
            self.template.normalise()
            self._selected_vertex = None
            self._redraw()

    def _on_delete_key(self, _event):
        if self._selected_wall is not None:
            idx = self._selected_wall
            if 0 <= idx < len(self.template.walls):
                self._push_undo()
                del self.template.walls[idx]
                n = len(self.template.walls)
                self.shell.set_status(
                    f"Wall removed. {n} interior wall(s) left.")
            self._selected_wall = None
            self._redraw()
            return
        if self._selected_furniture is not None:
            self._push_undo()
            del self.template.furniture[self._selected_furniture]
            self._selected_furniture = None
            self._redraw()

    def _delete_selection(self):
        self._on_delete_key(None)

    def _on_flip(self, event):
        """Rotate the selected Door/Window by 90° (or 180° with Shift)."""
        if self._selected_furniture is None:
            return
        idx = self._selected_furniture
        if not (0 <= idx < len(self.template.furniture)):
            return
        fi = self.template.furniture[idx]
        if fi.type not in self._EDGE_SNAP_TYPES:
            return
        # Tk reports Shift in event.state bit 0x0001 on all platforms.
        shift = bool(getattr(event, "state", 0) & 0x0001)
        # A capital-F keysym also implies shift.
        if not shift and getattr(event, "keysym", "") == "F":
            shift = True
        step = 180 if shift else 90
        self._push_undo()
        fi.rotation = (fi.rotation + step) % 360
        self.shell.set_status(f"Rotation: {int(fi.rotation)}\u00b0")
        self._redraw()
        return "break"

    # ------------------------------------------------------------------
    # File actions
    # ------------------------------------------------------------------

    def _new_blank_template(self):
        self.template = RoomTemplate.rectangle(
            "New Room", 300, 220,
            roomtype="bedroom",
            fill_color="#EBF3FB",
            border_color="#378ADD",
        )
        self._editing_key = None

    def _new_blank_and_draw(self):
        if self._wall_mode:
            self._cancel_wall_mode()
        self._new_blank_template()
        self._template_stack.clear()
        self._browse_home_snapshot = None
        self._sync_back_button()
        self._sync_home_button()
        self._selected_furniture = None
        self._selected_vertex = None
        self._selected_wall = None
        self._fill_swatch.config(bg=self.template.fill_color)
        self._border_swatch.config(bg=self.template.border_color)
        if hasattr(self, "_vertex_var"):
            self._vertex_var.set(max(3, min(24, len(self.template.polygon) or 4)))
        self._sync_size_entries_to_bbox()
        self._clear_history()
        self.renderer.reset_zoom()
        self._first_draw()

    def _reset_shape(self):
        self._reshape_to_n(4)

    def _on_reshape_clicked(self):
        try:
            n = int(self._vertex_var.get())
        except Exception:
            n = 4
        n = max(3, min(24, n))
        self._reshape_to_n(n)
        self.shell.set_status(f"Reshaped to {n}-sided polygon.")

    # ------------------------------------------------------------------
    # Base size (Author-only): uniform scale + target W/H
    # ------------------------------------------------------------------

    def _sync_size_entries_to_bbox(self) -> None:
        """Pre-fill the W/H entries with the current bbox in feet."""
        if not hasattr(self, "_size_w_var"):
            return
        try:
            _, _, bw, bh = self.template.bbox()
            self._size_w_var.set(f"{px_to_ft(bw):.1f}")
            self._size_h_var.set(f"{px_to_ft(bh):.1f}")
        except Exception:
            pass

    def _on_apply_scale_clicked(self) -> None:
        try:
            s = float(self._scale_var.get())
        except Exception:
            s = 1.0
        s = max(0.05, min(10.0, s))
        if abs(s - 1.0) < 1e-4:
            self.shell.set_status("Scale unchanged.")
            return
        self._apply_uniform_scale(s)
        self._scale_var.set(1.0)
        self.shell.set_status(f"Scaled by {s:.2f}x.")

    def _on_resize_clicked(self) -> None:
        try:
            w_ft = float(self._size_w_var.get())
            h_ft = float(self._size_h_var.get())
        except Exception:
            self.shell.set_status("Enter numeric W/H in feet.")
            return
        if w_ft <= 0 or h_ft <= 0:
            self.shell.set_status("W/H must be positive.")
            return
        self._apply_target_size_ft(w_ft, h_ft)

    def _apply_uniform_scale(self, s: float) -> None:
        """Scale the polygon, walls, and furniture uniformly by ``s``
        about the template origin. One undo frame."""
        self._push_undo()
        self.template.polygon = [(x * s, y * s)
                                 for (x, y) in self.template.polygon]
        for w in self.template.walls:
            w.x0 *= s; w.y0 *= s; w.x1 *= s; w.y1 *= s
            w.thickness *= s
        for f in self.template.furniture:
            f.x *= s; f.y *= s; f.w *= s; f.h *= s
        self.template.normalise()
        self._selected_vertex = None
        self._selected_furniture = None
        self._selected_wall = None
        self.renderer.fit(self.template)
        self._sync_size_entries_to_bbox()
        self._redraw()

    def _apply_target_size_ft(self, w_ft: float, h_ft: float) -> None:
        """Scale the template so its bbox matches the target W/H (feet).
        Independent X/Y scale factors. One undo frame."""
        target_w = float(ft_to_px(w_ft))
        target_h = float(ft_to_px(h_ft))
        _, _, bw, bh = self.template.bbox()
        if bw <= 0 or bh <= 0:
            self.shell.set_status("Cannot resize an empty template.")
            return
        sx = target_w / bw
        sy = target_h / bh
        if abs(sx - 1.0) < 1e-4 and abs(sy - 1.0) < 1e-4:
            self.shell.set_status("Size unchanged.")
            return
        self._push_undo()
        self.template.polygon = [(x * sx, y * sy)
                                 for (x, y) in self.template.polygon]
        for w in self.template.walls:
            w.x0 *= sx; w.y0 *= sy; w.x1 *= sx; w.y1 *= sy
            # Use the geometric mean for thickness so it scales sensibly
            # under non-uniform stretches.
            w.thickness *= math.sqrt(max(1e-6, sx * sy))
        for f in self.template.furniture:
            f.x *= sx; f.y *= sy
            f.w *= sx; f.h *= sy
        self.template.normalise()
        self._selected_vertex = None
        self._selected_furniture = None
        self._selected_wall = None
        self.renderer.fit(self.template)
        self._sync_size_entries_to_bbox()
        self._redraw()
        self.shell.set_status(
            f"Resized to {w_ft:.1f} x {h_ft:.1f} ft.")

    def _reshape_to_n(self, n: int) -> None:
        """Replace the polygon with a regular N-gon inscribed in the
        current bbox (or a 300x220 default for blank rooms). Pushes a
        single undo frame covering the whole change."""
        self._push_undo()
        _, _, w, h = self.template.bbox()
        if w <= 0 or h <= 0:
            w, h = 300.0, 220.0
        # Keep the bbox rectangular for N-gons so the inscribed circle
        # sits on a sensible radius.
        w = max(80.0, float(w))
        h = max(80.0, float(h))
        poly = regular_polygon(n, (0.0, 0.0, w, h), grid=GRID_SIZE)
        self.template.polygon = [tuple(p) for p in poly]
        self.template.preset_id = None  # preset interiors no longer map
        self.template.normalise()
        self._selected_vertex = None
        self._selected_furniture = None
        self._selected_wall = None
        if hasattr(self, "_vertex_var"):
            try:
                self._vertex_var.set(len(self.template.polygon))
            except Exception:
                pass
        self._redraw()

    def _recenter(self):
        self.renderer.reset_zoom()
        self._first_draw()

    def _save_room_dialog(self):
        known_types = list(DEFAULT_ROOMTYPES)
        for t in self.library.roomtypes():
            if t not in known_types:
                known_types.append(t)

        dlg = tk.Toplevel(self)
        dlg.title("Save Room")
        dlg.configure(bg=C["panel"])
        dlg.transient(self); dlg.grab_set()

        frm = tk.Frame(dlg, bg=C["panel"], padx=14, pady=10)
        frm.pack()
        tk.Label(frm, text="Title", bg=C["panel"]).grid(row=0, column=0, sticky="w")
        title_var = tk.StringVar(value=self.template.label)
        tk.Entry(frm, textvariable=title_var, width=26).grid(
            row=0, column=1, padx=4, pady=2)

        tk.Label(frm, text="Room type", bg=C["panel"]).grid(
            row=1, column=0, sticky="w")
        rt_var = tk.StringVar(value=self.template.roomtype)
        rt_cbo = ttk.Combobox(frm, textvariable=rt_var, values=known_types, width=22)
        rt_cbo.grid(row=1, column=1, padx=4, pady=2)

        overwrite_var = tk.IntVar(value=1 if self._editing_key else 0)
        tk.Checkbutton(frm, text="Overwrite existing (when editing)",
                       variable=overwrite_var, bg=C["panel"]).grid(
            row=2, column=0, columnspan=2, sticky="w")

        err = tk.Label(frm, text="", bg=C["panel"], fg=C["bad"])
        err.grid(row=3, column=0, columnspan=2, sticky="w")

        btns = tk.Frame(frm, bg=C["panel"])
        btns.grid(row=4, column=0, columnspan=2, pady=(8, 0))

        def do_save():
            t = title_var.get().strip() or "Untitled Room"
            rt = rt_var.get().strip() or "other"
            self.template.label = t
            self.template.roomtype = rt
            self.template.normalise()
            if self._editing_key and overwrite_var.get():
                self.library.update(self._editing_key, self.template.copy())
                self.shell.set_status(f"Updated \u2018{t}\u2019.")
            else:
                self._editing_key = self.library.add(self.template.copy())
                self.shell.set_status(f"Saved \u2018{t}\u2019 to library.")
            self._render_library()
            dlg.destroy()

        label_button(btns, "Save", do_save, primary=True).pack(side="left", padx=4)
        label_button(btns, "Cancel", dlg.destroy).pack(side="left", padx=4)

    # ------------------------------------------------------------------
    # Custom furniture
    # ------------------------------------------------------------------

    def _new_custom_dialog(self):
        CustomFurnitureEditor(self, on_save=self._after_custom_save)

    def _manage_custom(self):
        store = get_cf_store()
        items = store.all()
        if not items:
            messagebox.showinfo("Custom Furniture",
                                "No custom furniture yet. Click '+ New Furniture...' to create.")
            return
        dlg = tk.Toplevel(self)
        dlg.title("Manage Custom Furniture")
        dlg.configure(bg=C["panel"]); dlg.transient(self)
        for cf in items:
            row = tk.Frame(dlg, bg=C["panel"])
            row.pack(fill="x", padx=10, pady=2)
            tk.Label(row, text=cf.label, bg=C["panel"]).pack(side="left")
            def on_del(cfid=cf.id, d=dlg):
                store.remove(cfid)
                d.destroy()
                self._render_catalog()
            def on_edit(cfid=cf.id, d=dlg):
                CustomFurnitureEditor(self, editing_id=cfid,
                                      on_save=self._after_custom_save)
                d.destroy()
            label_button(row, "Edit", on_edit).pack(side="right", padx=2)
            label_button(row, "Delete", on_del).pack(side="right", padx=2)

    def _after_custom_save(self, _cf):
        self._render_catalog()

    # ------------------------------------------------------------------
    # Stage hooks
    # ------------------------------------------------------------------

    def teardown(self):
        try:
            if self._wall_mode:
                self._end_wall_mode_internal()
            self._disarm_furniture()
            self.unbind_all("<Delete>")
            self.unbind_all("<BackSpace>")
            for seq in ("<Control-z>", "<Control-Z>",
                        "<Control-y>", "<Control-Y>",
                        "<Control-Shift-z>", "<Control-Shift-Z>",
                        "<KeyPress-f>", "<KeyPress-F>",
                        "<KeyPress-r>", "<KeyPress-R>",
                        "<KeyPress-bracketleft>", "<KeyPress-bracketright>"):
                self.unbind_all(seq)
        except Exception:
            pass


# ===========================================================================
# Custom furniture mini-editor
# ===========================================================================

class CustomFurnitureEditor(tk.Toplevel):
    """Dialog for authoring ``CustomFurniture`` from primitive shapes."""

    _TOOLS = (
        ("rect", "Rectangle"),
        ("square", "Square"),
        ("circle", "Circle / ellipse"),
        ("triangle", "Triangle (right)"),
        ("line", "Line segment"),
    )

    def __init__(self, parent, editing_id: Optional[str] = None,
                 on_save=None):
        super().__init__(parent)
        self.title("Custom Furniture Editor")
        self.configure(bg=C["panel"])
        self.transient(parent)
        self.on_save = on_save
        self.geometry("1000x750")
        self.minsize(720, 520)
        self.resizable(True, True)
        self._paper_s = 1.0
        self._paper_ox = 0.0
        self._paper_oy = 0.0

        self.store = get_cf_store()
        self.editing_id = editing_id
        self.primitives: List[Primitive] = []
        self.title_var = tk.StringVar(value="My Furniture")
        self.active_tool = tk.StringVar(value="rect")
        self.active_color = "#D9C7A3"
        self._drawing: Optional[Tuple[float, float]] = None
        self._selected: Optional[int] = None
        self._tool_frames: dict = {}
        self._show_grid = tk.BooleanVar(value=False)

        if editing_id:
            cf = self.store.get(editing_id)
            if cf:
                self.title_var.set(cf.label)
                self.primitives = [
                    Primitive.from_dict(p.to_dict()) for p in cf.primitives]

        self._build()

    def _build(self) -> None:
        root = tk.Frame(self, bg=C["panel"])
        root.pack(fill="both", expand=True, padx=8, pady=8)

        top = tk.Frame(root, bg=C["panel"])
        top.pack(fill="x", pady=(0, 6))
        tk.Label(top, text="Custom Furniture",
                 font=("Helvetica", 11, "bold"), bg=C["panel"], fg=C["text"]).pack(
                     anchor="w")
        tk.Label(
            top,
            text="Shapes stay in {}×{} design units; the room scales the bundle.".format(
                int(BASE_W), int(BASE_H)),
            font=("Helvetica", 8), bg=C["panel"], fg=C["text_dim"],
            wraplength=520, justify="left").pack(anchor="w", pady=(0, 4))

        bar = tk.Frame(top, bg=C["panel"])
        bar.pack(fill="x", pady=(0, 2))
        tk.Label(bar, text="Name", bg=C["panel"], font=("Helvetica", 9)).pack(
            side="left")
        tk.Entry(bar, textvariable=self.title_var, width=20).pack(
            side="left", padx=(4, 14))

        tip = tk.Label(bar, text="", bg=C["panel"], fg=C["text_dim"],
                       font=("Helvetica", 8), width=28, anchor="w")
        tip.pack(side="left", fill="x", expand=True)

        self._tool_frames.clear()
        tool_strip = tk.Frame(bar, bg=C["panel"])
        tool_strip.pack(side="right")
        for key, label in self._TOOLS:

            def pick(k=key):
                self._select_tool(k)

            cell = tk.Frame(
                tool_strip, bg=C["good_lt"], highlightthickness=1,
                highlightbackground=C["panel_bdr"], cursor="hand2")
            cell.pack(side="left", padx=2)
            lb = tk.Label(
                cell, text=label, bg=C["good_lt"], fg=C["text"],
                font=("Helvetica", 8), cursor="hand2")
            lb.pack(padx=5, pady=2)
            for w in (cell, lb):
                w.bind("<Button-1>", lambda e, pk=pick: pk())
                w.bind("<Enter>", lambda e, _l=label: tip.config(
                    text=f"{_l}: drag on the canvas."))
                w.bind("<Leave>", lambda e: tip.config(text=""))
            self._tool_frames[key] = cell
        self._select_tool(self.active_tool.get())

        color_row = tk.Frame(top, bg=C["panel"])
        color_row.pack(fill="x", pady=(4, 0))
        tk.Label(color_row, text="Color", bg=C["panel"],
                 font=("Helvetica", 9)).pack(side="left")
        self._color_lbl = tk.Label(
            color_row, text="  ", bg=self.active_color,
            relief="solid", bd=1, width=3, cursor="hand2")
        self._color_lbl.pack(side="left", padx=6)
        self._color_lbl.bind("<Button-1>", lambda e: self._pick_color())

        ref_lbl = (
            f"Placing at default size (\u224860\u00d760 plan units) \u2248 "
            f"{fmt_ft(60)}\u00d7{fmt_ft(60)}."
        )
        tk.Label(color_row, text=ref_lbl, bg=C["panel"], fg=C["text_dim"],
                 font=("Helvetica", 8), wraplength=380, justify="left").pack(
                     side="left", padx=(8, 0))

        pw = tk.PanedWindow(
            root, orient=tk.HORIZONTAL, sashwidth=5, bg=C["panel"],
            sashrelief=tk.RAISED)
        pw.pack(fill="both", expand=True, pady=(6, 0))

        left = tk.Frame(pw, bg=C["panel"])
        right = tk.Frame(pw, bg=C["panel"], width=260)
        pw.add(left, minsize=520, stretch="always")
        pw.add(right, minsize=220, stretch="never")

        paper = tk.LabelFrame(
            left, text="Drawing area", bg=C["panel"], fg=C["text"],
            font=("Helvetica", 9, "bold"), bd=1, relief="flat", padx=4, pady=4)
        opts = tk.Frame(paper, bg=C["panel"])
        opts.pack(fill="x", pady=(0, 4))
        tk.Checkbutton(
            opts, text="Show grid", variable=self._show_grid,
            command=self._redraw, bg=C["panel"], fg=C["text"],
            font=("Helvetica", 9), selectcolor=C["panel"]).pack(side="left")
        label_button(opts, "Fit to canvas", self._fit_to_canvas).pack(
            side="right", padx=2)

        self.canvas = tk.Canvas(
            paper, bg="#F5F3EC",
            highlightthickness=1, highlightbackground=C["panel_bdr"])
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_editor_canvas_configure)
        self.canvas.bind("<Button-1>", self._on_down)
        self.canvas.bind("<B1-Motion>", self._on_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_up)
        self.canvas.bind("<Button-3>", self._on_rclick_canvas)

        plist = tk.LabelFrame(
            right, text="Primitives", bg=C["panel"], fg=C["text"],
            font=("Helvetica", 9, "bold"), bd=1, relief="flat", padx=6, pady=4)
        plist.pack(fill="both", expand=True)
        lb_fr = tk.Frame(plist, bg=C["panel"])
        lb_fr.pack(fill="both", expand=True, pady=(0, 4))
        sb = tk.Scrollbar(lb_fr)
        sb.pack(side="right", fill="y")
        self._lb = tk.Listbox(
            lb_fr, height=10, font=("Helvetica", 9),
            bg=C["toolbar"], fg=C["text"],
            selectbackground=C["accent_lt"],
            selectforeground=C["accent"],
            yscrollcommand=sb.set)
        self._lb.pack(side="left", fill="both", expand=True)
        sb.config(command=self._lb.yview)
        self._lb.bind("<<ListboxSelect>>", self._on_list_select)
        self._lb.bind("<Button-3>", self._on_rclick_list)

        rot_fr = tk.Frame(plist, bg=C["panel"])
        rot_fr.pack(fill="x", pady=(0, 6))
        self._rot_ccw_btn = label_button(
            rot_fr, "\u27f2 \u221290\u00b0",
            lambda: self._rotate_selected_primitive(-90))
        self._rot_ccw_btn.pack(side="left", padx=(0, 4))
        self._rot_cw_btn = label_button(
            rot_fr, "\u27f3 +90\u00b0",
            lambda: self._rotate_selected_primitive(90))
        self._rot_cw_btn.pack(side="left")

        self._ctx = tk.Menu(self, tearoff=0)
        self._ctx.add_command(
            label="Rotate 90\u00b0 CW",
            command=lambda: self._rotate_selected_primitive(90))
        self._ctx.add_command(
            label="Rotate 90\u00b0 CCW",
            command=lambda: self._rotate_selected_primitive(-90))
        self._ctx.add_separator()
        self._ctx.add_command(label="Delete", command=self._menu_delete)
        self._ctx.add_command(label="Duplicate", command=self._menu_dup)

        btn = tk.Frame(right, bg=C["panel"])
        btn.pack(fill="x", pady=(6, 0))
        label_button(btn, "Clear", self._clear).pack(side="left", padx=(0, 3))
        label_button(btn, "Cancel", self.destroy).pack(side="right", padx=3)
        label_button(btn, "Save", self._save, primary=True).pack(
            side="right", padx=3)

        self._refresh_listbox()
        self._redraw()

    def _on_editor_canvas_configure(self, event) -> None:
        cw = max(1, int(getattr(event, "width", 1)))
        ch = max(1, int(getattr(event, "height", 1)))
        s = min(cw / BASE_W, ch / BASE_H)
        self._paper_s = s
        self._paper_ox = (cw - BASE_W * s) * 0.5
        self._paper_oy = (ch - BASE_H * s) * 0.5
        self._redraw()

    def _rotate_selected_primitive(self, delta: int) -> None:
        if self._selected is None or not (
                0 <= self._selected < len(self.primitives)):
            return
        p = self.primitives[self._selected]
        p.rotation = (float(p.rotation) + float(delta)) % 360.0
        self._refresh_listbox()
        self._redraw()

    def _sync_rotate_btns(self) -> None:
        if not hasattr(self, "_rot_cw_btn"):
            return
        st = ("normal" if self._selected is not None else "disabled")
        try:
            self._rot_cw_btn.config(state=st)
            self._rot_ccw_btn.config(state=st)
        except tk.TclError:
            pass

    def _draw_selection_outline(self, c: tk.Canvas,
                                p: Primitive, ox: float, oy: float, s: float
                                ) -> None:
        pad = 2.0
        rot = float(p.rotation) % 360.0
        x0, y0 = p.x - pad, p.y - pad
        x1, y1 = p.x + p.w + pad, p.y + p.h + pad
        if abs(rot) < 0.08:
            c.create_rectangle(
                ox + x0 * s, oy + y0 * s,
                ox + x1 * s, oy + y1 * s,
                outline="#E85D24", width=2, dash=(3, 2))
            return
        cxp = p.x + p.w * 0.5
        cyp = p.y + p.h * 0.5
        rad = math.radians(rot)
        co, sn = math.cos(rad), math.sin(rad)
        corners = (
            (x0 - cxp, y0 - cyp), (x1 - cxp, y0 - cyp),
            (x1 - cxp, y1 - cyp), (x0 - cxp, y1 - cyp),
        )
        flat: List[float] = []
        for lx, ly in corners:
            rx = co * lx - sn * ly + cxp
            ry = sn * lx + co * ly + cyp
            flat.extend((ox + rx * s, oy + ry * s))
        flat.extend((flat[0], flat[1]))
        c.create_line(*flat, fill="#E85D24", width=2, dash=(3, 2))
        self.active_tool.set(name)
        for k, fr in self._tool_frames.items():
            on = (k == name)
            fr.config(
                highlightbackground=(C["accent"] if on else C["panel_bdr"]),
                highlightthickness=2 if on else 1,
            )

    def _refresh_listbox(self) -> None:
        if not hasattr(self, "_lb"):
            return
        self._lb.delete(0, tk.END)
        for i, p in enumerate(self.primitives):
            ang = int(round(float(p.rotation))) % 360
            atxt = f"  \u2220{ang}\u00b0" if ang != 0 else ""
            self._lb.insert(
                tk.END,
                f"  {i + 1}.  {p.kind:8}  {p.w:.1f}\u00d7{p.h:.1f}  "
                f"@{p.x:.0f},{p.y:.0f}{atxt}")
        if self._selected is not None and 0 <= self._selected < len(self.primitives):
            self._lb.selection_set(self._selected)
            self._lb.see(self._selected)
        self._sync_rotate_btns()

    def _on_list_select(self, _event=None) -> None:
        sel = self._lb.curselection()
        if not sel:
            return
        self._selected = int(sel[0])
        self._redraw()

    def _on_rclick_list(self, event) -> None:
        sel = self._lb.nearest(event.y)
        self._lb.selection_clear(0, tk.END)
        self._lb.selection_set(sel)
        self._selected = sel
        self._redraw()
        try:
            self._ctx.post(event.x_root, event.y_root)
        except tk.TclError:
            pass

    def _on_rclick_canvas(self, event) -> None:
        hit = self._hit(event.x, event.y)
        if hit is None:
            return
        self._selected = hit
        self._refresh_listbox()
        self._redraw()
        try:
            self._ctx.post(event.x_root, event.y_root)
        except tk.TclError:
            pass

    def _menu_delete(self) -> None:
        if self._selected is None:
            return
        if 0 <= self._selected < len(self.primitives):
            del self.primitives[self._selected]
            self._selected = None
            self._refresh_listbox()
            self._redraw()

    def _menu_dup(self) -> None:
        if self._selected is None:
            return
        if not (0 <= self._selected < len(self.primitives)):
            return
        p = self.primitives[self._selected]
        d = Primitive.from_dict(p.to_dict())
        d.x += 4
        d.y += 4
        self.primitives.append(d)
        self._selected = len(self.primitives) - 1
        self._refresh_listbox()
        self._redraw()

    def _fit_to_canvas(self) -> None:
        if not self.primitives:
            return
        minx = min(p.x for p in self.primitives)
        miny = min(p.y for p in self.primitives)
        for p in self.primitives:
            p.x -= minx - 2.0
            p.y -= miny - 2.0
        maxx = max(p.x + p.w for p in self.primitives)
        maxy = max(p.y + p.h for p in self.primitives)
        margin = 2.0
        if maxx <= BASE_W - margin and maxy <= BASE_H - margin:
            self._refresh_listbox()
            self._redraw()
            return
        sc = min(
            (BASE_W - 2 * margin) / max(maxx, 1e-6),
            (BASE_H - 2 * margin) / max(maxy, 1e-6),
            1.0,
        )
        for p in self.primitives:
            p.x = margin + (p.x - margin) * sc
            p.y = margin + (p.y - margin) * sc
            p.w *= sc
            p.h *= sc
        self._refresh_listbox()
        self._redraw()

    def _pick_color(self):
        c = tkinter.colorchooser.askcolor(initialcolor=self.active_color)
        if c and c[1]:
            self.active_color = c[1]
            self._color_lbl.config(bg=c[1])

    def _world(self, cx, cy) -> Tuple[float, float]:
        s = self._paper_s
        if s < 1e-9:
            s = 1.0
        ox, oy = self._paper_ox, self._paper_oy
        return (float(cx) - ox) / s, (float(cy) - oy) / s

    def _redraw(self):
        c = self.canvas
        c.delete("all")
        cw = max(1, int(c.winfo_width()))
        ch = max(1, int(c.winfo_height()))
        c.create_rectangle(0, 0, cw, ch, fill="#D8D4CD", outline="")
        s = self._paper_s
        ox, oy = self._paper_ox, self._paper_oy
        px1 = ox + BASE_W * s
        py1 = oy + BASE_H * s
        c.create_rectangle(ox, oy, px1, py1, fill="#F5F3EC", outline="")
        if self._show_grid.get():
            step = 10.0
            gc = "#E5E2DA"
            x = 0.0
            while x <= BASE_W:
                gx = ox + x * s
                c.create_line(gx, oy, gx, py1, fill=gc, width=1)
                x += step
            y = 0.0
            while y <= BASE_H:
                gy = oy + y * s
                c.create_line(ox, gy, px1, gy, fill=gc, width=1)
                y += step
        c.create_rectangle(
            ox + 1, oy + 1, px1 - 1, py1 - 1,
            outline="#AAAAAA", width=1, dash=(3, 3))
        from model.custom_furniture import _draw_primitive
        for i, p in enumerate(self.primitives):
            _draw_primitive(c, p, ox, oy, s, s)
            if i == self._selected:
                self._draw_selection_outline(c, p, ox, oy, s)
        tick_y = min(ch - 4, int(py1) - 4)
        for vx in range(0, int(BASE_W) + 1, 30):
            c.create_text(
                int(ox + vx * s), tick_y, text=str(vx), font=("Helvetica", 7),
                fill=C["text_dim"], anchor="s")
        for vy in range(0, int(BASE_H) + 1, 30):
            c.create_text(
                int(ox + 4), int(py1 - vy * s), text=str(vy),
                font=("Helvetica", 7),
                fill=C["text_dim"], anchor="w")

    def _hit(self, cx, cy) -> Optional[int]:
        wx, wy = self._world(cx, cy)
        for i in range(len(self.primitives) - 1, -1, -1):
            p = self.primitives[i]
            rot = float(p.rotation) % 360.0
            if abs(rot) < 0.08:
                if p.x <= wx <= p.x + p.w and p.y <= wy <= p.y + p.h:
                    return i
                continue
            cxp = p.x + p.w * 0.5
            cyp = p.y + p.h * 0.5
            rrad = math.radians(-rot)
            co, sn = math.cos(rrad), math.sin(rrad)
            dx, dy = wx - cxp, wy - cyp
            lx = co * dx - sn * dy
            ly = sn * dx + co * dy
            if -p.w * 0.5 <= lx <= p.w * 0.5 and -p.h * 0.5 <= ly <= p.h * 0.5:
                return i
        return None

    def _on_down(self, event):
        wx, wy = self._world(event.x, event.y)
        hit = self._hit(event.x, event.y)
        if hit is not None:
            self._selected = hit
            self._drawing = None
            self._drag_grip = (wx, wy)
            self._redraw()
            self._refresh_listbox()
            return
        self._selected = None
        self._drawing = (wx, wy)
        self._redraw()
        self._refresh_listbox()

    def _on_move(self, event):
        wx, wy = self._world(event.x, event.y)
        if self._selected is not None and self._drawing is None:
            gx, gy = self._drag_grip
            dx, dy = wx - gx, wy - gy
            p = self.primitives[self._selected]
            p.x += dx
            p.y += dy
            self._drag_grip = (wx, wy)
            self._redraw()
            self._refresh_listbox()
            return
        if self._drawing is None:
            return
        sx, sy = self._drawing
        w = wx - sx
        h = wy - sy
        if self.active_tool.get() == "square":
            side = min(abs(w), abs(h))
            w = side * (1 if w >= 0 else -1)
            h = side * (1 if h >= 0 else -1)
        prev = Primitive(
            kind=self.active_tool.get(),
            x=min(sx, sx + w), y=min(sy, sy + h),
            w=abs(w), h=abs(h), color=self.active_color)
        self._redraw()
        from model.custom_furniture import _draw_primitive
        _draw_primitive(
            self.canvas, prev,
            self._paper_ox, self._paper_oy, self._paper_s, self._paper_s)

    def _on_up(self, event):
        if self._drawing is None:
            return
        sx, sy = self._drawing
        self._drawing = None
        wx, wy = self._world(event.x, event.y)
        w = wx - sx
        h = wy - sy
        if self.active_tool.get() == "square":
            side = min(abs(w), abs(h))
            w = side * (1 if w >= 0 else -1)
            h = side * (1 if h >= 0 else -1)
        if abs(w) < 2 or abs(h) < 2:
            self._redraw()
            self._refresh_listbox()
            return
        self.primitives.append(Primitive(
            kind=self.active_tool.get(),
            x=min(sx, sx + w), y=min(sy, sy + h),
            w=abs(w), h=abs(h), color=self.active_color))
        self._selected = len(self.primitives) - 1
        self._redraw()
        self._refresh_listbox()

    def _on_rclick(self, event):
        """Deprecated path; canvas uses ``_on_rclick_canvas``."""
        self._on_rclick_canvas(event)

    def _clear(self):
        self.primitives = []
        self._selected = None
        self._redraw()
        self._refresh_listbox()

    def _save(self):
        title = self.title_var.get().strip() or "Custom"
        if not self.primitives:
            messagebox.showwarning("Empty",
                                   "Add at least one shape before saving.")
            return
        if self.editing_id:
            cf = self.store.get(self.editing_id)
            if cf:
                cf.label = title
                cf.primitives = list(self.primitives)
                self.store.save()
        else:
            cf = self.store.add(title, self.primitives)
        if self.on_save:
            self.on_save(cf)
        self.destroy()
