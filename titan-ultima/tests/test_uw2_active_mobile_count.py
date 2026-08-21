"""Locks in the ``0x7c00`` active-mobile-count interpretation in parse_free_lists.

UnderworldAdventures names ``0x7c00`` "number of active mobile objects", while
UWXtract instead loops ``active_items + 1`` bytes from the active-mobile list at
``0x7afc`` (see ``reference/uw2/UU2_mapping_data_structure_report.md``, "Active
Mobile Count Needs Verification"). ``level.parse_free_lists`` treats ``0x7c00``
as an exact count with no ``+1``.

The empirical check that settled it: across every populated level,
``raw_active[:active_count]`` is a clean run of non-free mobile object slots
with no exceptions, while the byte immediately past that boundary is
uncorrelated noise -- a stale free-list slot about as often as not -- which is
the signature of an exact count rather than a count-minus-one. That sweep needs
the real archive and lives in ``UW2RealActiveMobileTests``, skipped unless
``TITAN_UW2_GAMEDIR`` is set. The synthetic tests below pin the resulting
decode rules so the default suite needs no game files.
"""

from __future__ import annotations

import os
import struct
import unittest
from pathlib import Path

from titan.uw2.level import (
    ACTIVE_MOBILE_OFFSET,
    COUNTERS_OFFSET,
    LEVEL_BLOCK_MIN_SIZE,
    MOBILE_FREE_OFFSET,
    STATIC_FREE_OFFSET,
    parse_free_lists,
)

ACTIVE_LIST_SIZE = 0xFE


def _synthetic_level_block(
    *,
    active_slots: bytes,
    active_count: int,
    trailing_byte: int = 0xAB,
    mobile_free: tuple[int, ...] = (7, 8, 9),
    static_free: tuple[int, ...] = (600, 601),
    magic_marker: int = 0x7577,
) -> bytes:
    """A level block whose free-list regions alone are populated."""
    block = bytearray(LEVEL_BLOCK_MIN_SIZE)

    block[ACTIVE_MOBILE_OFFSET : ACTIVE_MOBILE_OFFSET + len(active_slots)] = (
        active_slots
    )
    # Stale data past the count, as the game leaves in the fixed 0xFE buffer.
    if len(active_slots) < ACTIVE_LIST_SIZE:
        block[ACTIVE_MOBILE_OFFSET + len(active_slots)] = trailing_byte

    for index, value in enumerate(mobile_free):
        struct.pack_into("<H", block, MOBILE_FREE_OFFSET + index * 2, value)
    for index, value in enumerate(static_free):
        struct.pack_into("<H", block, STATIC_FREE_OFFSET + index * 2, value)

    struct.pack_into("<H", block, COUNTERS_OFFSET, active_count)
    struct.pack_into("<H", block, COUNTERS_OFFSET + 2, len(mobile_free) - 1)
    struct.pack_into("<H", block, COUNTERS_OFFSET + 4, len(static_free) - 1)
    struct.pack_into("<H", block, COUNTERS_OFFSET + 6, magic_marker)
    return bytes(block)


class UW2ActiveMobileCountTests(unittest.TestCase):
    def test_active_count_is_exact_and_excludes_the_following_byte(self) -> None:
        block = _synthetic_level_block(
            active_slots=bytes((3, 5, 11)), active_count=3, trailing_byte=0x7F
        )

        free_lists = parse_free_lists(block)

        self.assertEqual(free_lists["active_mobile_count"], 3)
        # Exactly active_count entries -- a "+1" reading would append 0x7f.
        self.assertEqual(free_lists["active_mobile_slots"], [3, 5, 11])
        self.assertNotIn(0x7F, free_lists["active_mobile_slots"])

    def test_raw_active_list_preserves_the_full_buffer(self) -> None:
        # The whole 0xFE-byte buffer is retained so the boundary byte stays
        # inspectable without re-reading the archive.
        block = _synthetic_level_block(
            active_slots=bytes((3, 5, 11)), active_count=3, trailing_byte=0x7F
        )

        raw = bytes.fromhex(parse_free_lists(block)["raw_active_mobile_list_hex"])

        self.assertEqual(len(raw), ACTIVE_LIST_SIZE)
        self.assertEqual(raw[:3], bytes((3, 5, 11)))
        self.assertEqual(raw[3], 0x7F)

    def test_active_count_is_clamped_to_the_buffer(self) -> None:
        block = _synthetic_level_block(
            active_slots=bytes(range(1, 5)), active_count=0xFFFF
        )

        free_lists = parse_free_lists(block)

        self.assertEqual(free_lists["active_mobile_count"], 0xFFFF)
        self.assertEqual(len(free_lists["active_mobile_slots"]), ACTIVE_LIST_SIZE)

    def test_free_list_counts_are_stored_minus_one(self) -> None:
        block = _synthetic_level_block(
            active_slots=bytes((1,)),
            active_count=1,
            mobile_free=(7, 8, 9),
            static_free=(600, 601),
        )

        free_lists = parse_free_lists(block)

        self.assertEqual(free_lists["mobile_free_count_minus_one"], 2)
        self.assertEqual(free_lists["free_mobile_slots"], [7, 8, 9])
        self.assertEqual(free_lists["static_free_count_minus_one"], 1)
        self.assertEqual(free_lists["free_static_slots"], [600, 601])
        self.assertEqual(free_lists["magic_marker_hex"], "0x7577")


def _game_directory() -> Path | None:
    value = os.environ.get("TITAN_UW2_GAMEDIR")
    if not value:
        return None
    path = Path(value).expanduser()
    data = path if path.name.upper() == "DATA" else path / "DATA"
    return path if (data / "LEV.ARK").is_file() else None


@unittest.skipIf(
    _game_directory() is None,
    "set TITAN_UW2_GAMEDIR to a UU2 install to re-run the whole-archive sweep",
)
class UW2RealActiveMobileTests(unittest.TestCase):
    """Opt-in sweep of every populated level, as originally argued."""

    @classmethod
    def setUpClass(cls) -> None:
        from titan.uw2.map_pipeline import MAP_SLOT_COUNT, load_levels

        cls.levels = load_levels(_game_directory(), range(MAP_SLOT_COUNT))

    @staticmethod
    def _classify(slot_id: int, objects_by_slot: dict, free_mobile: set) -> str:
        if slot_id == 0:
            return "zero"
        obj = objects_by_slot.get(slot_id)
        if obj is None:
            return "out-of-range"
        if slot_id in free_mobile:
            return "free"
        if not obj["is_mobile"]:
            return "not-mobile"
        return "plausible-active-mobile"

    def _level_parts(self, level: dict) -> tuple[int, bytes, dict, set]:
        free_lists = level["free_lists"]
        return (
            free_lists["active_mobile_count"],
            bytes.fromhex(free_lists["raw_active_mobile_list_hex"]),
            {obj["slot"]: obj for obj in level["objects"]},
            set(free_lists["free_mobile_slots"]),
        )

    def test_active_count_prefix_is_always_internally_consistent(self) -> None:
        bad = []
        for level in self.levels:
            count, raw, objects_by_slot, free_mobile = self._level_parts(level)
            for index in range(count):
                kind = self._classify(raw[index], objects_by_slot, free_mobile)
                if kind != "plausible-active-mobile":
                    bad.append((level["slot_index"], index, raw[index], kind))

        self.assertEqual(
            bad,
            [],
            "active_mobile_count-prefix entries that are not plausible active "
            f"mobile objects, suggesting active_count over-counts: {bad}",
        )

    def test_byte_immediately_past_active_count_is_not_reliably_valid(self) -> None:
        kinds = []
        for level in self.levels:
            count, raw, objects_by_slot, free_mobile = self._level_parts(level)
            if count >= len(raw):
                continue
            kinds.append(self._classify(raw[count], objects_by_slot, free_mobile))

        self.assertGreater(
            kinds.count("free"),
            0,
            "expected levels where the byte past active_count is a stale "
            "free-list slot; if this fails, re-check whether active_count "
            "should include one more entry",
        )


if __name__ == "__main__":
    unittest.main()
