"""
packing.py – Dart-throwing packing algorithm.

Supports:
  • ROOM_CONSTRAINT 0/1/2 (all / bedrooms / public) — mirrors original
  • Zone-constrained packing: rooms placed inside a list of zone rects
  • Weighted room-type selection
"""

from __future__ import annotations
import random
from typing import Dict, List, Tuple, Optional

from config import (
    GRID_SIZE, PAD, TRY,
    A_SIZES, B_SIZES, C_SIZES, D_SIZES,
    T1_SIZES, T2_SIZES, LIB_SIZES, RR_SIZES,
    ROOM_CONSTRAINT, DEFAULT_WEIGHTS,
    N_BUSHES, BUSH_TRY, BUSH_R_RANGE, BUSH_PAD,
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

_BEDROOM_LABELS = {"BedroomA","BedroomB","BedroomC","BedroomD"}
_PUBLIC_LABELS  = {"TeaRoom1","TeaRoom2","Library","ReadingRoom"}


def _pick_label(weights: dict, con: int) -> str:
    """Weighted random room-type selection, filtered by constraint."""
    if con == 1:
        pool = {k: v for k, v in weights.items() if k in _BEDROOM_LABELS}
    elif con == 2:
        pool = {k: v for k, v in weights.items() if k in _PUBLIC_LABELS}
    else:
        pool = dict(weights)

    # filter out zero-weight rooms
    pool = {k: v for k, v in pool.items() if v > 0}
    if not pool:
        # fallback: equal weights for the constrained set
        if con == 1:
            pool = {k: 1.0 for k in _BEDROOM_LABELS}
        elif con == 2:
            pool = {k: 1.0 for k in _PUBLIC_LABELS}
        else:
            pool = {k: 1.0 for k in weights}

    total = sum(pool.values())
    r = random.uniform(0, total)
    cumulative = 0.0
    for label, w in pool.items():
        cumulative += w
        if r <= cumulative:
            return label
    return list(pool.keys())[-1]


def pack_rooms_into_hotel(
    site: Tuple[int,int,int,int],
    n_rooms: int,
    weights: Optional[Dict[str,float]] = None,
    seed: Optional[int] = None,
    constraint: Optional[int] = None,
    zones: Optional[List[Tuple[int,int,int,int]]] = None,
    zone_weights: Optional[List[Optional[Dict[str,float]]]] = None,
    pad: Optional[int] = None,
) -> Hotel:
    """
    Place up to n_rooms rooms inside site using dart-throwing.

    Parameters
    ----------
    site         : (sx, sy, sw, sh)
    n_rooms      : target count
    weights      : {label: weight} – controls room-type probabilities
    seed         : RNG seed
    constraint   : 0=all, 1=bedrooms, 2=public  (overrides config if given)
    zones        : list of (x,y,w,h) — rooms placed inside these rectangles
    zone_weights : per-zone weight dicts; overrides global weights for that zone
    pad          : padding between rooms in px (overrides config.PAD)
    """
    if seed is not None:
        random.seed(seed)

    con = constraint if constraint is not None else ROOM_CONSTRAINT
    w   = weights if weights is not None else DEFAULT_WEIGHTS
    _pad = pad if pad is not None else PAD
    sx, sy, sw, sh = site
    hotel = Hotel()

    # ── Zone-constrained mode ──────────────────────────────────
    if zones:
        for zi, zone in enumerate(zones):
            zx, zy, zw, zh = zone
            # per-zone weights override the global weights
            zw_dict = (zone_weights[zi]
                       if zone_weights and zi < len(zone_weights) and zone_weights[zi]
                       else None)
            zone_count = max(1, n_rooms // len(zones))
            for _ in range(zone_count):
                placed = False
                for _attempt in range(TRY):
                    if zw_dict is not None:
                        label = _pick_label(zw_dict, 0)  # zone weights already filtered
                    else:
                        label = _pick_label(w, con)
                    rw, rh = random.choice(_SIZE_MAP[label])
                    if rw >= zw or rh >= zh:
                        continue
                    x = snap_to_grid(random.uniform(zx, zx+zw-rw), GRID_SIZE)
                    y = snap_to_grid(random.uniform(zy, zy+zh-rh), GRID_SIZE)
                    if x < sx or y < sy or x+rw > sx+sw or y+rh > sy+sh:
                        continue
                    if not overlaps_any((x,y,rw,rh), hotel.as_tuples(), pad=_pad):
                        hotel.add_room(ROOM_CLASSES[label](x, y, rw, rh))
                        placed = True
                        break
        return hotel

    # ── Standard dart-throwing ────────────────────────────────
    for _ in range(n_rooms):
        placed = False
        for _attempt in range(TRY):
            label  = _pick_label(w, con)
            rw, rh = random.choice(_SIZE_MAP[label])

            if rw >= sw or rh >= sh:
                continue

            x = snap_to_grid(random.uniform(sx, sx+sw-rw), GRID_SIZE)
            y = snap_to_grid(random.uniform(sy, sy+sh-rh), GRID_SIZE)

            if not overlaps_any((x,y,rw,rh), hotel.as_tuples(), pad=_pad):
                hotel.add_room(ROOM_CLASSES[label](x, y, rw, rh))
                placed = True
                break

    return hotel


def pack_bushes(
    site: Tuple[int,int,int,int],
    hotel: Hotel,
    seed: Optional[int] = None,
    n_bushes: Optional[int] = None,
) -> List[Tuple[int,int,int]]:
    if seed is not None:
        random.seed(seed+1)
    count = n_bushes if n_bushes is not None else N_BUSHES
    sx, sy, sw, sh = site
    room_boxes = hotel.as_tuples()
    bushes: List[Tuple[int,int,int]] = []
    bush_boxes: List[Tuple[int,int,int,int]] = []
    for _ in range(count):
        for _a in range(BUSH_TRY):
            r = random.randint(*BUSH_R_RANGE)
            x = snap_to_grid(random.uniform(sx+2*r, sx+sw-2*r), GRID_SIZE)
            y = snap_to_grid(random.uniform(sy+2*r, sy+sh-2*r), GRID_SIZE)
            box = (x-2*r, y-2*r, 4*r, 4*r)
            if (not overlaps_any(box, room_boxes,  pad=BUSH_PAD) and
                not overlaps_any(box, bush_boxes,  pad=BUSH_PAD)):
                bushes.append((x, y, r))
                bush_boxes.append(box)
                break
    return bushes