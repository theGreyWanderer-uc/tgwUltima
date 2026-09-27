"""Tests for the lossless ``TYPES.DAT`` decoder."""

from __future__ import annotations

import struct
import unittest

from titan.u9.types_dat import U9TypesDat, U9TypesDatError

HEADER_SIZE = 8
RECORD_SIZE = 16
RECORD_STRUCT = "<IHHHBBBBH"
MAX_RECORDS = 8192
EXPECTED_SIZE = HEADER_SIZE + RECORD_SIZE * MAX_RECORDS


def _record(
    base_type_id: int,
    default_model_id: int,
    object_flags: int = 0,
    mass_code: int = 0,
    volume_code: int = 0,
    *,
    pointer_cell: int = 0,
    document_code: int = 0,
    durability_points: int = 0,
    handler_mask: int = 0,
) -> bytes:
    return struct.pack(
        RECORD_STRUCT,
        pointer_cell,
        base_type_id,
        default_model_id,
        object_flags,
        mass_code,
        volume_code,
        document_code,
        durability_points,
        handler_mask,
    )


def _build(records_data: list[bytes], *, npc_type_count: int = 2) -> bytes:
    filler = _record(0, 0, mass_code=254)
    padded = list(records_data) + [filler] * (MAX_RECORDS - len(records_data))
    header = struct.pack("<II", len(records_data), npc_type_count)
    return header + b"".join(padded)


class TypesDatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = _build(
            [
                _record(0, 0),
                _record(
                    1,
                    1805,
                    object_flags=0x0128,
                    mass_code=255,
                    volume_code=171,
                    pointer_cell=0xCDCDCDCD,
                    document_code=4,
                    durability_points=12,
                ),
                _record(2, 3448),
                _record(3, 3448),
            ]
        )

    def test_header_selects_active_records_from_physical_slots(self) -> None:
        types = U9TypesDat(self.data)
        self.assertEqual(types.header.active_type_count, 4)
        self.assertEqual(types.header.npc_type_count, 2)
        self.assertEqual(types.header.raw, self.data[:8])
        self.assertEqual(len(types), 4)
        self.assertEqual(len(types.records), 4)
        self.assertEqual(len(types.slots), MAX_RECORDS)
        self.assertEqual(len(types.inactive_slots), MAX_RECORDS - 4)
        self.assertTrue(types.records[3].is_active)
        self.assertFalse(types.slots[4].is_active)

    def test_record_fields_and_forensic_state(self) -> None:
        record = U9TypesDat(self.data).records[1]
        self.assertEqual(record.type_id, 1)
        self.assertEqual(record.runtime_handler_pointer_cell, 0xCDCDCDCD)
        self.assertEqual(record.runtime_pointer_state, "debug_fill")
        self.assertEqual(record.base_type_id, 1)
        self.assertEqual(record.default_model_id, 1805)
        self.assertEqual(record.object_flags, 0x0128)
        self.assertEqual(record.mass_code, 255)
        self.assertEqual(record.volume_code, 171)
        self.assertEqual(record.legacy_document_code, 4)
        self.assertEqual(record.durability_points, 12)
        self.assertEqual(record.runtime_handler_mask_cell, 0)
        self.assertEqual(record.raw, self.data[24:40])
        self.assertEqual(record.record_representation, "fixed_16_byte_record")

    def test_object_flags_and_mass_permissions(self) -> None:
        record = U9TypesDat(self.data).records[1]
        self.assertEqual(
            record.object_flag_names,
            ("non_camera_blocker", "art_finalized", "mesh_collision"),
        )
        self.assertEqual(record.unmapped_object_flag_bits, 0)
        self.assertFalse(record.can_drag)
        self.assertFalse(record.can_inventory)

    def test_unmapped_bits_and_runtime_cells_are_flagged_not_changed(self) -> None:
        data = _build(
            [_record(0, 0, object_flags=0x0200, pointer_cell=7, handler_mask=2)]
        )
        record = U9TypesDat(data).records[0]
        self.assertEqual(record.unmapped_object_flag_bits, 0x0200)
        self.assertEqual(
            record.warnings,
            (
                "unmapped_object_flag_bits",
                "unexpected_runtime_pointer_cell",
                "stored_runtime_handler_mask",
            ),
        )
        self.assertEqual(record.raw, data[8:24])

    def test_type_ids_for_model_uses_only_active_prefix(self) -> None:
        types = U9TypesDat(self.data)
        self.assertEqual(types.type_ids_for_model(1805), [1])
        self.assertEqual(types.type_ids_for_model(3448), [2, 3])
        self.assertEqual(types.type_ids_for_model(0), [])
        self.assertEqual(types.type_ids_for_model(9999), [])

    def test_active_and_physical_lookups(self) -> None:
        types = U9TypesDat(self.data)
        self.assertEqual(types.record_for(3), types.records[3])
        self.assertIsNone(types.record_for(4))
        self.assertEqual(types.slot_for(4), types.slots[4])
        self.assertIsNone(types.slot_for(MAX_RECORDS))

    def test_round_trip_is_byte_exact(self) -> None:
        self.assertEqual(U9TypesDat(self.data).to_bytes(), self.data)

    def test_iteration_visits_only_active_records(self) -> None:
        types = U9TypesDat(self.data)
        self.assertEqual([record.type_id for record in types], [0, 1, 2, 3])


class TypesDatValidationTests(unittest.TestCase):
    def test_accepts_the_exact_expected_size(self) -> None:
        data = _build([_record(0, 1805)])
        self.assertEqual(len(data), EXPECTED_SIZE)
        self.assertEqual(len(U9TypesDat(data)), 1)

    def test_rejects_a_short_or_long_table(self) -> None:
        with self.assertRaises(U9TypesDatError):
            U9TypesDat(b"\x00" * HEADER_SIZE + _record(0, 0) * 4)
        with self.assertRaises(U9TypesDatError):
            U9TypesDat(_build([]) + _record(0, 0))

    def test_rejects_data_smaller_than_header_and_partial_record(self) -> None:
        with self.assertRaises(U9TypesDatError):
            U9TypesDat(b"\x00" * 4)
        with self.assertRaises(U9TypesDatError):
            U9TypesDat(_build([])[:-4])

    def test_rejects_header_counts_beyond_capacity(self) -> None:
        data = bytearray(_build([]))
        struct.pack_into("<I", data, 0, MAX_RECORDS + 1)
        with self.assertRaises(U9TypesDatError):
            U9TypesDat(bytes(data))

        data = bytearray(_build([]))
        struct.pack_into("<I", data, 4, 353)
        with self.assertRaises(U9TypesDatError):
            U9TypesDat(bytes(data))


if __name__ == "__main__":
    unittest.main()
