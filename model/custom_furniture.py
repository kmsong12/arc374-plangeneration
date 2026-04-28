"""
custom_furniture.py - User-authored furniture built from primitives.

A CustomFurniture is a named bundle of primitive shapes (rect / square /
circle / triangle / line).  Each primitive has local coordinates in a
fixed authoring canvas (0..BASE_W, 0..BASE_H) and its own color.

When rendered as a "Custom" furniture item inside a room, the bundle is
uniformly scaled to fit the item's (w,h).

The catalog is persisted to `custom_furniture.json` in the project
folder.
"""

from __future__ import annotations
import json
import math
import os
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from rotated_canvas import RotatedCanvasProxy

BASE_W = 120.0
BASE_H = 120.0

_STORE: Optional["CustomFurnitureStore"] = None


@dataclass
class Primitive:
    kind: str     # "rect" | "square" | "circle" | "triangle" | "line"
    x: float
    y: float
    w: float
    h: float
    color: str = "#999999"
    outline: str = "#444444"
    rotation: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Primitive":
        return cls(
            kind=d["kind"],
            x=float(d["x"]), y=float(d["y"]),
            w=float(d["w"]), h=float(d["h"]),
            color=d.get("color", "#999999"),
            outline=d.get("outline", "#444444"),
            rotation=float(d.get("rotation", 0.0)),
        )


@dataclass
class CustomFurniture:
    id: str
    label: str
    primitives: List[Primitive] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "primitives": [p.to_dict() for p in self.primitives],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CustomFurniture":
        return cls(
            id=d["id"],
            label=d.get("label", "Custom"),
            primitives=[Primitive.from_dict(p)
                        for p in d.get("primitives", [])],
        )


class CustomFurnitureStore:
    """In-memory + JSON catalog of custom furniture."""

    def __init__(self, path: str):
        self.path = path
        self.items: Dict[str, CustomFurniture] = {}
        self.load()

    def load(self) -> None:
        if not os.path.isfile(self.path):
            self.items = {}
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.items = {}
            for d in data.get("items", []):
                cf = CustomFurniture.from_dict(d)
                self.items[cf.id] = cf
        except Exception:
            self.items = {}

    def save(self) -> None:
        data = {"items": [cf.to_dict() for cf in self.items.values()]}
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def add(self, label: str, primitives: List[Primitive]) -> CustomFurniture:
        cf = CustomFurniture(
            id=uuid.uuid4().hex[:10],
            label=label,
            primitives=list(primitives),
        )
        self.items[cf.id] = cf
        self.save()
        return cf

    def remove(self, cf_id: str) -> None:
        if cf_id in self.items:
            del self.items[cf_id]
            self.save()

    def get(self, cf_id: Optional[str]) -> Optional[CustomFurniture]:
        if cf_id is None:
            return None
        return self.items.get(cf_id)

    def all(self) -> List[CustomFurniture]:
        return list(self.items.values())


def get_store() -> CustomFurnitureStore:
    global _STORE
    if _STORE is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(os.path.dirname(here), "custom_furniture.json")
        _STORE = CustomFurnitureStore(path)
    return _STORE


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _draw_primitive_axis_aligned(
        c, p: Primitive,
        ox: float, oy: float, sx: float, sy: float,
        color_override: Optional[str] = None) -> None:
    fill = color_override if color_override else p.color
    outline = p.outline
    x0 = ox + p.x * sx
    y0 = oy + p.y * sy
    x1 = ox + (p.x + p.w) * sx
    y1 = oy + (p.y + p.h) * sy
    if p.kind == "line":
        c.create_line(x0, y0, x1, y1, fill=outline, width=2)
    elif p.kind in ("rect", "square"):
        c.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline, width=1.2)
    elif p.kind == "circle":
        c.create_oval(x0, y0, x1, y1, fill=fill, outline=outline, width=1.2)
    elif p.kind == "triangle":
        # right-pointing triangle inscribed in the bbox
        c.create_polygon(
            x0, y1,
            (x0 + x1) / 2, y0,
            x1, y1,
            fill=fill, outline=outline, width=1.2)


def _draw_primitive(c, p: Primitive,
                    ox: float, oy: float, sx: float, sy: float,
                    color_override: Optional[str] = None) -> None:
    rot = float(p.rotation) % 360.0
    if abs(rot) < 0.08 or abs(rot - 360.0) < 0.08:
        _draw_primitive_axis_aligned(c, p, ox, oy, sx, sy, color_override)
        return
    cx = ox + (p.x + p.w * 0.5) * sx
    cy = oy + (p.y + p.h * 0.5) * sy
    rad = math.radians(rot)
    proxy = RotatedCanvasProxy(c, cx, cy, math.cos(rad), math.sin(rad))
    local_ox = -p.w * 0.5 * sx
    local_oy = -p.h * 0.5 * sy
    pl = Primitive(
        kind=p.kind, x=0.0, y=0.0, w=p.w, h=p.h,
        color=p.color, outline=p.outline, rotation=0.0,
    )
    _draw_primitive_axis_aligned(
        proxy, pl, local_ox, local_oy, sx, sy, color_override)


def draw_custom(c, cf_id: Optional[str],
                x: float, y: float, w: float, h: float,
                color_override: Optional[str] = None) -> None:
    """Render a CustomFurniture at absolute (x,y) scaled to (w,h)."""
    store = get_store()
    cf = store.get(cf_id)
    if cf is None or not cf.primitives:
        # Fallback: neutral hatched rectangle
        c.create_rectangle(x, y, x + w, y + h,
                           fill=color_override or "#EEEEEE",
                           outline="#888", width=1)
        c.create_line(x, y, x + w, y + h, fill="#888", width=0.8)
        c.create_line(x + w, y, x, y + h, fill="#888", width=0.8)
        return
    sx = w / BASE_W
    sy = h / BASE_H
    for p in cf.primitives:
        _draw_primitive(c, p, x, y, sx, sy, color_override)
