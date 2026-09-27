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

from titan.u9.npc import (
    LIVE_RECORD_COUNT,
    NO_COMBAT_BEHAVIOR,
    RECORD_SIZE,
    U9NpcError,
    U9NpcState,
    U9NpcTrait,
    U9Npcs,
)

CODEX_RECORD_SIZE = 323


def _record(
    name: str = "",
    *,
    pool_handle: int = 0,
    gender: int = 0,
    magic_tier: int = 0,
    armor: tuple[int, int] = (0, 0),
    core_codes: tuple[int, int, int] = (0, 0, 0),
    health: tuple[int, int, int] = (0, 0, 0),
    mana: tuple[int, int, int] = (0, 0, 0),
    early_reserved: tuple[int, bytes] = (0, b"\x00" * 3),
    combat_behavior_id: int = NO_COMBAT_BEHAVIOR,
    state_flags: int = 0,
    routines: tuple[int, int, int] = (0, 0, 0),
    awareness: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0),
    region: int = 0,
    pos: tuple[int, int, int] = (0, 0, 0),
    position_tail: bytes = b"\x00" * 2,
    routine_cursor: tuple[int, int, int] = (0, 0, 0),
    scale: tuple[int, int, int] = (100, 100, 100),
    scale_reserved: int = 0,
    equipped: tuple[int, ...] = (0, 0, 0, 0, 0, 0, 0),
    attachments: tuple[int, ...] = (0, 0, 0, 0, 0, 0, 0),
    active_weapon_category_id: int = 0,
    invulnerability_duration: int = 0,
    movement_behavior_id: int = -1,
    breath: tuple[int, int, int] = (0, 0, 0),
    breath_reserved: bytes = b"\x00" * 10,
    trait_flags: int = 0,
    impact_material_id: int = 0,
    impact_reserved: bytes = b"\x00" * 20,
    proximity_reserved: int = 0,
    proximity: tuple[int, int] = (0, 0),
    routine_timing: tuple[int, int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0, 0),
    timing_reserved: bytes = b"\x00" * 20,
    routine_stack: bytes = b"\x00" * 8,
    spellbook_flags: bytes = b"\x00" * 12,
    combat_skills: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0),
    trailing_reserved: bytes = b"\x00" * 4,
) -> bytes:
    r = bytearray(RECORD_SIZE)
    struct.pack_into("<I", r, 0x00, pool_handle)
    encoded = name.encode("ascii")[:31]
    r[0x04 : 0x04 + len(encoded)] = encoded
    r[0x24] = gender
    r[0x25] = magic_tier
    r[0x26], r[0x27] = armor
    struct.pack_into("<3i", r, 0x28, *core_codes)
    struct.pack_into("<3H", r, 0x34, *health)
    struct.pack_into("<3H", r, 0x3A, *mana)
    r[0x40] = early_reserved[0]
    r[0x41:0x44] = early_reserved[1]
    struct.pack_into("<i", r, 0x44, combat_behavior_id)
    struct.pack_into("<I", r, 0x48, state_flags)
    struct.pack_into("<3H", r, 0x4C, *routines)
    struct.pack_into("<BBHBB", r, 0x52, *awareness)
    struct.pack_into("<i", r, 0x58, region)
    struct.pack_into("<iih", r, 0x5C, *pos)
    r[0x66:0x68] = position_tail
    struct.pack_into("<BBH", r, 0x68, *routine_cursor)
    r[0x6C], r[0x6D], r[0x6E] = scale
    r[0x6F] = scale_reserved
    struct.pack_into("<7I", r, 0x70, *equipped)
    struct.pack_into("<7i", r, 0x8C, *attachments)
    struct.pack_into("<i", r, 0xA8, active_weapon_category_id)
    struct.pack_into("<I", r, 0xAC, invulnerability_duration)
    struct.pack_into("<i", r, 0xB0, movement_behavior_id)
    struct.pack_into("<3H", r, 0xB4, *breath)
    r[0xBA:0xC4] = breath_reserved
    struct.pack_into("<I", r, 0xC4, trait_flags)
    struct.pack_into("<i", r, 0xC8, impact_material_id)
    r[0xCC:0xE0] = impact_reserved
    struct.pack_into("<H", r, 0xE0, proximity_reserved)
    struct.pack_into("<2H", r, 0xE2, *proximity)
    struct.pack_into("<HiHHiIi", r, 0xE6, *routine_timing)
    r[0xFC:0x110] = timing_reserved
    r[0x110:0x118] = routine_stack
    r[0x118:0x124] = spellbook_flags
    struct.pack_into("<5i", r, 0x124, *combat_skills)
    r[0x138:0x13C] = trailing_reserved
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
            "Dermot",
            pool_handle=1024,
            gender=0,
            magic_tier=3,
            armor=(40, 5),
            core_codes=(1, 2, 3),
            health=(200, 255, 250),
            mana=(1, 12, 10),
            early_reserved=(10, b"XYZ"),
            combat_behavior_id=34,
            state_flags=U9NpcState.CLONED_ARCHETYPE | U9NpcState.PRIMARY_HOSTILE_MODE,
            routines=(7, 8, 9),
            awareness=(4, 2, 400, 90, 25),
            region=9,
            pos=(60544, 58819, -12),
            position_tail=b"PQ",
            routine_cursor=(2, 6, 11),
            scale=(80, 80, 80),
            scale_reserved=7,
            equipped=(1, 2, 3, 4, 5, 6, 7),
            attachments=(-1, -2, -3, -4, -5, -6, -7),
            active_weapon_category_id=12,
            invulnerability_duration=500,
            movement_behavior_id=8,
            breath=(20, 30, 25),
            breath_reserved=b"0123456789",
            trait_flags=U9NpcTrait.BOSS | U9NpcTrait.HUMANOID_BODY,
            impact_material_id=3,
            impact_reserved=b"abcdefghijklmnopqrst",
            proximity_reserved=13,
            proximity=(300, 400),
            routine_timing=(23, -2, 100, 80, -1, 9, 44),
            timing_reserved=b"ABCDEFGHIJKLMNOPQRST",
            routine_stack=b"ABCDEFGH",
            spellbook_flags=bytes(range(12)),
            combat_skills=(0, 1, 2, 3, -1),
            trailing_reserved=b"TAIL",
        )
        n = U9Npcs(block).npc(0)
        self.assertEqual(n.name, "Dermot")
        self.assertEqual(n.pool_handle, 1024)
        self.assertFalse(n.is_female)
        self.assertEqual((n.magic_tier, n.armor_rating, n.armor_modifier), (3, 40, 5))
        self.assertEqual((n.might_code, n.agility_code, n.intellect_code), (1, 2, 3))
        self.assertEqual(
            (n.health_current, n.health_bonus_maximum, n.health_base_maximum),
            (200, 255, 250),
        )
        self.assertEqual(
            (n.mana_current, n.mana_bonus_maximum, n.mana_base_maximum),
            (1, 12, 10),
        )
        self.assertEqual((n.reserved_0x40, n.residual_0x41_0x43), (10, b"XYZ"))
        self.assertEqual(n.combat_behavior_id, 34)
        self.assertEqual(
            n.state_flags,
            U9NpcState.CLONED_ARCHETYPE | U9NpcState.PRIMARY_HOSTILE_MODE,
        )
        self.assertTrue(n.has_combat_behavior)
        self.assertEqual(
            (n.active_routine_id, n.fallback_routine_id, n.fallback_routine_argument),
            (7, 8, 9),
        )
        self.assertEqual(
            (
                n.magic_resistance_modifier,
                n.route_search_workers,
                n.awareness_radius,
                n.awareness_arc_degrees,
                n.guaranteed_awareness_percent,
            ),
            (4, 2, 400, 90, 25),
        )
        self.assertEqual(n.region, 9)
        self.assertEqual(n.position, (60544, 58819, -12))
        self.assertEqual(n.position_tail, b"PQ")
        self.assertEqual(
            (n.routine_stack_depth, n.routine_step_index, n.active_routine_argument),
            (2, 6, 11),
        )
        self.assertEqual(n.scale, (80, 80, 80))
        self.assertEqual(n.reserved_0x6f, 7)
        self.assertEqual(n.equipped_object_offsets, (1, 2, 3, 4, 5, 6, 7))
        self.assertEqual(n.model_attachment_ids, (-1, -2, -3, -4, -5, -6, -7))
        self.assertEqual(n.active_weapon_category_id, 12)
        self.assertEqual(n.invulnerability_duration, 500)
        self.assertEqual(n.movement_behavior_id, 8)
        self.assertEqual(
            (n.breath_current, n.breath_bonus_maximum, n.breath_base_maximum),
            (20, 30, 25),
        )
        self.assertEqual(n.reserved_0xba_0xc3, b"0123456789")
        self.assertEqual(n.trait_flags, U9NpcTrait.BOSS | U9NpcTrait.HUMANOID_BODY)
        self.assertEqual(n.impact_material_id, 3)
        self.assertEqual(n.reserved_0xcc_0xdf, b"abcdefghijklmnopqrst")
        self.assertEqual(n.reserved_0xe0, 13)
        self.assertEqual(
            (n.proximity_enter_radius, n.proximity_exit_radius), (300, 400)
        )
        self.assertEqual(
            (
                n.queued_routine_argument,
                n.route_search_counter,
                n.routine_end_time,
                n.routine_start_time,
                n.primary_routine_duration,
                n.queued_routine_id,
                n.secondary_routine_duration,
            ),
            (23, -2, 100, 80, -1, 9, 44),
        )
        self.assertEqual(n.reserved_0xfc_0x10f, b"ABCDEFGHIJKLMNOPQRST")
        self.assertEqual(n.routine_stack, b"ABCDEFGH")
        self.assertEqual(n.spellbook_flags, bytes(range(12)))
        self.assertEqual(
            (
                n.unarmed_skill_code,
                n.one_handed_skill_code,
                n.two_handed_skill_code,
                n.blunt_skill_code,
                n.ranged_skill_code,
            ),
            (0, 1, 2, 3, -1),
        )
        self.assertEqual(n.reserved_0x138_0x13b, b"TAIL")

    def test_gender_flag(self) -> None:
        self.assertTrue(U9Npcs(_record("Mariah", gender=1)).npc(0).is_female)
        self.assertFalse(U9Npcs(_record("Shamino", gender=0)).npc(0).is_female)

    def test_behavior_sentinel_means_no_combat_behavior(self) -> None:
        n = U9Npcs(_record("Geoffrey", combat_behavior_id=NO_COMBAT_BEHAVIOR)).npc(0)
        self.assertEqual(n.combat_behavior_id, NO_COMBAT_BEHAVIOR)
        self.assertFalse(n.has_combat_behavior)

    def test_complete_raw_record_is_retained(self) -> None:
        source = _record("Avatar")
        n = U9Npcs(source).npc(0)
        self.assertEqual(len(n.raw), RECORD_SIZE)
        self.assertEqual(n.to_bytes(), source)

    def test_health_anomaly_without_combat_ai_is_flagged_unreachable(self) -> None:
        n = U9Npcs(
            _record(
                "Silver Serpent",
                health=(65535, 0, 0),
                combat_behavior_id=NO_COMBAT_BEHAVIOR,
            )
        ).npc(0)

        self.assertEqual(n.health_current, 65535)
        self.assertEqual(n.health_status, "unreachable: no combat AI")

    def test_reachable_health_anomaly_is_flagged_as_clamped_on_first_write(
        self,
    ) -> None:
        n = U9Npcs(
            _record(
                "Creeper",
                health=(12850, 50, 0),
                combat_behavior_id=12,
            )
        ).npc(0)

        self.assertEqual(n.health_current, 12850)
        self.assertEqual(n.health_status, "clamped_on_first_write")

    def test_normal_health_has_no_status(self) -> None:
        n = U9Npcs(_record("Avatar", health=(100, 100, 100), combat_behavior_id=0)).npc(
            0
        )
        self.assertIsNone(n.health_status)


class NpcLevelCodeTests(unittest.TestCase):
    def test_all_level_cells_are_signed_i32_with_raw_bytes(self) -> None:
        raw = bytearray(
            _record(
                "Skeleton Archer",
                core_codes=(168430080, 3, -1),
                combat_skills=(200, 1, 2, 3, -1),
            )
        )
        npc = U9Npcs(bytes(raw)).npc(0)

        cells = {name: (value, stored) for name, value, stored in npc.level_code_items}
        self.assertEqual(len(cells), 8)
        self.assertEqual(cells["might"], (168430080, bytes.fromhex("00 0a 0a 0a")))
        self.assertEqual(cells["unarmed_skill"], (200, bytes.fromhex("c8 00 00 00")))
        self.assertEqual(cells["ranged_skill"], (-1, bytes.fromhex("ff ff ff ff")))


class NpcArrayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.block = (
            _record("Avatar", region=9, combat_behavior_id=0)
            + _record("LordBritish", region=9, combat_behavior_id=39)
            + _record("Valkadesh", region=40, combat_behavior_id=10)
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

    def test_round_trip_preserves_complete_record_block(self) -> None:
        self.assertEqual(self.npcs.to_bytes(), self.block)

    def test_by_name(self) -> None:
        matched = self.npcs.by_name("Valkadesh")
        self.assertIsNotNone(matched)
        assert matched is not None
        self.assertEqual(matched.index, 2)
        self.assertIsNone(self.npcs.by_name("Nobody"))

    def test_in_region_and_by_combat_behavior(self) -> None:
        self.assertEqual(
            [n.name for n in self.npcs.in_region(9)], ["Avatar", "LordBritish"]
        )
        self.assertEqual(
            [n.name for n in self.npcs.by_combat_behavior(10)], ["Valkadesh"]
        )

    def test_combat_behavior_histogram(self) -> None:
        histogram = self.npcs.combat_behavior_histogram()
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
            _record(f"NPC{i}", region=9, pos=(1000 + i, 2000 + i, 30))
            for i in range(count)
        )

    def test_finds_an_embedded_block(self) -> None:
        data = b"\xaa" * 777 + self._block(20) + b"\xbb" * 300
        offset, count = U9Npcs.find_block(data)
        self.assertEqual(offset, 777)
        self.assertEqual(count, 20)

    def test_a_blank_slot_does_not_split_the_block(self) -> None:
        data = self._block(10) + _record("") + self._block(10)
        offset, count = U9Npcs.find_block(data)
        self.assertEqual(offset, 0)
        self.assertEqual(count, 21)

    def test_live_block_is_capped_at_the_serialized_slot_count(self) -> None:
        data = self._block(LIVE_RECORD_COUNT + 1)
        offset, count = U9Npcs.find_block(data)
        self.assertEqual(offset, 0)
        self.assertEqual(count, LIVE_RECORD_COUNT)

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
        data = b"\xaa" * 300 + block
        offset, count = U9Npcs.find_block(data)
        self.assertEqual(offset, 300)
        self.assertEqual(count, 20)
        assert offset is not None
        self.assertEqual(
            U9Npcs(data[offset : offset + count * RECORD_SIZE]).npc(0).name, "NPC0"
        )

    def test_backward_walk_does_not_cross_blank_padding(self) -> None:
        # Blank records are legal inside the array, but a run of them is also
        # what unrelated zero padding looks like; walking back into it would
        # drag the start far below the real array.
        data = b"\x00" * (RECORD_SIZE * 40) + self._block(20)
        offset, count = U9Npcs.find_block(data)
        self.assertEqual(offset, RECORD_SIZE * 40)
        self.assertEqual(count, 20)

    def test_returns_none_when_no_block_is_present(self) -> None:
        self.assertEqual(U9Npcs.find_block(b"\xaa" * 5000), (None, 0))

    def test_short_run_is_not_a_block(self) -> None:
        self.assertEqual(U9Npcs.find_block(b"\xaa" * 400 + self._block(4)), (None, 0))


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
