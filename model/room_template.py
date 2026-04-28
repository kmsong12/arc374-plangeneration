"""
room_template.py - RoomTemplate: a reusable room authored by the user.

A template is the "design" of a room: its polygon outline, its furniture,
its fill/border colors, a free-form label and a free-form roomtype tag
("bedroom", "public room", or anything the user wants).

Coordinates are LOCAL to the template (0,0 in the template's own frame).
Instances placed on a site get their own (x,y,rotation) in plan.py.

A template may optionally carry a `preset_id` pointing at a hand-drawn
renderer in presets.py — in that case, furniture is ignored and the
preset renderer is used for drawing.
"""

from __future__ import annotations
import copy
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple

from geometry_utils import polygon_bbox, rect_to_polygon


@dataclass
class FurnitureItem:
    """A piece of furniture placed inside a room template (local coords)."""
    type: str                   # catalog key (e.g. "Bed_Queen") or "Custom"
    x: float
    y: float
    w: float
    h: float
    color: Optional[str] = None         # fill override; None => catalog default
    rotation: float = 0.0               # degrees, around item's own centre
    custom_id: Optional[str] = None     # for CustomFurniture lookup
    label: Optional[str] = None         # optional user-visible name

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FurnitureItem":
        return cls(
            type=d["type"],
            x=float(d["x"]), y=float(d["y"]),
            w=float(d["w"]), h=float(d["h"]),
            color=d.get("color"),
            rotation=float(d.get("rotation", 0.0)),
            custom_id=d.get("custom_id"),
            label=d.get("label"),
        )


@dataclass
class Wall:
    """An interior divider drawn inside a room (local coordinates).

    Represented as a thick line segment from (x0,y0) to (x1,y1). Thickness
    is stored in pixels (convert via units.ft_to_px for persistence).
    Walls are currently visual only: they do not block furniture placement.
    """
    x0: float
    y0: float
    x1: float
    y1: float
    thickness: float = 6.0                 # pixels
    color: str = "#6E6E6A"                 # slate

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Wall":
        return cls(
            x0=float(d["x0"]), y0=float(d["y0"]),
            x1=float(d["x1"]), y1=float(d["y1"]),
            thickness=float(d.get("thickness", 6.0)),
            color=d.get("color", "#6E6E6A"),
        )


@dataclass
class RoomTemplate:
    """Reusable room blueprint (local coordinates)."""
    label: str = "Room"
    roomtype: str = "bedroom"
    polygon: List[Tuple[float, float]] = field(default_factory=list)
    furniture: List[FurnitureItem] = field(default_factory=list)
    walls: List[Wall] = field(default_factory=list)
    fill_color: str = "#EBF3FB"
    border_color: str = "#378ADD"
    preset_id: Optional[str] = None    # None for user-authored

    # --- convenience ----------------------------------------------------

    @classmethod
    def rectangle(cls, label: str, w: float, h: float,
                  roomtype: str = "bedroom",
                  fill_color: str = "#EBF3FB",
                  border_color: str = "#378ADD") -> "RoomTemplate":
        """Create a rectangular template with corners at (0,0)-(w,h)."""
        return cls(
            label=label,
            roomtype=roomtype,
            polygon=rect_to_polygon(0, 0, w, h),
            fill_color=fill_color,
            border_color=border_color,
        )

    def bbox(self) -> Tuple[float, float, float, float]:
        return polygon_bbox(self.polygon)

    def size(self) -> Tuple[float, float]:
        x, y, w, h = self.bbox()
        return (w, h)

    def normalise(self) -> None:
        """Shift polygon so its bbox starts at (0,0); adjust furniture and walls."""
        x, y, _, _ = self.bbox()
        if x == 0 and y == 0:
            return
        self.polygon = [(px - x, py - y) for px, py in self.polygon]
        for f in self.furniture:
            f.x -= x
            f.y -= y
        for w in self.walls:
            w.x0 -= x
            w.y0 -= y
            w.x1 -= x
            w.y1 -= y

    def copy(self) -> "RoomTemplate":
        return RoomTemplate(
            label=self.label,
            roomtype=self.roomtype,
            polygon=list(self.polygon),
            furniture=[copy.copy(f) for f in self.furniture],
            walls=[copy.copy(w) for w in self.walls],
            fill_color=self.fill_color,
            border_color=self.border_color,
            preset_id=self.preset_id,
        )

    # --- serialisation --------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "label":        self.label,
            "roomtype":     self.roomtype,
            "polygon":      [list(p) for p in self.polygon],
            "furniture":    [f.to_dict() for f in self.furniture],
            "walls":        [w.to_dict() for w in self.walls],
            "fill_color":   self.fill_color,
            "border_color": self.border_color,
            "preset_id":    self.preset_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RoomTemplate":
        return cls(
            label=d.get("label", "Room"),
            roomtype=d.get("roomtype", "bedroom"),
            polygon=[tuple(p) for p in d.get("polygon", [])],
            furniture=[FurnitureItem.from_dict(f)
                       for f in d.get("furniture", [])],
            walls=[Wall.from_dict(w) for w in d.get("walls", [])],
            fill_color=d.get("fill_color", "#EBF3FB"),
            border_color=d.get("border_color", "#378ADD"),
            preset_id=d.get("preset_id"),
        )
