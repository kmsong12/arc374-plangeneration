"""
plan.py - Plan: a generated layout (replaces the old `Hotel` model).

A plan owns:
    * placed rooms (RoomInstance: template reference + pose overrides)
    * landscape items (benches, paths)
    * bushes (trees)
    * zone rectangles (only used while generating, but kept for round-trip)

A RoomInstance remembers its SOURCE template by key. On load, if the key
is missing from the current library, the embedded `template_snapshot`
field is used as a fallback so plans stay visually consistent across
library edits.
"""

from __future__ import annotations
import copy
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from geometry_utils import (
    polygon_bbox, polygon_centroid, rotate_polygon, translate_polygon,
)
from model.room_template import RoomTemplate, FurnitureItem


@dataclass
class RoomInstance:
    """A placed room inside a Plan. Coordinates are WORLD (site) px."""
    template_key: str
    template_snapshot: RoomTemplate    # embedded copy for render robustness
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0              # degrees, multiples of 90 expected
    fill_override: Optional[str] = None
    pinned: bool = False
    iid: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    # --- derived geometry ------------------------------------------------

    def template_point_to_world(self, lx: float, ly: float) -> Tuple[float, float]:
        """Template-local point → site coordinates (matches ``world_polygon``)."""
        poly0 = self.template_snapshot.polygon
        if not poly0:
            return (lx + self.x, ly + self.y)
        rot = float(self.rotation) % 360.0
        if abs(rot) < 1e-6:
            return (lx + self.x, ly + self.y)
        ccx, ccy = polygon_centroid(poly0)
        pr = rotate_polygon([(lx, ly)], rot, ccx, ccy)
        rx, ry = pr[0]
        rpoly = rotate_polygon(poly0, rot)
        bx, by, _, _ = polygon_bbox(rpoly)
        return (rx - bx + self.x, ry - by + self.y)

    def world_polygon(self) -> List[Tuple[float, float]]:
        """Return the room's polygon in world (site) coordinates."""
        poly = self.template_snapshot.polygon
        if self.rotation:
            poly = rotate_polygon(poly, self.rotation)
            bx, by, _, _ = polygon_bbox(poly)
            # re-anchor so the rotated bbox sits at (0,0) before translation
            poly = [(px - bx, py - by) for px, py in poly]
        return translate_polygon(poly, self.x, self.y)

    def world_bbox(self) -> Tuple[float, float, float, float]:
        return polygon_bbox(self.world_polygon())

    @property
    def label(self) -> str:
        return self.template_snapshot.label

    @property
    def roomtype(self) -> str:
        return self.template_snapshot.roomtype

    @property
    def w(self) -> float:
        return self.world_bbox()[2]

    @property
    def h(self) -> float:
        return self.world_bbox()[3]

    @property
    def cx(self) -> float:
        x, y, w, h = self.world_bbox()
        return x + w / 2.0

    @property
    def cy(self) -> float:
        x, y, w, h = self.world_bbox()
        return y + h / 2.0

    @property
    def area(self) -> float:
        x, y, w, h = self.world_bbox()
        return w * h

    # --- mutation -------------------------------------------------------

    def move(self, dx: float, dy: float) -> None:
        self.x += dx
        self.y += dy

    def rotate_90(self) -> None:
        self.rotation = (self.rotation + 90) % 360

    # --- serialisation --------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "iid": self.iid,
            "template_key": self.template_key,
            "template_snapshot": self.template_snapshot.to_dict(),
            "x": self.x, "y": self.y,
            "rotation": self.rotation,
            "fill_override": self.fill_override,
            "pinned": self.pinned,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RoomInstance":
        return cls(
            iid=d.get("iid", uuid.uuid4().hex[:8]),
            template_key=d.get("template_key", ""),
            template_snapshot=RoomTemplate.from_dict(d["template_snapshot"]),
            x=float(d.get("x", 0)), y=float(d.get("y", 0)),
            rotation=float(d.get("rotation", 0)),
            fill_override=d.get("fill_override"),
            pinned=bool(d.get("pinned", False)),
        )


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

@dataclass
class Plan:
    rooms: List[RoomInstance] = field(default_factory=list)
    landscape: List[dict] = field(default_factory=list)   # {type, x, y, w, h, ...}
    bushes: List[Tuple[float, float, float]] = field(default_factory=list)
    zones: List[Tuple[float, float, float, float]] = field(default_factory=list)
    site: Tuple[int, int, int, int] = (50, 50, 800, 540)
    title: str = ""

    # --- mutation -------------------------------------------------------

    def add_room(self, room: RoomInstance) -> None:
        self.rooms.append(room)

    def remove_room(self, room: RoomInstance) -> None:
        if room in self.rooms:
            self.rooms.remove(room)

    def clear(self) -> None:
        self.rooms.clear()
        self.landscape.clear()
        self.bushes.clear()
        self.zones.clear()

    def clear_landscape(self) -> None:
        self.landscape.clear()
        self.bushes.clear()

    def room_at(self, px: float, py: float) -> Optional[RoomInstance]:
        for room in reversed(self.rooms):
            x, y, w, h = room.world_bbox()
            if x <= px <= x + w and y <= py <= y + h:
                return room
        return None

    # --- metrics --------------------------------------------------------

    def compute_metrics(self, site=None) -> Dict:
        sx, sy, sw, sh = site if site is not None else self.site
        site_area_px = sw * sh
        built_px = sum(r.area for r in self.rooms)
        open_px = max(0.0, site_area_px - built_px)
        density = (built_px / site_area_px * 100) if site_area_px else 0

        counts: Dict[str, int] = {}
        areas: Dict[str, float] = {}
        for r in self.rooms:
            counts[r.label] = counts.get(r.label, 0) + 1
            areas[r.label] = areas.get(r.label, 0) + r.area
        avg_areas = {t: areas[t] / counts[t] for t in counts}

        return {
            "total_rooms":    len(self.rooms),
            "site_area_px":   site_area_px,
            "built_area_px":  built_px,
            "open_area_px":   open_px,
            "density":        round(density, 1),
            "counts":         counts,
            "avg_areas_px":   avg_areas,
        }

    # --- snapshot for undo ---------------------------------------------

    def snapshot(self) -> "Plan":
        return copy.deepcopy(self)

    def restore(self, snap: "Plan") -> None:
        self.rooms = list(snap.rooms)
        self.landscape = list(snap.landscape)
        self.bushes = list(snap.bushes)
        self.zones = list(snap.zones)
        self.site = tuple(snap.site)
        self.title = snap.title

    # --- serialisation --------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "title":     self.title,
            "site":      list(self.site),
            "rooms":     [r.to_dict() for r in self.rooms],
            "landscape": list(self.landscape),
            "bushes":    [list(b) for b in self.bushes],
            "zones":     [list(z) for z in self.zones],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Plan":
        p = cls()
        p.title = d.get("title", "")
        p.site = tuple(d.get("site", (50, 50, 800, 540)))
        p.rooms = [RoomInstance.from_dict(r) for r in d.get("rooms", [])]
        p.landscape = [dict(l) for l in d.get("landscape", [])]
        p.bushes = [tuple(b) for b in d.get("bushes", [])]
        p.zones = [tuple(z) for z in d.get("zones", [])]
        return p


# ---------------------------------------------------------------------------
# PlanLibrary (saved user plans)
# ---------------------------------------------------------------------------

import json
import os


class PlanLibrary:
    def __init__(self, path: str):
        self.path = path
        self.plans: Dict[str, Plan] = {}
        self.load()

    def load(self) -> None:
        if not os.path.isfile(self.path):
            self.plans = {}
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.plans = {k: Plan.from_dict(v)
                          for k, v in data.get("plans", {}).items()}
        except Exception:
            self.plans = {}

    def save(self) -> None:
        try:
            data = {"plans": {k: p.to_dict() for k, p in self.plans.items()}}
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def add(self, plan: Plan, title: Optional[str] = None) -> str:
        key = uuid.uuid4().hex[:10]
        p = copy.deepcopy(plan)
        if title:
            p.title = title
        self.plans[key] = p
        self.save()
        return key

    def remove(self, key: str) -> None:
        if key in self.plans:
            del self.plans[key]
            self.save()

    def get(self, key: str) -> Optional[Plan]:
        return self.plans.get(key)

    def all(self) -> List[Tuple[str, Plan]]:
        return list(self.plans.items())


_PLAN_LIBRARY: Optional[PlanLibrary] = None


def get_plan_library() -> PlanLibrary:
    global _PLAN_LIBRARY
    if _PLAN_LIBRARY is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(os.path.dirname(here), "plan_library.json")
        _PLAN_LIBRARY = PlanLibrary(path)
    return _PLAN_LIBRARY
