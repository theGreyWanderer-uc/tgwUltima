"""Tests for titan.u9.npc's runtime/NPC.FLX decoder.

Fixtures match the layout verified against the real 111,232-byte payload:
352 records of exactly 316 bytes, with the Ultima Codex's field offsets but
not its record size. See the module docstring for the stride evidence.

The properties pinned down here are the ones that were easy to get wrong --
the 316-byte stride, an empty name field being a legal blank slot rather
than the end of the array, and a savegame's array being *longer* than the
shipped one because the engine appends runtime-spawned creatures.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.npc import NO_CLASS, RECORD_SIZE, U9Npc, U9NpcError, U9Npcs

CODEX_RECORD_SIZE = 323


def _record(
    name: str = "",
    *,
    unknown_id: int = 0,
    gender: int = 0,
    health: tuple[int, int] = (0, 0),
    mana: tuple[int, int] = (0, 0),
    class_id: int = NO_CLASS,
    combat_value: int = 0,
    region: int = 0,
    pos: tuple[int, int, int] = (0, 0, 0),
    scale: tuple[int, int, int] = (100, 100, 100),
) -> bytes:
    r = bytearray(RECORD_SIZE)
    struct.pack_into("<I", r, 0x00, unknown_id)
    encoded = name.encode("ascii")[:31]
    r[0x04 : 0x04 + len(encoded)] = encoded
    r[0x24] = gender
    struct.pack_into("<3H", r, 0x34, health[0], health[1], health[1])
    struct.pack_into("<3H", r, 0x3A, mana[0], mana[1], mana[1])
    struct.pack_into("<H", r, 0x44, class_id)
    struct.pack_into("<H", r, 0x54, combat_value)
    struct.pack_into("<I", r, 0x58, region)
    struct.pack_into("<II", r, 0x5C, pos[0], pos[1])
    struct.pack_into("<H", r, 0x64, pos[2])
    r[0x6C], r[0x6D], r[0x6E] = scale
    return bytes(r)


class NpcRecordTests(unittest.TestCase):
    def test_record_size_is_316_not_the_codex_323(self) -> None:
        # 111,232 is the real payload; only 316 divides it without remainder.
        self.assertEqual(RECORD_SIZE, 316)
        self.assertEqual(111232 % RECORD_SIZE, 0)
        self.assertEqual(111232 // RECORD_SIZE, 352)
        self.assertNotEqual(111232 % CODEX_RECORD_SIZE, 0)

    def test_decodes_every_documented_field(self) -> None:
        block = _record(
            "Dermot", unknown_id=1024, gender=0, health=(200, 255), mana=(1, 2),
            class_id=34, combat_value=400, region=9, pos=(60544, 58819, 2631),
            scale=(80, 80, 80),
        )
        n = U9Npcs(block).npc(0)
        self.assertEqual(n.name, "Dermot")
        self.assertEqual(n.unknown_id, 1024)
        self.assertFalse(n.is_female)
        self.assertEqual((n.health_current, n.health_max), (200, 255))
        self.assertEqual((n.mana_current, n.mana_max), (1, 2))
        self.assertEqual(n.health_max, n.health_max2)
        self.assertEqual(n.mana_max, n.mana_max2)
        self.assertEqual(n.class_id, 34)
        self.assertTrue(n.has_class)
        self.assertEqual(n.combat_value, 400)
        self.assertEqual(n.region, 9)
        self.assertEqual(n.position, (60544, 58819, 2631))
        self.assertEqual(n.scale, (80, 80, 80))

    def test_gender_flag(self) -> None:
        self.assertTrue(U9Npcs(_record("Mariah", gender=1)).npc(0).is_female)
        self.assertFalse(U9Npcs(_record("Shamino", gender=0)).npc(0).is_female)

    def test_class_sentinel_means_no_class(self) -> None:
        n = U9Npcs(_record("Geoffrey", class_id=NO_CLASS)).npc(0)
        self.assertEqual(n.class_id, NO_CLASS)
        self.assertFalse(n.has_class)

    def test_raw_bytes_are_kept_for_undecoded_fields(self) -> None:
        n = U9Npcs(_record("Avatar")).npc(0)
        self.assertEqual(len(n.raw), RECORD_SIZE)


class NpcArrayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.block = (
            _record("Avatar", region=9, class_id=0)
            + _record("LordBritish", region=9, class_id=39)
            + _record("Valkadesh", region=40, class_id=10)
            + _record("")  # a blank slot, as the shipped file contains
        )
        self.npcs = U9Npcs(self.block)

    def test_indexes_are_positional(self) -> None:
        self.assertEqual(len(self.npcs), 4)
        self.assertEqual([n.index for n in self.npcs], [0, 1, 2, 3])
        self.assertEqual(self.npcs.npc(1).name, "LordBritish")

    def test_blank_slot_is_kept_not_dropped(self) -> None:
        # Index is identity -- dropping a blank slot would shift every later NPC.
        self.assertEqual(self.npcs.npc(3).name, "")

    def test_by_name(self) -> None:
        self.assertEqual(self.npcs.by_name("Valkadesh").index, 2)
        self.assertIsNone(self.npcs.by_name("Nobody"))

    def test_in_region_and_by_class(self) -> None:
        self.assertEqual([n.name for n in self.npcs.in_region(9)], ["Avatar", "LordBritish"])
        self.assertEqual([n.name for n in self.npcs.by_class(10)], ["Valkadesh"])

    def test_class_histogram(self) -> None:
        histogram = self.npcs.class_histogram()
        self.assertEqual(histogram[0], 1)
        self.assertEqual(histogram[39], 1)
        self.assertEqual(sum(histogram.values()), 4)

    def test_out_of_range_index_raises(self) -> None:
        with self.assertRaises(U9NpcError):
            self.npcs.npc(99)
        with self.assertRaises(U9NpcError):
            self.npcs.npc(-1)


class NpcValidationTests(unittest.TestCase):
    def test_rejects_a_partial_record(self) -> None:
        with self.assertRaises(U9NpcError):
            U9Npcs(_record("Avatar")[:-4])

    def test_rejects_data_smaller_than_one_record(self) -> None:
        with self.assertRaises(U9NpcError):
            U9Npcs(b"\x00" * 8)

    def test_rejects_a_non_multiple_of_the_stride(self) -> None:
        ragged = _record("Avatar") + b"\x00" * 7
        with self.assertRaises(U9NpcError):
            U9Npcs(ragged)


class NpcBlockSearchTests(unittest.TestCase):
    """A savegame embeds the array at an offset that is not fixed."""

    def _block(self, count: int) -> bytes:
        return b"".join(
            _record(f"NPC{i}", region=9, pos=(1000 + i, 2000 + i, 30)) for i in range(count)
        )

    def test_finds_an_embedded_block(self) -> None:
        data = b"\xAA" * 777 + self._block(20) + b"\xBB" * 300
        offset, count = U9Npcs.find_block(data)
        self.assertEqual(offset, 777)
        self.assertEqual(count, 20)

    def test_a_blank_slot_does_not_split_the_block(self) -> None:
        data = self._block(10) + _record("") + self._block(10)
        offset, count = U9Npcs.find_block(data)
        self.assertEqual(offset, 0)
        self.assertEqual(count, 21)

    def test_zero_padding_does_not_outrank_the_real_block(self) -> None:
        # All-NUL name fields satisfy the NUL-terminated test trivially, so
        # runs are scored by how many records carry an actual name.
        data = b"\x00" * (RECORD_SIZE * 60) + self._block(20)
        offset, count = U9Npcs.find_block(data)
        self.assertEqual(offset, RECORD_SIZE * 60)
        self.assertEqual(count, 20)

    def test_recovers_a_first_record_the_forward_scan_skipped(self) -> None:
        # A forward scan can latch onto the array one record late. Real
        # savegames do this, and the result is every NPC shifted by one
        # index -- which reads as hundreds of spurious field changes.
        block = self._block(20)
        data = b"\xAA" * 300 + block
        offset, count = U9Npcs.find_block(data)
        self.assertEqual(offset, 300)
        self.assertEqual(count, 20)
        self.assertEqual(U9Npcs(data[offset : offset + count * RECORD_SIZE]).npc(0).name, "NPC0")

    def test_backward_walk_does_not_cross_blank_padding(self) -> None:
        # Blank records are legal inside the array, but a run of them is also
        # what unrelated zero padding looks like; walking back into it would
        # drag the start far below the real array.
        data = b"\x00" * (RECORD_SIZE * 40) + self._block(20)
        offset, count = U9Npcs.find_block(data)
        self.assertEqual(offset, RECORD_SIZE * 40)
        self.assertEqual(count, 20)

    def test_returns_none_when_no_block_is_present(self) -> None:
        self.assertEqual(U9Npcs.find_block(b"\xAA" * 5000), (None, 0))

    def test_short_run_is_not_a_block(self) -> None:
        self.assertEqual(U9Npcs.find_block(b"\xAA" * 400 + self._block(4)), (None, 0))


class NpcDiffTests(unittest.TestCase):
    def test_changed_fields_reports_offsets_and_counts(self) -> None:
        a = U9Npcs(_record("Dermot", region=9, pos=(100, 200, 30)))
        b = U9Npcs(_record("Dermot", region=9, pos=(101, 200, 30)))
        changed = a.changed_fields(b)
        self.assertEqual(changed, {0x5C: 1})

    def test_identical_copies_report_nothing(self) -> None:
        a = U9Npcs(_record("Dermot", region=9))
        self.assertEqual(a.changed_fields(U9Npcs(_record("Dermot", region=9))), {})

    def test_only_the_shared_prefix_is_compared(self) -> None:
        # A savegame's array is longer: the engine appends spawned creatures
        # after the authored NPCs, and those have no static counterpart.
        authored = U9Npcs(_record("Dermot", region=9))
        live = U9Npcs(_record("Dermot", region=9) + _record("Butterfly 4", region=14))
        self.assertEqual(len(live), 2)
        self.assertEqual(authored.changed_fields(live), {})


if __name__ == "__main__":
    unittest.main()
