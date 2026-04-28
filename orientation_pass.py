"""
Orientation pass for LLM ``orientation_goal``: pick 0/90/180/270° rotations
so door vectors (from template centroid toward Door furniture) align with
site-center “inward collaboration” vs outward privacy heuristics.

This is a deliberate spike: simple geometry only, no SAT re-check with neighbors.
"""

from __future__ import annotations
import math
from typing import Tuple

from geometry_utils import polygon_centroid
from model.plan import Plan

OrientationGoal = str  # "mixed" | "inward_collaborative" | "outward_private"


def _unit(vx: float, vy: float) -> Tuple[float, float]:
    d = math.hypot(vx, vy)
    if d < 1e-9:
        return (1.0, 0.0)
    return (vx / d, vy / d)


def _door_local_vector(tpl) -> Tuple[float, float]:
    """Rough unit vector from polygon centroid toward Door center (local)."""
    poly = tpl.polygon or []
    if not poly:
        return (1.0, 0.0)
    cx, cy = polygon_centroid(poly)
    doors = [(f.x + f.w * 0.5, f.y + f.h * 0.5)
             for f in tpl.furniture
             if getattr(f, "type", "") == "Door"]
    if not doors:
        return (1.0, 0.0)
    mx = sum(px for px, _ in doors) / len(doors)
    my = sum(py for _, py in doors) / len(doors)
    return _unit(mx - cx, my - cy)


def _rot(vx: float, vy: float, deg: float) -> Tuple[float, float]:
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    return (vx * c - vy * s, vx * s + vy * c)


def apply_orientation_goal(plan: Plan, site: Tuple[float, float, float, float],
                           goal: OrientationGoal) -> None:
    if goal in (None, "", "mixed"):
        return
    sx, sy, sw, sh = site
    ax, ay = sx + sw / 2.0, sy + sh / 2.0

    for inst in plan.rooms:
        tpl = inst.template_snapshot
        lvx, lvy = _door_local_vector(tpl)
        bx, by, bw, bh = tpl.bbox()
        rcx = float(inst.x) + bx + bw / 2.0
        rcy = float(inst.y) + by + bh / 2.0
        to_in = _unit(ax - rcx, ay - rcy)

        best_rot = 0.0
        best_sc = -1e9
        for rot in (0.0, 90.0, 180.0, 270.0):
            wx, wy = _rot(lvx, lvy, rot)
            if goal == "inward_collaborative":
                score = wx * to_in[0] + wy * to_in[1]
            elif goal == "outward_private":
                score = -(wx * to_in[0] + wy * to_in[1])
            else:
                return
            if score > best_sc:
                best_sc = score
                best_rot = rot
        inst.rotation = best_rot % 360.0

