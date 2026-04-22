"""
hotel.py - Hotel model (pure data, no Tkinter).
Includes JSON serialisation for save/load.
"""

from __future__ import annotations
import copy
import json
from typing import List, Tuple, Dict, Optional
from rooms import Room, ROOM_CLASSES


class Hotel:

    def __init__(self):
        self.rooms: List[Room] = []

    #  Mutation ------------------------------------------------

    def add_room(self, room: Room):
        self.rooms.append(room)

    def remove_room(self, room: Room):
        if room in self.rooms:
            self.rooms.remove(room)

    def clear(self):
        self.rooms.clear()

    def replace_rooms(self, rooms: List[Room]):
        self.rooms = list(rooms)

    #  Queries --------------------------------------------------

    def as_tuples(self) -> List[Tuple[int,int,int,int]]:
        return [r.as_tuple() for r in self.rooms]

    def room_at(self, px: int, py: int) -> Optional[Room]:
        for room in reversed(self.rooms):
            if room.contains(px, py):
                return room
        return None

    #  Metrics --------------------------------------------------

    def compute_metrics(self, site: Tuple[int,int,int,int]) -> Dict:
        sx, sy, sw, sh = site
        site_area  = sw * sh
        built_area = sum(r.area for r in self.rooms)
        open_area  = site_area - built_area
        density    = (built_area / site_area * 100) if site_area else 0

        counts: Dict[str,int]   = {}
        areas:  Dict[str,float] = {}
        for r in self.rooms:
            counts[r.label] = counts.get(r.label, 0) + 1
            areas[r.label]  = areas.get(r.label, 0)  + r.area

        avg_areas = {t: areas[t]/counts[t] for t in counts}
        return {
            "total_rooms": len(self.rooms),
            "site_area":   site_area,
            "built_area":  built_area,
            "open_area":   open_area,
            "density":     round(density, 1),
            "counts":      counts,
            "avg_areas":   avg_areas,
        }

    # Serialisation --------------------------------------------------

    def to_dict(self) -> dict:
        return {"rooms": [
            {"label": r.label, "x": r.x, "y": r.y, "w": r.w, "h": r.h,
             "pinned": r.pinned}
            for r in self.rooms
        ]}

    @classmethod
    def from_dict(cls, data: dict) -> "Hotel":
        h = cls()
        for d in data.get("rooms", []):
            room_cls = ROOM_CLASSES.get(d["label"])
            if room_cls:
                h.add_room(room_cls(d["x"], d["y"], d["w"], d["h"],
                                    pinned=d.get("pinned", False)))
        return h

    def save_json(self, path: str):
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load_json(cls, path: str) -> "Hotel":
        with open(path) as f:
            return cls.from_dict(json.load(f))

    # Snapshot for undo --------------------------------------------

    def snapshot(self) -> list:
        """Return a deep copy of room list for undo."""
        return [
            ROOM_CLASSES[r.label](r.x, r.y, r.w, r.h, pinned=r.pinned)
            for r in self.rooms
        ]

    def restore(self, snapshot: list):
        self.rooms = snapshot