"""theme.py - Centralised color palette + shared widget helpers."""

from __future__ import annotations
import tkinter as tk

C = {
    "bg":        "#F0EDE5",
    "panel":     "#FAFAF6",
    "panel_bdr": "#D8D5CC",
    "toolbar":   "#FFFFFF",
    "accent":    "#2D6A9F",
    "accent_lt": "#EBF3FB",
    "good":      "#2D9F6A",
    "good_lt":   "#E3F5EB",
    "warn_bg":   "#FFF8E1",
    "warn_fg":   "#8A6800",
    "bad":       "#C44444",
    "bad_lt":    "#FDECEC",
    "text":      "#2C2C2A",
    "text_dim":  "#888880",
    "sep":       "#E2DFD7",
    "metric_bg": "#F5F2EA",
    "bench":     "#9C8462",
    "path":      "#D4CCBA",
    "handle":    "#E85D24",
}


def label_button(parent, text, cmd, primary=False, bg=None, fg=None):
    """A clickable label styled as a button."""
    _bg = bg or (C["accent_lt"] if primary else C["toolbar"])
    _fg = fg or (C["accent"]    if primary else C["text"])
    b = tk.Label(parent, text=text, bg=_bg, fg=_fg,
                 font=("Helvetica", 10), padx=10, cursor="hand2")
    b.bind("<Button-1>", lambda e: cmd())
    original_bg = _bg
    b.bind("<Enter>", lambda e: b.config(bg=C["accent_lt"]))
    b.bind("<Leave>", lambda e: b.config(bg=original_bg))
    return b


def section(parent, text):
    tk.Label(parent, text=text, font=("Helvetica", 8, "bold"),
             bg=C["panel"], fg=C["text_dim"], anchor="w").pack(
        fill="x", pady=(8, 3))


def hsep(parent):
    tk.Frame(parent, bg=C["sep"], height=1).pack(fill="x", pady=6)


def vsep(parent):
    tk.Frame(parent, bg=C["sep"], width=1).pack(
        side="left", fill="y", pady=6, padx=4)


def slider(parent, label, var, lo, hi, step, cb=None):
    row = tk.Frame(parent, bg=C["panel"])
    row.pack(fill="x", pady=(4, 0))
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
             showvalue=False, length=180).pack(fill="x")
