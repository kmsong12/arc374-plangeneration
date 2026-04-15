"""
rooms.py - Room data model.

Drawing is handled by canvas_renderer.py 

"""

from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class Room:
    # Base room. All coordinates in canvas pixels.
    x: int
    y: int
    w: int
    h: int
    label: str = "Room"

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def area(self) -> int:
        return self.w * self.h

    def move(self, dx: int, dy: int):
        self.x += dx
        self.y += dy

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h


@dataclass
class BedroomA(Room):
    label: str = "BedroomA"

@dataclass
class BedroomB(Room):
    label: str = "BedroomB"

@dataclass
class BedroomC(Room):
    label: str = "BedroomC"

@dataclass
class BedroomD(Room):
    label: str = "BedroomD"

@dataclass
class TeaRoom1(Room):
    label: str = "TeaRoom1"

@dataclass
class TeaRoom2(Room):
    label: str = "TeaRoom2"

@dataclass
class Library(Room):
    label: str = "Library"

@dataclass
class ReadingRoom(Room):
    label: str = "ReadingRoom"


# Convenience map: label string → Room subclass
ROOM_CLASSES = {
    "BedroomA":    BedroomA,
    "BedroomB":    BedroomB,
    "BedroomC":    BedroomC,
    "BedroomD":    BedroomD,
    "TeaRoom1":    TeaRoom1,
    "TeaRoom2":    TeaRoom2,
    "Library":     Library,
    "ReadingRoom": ReadingRoom,
}
