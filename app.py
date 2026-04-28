"""
app.py - AppShell: 3-stage wizard that mounts each stage into the body.

The shell owns:
    * top step-indicator (Author / Generate / Finalize)
    * shared toolbar with save/quit
    * shared state: RoomLibrary, PlanLibrary, current Plan buffer

Each stage is a ttk.Frame subclass that receives the shell as its parent
and exposes `teardown()` so the shell can cleanly swap stages.
"""

from __future__ import annotations
import tkinter as tk
from tkinter import messagebox, ttk

from config import (
    CANVAS_W, CANVAS_H, SIDEBAR_LEFT_W, SIDEBAR_RIGHT_W,
    TOOLBAR_H, STEPBAR_H, METRICS_BAR_H,
)
from theme import C, label_button
from model.plan import Plan, get_plan_library
from model.room_library import get_library


STAGES = [
    ("author",   "1 · Room Author"),
    ("generate", "2 · Generation"),
    ("finalize", "3 · Finalize & Export"),
]


class AppShell(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("arc374 · Floor-Plan Generator")

        total_w = SIDEBAR_LEFT_W + CANVAS_W + SIDEBAR_RIGHT_W + 30
        total_h = CANVAS_H + STEPBAR_H + TOOLBAR_H + METRICS_BAR_H + 40
        self.geometry(f"{total_w}x{total_h}")
        self.minsize(1100, 700)
        self.configure(bg=C["bg"])

        # Shared state
        self.room_library = get_library()
        self.plan_library = get_plan_library()
        # Cross-stage hand-off plan: when Stage 2 "sends to finalize" it
        # stores the plan here; Stage 3 picks it up on activation.
        self.handoff_plan: Plan | None = None
        self.last_llm_settings: dict | None = None

        # Layout skeleton
        self._build_stepbar()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()

        self._current_stage = None
        self._current_stage_id = None
        self.activate_stage("author")

        self.bind("<Control-1>", lambda _e: self.activate_stage("author"))
        self.bind("<Control-2>", lambda _e: self.activate_stage("generate"))
        self.bind("<Control-3>", lambda _e: self.activate_stage("finalize"))

    # ------------------------------------------------------------------
    # UI chrome
    # ------------------------------------------------------------------

    def _build_stepbar(self):
        bar = tk.Frame(self, bg=C["panel"], height=STEPBAR_H)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        self._step_labels = {}
        inner = tk.Frame(bar, bg=C["panel"])
        inner.pack(pady=6)
        for sid, label in STAGES:
            fr = tk.Frame(inner, bg=C["panel"])
            fr.pack(side="left", padx=14)
            lbl = tk.Label(fr, text=label, font=("Helvetica", 11, "bold"),
                           bg=C["panel"], fg=C["text_dim"],
                           padx=14, pady=4, cursor="hand2")
            lbl.pack()
            bar_line = tk.Frame(fr, bg=C["panel"], height=3)
            bar_line.pack(fill="x", padx=6)
            lbl.bind("<Button-1>",
                     lambda e, s=sid: self.activate_stage(s))
            bar_line.bind("<Button-1>",
                          lambda e, s=sid: self.activate_stage(s))
            self._step_labels[sid] = (lbl, bar_line)
        # divider under the step bar
        tk.Frame(self, bg=C["sep"], height=1).pack(fill="x")

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=C["toolbar"], height=TOOLBAR_H)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        left = tk.Frame(bar, bg=C["toolbar"])
        left.pack(side="left", fill="y", padx=8)
        right = tk.Frame(bar, bg=C["toolbar"])
        right.pack(side="right", fill="y", padx=8)

        self._toolbar_left = left
        self._toolbar_right = right

        label_button(right, "Quit", self.destroy).pack(side="right", padx=3)
        tk.Frame(self, bg=C["sep"], height=1).pack(fill="x")

    def _build_body(self):
        body = tk.Frame(self, bg=C["bg"])
        body.pack(side="top", fill="both", expand=True)
        self.body = body

    def _build_statusbar(self):
        bar = tk.Frame(self, bg=C["panel"], height=METRICS_BAR_H)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        self.status_var = tk.StringVar(value="Ready.")
        tk.Label(bar, textvariable=self.status_var,
                 bg=C["panel"], fg=C["text_dim"],
                 font=("Helvetica", 9), anchor="w").pack(
            side="left", padx=10, pady=4)

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    # ------------------------------------------------------------------
    # Stage switching
    # ------------------------------------------------------------------

    def activate_stage(self, stage_id: str):
        if stage_id == self._current_stage_id and self._current_stage:
            return

        # teardown current
        if self._current_stage is not None:
            try:
                self._current_stage.teardown()
            except Exception:
                pass
            self._current_stage.destroy()
            self._current_stage = None

        # clear toolbar extras
        for child in list(self._toolbar_left.winfo_children()):
            child.destroy()
        for child in list(self._toolbar_right.winfo_children()):
            if child.cget("text") != "Quit":
                child.destroy()

        # highlight step
        for sid, (lbl, line) in self._step_labels.items():
            if sid == stage_id:
                lbl.config(fg=C["accent"])
                line.config(bg=C["accent"])
            else:
                lbl.config(fg=C["text_dim"])
                line.config(bg=C["panel"])

        # instantiate
        if stage_id == "author":
            from stages.stage_author import AuthorStage
            self._current_stage = AuthorStage(self.body, self)
        elif stage_id == "generate":
            from stages.stage_generate import GenerateStage
            self._current_stage = GenerateStage(self.body, self)
        elif stage_id == "finalize":
            from stages.stage_finalize import FinalizeStage
            self._current_stage = FinalizeStage(self.body, self)
        else:
            raise ValueError(stage_id)

        self._current_stage.pack(fill="both", expand=True)
        self._current_stage_id = stage_id


def main():
    app = AppShell()
    app.mainloop()


if __name__ == "__main__":
    main()
