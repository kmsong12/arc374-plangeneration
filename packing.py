"""
packing.py - Generic dart-throwing packer that operates on RoomTemplates.

Also exposes `pack_rooms_into_hotel` (legacy signature) for the existing
test suite, which still talks to the old `Hotel`/`rooms.py` machinery.

The packer is driven by a `candidates` list where each entry is
`(template_key, RoomTemplate, weight)`. For every attempt it samples one
candidate by weight, rolls a random grid-snapped position, and keeps it
if the template's axis-aligned bounding box doesn't overlap any already
placed room (with optional padding).

Both the unconstrained site packer and the zone-constrained packer are
supported.  Landscape bush placement is also exposed here for
convenience.
"""

from __future__ import annotations
import random
from typing import Dict, List, Optional, Sequence, Tuple

from geometry_utils import snap_to_grid, overlaps_any
from model.plan import Plan, RoomInstance
from model.room_template import RoomTemplate
from model.room_library import RoomLibrary

# Legacy size map (kept only for `pack_rooms_into_hotel` used by tests).
from config import (
    A_SIZES, B_SIZES, C_SIZES, D_SIZES,
    T1_SIZES, T2_SIZES, LIB_SIZES, RR_SIZES,
    DEFAULT_WEIGHTS,
    N_BUSHES,
    N_ROOMS_DEFAULT,
)
from rooms import (
    BedroomA, BedroomB, BedroomC, BedroomD,
    TeaRoom1, TeaRoom2, Library, ReadingRoom,
)
from hotel import Hotel as _LegacyHotel

_LEGACY_SIZES = {
    "BedroomA":   A_SIZES,
    "BedroomB":   B_SIZES,
    "BedroomC":   C_SIZES,
    "BedroomD":   D_SIZES,
    "TeaRoom1":   T1_SIZES,
    "TeaRoom2":   T2_SIZES,
    "Library":    LIB_SIZES,
    "ReadingRoom": RR_SIZES,
}
_LEGACY_CLASSES = {
    "BedroomA": BedroomA, "BedroomB": BedroomB,
    "BedroomC": BedroomC, "BedroomD": BedroomD,
    "TeaRoom1": TeaRoom1, "TeaRoom2": TeaRoom2,
    "Library":  Library,  "ReadingRoom": ReadingRoom,
}


Candidate = Tuple[str, RoomTemplate, float]  # (key, template, weight)

DEFAULT_TRY = 200


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _norm(weights: Sequence[float]) -> List[float]:
    total = sum(max(0.0, w) for w in weights) or 1.0
    return [max(0.0, w) / total for w in weights]


def _pick(candidates: List[Candidate]) -> Optional[Candidate]:
    filtered = [(k, t, w) for (k, t, w) in candidates if w > 0]
    if not filtered:
        return None
    weights = [w for (_, _, w) in filtered]
    picks = random.choices(filtered, weights=weights, k=1)
    return picks[0]


def _candidates_from_library(library: RoomLibrary,
                              enabled_types: Optional[List[str]] = None,
                              weights: Optional[Dict[str, float]] = None
                              ) -> List[Candidate]:
    """
    Build candidate list from the library.  Weights keys:
      * template key (uuid) -> applies to that specific template
      * "#<roomtype>"       -> applies to any template of that roomtype
      * missing             -> weight 1.0
    """
    weights = weights or {}
    out: List[Candidate] = []
    for key, tpl in library.all():
        if enabled_types is not None and tpl.roomtype not in enabled_types:
            continue
        w = weights.get(key)
        if w is None:
            w = weights.get(f"#{tpl.roomtype}", 1.0)
        if w <= 0:
            continue
        out.append((key, tpl, float(w)))
    return out


# ---------------------------------------------------------------------------
# Core packer
# ---------------------------------------------------------------------------

def pack_rooms(site: Tuple[int, int, int, int],
               candidates: List[Candidate],
               n_rooms: int,
               seed: Optional[int] = None,
               pad: int = 30,
               grid: int = 10,
               zones: Optional[List[Tuple[int, int, int, int]]] = None,
               zone_weights: Optional[List[Optional[Dict[str, float]]]] = None,
               library: Optional[RoomLibrary] = None,
               existing: Optional[List[RoomInstance]] = None) -> Plan:
    """
    Dart-throw `n_rooms` instances of the supplied candidates into the site.

    If `zones` are given, rooms are instead distributed across each zone,
    optionally weighted by a per-zone weights dict (keys as in
    `_candidates_from_library`).
    """
    if seed is not None:
        random.seed(seed)

    plan = Plan()
    plan.site = site
    sx, sy, sw, sh = site

    existing_boxes: List[Tuple[int, int, int, int]] = []
    if existing:
        for r in existing:
            bx, by, bw, bh = r.world_bbox()
            existing_boxes.append((int(bx), int(by), int(bw), int(bh)))
            plan.add_room(r)

    def _try_place(c_list: List[Candidate], region) -> bool:
        if not c_list:
            return False
        for _ in range(DEFAULT_TRY):
            pick = _pick(c_list)
            if not pick:
                return False
            key, tpl, _ = pick
            _, _, tw, th = tpl.bbox()
            if tw <= 0 or th <= 0:
                continue
            rx0, ry0, rw, rh = region
            if tw >= rw or th >= rh:
                continue
            x = snap_to_grid(random.uniform(rx0, rx0 + rw - tw), grid)
            y = snap_to_grid(random.uniform(ry0, ry0 + rh - th), grid)
            if x < sx or y < sy or x + tw > sx + sw or y + th > sy + sh:
                continue
            if overlaps_any((x, y, tw, th), existing_boxes, pad=pad):
                continue
            inst = RoomInstance(
                template_key=key,
                template_snapshot=tpl.copy(),
                x=x, y=y,
            )
            # Shift polygon so its bbox starts at (0,0) inside the template;
            # x,y above is the world offset for bbox origin.
            tpl2 = inst.template_snapshot
            tpl2.normalise()
            plan.add_room(inst)
            existing_boxes.append((x, y, int(tw), int(th)))
            return True
        return False

    if zones:
        for zi, zone in enumerate(zones):
            plan.zones.append(zone)
            zone_cands = candidates
            if zone_weights and zi < len(zone_weights) and zone_weights[zi]:
                # rebuild candidates with zone-specific weights
                zone_w = zone_weights[zi]
                zone_cands = []
                for k, t, _w in candidates:
                    zw = zone_w.get(k)
                    if zw is None:
                        zw = zone_w.get(f"#{t.roomtype}", 0.0)
                    if zw > 0:
                        zone_cands.append((k, t, float(zw)))
            per_zone = max(1, n_rooms // len(zones))
            for _ in range(per_zone):
                _try_place(zone_cands, zone)
    else:
        for _ in range(n_rooms):
            _try_place(candidates, site)

    return plan


# ---------------------------------------------------------------------------
# Bush packing (same algorithm as before, but returns list of circles).
# ---------------------------------------------------------------------------

def pack_bushes(site: Tuple[int, int, int, int],
                plan: Plan,
                seed: Optional[int] = None,
                n_bushes: int = 30,
                r_range: Tuple[int, int] = (8, 16),
                pad: int = 15,
                grid: int = 10,
                tries: int = 200) -> List[Tuple[int, int, int]]:
    if seed is not None:
        random.seed(seed + 1)

    sx, sy, sw, sh = site
    room_boxes: List[Tuple[int, int, int, int]] = []
    for room in plan.rooms:
        x, y, w, h = room.world_bbox()
        room_boxes.append((int(x), int(y), int(w), int(h)))
    bushes: List[Tuple[int, int, int]] = []
    bush_boxes: List[Tuple[int, int, int, int]] = []
    for _ in range(n_bushes):
        for _a in range(tries):
            r = random.randint(*r_range)
            x = snap_to_grid(random.uniform(sx + 2 * r, sx + sw - 2 * r), grid)
            y = snap_to_grid(random.uniform(sy + 2 * r, sy + sh - 2 * r), grid)
            box = (x - 2 * r, y - 2 * r, 4 * r, 4 * r)
            if (not overlaps_any(box, room_boxes, pad=pad) and
                    not overlaps_any(box, bush_boxes, pad=pad)):
                bushes.append((x, y, r))
                bush_boxes.append(box)
                break
    return bushes


# ---------------------------------------------------------------------------
# High-level convenience wrappers used by the Random and Zoning sub-modes.
# ---------------------------------------------------------------------------

def random_pack(library: RoomLibrary,
                site: Tuple[int, int, int, int],
                n_rooms: int,
                enabled_types: Optional[List[str]] = None,
                weights: Optional[Dict[str, float]] = None,
                seed: Optional[int] = None,
                pad: int = 30) -> Plan:
    cands = _candidates_from_library(library, enabled_types, weights)
    return pack_rooms(site=site, candidates=cands,
                      n_rooms=n_rooms, seed=seed, pad=pad)


def zone_pack(library: RoomLibrary,
              site: Tuple[int, int, int, int],
              zones: List[Tuple[int, int, int, int]],
              zone_specs: List[dict],
              seed: Optional[int] = None,
              pad: int = 30) -> Plan:
    """
    zone_specs[i] is a dict like:
        {"weights": {key_or_#type: weight, ...}, "max": int}
    zones[i] matches zone_specs[i].
    """
    cands_all = _candidates_from_library(library)
    per_zone_counts = [int(s.get("max", 1)) for s in zone_specs]
    per_zone_weights = [s.get("weights") for s in zone_specs]

    if seed is not None:
        random.seed(seed)

    plan = Plan()
    plan.site = site
    sx, sy, sw, sh = site
    existing_boxes: List[Tuple[int, int, int, int]] = []

    def _try_place(region, zone_w: Optional[Dict[str, float]]) -> bool:
        local_cands: List[Candidate] = []
        for k, t, _w in cands_all:
            if zone_w is None:
                wv = 1.0
            else:
                wv = zone_w.get(k)
                if wv is None:
                    wv = zone_w.get(f"#{t.roomtype}", 0.0)
            if wv > 0:
                local_cands.append((k, t, float(wv)))
        if not local_cands:
            return False
        for _ in range(DEFAULT_TRY):
            pick = _pick(local_cands)
            if not pick:
                return False
            key, tpl, _ = pick
            _, _, tw, th = tpl.bbox()
            rx, ry, rw, rh = region
            if tw <= 0 or th <= 0 or tw >= rw or th >= rh:
                continue
            x = snap_to_grid(random.uniform(rx, rx + rw - tw), 10)
            y = snap_to_grid(random.uniform(ry, ry + rh - th), 10)
            if x < sx or y < sy or x + tw > sx + sw or y + th > sy + sh:
                continue
            if overlaps_any((x, y, tw, th), existing_boxes, pad=pad):
                continue
            inst = RoomInstance(
                template_key=key,
                template_snapshot=tpl.copy(),
                x=x, y=y,
            )
            inst.template_snapshot.normalise()
            plan.add_room(inst)
            existing_boxes.append((int(x), int(y), int(tw), int(th)))
            return True
        return False

    for zi, zone in enumerate(zones):
        plan.zones.append(zone)
        count = per_zone_counts[zi] if zi < len(per_zone_counts) else 1
        zw = per_zone_weights[zi] if zi < len(per_zone_weights) else None
        for _ in range(count):
            _try_place(zone, zw)

    return plan


# ---------------------------------------------------------------------------
# LLM-driven packing (preset-style weights + optional spatial layout)
# ---------------------------------------------------------------------------

def expand_preset_weights_for_library(
        library: RoomLibrary,
        preset_weights: Dict[str, float]) -> Dict[str, float]:
    """Map seed labels (BedroomA, TeaRoom1, …) to library template keys."""
    out: Dict[str, float] = {}
    for key, tpl in library.all():
        w = preset_weights.get(tpl.label)
        if w is None and getattr(tpl, "preset_id", None):
            w = preset_weights.get(str(tpl.preset_id))
        if w is None:
            w = 1.0
        out[key] = max(0.0, float(w))
    return out


def _zone_weight_by_roomtype(
        library: RoomLibrary,
        full_w: Dict[str, float],
        allow_roomtype: str) -> Dict[str, float]:
    zw: Dict[str, float] = {}
    for key, tpl in library.all():
        if tpl.roomtype != allow_roomtype:
            zw[key] = 0.0
        else:
            zw[key] = full_w.get(key, 1.0)
    return zw


def _spatial_zones_and_weights(
        library: RoomLibrary,
        site: Tuple[int, int, int, int],
        full_w: Dict[str, float],
        spatial: str,
        ) -> Tuple[Optional[List[Tuple[int, int, int, int]]],
                   Optional[List[Dict[str, float]]]]:
    sx, sy, sw, sh = site
    half_w = max(1, sw // 2)
    half_h = max(1, sh // 2)
    top = (sx, sy, sw, half_h)
    bot = (sx, sy + half_h, sw, sh - half_h)
    left = (sx, sy, half_w, sh)
    right = (sx + half_w, sy, sw - half_w, sh)
    zbed = _zone_weight_by_roomtype(library, full_w, "bedroom")
    zpub = _zone_weight_by_roomtype(library, full_w, "public room")
    if spatial == "bedrooms_top":
        return [top, bot], [zbed, zpub]
    if spatial == "bedrooms_bottom":
        return [top, bot], [zpub, zbed]
    if spatial == "bedrooms_left":
        return [left, right], [zbed, zpub]
    if spatial == "bedrooms_right":
        return [left, right], [zpub, zbed]
    return None, None


def pack_from_llm_settings(
        library: RoomLibrary,
        site: Tuple[int, int, int, int],
        settings: dict,
        seed: Optional[int] = None,
        ) -> Plan:
    """
    Build a plan from ``llm_bridge.prompt_to_settings`` output:
    weights, n_rooms, pad, n_bushes, spatial.
    """
    preset_w = settings.get("weights") or {}
    full_w = expand_preset_weights_for_library(library, preset_w)
    cands = _candidates_from_library(library, None, full_w)
    if not cands:
        cands = _candidates_from_library(library, None, None)
    n_rooms = int(settings.get("n_rooms", N_ROOMS_DEFAULT))
    n_rooms = max(2, min(40, n_rooms))
    pad = int(settings.get("pad", 30))
    pad = max(0, min(80, pad))
    spatial = settings.get("spatial", "mixed")
    zones, zone_weights = _spatial_zones_and_weights(
        library, site, full_w, spatial)
    if zones and zone_weights:
        plan = pack_rooms(
            site=site, candidates=cands, n_rooms=n_rooms,
            seed=seed, pad=pad, zones=zones, zone_weights=zone_weights)
    else:
        plan = pack_rooms(
            site=site, candidates=cands, n_rooms=n_rooms,
            seed=seed, pad=pad)
    return plan


def pack_bushes_for_llm(
        site: Tuple[int, int, int, int],
        plan: Plan,
        settings: dict,
        seed: Optional[int] = None) -> List[Tuple[int, int, int]]:
    nb = settings.get("n_bushes")
    if nb is None:
        nb = N_BUSHES
    nb = max(0, min(80, int(nb)))
    return pack_bushes(site, plan, seed=seed, n_bushes=nb)


# ---------------------------------------------------------------------------
# Legacy compatibility (the old test_suite still uses this entry point).
# ---------------------------------------------------------------------------

def _pick_label_legacy(weights):
    total = sum(max(0.0, w) for w in weights.values()) or 1.0
    keys = list(weights.keys())
    probs = [max(0.0, weights[k]) / total for k in keys]
    return random.choices(keys, weights=probs, k=1)[0]


def pack_rooms_into_hotel(site, n_rooms, seed=None,
                          pad=30, constraint=0, weights=None):
    """
    Legacy entry point: dart-throw on the old (label, x, y, w, h) world.

    Kept only so the pre-existing `test_suite.py` keeps passing.  New
    code should call `random_pack` / `zone_pack` on the library.
    """
    if seed is not None:
        random.seed(seed)

    active_weights = dict(weights or DEFAULT_WEIGHTS)
    bedrooms = {"BedroomA", "BedroomB", "BedroomC", "BedroomD"}
    publics  = {"TeaRoom1", "TeaRoom2", "Library", "ReadingRoom"}
    if constraint == 1:
        for k in list(active_weights.keys()):
            if k not in bedrooms:
                active_weights[k] = 0.0
    elif constraint == 2:
        for k in list(active_weights.keys()):
            if k not in publics:
                active_weights[k] = 0.0

    sx, sy, sw, sh = site
    placed_tuples = []
    hotel = _LegacyHotel()
    for _ in range(n_rooms):
        for _a in range(DEFAULT_TRY):
            label = _pick_label_legacy(active_weights)
            if active_weights.get(label, 0) <= 0:
                continue
            sizes = _LEGACY_SIZES[label]
            w, h = random.choice(sizes)
            if w >= sw or h >= sh:
                continue
            x = snap_to_grid(random.uniform(sx, sx + sw - w), 10)
            y = snap_to_grid(random.uniform(sy, sy + sh - h), 10)
            if x < sx or y < sy or x + w > sx + sw or y + h > sy + sh:
                continue
            if overlaps_any((x, y, w, h), placed_tuples, pad=pad):
                continue
            klass = _LEGACY_CLASSES[label]
            hotel.add_room(klass(x=x, y=y, w=w, h=h))
            placed_tuples.append((x, y, w, h))
            break
    return hotel
