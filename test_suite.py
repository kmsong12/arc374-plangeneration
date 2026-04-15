"""
test_suite.py – Comprehensive unit tests for arc374-plangeneration.

Run directly:
    python test_suite.py
or via unittest discovery:
    python -m unittest test_suite
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# ── Ensure project root is on the path ────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DEFAULT_WEIGHTS
from geometry_utils import (
    clamp,
    overlaps_any,
    point_in_rect,
    rect_from_two_points,
    rect_overlap,
    snap_to_grid,
)
from hotel import Hotel
from packing import pack_rooms_into_hotel
from rooms import (
    ROOM_CLASSES,
    BedroomA, BedroomB, BedroomC, BedroomD,
    Library, ReadingRoom, Room, TeaRoom1, TeaRoom2,
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. geometry_utils
# ══════════════════════════════════════════════════════════════════════════════

class TestSnapToGrid(unittest.TestCase):

    def test_already_on_grid(self):
        self.assertEqual(snap_to_grid(100, 10), 100)

    def test_rounds_up(self):
        self.assertEqual(snap_to_grid(106, 10), 110)

    def test_rounds_down(self):
        self.assertEqual(snap_to_grid(104, 10), 100)

    def test_exact_midpoint_rounds_to_nearest(self):
        # Python uses banker's rounding: round(10.5) == 10 (round half to even)
        self.assertEqual(snap_to_grid(105, 10), 100)

    def test_returns_int(self):
        self.assertIsInstance(snap_to_grid(73.7, 10), int)

    # edge cases
    def test_zero_value(self):
        self.assertEqual(snap_to_grid(0, 10), 0)

    def test_grid_size_one(self):
        self.assertEqual(snap_to_grid(7.4, 1), 7)

    def test_negative_value(self):
        # -14 / 10 = -1.4 → rounds to -1 → -10
        self.assertEqual(snap_to_grid(-14, 10), -10)


class TestRectOverlap(unittest.TestCase):

    def test_clearly_overlapping(self):
        self.assertTrue(rect_overlap(0, 0, 100, 100, 50, 50, 100, 100))

    def test_no_overlap_horizontal(self):
        self.assertFalse(rect_overlap(0, 0, 100, 100, 200, 0, 100, 100))

    def test_no_overlap_vertical(self):
        self.assertFalse(rect_overlap(0, 0, 100, 100, 0, 200, 100, 100))

    def test_touching_edge_is_not_overlap(self):
        # right edge of first == left edge of second → no overlap
        self.assertFalse(rect_overlap(0, 0, 100, 100, 100, 0, 100, 100))

    def test_partial_overlap(self):
        self.assertTrue(rect_overlap(0, 0, 100, 100, 90, 90, 100, 100))

    # edge cases
    def test_one_inside_other(self):
        self.assertTrue(rect_overlap(0, 0, 200, 200, 50, 50, 50, 50))

    def test_identical_rects(self):
        self.assertTrue(rect_overlap(10, 10, 50, 50, 10, 10, 50, 50))

    def test_zero_size_rect(self):
        # a 0×0 rect cannot overlap anything
        self.assertFalse(rect_overlap(0, 0, 0, 0, 0, 0, 100, 100))


class TestOverlapsAny(unittest.TestCase):

    def test_no_rooms(self):
        self.assertFalse(overlaps_any((0, 0, 100, 100), []))

    def test_overlap_detected(self):
        rooms = [(50, 50, 100, 100)]
        self.assertTrue(overlaps_any((80, 80, 50, 50), rooms))

    def test_no_overlap(self):
        rooms = [(0, 0, 100, 100)]
        self.assertFalse(overlaps_any((200, 200, 50, 50), rooms))

    def test_padding_triggers_overlap(self):
        # rects don't overlap on their own, but with pad=20 they do
        rooms = [(0, 0, 100, 100)]
        self.assertTrue(overlaps_any((110, 0, 50, 50), rooms, pad=20))

    # edge cases
    def test_touching_without_padding(self):
        rooms = [(0, 0, 100, 100)]
        self.assertFalse(overlaps_any((100, 0, 50, 50), rooms, pad=0))

    def test_multiple_rooms_only_one_overlaps(self):
        rooms = [(0, 0, 50, 50), (500, 500, 50, 50)]
        self.assertTrue(overlaps_any((30, 30, 50, 50), rooms))

    def test_zero_pad_is_default(self):
        rooms = [(0, 0, 100, 100)]
        result_explicit = overlaps_any((150, 0, 50, 50), rooms, pad=0)
        result_default  = overlaps_any((150, 0, 50, 50), rooms)
        self.assertEqual(result_explicit, result_default)


class TestPointInRect(unittest.TestCase):

    def test_centre_is_inside(self):
        self.assertTrue(point_in_rect(50, 50, 0, 0, 100, 100))

    def test_outside(self):
        self.assertFalse(point_in_rect(200, 200, 0, 0, 100, 100))

    def test_on_left_edge(self):
        self.assertTrue(point_in_rect(0, 50, 0, 0, 100, 100))

    def test_on_right_edge(self):
        self.assertTrue(point_in_rect(100, 50, 0, 0, 100, 100))

    # edge cases
    def test_corner_point(self):
        self.assertTrue(point_in_rect(0, 0, 0, 0, 100, 100))

    def test_just_outside_right(self):
        self.assertFalse(point_in_rect(101, 50, 0, 0, 100, 100))

    def test_zero_size_rect(self):
        # only the origin point itself is "inside" a 0×0 rect
        self.assertTrue(point_in_rect(5, 5, 5, 5, 0, 0))
        self.assertFalse(point_in_rect(6, 5, 5, 5, 0, 0))


class TestRectFromTwoPoints(unittest.TestCase):

    def test_top_left_to_bottom_right(self):
        self.assertEqual(rect_from_two_points(0, 0, 100, 80), (0, 0, 100, 80))

    def test_bottom_right_to_top_left(self):
        # reversed point order should still produce a valid rect
        self.assertEqual(rect_from_two_points(100, 80, 0, 0), (0, 0, 100, 80))

    def test_same_point_gives_zero_size(self):
        self.assertEqual(rect_from_two_points(50, 50, 50, 50), (50, 50, 0, 0))

    # edge cases
    def test_negative_coordinates(self):
        x, y, w, h = rect_from_two_points(-50, -50, 50, 50)
        self.assertEqual((x, y), (-50, -50))
        self.assertEqual((w, h), (100, 100))

    def test_width_height_always_positive(self):
        _, _, w, h = rect_from_two_points(200, 200, 10, 10)
        self.assertGreaterEqual(w, 0)
        self.assertGreaterEqual(h, 0)

    def test_horizontal_line(self):
        x, y, w, h = rect_from_two_points(0, 5, 100, 5)
        self.assertEqual(h, 0)
        self.assertEqual(w, 100)


class TestClamp(unittest.TestCase):

    def test_value_in_range(self):
        self.assertEqual(clamp(50, 0, 100), 50)

    def test_value_below_min(self):
        self.assertEqual(clamp(-10, 0, 100), 0)

    def test_value_above_max(self):
        self.assertEqual(clamp(150, 0, 100), 100)

    def test_value_at_min(self):
        self.assertEqual(clamp(0, 0, 100), 0)

    def test_value_at_max(self):
        self.assertEqual(clamp(100, 0, 100), 100)

    # edge cases
    def test_floats(self):
        self.assertAlmostEqual(clamp(1.5, 0.0, 1.0), 1.0)

    def test_min_equals_max(self):
        self.assertEqual(clamp(50, 10, 10), 10)

    def test_negative_range(self):
        self.assertEqual(clamp(-5, -10, -1), -5)


# ══════════════════════════════════════════════════════════════════════════════
# 2. hotel
# ══════════════════════════════════════════════════════════════════════════════

SITE = (0, 0, 800, 600)


class TestHotelMutation(unittest.TestCase):

    def setUp(self):
        self.hotel = Hotel()
        self.room_a = BedroomA(10, 10, 160, 220)
        self.room_b = BedroomB(300, 10, 240, 160)

    def test_add_room_increases_count(self):
        self.hotel.add_room(self.room_a)
        self.assertEqual(len(self.hotel.rooms), 1)

    def test_add_multiple_rooms(self):
        self.hotel.add_room(self.room_a)
        self.hotel.add_room(self.room_b)
        self.assertEqual(len(self.hotel.rooms), 2)

    def test_remove_room_decreases_count(self):
        self.hotel.add_room(self.room_a)
        self.hotel.remove_room(self.room_a)
        self.assertEqual(len(self.hotel.rooms), 0)

    def test_remove_nonexistent_room_is_safe(self):
        self.hotel.add_room(self.room_a)
        self.hotel.remove_room(self.room_b)   # room_b was never added
        self.assertEqual(len(self.hotel.rooms), 1)

    def test_clear_empties_hotel(self):
        self.hotel.add_room(self.room_a)
        self.hotel.add_room(self.room_b)
        self.hotel.clear()
        self.assertEqual(len(self.hotel.rooms), 0)


class TestHotelRoomAt(unittest.TestCase):

    def setUp(self):
        self.hotel = Hotel()
        self.room = BedroomA(100, 100, 160, 220)
        self.hotel.add_room(self.room)

    def test_hit_inside_room(self):
        self.assertIs(self.hotel.room_at(150, 150), self.room)

    def test_miss_outside_room(self):
        self.assertIsNone(self.hotel.room_at(0, 0))

    def test_hit_on_border(self):
        # contains() is inclusive on both ends
        self.assertIs(self.hotel.room_at(100, 100), self.room)

    def test_empty_hotel_returns_none(self):
        empty = Hotel()
        self.assertIsNone(empty.room_at(100, 100))

    def test_last_added_room_is_returned_on_overlap(self):
        # room2 drawn on top (added later) → should be returned
        room2 = BedroomB(120, 120, 240, 160)
        self.hotel.add_room(room2)
        hit = self.hotel.room_at(150, 150)
        self.assertIs(hit, room2)


class TestHotelMetrics(unittest.TestCase):

    def test_empty_hotel(self):
        m = Hotel().compute_metrics(SITE)
        self.assertEqual(m["total_rooms"], 0)
        self.assertEqual(m["built_area"], 0)
        self.assertEqual(m["density"], 0.0)

    def test_single_room(self):
        h = Hotel()
        h.add_room(BedroomA(0, 0, 160, 220))
        m = h.compute_metrics(SITE)
        self.assertEqual(m["total_rooms"], 1)
        self.assertEqual(m["built_area"], 160 * 220)
        self.assertIn("BedroomA", m["counts"])
        self.assertEqual(m["counts"]["BedroomA"], 1)

    def test_density_calculation(self):
        h = Hotel()
        sx, sy, sw, sh = SITE
        # fill half the site exactly
        h.add_room(BedroomA(0, 0, sw // 2, sh))
        m = h.compute_metrics(SITE)
        self.assertAlmostEqual(m["density"], 50.0, places=0)

    def test_avg_areas_per_type(self):
        h = Hotel()
        h.add_room(BedroomA(0, 0, 160, 220))
        h.add_room(BedroomA(200, 0, 180, 240))
        m = h.compute_metrics(SITE)
        expected_avg = (160*220 + 180*240) / 2
        self.assertAlmostEqual(m["avg_areas"]["BedroomA"], expected_avg)

    # edge cases
    def test_zero_site_area_does_not_raise(self):
        h = Hotel()
        m = h.compute_metrics((0, 0, 0, 0))
        self.assertEqual(m["density"], 0)

    def test_open_area_equals_site_minus_built(self):
        h = Hotel()
        h.add_room(BedroomA(0, 0, 160, 220))
        m = h.compute_metrics(SITE)
        self.assertEqual(m["open_area"], m["site_area"] - m["built_area"])

    def test_multiple_room_types_counted_separately(self):
        h = Hotel()
        h.add_room(BedroomA(0, 0, 160, 220))
        h.add_room(Library(300, 0, 360, 300))
        m = h.compute_metrics(SITE)
        self.assertIn("BedroomA", m["counts"])
        self.assertIn("Library", m["counts"])


class TestHotelSnapshotRestore(unittest.TestCase):

    def test_snapshot_is_independent_copy(self):
        h = Hotel()
        r = BedroomA(0, 0, 160, 220)
        h.add_room(r)
        snap = h.snapshot()
        h.clear()
        # original hotel is empty; snapshot still has the room
        self.assertEqual(len(snap), 1)
        self.assertEqual(len(h.rooms), 0)

    def test_restore_repopulates_hotel(self):
        h = Hotel()
        h.add_room(BedroomA(0, 0, 160, 220))
        snap = h.snapshot()
        h.clear()
        h.restore(snap)
        self.assertEqual(len(h.rooms), 1)

    def test_snapshot_preserves_room_data(self):
        h = Hotel()
        h.add_room(BedroomA(10, 20, 160, 220))
        snap = h.snapshot()
        self.assertEqual(snap[0].x, 10)
        self.assertEqual(snap[0].y, 20)
        self.assertEqual(snap[0].label, "BedroomA")

    # edge case: snapshot of empty hotel
    def test_empty_snapshot(self):
        snap = Hotel().snapshot()
        self.assertEqual(snap, [])


class TestHotelSerialisation(unittest.TestCase):

    def _make_hotel(self):
        h = Hotel()
        h.add_room(BedroomA(10, 20, 160, 220))
        h.add_room(Library(300, 50, 360, 300))
        return h

    def test_to_dict_structure(self):
        d = self._make_hotel().to_dict()
        self.assertIn("rooms", d)
        self.assertEqual(len(d["rooms"]), 2)
        self.assertEqual(d["rooms"][0]["label"], "BedroomA")

    def test_from_dict_reconstructs_rooms(self):
        original = self._make_hotel()
        restored = Hotel.from_dict(original.to_dict())
        self.assertEqual(len(restored.rooms), 2)
        self.assertEqual(restored.rooms[0].label, "BedroomA")
        self.assertEqual(restored.rooms[0].x, 10)

    def test_roundtrip_preserves_all_fields(self):
        original = self._make_hotel()
        restored = Hotel.from_dict(original.to_dict())
        for orig, rest in zip(original.rooms, restored.rooms):
            self.assertEqual(orig.as_tuple(), rest.as_tuple())
            self.assertEqual(orig.label, rest.label)

    # edge cases
    def test_from_dict_empty_rooms_list(self):
        h = Hotel.from_dict({"rooms": []})
        self.assertEqual(len(h.rooms), 0)

    def test_from_dict_unknown_label_skipped(self):
        data = {"rooms": [{"label": "UnknownRoom", "x": 0, "y": 0, "w": 100, "h": 100}]}
        h = Hotel.from_dict(data)
        self.assertEqual(len(h.rooms), 0)

    def test_to_dict_is_json_serialisable(self):
        d = self._make_hotel().to_dict()
        # should not raise
        json.dumps(d)

    def test_save_and_load_json(self):
        original = self._make_hotel()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            tmp_path = f.name
        try:
            original.save_json(tmp_path)
            loaded = Hotel.load_json(tmp_path)
            self.assertEqual(len(loaded.rooms), len(original.rooms))
        finally:
            os.unlink(tmp_path)


# ══════════════════════════════════════════════════════════════════════════════
# 3. packing
# ══════════════════════════════════════════════════════════════════════════════

PACK_SITE = (0, 0, 800, 600)


class TestPackRoomsIntoHotel(unittest.TestCase):

    def test_returns_hotel_instance(self):
        h = pack_rooms_into_hotel(PACK_SITE, 5, seed=1)
        self.assertIsInstance(h, Hotel)

    def test_seed_gives_reproducible_result(self):
        h1 = pack_rooms_into_hotel(PACK_SITE, 8, seed=42)
        h2 = pack_rooms_into_hotel(PACK_SITE, 8, seed=42)
        self.assertEqual(h1.as_tuples(), h2.as_tuples())

    def test_different_seeds_give_different_results(self):
        h1 = pack_rooms_into_hotel(PACK_SITE, 8, seed=1)
        h2 = pack_rooms_into_hotel(PACK_SITE, 8, seed=99)
        # With 8 rooms and a large site it would be astronomically unlikely
        # for both layouts to be identical.
        self.assertNotEqual(h1.as_tuples(), h2.as_tuples())

    def test_no_rooms_overlap(self):
        h = pack_rooms_into_hotel(PACK_SITE, 10, seed=7, pad=0)
        tuples = h.as_tuples()
        for i, r1 in enumerate(tuples):
            for j, r2 in enumerate(tuples):
                if i == j:
                    continue
                x1, y1, w1, h1_ = r1
                x2, y2, w2, h2_ = r2
                self.assertFalse(
                    rect_overlap(x1, y1, w1, h1_, x2, y2, w2, h2_),
                    msg=f"Rooms {i} and {j} overlap: {r1} vs {r2}"
                )

    def test_all_rooms_inside_site(self):
        sx, sy, sw, sh = PACK_SITE
        h = pack_rooms_into_hotel(PACK_SITE, 10, seed=3)
        for room in h.rooms:
            self.assertGreaterEqual(room.x, sx, msg=f"{room} left edge outside site")
            self.assertGreaterEqual(room.y, sy, msg=f"{room} top edge outside site")
            self.assertLessEqual(room.x + room.w, sx + sw, msg=f"{room} right edge outside site")
            self.assertLessEqual(room.y + room.h, sy + sh, msg=f"{room} bottom edge outside site")

    def test_constraint_0_allows_all_types(self):
        h = pack_rooms_into_hotel(PACK_SITE, 20, seed=0, constraint=0)
        labels = {r.label for r in h.rooms}
        # With 20 rooms and equal weights, we'd expect a mix; at least one bedroom
        # and one public room type with high probability. Run with seed for determinism.
        h2 = pack_rooms_into_hotel(PACK_SITE, 20, seed=5, constraint=0)
        all_labels = {r.label for r in h2.rooms}
        bedroom_labels  = {"BedroomA", "BedroomB", "BedroomC", "BedroomD"}
        public_labels   = {"TeaRoom1", "TeaRoom2", "Library", "ReadingRoom"}
        self.assertTrue(all_labels & bedroom_labels or all_labels & public_labels)

    def test_constraint_1_only_bedrooms(self):
        h = pack_rooms_into_hotel(PACK_SITE, 10, seed=10, constraint=1)
        bedroom_labels = {"BedroomA", "BedroomB", "BedroomC", "BedroomD"}
        for room in h.rooms:
            self.assertIn(room.label, bedroom_labels,
                          msg=f"Non-bedroom room found with constraint=1: {room.label}")

    def test_constraint_2_only_public(self):
        h = pack_rooms_into_hotel(PACK_SITE, 10, seed=11, constraint=2)
        public_labels = {"TeaRoom1", "TeaRoom2", "Library", "ReadingRoom"}
        for room in h.rooms:
            self.assertIn(room.label, public_labels,
                          msg=f"Non-public room found with constraint=2: {room.label}")

    # edge cases
    def test_n_rooms_zero(self):
        h = pack_rooms_into_hotel(PACK_SITE, 0, seed=1)
        self.assertEqual(len(h.rooms), 0)

    def test_very_small_site_places_no_rooms(self):
        # All room sizes are at least 125×125; a 50×50 site cannot fit any.
        tiny_site = (0, 0, 50, 50)
        h = pack_rooms_into_hotel(tiny_site, 10, seed=1)
        self.assertEqual(len(h.rooms), 0)

    def test_custom_weights_respected(self):
        # Force only BedroomA by giving all other types weight 0.
        weights = {k: 0.0 for k in DEFAULT_WEIGHTS}
        weights["BedroomA"] = 1.0
        h = pack_rooms_into_hotel(PACK_SITE, 10, seed=2, constraint=0, weights=weights)
        for room in h.rooms:
            self.assertEqual(room.label, "BedroomA")


# ══════════════════════════════════════════════════════════════════════════════
# 4. rooms
# ══════════════════════════════════════════════════════════════════════════════

ALL_ROOM_CLASSES = [
    BedroomA, BedroomB, BedroomC, BedroomD,
    TeaRoom1, TeaRoom2, Library, ReadingRoom,
]

EXPECTED_LABELS = {
    BedroomA:    "BedroomA",
    BedroomB:    "BedroomB",
    BedroomC:    "BedroomC",
    BedroomD:    "BedroomD",
    TeaRoom1:    "TeaRoom1",
    TeaRoom2:    "TeaRoom2",
    Library:     "Library",
    ReadingRoom: "ReadingRoom",
}


class TestRoomInstantiation(unittest.TestCase):

    def test_all_subclasses_instantiate(self):
        for cls in ALL_ROOM_CLASSES:
            with self.subTest(cls=cls.__name__):
                r = cls(0, 0, 100, 100)
                self.assertIsInstance(r, Room)

    def test_labels_are_correct(self):
        for cls, expected in EXPECTED_LABELS.items():
            with self.subTest(cls=cls.__name__):
                r = cls(0, 0, 100, 100)
                self.assertEqual(r.label, expected)

    def test_room_classes_map_has_all_types(self):
        self.assertEqual(set(ROOM_CLASSES.keys()), set(EXPECTED_LABELS.values()))

    # edge cases
    def test_zero_size_room_instantiates(self):
        r = BedroomA(0, 0, 0, 0)
        self.assertEqual(r.area, 0)

    def test_large_coordinates(self):
        r = Library(10_000, 10_000, 400, 360)
        self.assertEqual(r.x, 10_000)

    def test_negative_coordinates(self):
        r = BedroomC(-50, -50, 150, 150)
        self.assertEqual(r.x, -50)
        self.assertEqual(r.y, -50)


class TestRoomAsTuple(unittest.TestCase):

    def test_returns_four_element_tuple(self):
        r = BedroomA(10, 20, 160, 220)
        self.assertEqual(r.as_tuple(), (10, 20, 160, 220))

    def test_values_match_attributes(self):
        r = Library(5, 15, 360, 300)
        x, y, w, h = r.as_tuple()
        self.assertEqual(x, r.x)
        self.assertEqual(y, r.y)
        self.assertEqual(w, r.w)
        self.assertEqual(h, r.h)

    # edge case
    def test_zero_dimensions(self):
        r = ReadingRoom(0, 0, 0, 0)
        self.assertEqual(r.as_tuple(), (0, 0, 0, 0))


class TestRoomContains(unittest.TestCase):

    def setUp(self):
        self.room = BedroomA(100, 100, 160, 220)

    def test_point_inside(self):
        self.assertTrue(self.room.contains(150, 150))

    def test_point_outside(self):
        self.assertFalse(self.room.contains(0, 0))

    def test_top_left_corner(self):
        self.assertTrue(self.room.contains(100, 100))

    def test_bottom_right_corner(self):
        self.assertTrue(self.room.contains(260, 320))

    def test_just_outside_right(self):
        self.assertFalse(self.room.contains(261, 200))

    # edge cases
    def test_zero_size_room_only_contains_origin(self):
        r = BedroomA(50, 50, 0, 0)
        self.assertTrue(r.contains(50, 50))
        self.assertFalse(r.contains(51, 50))

    def test_negative_position_room(self):
        # room spans x: -100..50,  y: -100..50
        r = BedroomC(-100, -100, 150, 150)
        self.assertTrue(r.contains(-50, -50))   # clearly inside
        self.assertTrue(r.contains(0, 0))        # 0 <= 50 → still inside
        self.assertFalse(r.contains(60, 60))     # beyond right/bottom edge


class TestRoomMove(unittest.TestCase):

    def test_move_positive_delta(self):
        r = BedroomA(100, 100, 160, 220)
        r.move(50, 30)
        self.assertEqual(r.x, 150)
        self.assertEqual(r.y, 130)

    def test_move_negative_delta(self):
        r = BedroomA(100, 100, 160, 220)
        r.move(-50, -30)
        self.assertEqual(r.x, 50)
        self.assertEqual(r.y, 70)

    def test_move_zero_delta(self):
        r = BedroomA(100, 100, 160, 220)
        r.move(0, 0)
        self.assertEqual(r.x, 100)
        self.assertEqual(r.y, 100)

    def test_move_does_not_change_size(self):
        r = BedroomA(100, 100, 160, 220)
        r.move(99, 99)
        self.assertEqual(r.w, 160)
        self.assertEqual(r.h, 220)

    # edge cases
    def test_cumulative_moves(self):
        r = BedroomA(0, 0, 160, 220)
        r.move(10, 10)
        r.move(10, 10)
        self.assertEqual(r.x, 20)
        self.assertEqual(r.y, 20)

    def test_move_to_negative_coords(self):
        r = BedroomA(10, 10, 160, 220)
        r.move(-50, -50)
        self.assertEqual(r.x, -40)
        self.assertEqual(r.y, -40)

    def test_area_property(self):
        r = BedroomA(0, 0, 160, 220)
        self.assertEqual(r.area, 160 * 220)

    def test_centroid_properties(self):
        r = BedroomA(0, 0, 160, 220)
        self.assertAlmostEqual(r.cx, 80.0)
        self.assertAlmostEqual(r.cy, 110.0)


# ══════════════════════════════════════════════════════════════════════════════
# 5. llm_bridge
# ══════════════════════════════════════════════════════════════════════════════

import llm_bridge as _bridge


class TestFindApiKey(unittest.TestCase):
    """Tests for llm_bridge._find_api_key."""

    def test_returns_empty_when_no_sources(self):
        """No env var, no .env file, no secrets.py → empty string."""
        env_backup = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            with patch("llm_bridge.os.path.isfile", return_value=False):
                result = _bridge._find_api_key()
            self.assertEqual(result, "")
        finally:
            if env_backup is not None:
                os.environ["ANTHROPIC_API_KEY"] = env_backup

    def test_returns_env_var_when_set(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test-key"}):
            # Make sure no file read is needed
            with patch("llm_bridge.os.path.isfile", return_value=False):
                result = _bridge._find_api_key()
        self.assertEqual(result, "sk-ant-test-key")

    def test_reads_key_from_dot_env_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False
        ) as f:
            f.write("ANTHROPIC_API_KEY=sk-ant-from-dotenv\n")
            tmp_path = f.name

        env_backup = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            # Patch isfile to return True only for .env, and open to use our file
            def fake_isfile(path):
                return path == tmp_path or path.endswith(".env")

            with patch("llm_bridge.os.environ.get", return_value=""), \
                 patch("llm_bridge.os.path.isfile", side_effect=fake_isfile), \
                 patch("llm_bridge.os.path.join", side_effect=lambda *args: tmp_path
                       if args[-1] == ".env" else "/nonexistent/secrets.py"):
                result = _bridge._find_api_key()
            self.assertEqual(result, "sk-ant-from-dotenv")
        finally:
            if env_backup is not None:
                os.environ["ANTHROPIC_API_KEY"] = env_backup
            os.unlink(tmp_path)

    # edge cases
    def test_strips_whitespace_from_env_var(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "  sk-ant-padded  "}):
            with patch("llm_bridge.os.path.isfile", return_value=False):
                result = _bridge._find_api_key()
        self.assertEqual(result, "sk-ant-padded")

    def test_empty_env_var_falls_through_to_files(self):
        """An empty env var should not short-circuit; files are consulted."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            with patch("llm_bridge.os.path.isfile", return_value=False):
                result = _bridge._find_api_key()
        self.assertEqual(result, "")

    def test_returns_empty_when_env_key_is_blank_and_no_files(self):
        env_backup = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            with patch("llm_bridge.os.path.isfile", return_value=False):
                key = _bridge._find_api_key()
            self.assertEqual(key, "")
        finally:
            if env_backup is not None:
                os.environ["ANTHROPIC_API_KEY"] = env_backup


class TestPromptToSettings(unittest.TestCase):
    """Tests for llm_bridge.prompt_to_settings."""

    def _mock_api_response(self, json_text: str):
        """Return a mock anthropic client whose messages.create returns json_text."""
        mock_content = MagicMock()
        mock_content.text = json_text
        mock_message = MagicMock()
        mock_message.content = [mock_content]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        return mock_client

    def test_raises_runtime_error_when_no_api_key(self):
        with patch.object(_bridge, "_find_api_key", return_value=""):
            with self.assertRaises(RuntimeError):
                _bridge.prompt_to_settings("mostly bedrooms")

    def test_falls_back_to_default_weights_on_bad_json(self):
        """When the API returns non-JSON, prompt_to_settings returns DEFAULT_WEIGHTS."""
        mock_client = self._mock_api_response("this is not json at all")
        with patch.object(_bridge, "_find_api_key", return_value="sk-ant-fake"), \
             patch("anthropic.Anthropic", return_value=mock_client):
            result = _bridge.prompt_to_settings("anything")
        self.assertEqual(result["weights"], DEFAULT_WEIGHTS)

    def test_parses_valid_weights_response(self):
        weights_json = json.dumps({"weights": {
            "BedroomA": 3, "BedroomB": 2, "BedroomC": 1, "BedroomD": 1,
            "TeaRoom1": 0, "TeaRoom2": 0, "Library": 0, "ReadingRoom": 0,
        }})
        mock_client = self._mock_api_response(weights_json)
        with patch.object(_bridge, "_find_api_key", return_value="sk-ant-fake"), \
             patch("anthropic.Anthropic", return_value=mock_client):
            result = _bridge.prompt_to_settings("mostly bedrooms")
        self.assertEqual(result["weights"]["BedroomA"], 3.0)
        self.assertEqual(result["weights"]["Library"], 0.0)

    def test_weight_values_are_non_negative(self):
        """Negative values in the API response should be clamped to 0."""
        weights_json = json.dumps({"weights": {
            "BedroomA": -5, "BedroomB": 1, "BedroomC": 1, "BedroomD": 1,
            "TeaRoom1": 1, "TeaRoom2": 1, "Library": 1, "ReadingRoom": 1,
        }})
        mock_client = self._mock_api_response(weights_json)
        with patch.object(_bridge, "_find_api_key", return_value="sk-ant-fake"), \
             patch("anthropic.Anthropic", return_value=mock_client):
            result = _bridge.prompt_to_settings("test")
        self.assertGreaterEqual(result["weights"]["BedroomA"], 0.0)

    def test_all_default_weight_keys_present_in_output(self):
        """Output weights must have every key that DEFAULT_WEIGHTS has."""
        # Partial response: only some keys supplied by the API
        weights_json = json.dumps({"weights": {"BedroomA": 2}})
        mock_client = self._mock_api_response(weights_json)
        with patch.object(_bridge, "_find_api_key", return_value="sk-ant-fake"), \
             patch("anthropic.Anthropic", return_value=mock_client):
            result = _bridge.prompt_to_settings("test")
        for key in DEFAULT_WEIGHTS:
            self.assertIn(key, result["weights"])

    def test_optional_n_rooms_clamped(self):
        data = json.dumps({"weights": DEFAULT_WEIGHTS, "n_rooms": 100})
        mock_client = self._mock_api_response(data)
        with patch.object(_bridge, "_find_api_key", return_value="sk-ant-fake"), \
             patch("anthropic.Anthropic", return_value=mock_client):
            result = _bridge.prompt_to_settings("test")
        self.assertLessEqual(result["n_rooms"], 24)

    def test_optional_pad_clamped(self):
        data = json.dumps({"weights": DEFAULT_WEIGHTS, "pad": 999})
        mock_client = self._mock_api_response(data)
        with patch.object(_bridge, "_find_api_key", return_value="sk-ant-fake"), \
             patch("anthropic.Anthropic", return_value=mock_client):
            result = _bridge.prompt_to_settings("test")
        self.assertLessEqual(result["pad"], 80)

    # edge cases
    def test_empty_prompt_still_returns_weights(self):
        weights_json = json.dumps({"weights": DEFAULT_WEIGHTS})
        mock_client = self._mock_api_response(weights_json)
        with patch.object(_bridge, "_find_api_key", return_value="sk-ant-fake"), \
             patch("anthropic.Anthropic", return_value=mock_client):
            result = _bridge.prompt_to_settings("")
        self.assertIn("weights", result)

    def test_invalid_spatial_value_excluded(self):
        data = json.dumps({"weights": DEFAULT_WEIGHTS, "spatial": "not_a_valid_value"})
        mock_client = self._mock_api_response(data)
        with patch.object(_bridge, "_find_api_key", return_value="sk-ant-fake"), \
             patch("anthropic.Anthropic", return_value=mock_client):
            result = _bridge.prompt_to_settings("test")
        self.assertNotIn("spatial", result)

    def test_valid_spatial_value_included(self):
        data = json.dumps({"weights": DEFAULT_WEIGHTS, "spatial": "bedrooms_top"})
        mock_client = self._mock_api_response(data)
        with patch.object(_bridge, "_find_api_key", return_value="sk-ant-fake"), \
             patch("anthropic.Anthropic", return_value=mock_client):
            result = _bridge.prompt_to_settings("test")
        self.assertEqual(result.get("spatial"), "bedrooms_top")


# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
