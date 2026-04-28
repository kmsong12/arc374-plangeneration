"""
room_library.py - Persistent catalog of RoomTemplates.

The library is shared across all three stages.  On first launch (or when
the JSON file is missing / empty) it is seeded with 8 starter templates
that wrap the hand-drawn preset rooms from presets.py so users get
visually-rich examples to duplicate and edit.
"""

from __future__ import annotations
import json
import os
import uuid
from typing import Dict, Iterable, List, Optional

from model.room_template import RoomTemplate, FurnitureItem
from geometry_utils import rect_to_polygon


# ---------------------------------------------------------------------------
# Seeded starter templates
# ---------------------------------------------------------------------------

_SEED_SPECS = [
    # (label, roomtype, preset_id, width, height, fill, border)
    ("BedroomA",    "bedroom",     "BedroomA",    220, 260, "#EBF3FB", "#378ADD"),
    ("BedroomB",    "bedroom",     "BedroomB",    260, 180, "#EBF3FB", "#378ADD"),
    ("BedroomC",    "bedroom",     "BedroomC",    150, 150, "#EDF5E2", "#639922"),
    ("BedroomD",    "bedroom",     "BedroomD",    180, 320, "#EDF5E2", "#639922"),
    ("TeaRoom1",    "public room", "TeaRoom1",    220, 220, "#FDF3E2", "#C27A18"),
    ("TeaRoom2",    "public room", "TeaRoom2",    260, 200, "#FDF3E2", "#C27A18"),
    ("Library",     "public room", "Library",     400, 360, "#FCF0F5", "#C8447A"),
    ("ReadingRoom", "public room", "ReadingRoom", 200, 200, "#F1F0FD", "#7B72D8"),
]


def _seed_templates() -> Dict[str, RoomTemplate]:
    out: Dict[str, RoomTemplate] = {}
    for label, roomtype, preset_id, w, h, fill, border in _SEED_SPECS:
        tpl = RoomTemplate(
            label=label,
            roomtype=roomtype,
            polygon=rect_to_polygon(0, 0, w, h),
            fill_color=fill,
            border_color=border,
            preset_id=preset_id,
        )
        key = uuid.uuid4().hex[:10]
        out[key] = tpl
    return out


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

class RoomLibrary:

    def __init__(self, path: str):
        self.path = path
        self.templates: Dict[str, RoomTemplate] = {}
        self.load()
        if not self.templates:
            self.templates = _seed_templates()
            self.save()

    # --- persistence ----------------------------------------------------

    def load(self) -> None:
        if not os.path.isfile(self.path):
            self.templates = {}
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.templates = {}
            for key, td in data.get("templates", {}).items():
                self.templates[key] = RoomTemplate.from_dict(td)
        except Exception:
            self.templates = {}

    def save(self) -> None:
        data = {"templates": {k: t.to_dict()
                              for k, t in self.templates.items()}}
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # --- mutation -------------------------------------------------------

    def add(self, template: RoomTemplate) -> str:
        key = uuid.uuid4().hex[:10]
        self.templates[key] = template
        self.save()
        return key

    def update(self, key: str, template: RoomTemplate) -> None:
        if key in self.templates:
            self.templates[key] = template
            self.save()

    def remove(self, key: str) -> None:
        if key in self.templates:
            del self.templates[key]
            self.save()

    def reset_to_seeds(self) -> None:
        self.templates = _seed_templates()
        self.save()

    # --- queries --------------------------------------------------------

    def get(self, key: str) -> Optional[RoomTemplate]:
        return self.templates.get(key)

    def all(self) -> List[tuple]:
        """Return list of (key, template) pairs preserving insertion order."""
        return list(self.templates.items())

    def by_roomtype(self, roomtype: str) -> List[tuple]:
        return [(k, t) for k, t in self.templates.items()
                if t.roomtype == roomtype]

    def roomtypes(self) -> List[str]:
        types = []
        for t in self.templates.values():
            if t.roomtype not in types:
                types.append(t.roomtype)
        return types


_LIBRARY: Optional[RoomLibrary] = None


def get_library() -> RoomLibrary:
    """Return the process-wide singleton RoomLibrary."""
    global _LIBRARY
    if _LIBRARY is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(os.path.dirname(here), "room_library.json")
        _LIBRARY = RoomLibrary(path)
    return _LIBRARY
