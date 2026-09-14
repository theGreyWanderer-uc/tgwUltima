"""Tests for titan.u9.types_dat's TYPES.DAT decoder.

Fixture matches the exact byte layout re-validated against real game
data in this project (131,080 bytes = 8-byte header + 16*8192 records,
zero remainder) -- see the module docstring.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.types_dat import U9TypesDat, U9TypesDatError

HEADER_SIZE = 8
RECORD_SIZE = 16
RECORD_STRUCT = "<IHHHBBBBH"
MAX_RECORDS = 8192
EXPECTED_SIZE = HEADER_SIZE + RECORD_SIZE * MAX_RECORDS


def _record(usecode_id: int, default_model_id: int, type_flags: int = 0, weight: int = 0, volume: int = 0) -> bytes:
    return struct.pack(RECORD_STRUCT, 0, usecode_id, default_model_id, type_flags, weight, volume, 0, 0, 0)


def _build(records_data: list[bytes]) -> bytes:
    """A complete 131,080-byte table: the given records, then empty ones.

    TYPES.DAT is indexed by type ID, so the real file always holds the full
    8,192-entry table and the reader requires exactly that size. A short
    fixture is rejected, as it should be.
    """
    filler = struct.pack(RECORD_STRUCT, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    padded = list(records_data) + [filler] * (MAX_RECORDS - len(records_data))
    return b"\x00" * HEADER_SIZE + b"".join(padded)


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
        self.assertEqual(len(types), MAX_RECORDS)
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
        self.assertEqual([r.type_id for r in types][:4], [0, 1, 2, 3])
        self.assertEqual(len(list(types)), MAX_RECORDS)


class TypesDatValidationTests(unittest.TestCase):
    """TYPES.DAT has no magic number, so its exact size is the only guard."""

    def test_accepts_the_exact_expected_size(self) -> None:
        data = _build([_record(usecode_id=1, default_model_id=1805)])
        self.assertEqual(len(data), EXPECTED_SIZE)
        self.assertEqual(len(U9TypesDat(data)), MAX_RECORDS)

    def test_rejects_a_short_table(self) -> None:
        short = b"\x00" * HEADER_SIZE + _record(0, 0) * 4
        with self.assertRaises(U9TypesDatError):
            U9TypesDat(short)

    def test_rejects_a_long_table(self) -> None:
        long = _build([]) + _record(0, 0)
        with self.assertRaises(U9TypesDatError):
            U9TypesDat(long)

    def test_rejects_data_smaller_than_the_header(self) -> None:
        with self.assertRaises(U9TypesDatError):
            U9TypesDat(b"\x00" * 4)

    def test_rejects_a_partial_trailing_record(self) -> None:
        # The old reader silently dropped a partial trailing record.
        # static/highway.dat is exactly this shape and parsed as 776
        # records of nonsense instead of being rejected.
        truncated = _build([])[:-4]
        with self.assertRaises(U9TypesDatError):
            U9TypesDat(truncated)

    def test_rejects_a_whole_number_of_records_at_the_wrong_count(self) -> None:
        # Every terrain.* file in the game is 8 + 16*N bytes by coincidence,
        # so "a whole number of records" is not a sufficient check -- 143
        # files in this project's copy would pass it.
        terrain_shaped = b"\x00" * HEADER_SIZE + _record(0, 0) * 4177
        self.assertEqual((len(terrain_shaped) - HEADER_SIZE) % RECORD_SIZE, 0)
        with self.assertRaises(U9TypesDatError):
            U9TypesDat(terrain_shaped)


if __name__ == "__main__":
    unittest.main()
