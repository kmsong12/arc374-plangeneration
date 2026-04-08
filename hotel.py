"""
hotel.py – Hotel model: a collection of Room objects.

"""

from __future__ import annotations
from typing import List, Tuple, Dict
from rooms import Room


class Hotel:
    def __init__(self):
        self.rooms: List[Room] = []

    #  Mutation ------------------------------------------------

    def add_room(self, room: Room):
        self.rooms.append(room)

    def remove_room(self, room: Room):
        self.rooms.remove(room)

    def clear(self):
        self.rooms.clear()

    #  Queries --------------------------------------------------

    def as_tuples(self) -> List[Tuple[int, int, int, int]]:
        return [r.as_tuple() for r in self.rooms]

    def room_at(self, px: int, py: int) -> Room | None:
        # Return the topmost room under pixel (px, py), or None.
        for room in reversed(self.rooms):
            if room.contains(px, py):
                return room
        return None

    #  Metrics --------------------------------------------------

    def compute_metrics(self, site: Tuple[int, int, int, int]) -> Dict:
        # Return a dict of statistics for the metrics bar / panel.
        # site = (sx, sy, sw, sh)
        sx, sy, sw, sh = site
        site_area  = sw * sh
        built_area = sum(r.area for r in self.rooms)
        open_area  = site_area - built_area
        density    = (built_area / site_area * 100) if site_area else 0

        counts: Dict[str, int]   = {}
        areas:  Dict[str, float] = {}
        for r in self.rooms:
            counts[r.label] = counts.get(r.label, 0) + 1
            areas[r.label]  = areas.get(r.label, 0)  + r.area

        avg_areas = {t: areas[t] / counts[t] for t in counts}

        return {
            "total_rooms":  len(self.rooms),
            "site_area":    site_area,
            "built_area":   built_area,
            "open_area":    open_area,
            "density":      round(density, 1),
            "counts":       counts,
            "avg_areas":    avg_areas,
        }
