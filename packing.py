"""
packing.py – Dart-throwing packing algorithm.
Room-type constraint:
  ROOM_CONSTRAINT 0 = all rooms
  ROOM_CONSTRAINT 1 = bedrooms only  (t in 0..0.5)
  ROOM_CONSTRAINT 2 = public rooms   (t in 0.5..1)
  
"""

from __future__ import annotations
import random
from typing import Dict, List, Tuple

from config import (
    GRID_SIZE, PAD, TRY,
    A_SIZES, B_SIZES, C_SIZES, D_SIZES,
    T1_SIZES, T2_SIZES, LIB_SIZES, RR_SIZES,
    ROOM_CONSTRAINT,
)
from geometry_utils import snap_to_grid, overlaps_any
from hotel import Hotel
from rooms import ROOM_CLASSES

_SIZE_MAP = {
    "BedroomA":    A_SIZES,
    "BedroomB":    B_SIZES,
    "BedroomC":    C_SIZES,
    "BedroomD":    D_SIZES,
    "TeaRoom1":    T1_SIZES,
    "TeaRoom2":    T2_SIZES,
    "Library":     LIB_SIZES,
    "ReadingRoom": RR_SIZES,
}


def _t_to_label(t: float) -> str:
    if   t < 1/8: return "BedroomA"
    elif t < 2/8: return "BedroomB"
    elif t < 3/8: return "BedroomC"
    elif t < 4/8: return "BedroomD"
    elif t < 5/8: return "TeaRoom1"
    elif t < 6/8: return "TeaRoom2"
    elif t < 7/8: return "Library"
    else:         return "ReadingRoom"


def pack_rooms_into_hotel(
    site: Tuple[int,int,int,int],
    n_rooms: int,
    weights: Dict[str,float] | None = None,
    seed: int | None = None,
    constraint: int | None = None,
) -> Hotel:
    """
    constraint overrides config.ROOM_CONSTRAINT if supplied.
      0 = all rooms
      1 = bedrooms only
      2 = public rooms only
    """
    if seed is not None:
        random.seed(seed)

    # resolve constraint
    con = constraint if constraint is not None else ROOM_CONSTRAINT

    sx, sy, sw, sh = site
    hotel = Hotel()

    for _ in range(n_rooms):
        placed = False
        for _attempt in range(TRY):
            # mirror original Processing logic exactly
            t = random.random()
            if   con == 1: t = random.uniform(0, 0.5)
            elif con == 2: t = random.uniform(0.5, 1.0)

            label  = _t_to_label(t)
            rw, rh = random.choice(_SIZE_MAP[label])

            if rw >= sw or rh >= sh:
                continue

            x = snap_to_grid(random.uniform(sx, sx+sw-rw), GRID_SIZE)
            y = snap_to_grid(random.uniform(sy, sy+sh-rh), GRID_SIZE)

            if not overlaps_any((x,y,rw,rh), hotel.as_tuples(), pad=PAD):
                hotel.add_room(ROOM_CLASSES[label](x, y, rw, rh))
                placed = True
                break

        if not placed:
            pass   # skip, keep trying remaining rooms

    return hotel


# ── Bush placement ─────────────────────────────────────────────
from config import N_BUSHES, BUSH_TRY, BUSH_R_RANGE, BUSH_PAD

def pack_bushes(site, hotel, seed=None):
    if seed is not None:
        random.seed(seed+1)
    sx,sy,sw,sh = site
    room_boxes   = hotel.as_tuples()
    bushes: list = []
    bush_boxes: list = []
    for _ in range(N_BUSHES):
        for _a in range(BUSH_TRY):
            r = random.randint(*BUSH_R_RANGE)
            x = snap_to_grid(random.uniform(sx+2*r, sx+sw-2*r), GRID_SIZE)
            y = snap_to_grid(random.uniform(sy+2*r, sy+sh-2*r), GRID_SIZE)
            box = (x-2*r, y-2*r, 4*r, 4*r)
            if (not overlaps_any(box, room_boxes,  pad=BUSH_PAD) and
                not overlaps_any(box, bush_boxes,  pad=BUSH_PAD)):
                bushes.append((x,y,r))
                bush_boxes.append(box)
                break
    return bushes