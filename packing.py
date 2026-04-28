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
from orientation_pass import apply_orientation_goal

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


def _layout_effective_pad(base_pad: int, layout_style: str,
                          min_center_distance: float) -> int:
    lp = max(0, int(base_pad))
    mcd = float(min_center_distance or 0.0)
    extra = int(round(mcd * 0.5))
    if layout_style == "scattered":
        extra += 14
    elif layout_style == "clustered":
        extra = max(0, extra - 6)
    return max(0, min(160, lp + extra))


def _sample_xy(
        rx0: int, ry0: int, rw: int, rh: int,
        tw: int, th: int,
        sx: int, sy: int, sw: int, sh: int,
        grid: int,
        clustering: float,
        layout_style: str,
        ) -> Optional[Tuple[float, float]]:
    """Return a candidate ``(x, y)`` for bbox origin or ``None`` if degenerate."""
    if rw < tw or rh < th:
        return None
    lo_x = float(rx0)
    hi_x = float(rx0 + rw - tw)
    lo_y = float(ry0)
    hi_y = float(ry0 + rh - th)
    if hi_x < lo_x or hi_y < lo_y:
        return None

    reg_cx = (lo_x + hi_x) / 2.0
    reg_cy = (lo_y + hi_y) / 2.0
    site_cx = float(sx + sw / 2.0)
    site_cy = float(sy + sh / 2.0)
    target_x = reg_cx * (1.0 - clustering) + (0.6 * reg_cx + 0.4 * site_cx) * clustering
    target_y = reg_cy * (1.0 - clustering) + (0.6 * reg_cy + 0.4 * site_cy) * clustering

    ls = (layout_style or "mixed").lower()
    if ls == "corridor":
        reg_cy = (lo_y + hi_y) / 2.0
        jitter = min(hi_y - lo_y, (hi_y - lo_y) * 0.35 + 1e-6)
        y = reg_cy + (random.random() - 0.5) * jitter
        y = max(lo_y, min(hi_y, y))
        x = random.uniform(lo_x, hi_x)
    elif ls == "scattered":
        jx = (random.random() - 0.5) * (hi_x - lo_x) * 0.2
        jy = (random.random() - 0.5) * (hi_y - lo_y) * 0.2
        ux = random.uniform(lo_x, hi_x) + jx
        uy = random.uniform(lo_y, hi_y) + jy
        x = max(lo_x, min(hi_x, ux))
        y = max(lo_y, min(hi_y, uy))
    elif ls == "clustered":
        x = max(lo_x, min(hi_x,
                          random.gauss(target_x, (hi_x - lo_x) * 0.18 + 1e-6)))
        y = max(lo_y, min(hi_y,
                          random.gauss(target_y, (hi_y - lo_y) * 0.18 + 1e-6)))
    else:
        ux = random.uniform(lo_x, hi_x)
        uy = random.uniform(lo_y, hi_y)
        x = ux * (1.0 - clustering) + target_x * clustering
        y = uy * (1.0 - clustering) + target_y * clustering
        x = max(lo_x, min(hi_x, x))
        y = max(lo_y, min(hi_y, y))

    return (snap_to_grid(x, grid), snap_to_grid(y, grid))


def _allocate_rooms_per_zone(
        n_total: int, n_zones: int,
        explicit: Optional[List[int]],
        ) -> List[int]:
    """When ``explicit`` omitted, evenly split ``n_total``."""
    if n_zones <= 0:
        return []
    if explicit and len(explicit) == n_zones and sum(explicit) > 0:
        return [max(0, int(x)) for x in explicit]
    nt = max(1, n_total)
    base = nt // n_zones
    rem = nt % n_zones
    return [base + (1 if i < rem else 0) for i in range(n_zones)]


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
               existing: Optional[List[RoomInstance]] = None,
               *,
               clustering: float = 0.0,
               layout_style: str = "mixed",
               try_multiplier: float = 1.0,
               rooms_per_zone: Optional[List[int]] = None,
               ) -> Plan:
    """
    Dart-throw ``n_rooms`` instances into the site (or per-zone quotas).

    With ``zones``, uses ``rooms_per_zone`` when provided (sums drive totals),
    else splits ``n_rooms`` across zones.
    """
    if seed is not None:
        random.seed(seed)

    tm = float(try_multiplier) if try_multiplier > 0 else 1.0
    tm = max(0.25, min(5.0, tm))
    inner_tries = max(40, int(DEFAULT_TRY * tm))

    plan = Plan()
    plan.site = site
    sx, sy, sw, sh = site
    clump = float(max(0.0, min(1.0, clustering)))
    lst = str(layout_style or "mixed").lower()

    existing_boxes: List[Tuple[int, int, int, int]] = []
    if existing:
        for r in existing:
            bx, by, bw, bh = r.world_bbox()
            existing_boxes.append((int(bx), int(by), int(bw), int(bh)))
            plan.add_room(r)

    def _try_place(c_list: List[Candidate], region) -> bool:
        if not c_list:
            return False
        for _ in range(inner_tries):
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
            xy = _sample_xy(rx0, ry0, rw, rh, tw, th, sx, sy, sw, sh,
                            grid, clump, lst)
            if xy is None:
                continue
            x, y = xy
            if x < sx or y < sy or x + tw > sx + sw or y + th > sy + sh:
                continue
            if overlaps_any((x, y, tw, th), existing_boxes, pad=pad):
                continue
            inst = RoomInstance(
                template_key=key,
                template_snapshot=tpl.copy(),
                x=x, y=y,
            )
            tpl2 = inst.template_snapshot
            tpl2.normalise()
            plan.add_room(inst)
            existing_boxes.append((x, y, int(tw), int(th)))
            return True
        return False

    if zones:
        nz = len(zones)
        alloc = _allocate_rooms_per_zone(n_rooms, nz, rooms_per_zone)
        for zi, zone in enumerate(zones):
            plan.zones.append(zone)
            zone_cands = candidates
            if zone_weights and zi < len(zone_weights) and zone_weights[zi]:
                zone_w = zone_weights[zi]
                zone_cands = []
                for k, t, _w in candidates:
                    zw = zone_w.get(k)
                    if zw is None:
                        zw = zone_w.get(f"#{t.roomtype}", 0.0)
                    if zw > 0:
                        zone_cands.append((k, t, float(zw)))
            n_here = alloc[zi] if zi < len(alloc) else max(1, n_rooms // nz)
            for _ in range(max(0, n_here)):
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
    tw = max(1, sw // 3)
    th = max(1, sh // 3)
    qw = max(1, sw // 2)
    qh = max(1, sh // 2)

    top = (sx, sy, sw, half_h)
    bot = (sx, sy + half_h, sw, sh - half_h)
    left = (sx, sy, half_w, sh)
    right = (sx + half_w, sy, sw - half_w, sh)

    wst = (sx, sy, tw, sh)
    west_rest = (sx + tw, sy, sw - tw, sh)
    est = (sx + sw - tw, sy, tw, sh)
    east_rest = (sx, sy, sw - tw, sh)

    nth = (sx, sy, sw, th)
    midh = (sx, sy + th, sw, th)
    south_rest = (sx, sy + 2 * th, sw, sh - 2 * th)

    nstrip = (sx, sy, sw, th)
    srest = (sx, sy + th, sw, sh - th)

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

    if spatial == "bedrooms_west_third":
        return [wst, west_rest], [zbed, zpub]
    if spatial == "bedrooms_east_third":
        return [east_rest, est], [zpub, zbed]
    if spatial == "bedrooms_north_third":
        return [nstrip, srest], [zbed, zpub]
    if spatial == "bedrooms_south_third":
        return [srest, nstrip], [zpub, zbed]

    # Three stacked horizontal bands
    if spatial == "bedrooms_north_middle_south_three":
        z3 = (sx, sy + 2 * th, sw, max(1, sh - 2 * th))
        return [nth, midh, z3], [zbed, zpub, zpub]

    # Three vertical columns
    if spatial == "bedrooms_west_middle_east_three":
        cw = max(1, sw // 3)
        c0 = (sx, sy, cw, sh)
        c1 = (sx + cw, sy, cw, sh)
        c2 = (sx + 2 * cw, sy, max(1, sw - 2 * cw), sh)
        return [c0, c1, c2], [zbed, zpub, zpub]

    # Four quadrants — bedroom emphasis in one corner
    nw = (sx, sy, qw, qh)
    ne = (sx + qw, sy, sw - qw, qh)
    swq = (sx, sy + qh, qw, sh - qh)
    se = (sx + qw, sy + qh, sw - qw, sh - qh)
    if spatial == "bedrooms_nw_quarter":
        return [nw, ne, swq, se], [zbed, zpub, zpub, zpub]
    if spatial == "bedrooms_ne_quarter":
        return [nw, ne, swq, se], [zpub, zbed, zpub, zpub]
    if spatial == "bedrooms_sw_quarter":
        return [nw, ne, swq, se], [zpub, zpub, zbed, zpub]
    if spatial == "bedrooms_se_quarter":
        return [nw, ne, swq, se], [zpub, zpub, zpub, zbed]

    return None, None


def _pixel_zones_from_normalized(
        site: Tuple[int, int, int, int],
        rel_list: List[Tuple[float, float, float, float]],
        ) -> List[Tuple[int, int, int, int]]:
    sx, sy, sw, sh = site
    out: List[Tuple[int, int, int, int]] = []
    for fx, fy, fw, fh in rel_list:
        x = int(sx + fx * sw)
        y = int(sy + fy * sh)
        w = max(30, int(fw * sw))
        h = max(30, int(fh * sh))
        x = max(sx, min(sx + sw - w, x))
        y = max(sy, min(sy + sh - h, y))
        w = min(w, sx + sw - x)
        h = min(h, sy + sh - y)
        if w >= 30 and h >= 30:
            out.append((x, y, w, h))
    return out


def _merge_zone_spec_weights(
        library: RoomLibrary,
        full_w: Dict[str, float],
        spec: dict,
        ) -> Dict[str, float]:
    """Single zone weight map: template key -> float."""
    raw = spec.get("weights")
    out: Dict[str, float] = {}
    for key, tpl in library.all():
        w = None
        if isinstance(raw, dict):
            w = raw.get(tpl.label)
            if w is None:
                w = raw.get(f"#{tpl.roomtype}")
        if w is None:
            w = full_w.get(key, 0.0)
        out[key] = max(0.0, float(w))
    return out


def _apply_bedroom_bias(full_w: Dict[str, float],
                        library: RoomLibrary,
                        bias: float) -> None:
    """Scale bedroom vs public template weights in place."""
    b = max(0.0, min(1.0, float(bias)))
    for key, tpl in library.all():
        if tpl.roomtype == "bedroom":
            full_w[key] *= 0.25 + 0.75 * b
        else:
            full_w[key] *= 0.25 + 0.75 * (1.0 - b)


def _apply_roomtype_weights(
        full_w: Dict[str, float],
        library: RoomLibrary,
        rtw: Dict[str, float],
        ) -> None:
    for key, tpl in library.all():
        rt = tpl.roomtype
        if rt in rtw:
            full_w[key] *= max(0.0, float(rtw[rt]))


def _enabled_types_from_settings(settings: dict) -> Optional[List[str]]:
    """Normalize ``enabled_roomtypes`` / ``roomtypes`` for ``_candidates_from_library``."""
    raw = settings.get("enabled_roomtypes") or settings.get("roomtypes")
    if not isinstance(raw, list) or not raw:
        return None
    known = frozenset({"bedroom", "public room"})
    out: List[str] = []
    for x in raw:
        s = str(x).strip().lower().replace("_", " ")
        if s in ("public", "commons", "communal"):
            s = "public room"
        if s in known and s not in out:
            out.append(s)
    return out if out else None


def pack_from_llm_settings(
        library: RoomLibrary,
        site: Tuple[int, int, int, int],
        settings: dict,
        seed: Optional[int] = None,
        ) -> Plan:
    """
    Build a plan from ``llm_bridge.prompt_to_settings`` output (rich schema).
    """
    preset_w = settings.get("weights") or {}
    full_w = expand_preset_weights_for_library(library, preset_w)

    if "roomtype_weights" in settings and isinstance(settings["roomtype_weights"], dict):
        _apply_roomtype_weights(
            full_w, library, settings["roomtype_weights"])

    if "bedroom_bias" in settings:
        _apply_bedroom_bias(full_w, library, float(settings["bedroom_bias"]))

    enabled_types = _enabled_types_from_settings(settings)
    cands = _candidates_from_library(library, enabled_types, full_w)
    if not cands:
        cands = _candidates_from_library(library, None, full_w)
    if not cands:
        cands = _candidates_from_library(library, None, None)

    n_rooms = int(settings.get("n_rooms", N_ROOMS_DEFAULT))
    n_rooms = max(2, min(40, n_rooms))
    base_pad = int(settings.get("pad", 30))
    base_pad = max(0, min(120, base_pad))
    layout_style = str(settings.get("layout_style", "mixed")).lower()
    mcd = float(settings.get("min_center_distance") or 0.0)
    eff_pad = _layout_effective_pad(base_pad, layout_style, mcd)

    clustering = float(settings.get("clustering") or 0.0)
    clustering = max(0.0, min(1.0, clustering))
    if layout_style == "clustered":
        clustering = max(clustering, 0.35)
    if layout_style == "scattered":
        clustering *= 0.4

    try_mult = float(settings.get("entropy") or 1.0)
    try_mult = max(0.3, min(4.0, try_mult))

    rooms_pz = settings.get("rooms_per_zone")
    zs_norm = settings.get("zones_normalized")
    zones: Optional[List[Tuple[int, int, int, int]]] = None
    zone_weights: Optional[List[Optional[Dict[str, float]]]] = None

    if isinstance(zs_norm, list) and zs_norm:
        rel = []
        for z in zs_norm:
            if isinstance(z, (list, tuple)) and len(z) >= 4:
                rel.append((float(z[0]), float(z[1]), float(z[2]), float(z[3])))
            elif isinstance(z, dict):
                rel.append((float(z.get("x", 0)), float(z.get("y", 0)),
                            float(z.get("w", 1)), float(z.get("h", 1))))
        zon = _pixel_zones_from_normalized(site, rel)
        if zon:
            zones = zon
            specs = settings.get("zones_specs") or []
            zwlist: List[Optional[Dict[str, float]]] = []
            for i in range(len(zones)):
                sp = specs[i] if i < len(specs) else {"max": 10, "weights": {}}
                zwlist.append(_merge_zone_spec_weights(library, full_w, sp))
            zone_weights = zwlist

    spatial = str(settings.get("spatial", "mixed"))
    if (
            enabled_types is not None
            and len(enabled_types) == 1
            and spatial.startswith("bedrooms_")):
        spatial = "mixed"
    if zones is None:
        zones, zone_weights = _spatial_zones_and_weights(
            library, site, full_w, spatial)

    kwargs: dict = dict(
        site=site,
        candidates=cands,
        n_rooms=n_rooms,
        seed=seed,
        pad=eff_pad,
        clustering=clustering,
        layout_style=layout_style,
        try_multiplier=try_mult,
        rooms_per_zone=(
            rooms_pz if isinstance(rooms_pz, list) else None),
    )

    if zones and zone_weights:
        kwargs["zones"] = zones
        kwargs["zone_weights"] = zone_weights

    plan = pack_rooms(**kwargs)
    og = str(settings.get("orientation_goal") or "mixed").lower()
    if og in ("inward_collaborative", "outward_private"):
        apply_orientation_goal(plan, site, og)
    return plan


def pack_bushes_for_llm(
        site: Tuple[int, int, int, int],
        plan: Plan,
        settings: dict,
        seed: Optional[int] = None) -> List[Tuple[int, int, int]]:
    nb = settings.get("n_bushes")
    if nb is None:
        nb = N_BUSHES
    nb = max(0, min(120, int(nb)))
    bp = settings.get("bush_pad")
    pad_b = 15
    if bp is not None:
        pad_b = max(0, min(120, int(bp)))
    return pack_bushes(site, plan, seed=seed, n_bushes=nb, pad=pad_b)


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
