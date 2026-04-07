"""
packing.py – Dart-throwing packing algorithm.

Now weight-aware: accepts a dict of {label: weight} so that the
LLM prompt mode and the sliders can influence room composition
without touching the placement logic itself.
"""

from __future__ import annotations
import random
from typing import Dict, List, Tuple

from config import (
    GRID_SIZE, PAD, TRY,
    A_SIZES, B_SIZES, C_SIZES, D_SIZES,
    T1_SIZES, T2_SIZES, LIB_SIZES, RR_SIZES,
    DEFAULT_WEIGHTS,
)
from geometry_utils import snap_to_grid, overlaps_any
from hotel import Hotel
from rooms import ROOM_CLASSES

# Map label → size palette
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


def _weighted_choice(weights: Dict[str, float]) -> str:
    """Pick a room-type label using the supplied weight dict."""
    labels  = list(weights.keys())
    totals  = list(weights.values())
    return random.choices(labels, weights=totals, k=1)[0]


def pack_rooms_into_hotel(
    site: Tuple[int, int, int, int],
    n_rooms: int,
    weights: Dict[str, float] | None = None,
    seed: int | None = None,
) -> Hotel:
    """
    Place up to n_rooms non-overlapping rooms inside site using dart-throwing.

    Parameters
    ----------
    site    : (sx, sy, sw, sh) canvas-pixel rectangle
    n_rooms : target number of rooms
    weights : dict of {room_label: relative_weight}; defaults to equal weights
    seed    : optional RNG seed for reproducibility

    Returns
    -------
    A Hotel containing all successfully placed rooms.
    """
    if seed is not None:
        random.seed(seed)

    if weights is None:
        weights = DEFAULT_WEIGHTS.copy()

    # Normalise weights so they sum to 1
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}

    sx, sy, sw, sh = site
    hotel = Hotel()

    for _ in range(n_rooms):
        placed = False
        for _attempt in range(TRY):
            label  = _weighted_choice(weights)
            sizes  = _SIZE_MAP[label]
            rw, rh = random.choice(sizes)

            # Guard: room must fit inside site
            if rw >= sw or rh >= sh:
                continue

            x = snap_to_grid(random.uniform(sx, sx + sw - rw), GRID_SIZE)
            y = snap_to_grid(random.uniform(sy, sy + sh - rh), GRID_SIZE)

            candidate = (x, y, rw, rh)
            if not overlaps_any(candidate, hotel.as_tuples(), pad=PAD):
                room_cls = ROOM_CLASSES[label]
                hotel.add_room(room_cls(x, y, rw, rh))
                placed = True
                break

        if not placed:
            # Could not place this room after TRY attempts – skip
            pass

    return hotel


# ── Bush placement ─────────────────────────────────────────────

from config import N_BUSHES, BUSH_TRY, BUSH_R_RANGE, BUSH_PAD


def pack_bushes(
    site: Tuple[int, int, int, int],
    hotel: Hotel,
    seed: int | None = None,
) -> List[Tuple[int, int, int]]:
    """Return a list of (x, y, r) bush positions that don't overlap rooms."""
    if seed is not None:
        random.seed(seed + 1)   # use a different offset so bushes don't mirror rooms

    sx, sy, sw, sh = site
    room_boxes = hotel.as_tuples()
    bushes: List[Tuple[int, int, int]]       = []
    bush_boxes: List[Tuple[int, int, int, int]] = []

    for _ in range(N_BUSHES):
        for _attempt in range(BUSH_TRY):
            r = random.randint(*BUSH_R_RANGE)
            x = snap_to_grid(random.uniform(sx + 2 * r, sx + sw - 2 * r), GRID_SIZE)
            y = snap_to_grid(random.uniform(sy + 2 * r, sy + sh - 2 * r), GRID_SIZE)
            box = (x - 2 * r, y - 2 * r, 4 * r, 4 * r)
            if (not overlaps_any(box, room_boxes, pad=BUSH_PAD)
                    and not overlaps_any(box, bush_boxes, pad=BUSH_PAD)):
                bushes.append((x, y, r))
                bush_boxes.append(box)
                break

    return bushes
