"""Tests for titan.u9.types_dat's TYPES.DAT decoder.

Fixture matches the exact byte layout re-validated against real game
data in this project (131,080 bytes = 8-byte header + 16*8192 records,
zero remainder) -- see the module docstring.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.types_dat import U9TypesDat

HEADER_SIZE = 8
RECORD_STRUCT = "<IHHHBBBBH"


def _record(usecode_id: int, default_model_id: int, type_flags: int = 0, weight: int = 0, volume: int = 0) -> bytes:
    return struct.pack(RECORD_STRUCT, 0, usecode_id, default_model_id, type_flags, weight, volume, 0, 0, 0)


def _build(records_data: list[bytes]) -> bytes:
    return b"\x00" * HEADER_SIZE + b"".join(records_data)


class TypesDatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = _build([
            _record(usecode_id=0, default_model_id=0),  # type_id 0: no model
            _record(usecode_id=1, default_model_id=1805, type_flags=40, weight=255, volume=171),  # type_id 1
            _record(usecode_id=2, default_model_id=3448),  # type_id 2
            _record(usecode_id=3, default_model_id=3448),  # type_id 3: shares model with type_id 2
        ])

    def test_record_fields(self) -> None:
        types = U9TypesDat(self.data)
        self.assertEqual(len(types), 4)
        record = types.records[1]
        self.assertEqual(record.type_id, 1)
        self.assertEqual(record.usecode_id, 1)
        self.assertEqual(record.default_model_id, 1805)
        self.assertEqual(record.type_flags, 40)
        self.assertEqual(record.weight, 255)
        self.assertEqual(record.volume, 171)

    def test_type_ids_for_model_single_match(self) -> None:
        types = U9TypesDat(self.data)
        self.assertEqual(types.type_ids_for_model(1805), [1])

    def test_type_ids_for_model_multiple_matches(self) -> None:
        types = U9TypesDat(self.data)
        self.assertEqual(types.type_ids_for_model(3448), [2, 3])

    def test_type_ids_for_model_zero_is_never_matched(self) -> None:
        # default_model_id == 0 means "no model" -- type_id 0 must not show up under model_id 0.
        types = U9TypesDat(self.data)
        self.assertEqual(types.type_ids_for_model(0), [])

    def test_unmapped_model_id_returns_empty(self) -> None:
        types = U9TypesDat(self.data)
        self.assertEqual(types.type_ids_for_model(9999), [])

    def test_iteration_order(self) -> None:
        types = U9TypesDat(self.data)
        self.assertEqual([r.type_id for r in types], [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
