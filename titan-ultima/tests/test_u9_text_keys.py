"""Tests for titan.u9.text_keys's ``static/text.dat`` reader.

The table is built here from real keys with the same bucket hash and CRC the
game uses, so lookup, reachability and key recovery are checked against the
retail rule rather than against stored values copied from the file.
"""

from __future__ import annotations

import csv
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from titan.u9.cli import (
    TEXT_KEY_CSV_COLUMNS,
    cmd_text_key_lookup,
    cmd_text_keys_export,
    cmd_text_keys_info,
)
from titan.u9.flx_writer import build_flx
from titan.u9.npc import U9Npcs
from titan.u9.text import MARKER_SUFFIX, U9TextArchive
from titan.u9.text_keys import (
    U9TextKeyTable,
    U9TextKeyTableError,
    key_bucket,
    key_crc,
    reconstruct_keys,
    text_reference_status,
)
from tests.test_u9_text import _archive, _string

CORPUS = Path(__file__).resolve().parents[2] / "u9data" / "gameData_u9" / "static"

MARKER = "\\u9\\Source\\Usecode\\ConvoLib\\Raven\\Raven.cpp" + MARKER_SUFFIX
LINES = {
    0: MARKER,
    1: "Hello there.",
    2: "I'll be going.",
    3: "Raven is in the tower.",
    4: "It seems naïve.",
}
KEYS = {
    0: "C:" + MARKER,
    1: "Raven : Hello there.",
    2: "Avatar : I'll be going.",
    3: "UI : Raven is in the tower.",
    4: "Raven : It seems naïve.",
}


def _table_bytes(
    rows: list[list[tuple[int, int, int]]], trailing: bytes = b""
) -> bytes:
    out = [struct.pack("<i", len(rows))]
    for items in rows:
        out.append(struct.pack("<I", len(items)))
        out.extend(struct.pack("<III", *item) for item in items)
    return b"".join(out) + trailing


def _rows_for(
    keys: dict[int, str], bucket_count: int
) -> list[list[tuple[int, int, int]]]:
    rows: list[list[tuple[int, int, int]]] = [[] for _ in range(bucket_count)]
    for index, key in keys.items():
        raw = key.encode("latin-1")
        bucket = key_bucket(raw, bucket_count)
        rows[bucket].append((bucket, key_crc(raw), index))
    return rows


def _text_archive() -> U9TextArchive:
    return U9TextArchive(_archive({i: _string(t) for i, t in LINES.items()}, count=6))


def _bitwise_crc(data: bytes) -> int:
    """Table-free MSB-first CRC-32, independent of the module's table."""
    register = 0xFFFFFFFF
    for byte in data:
        register ^= byte << 24
        for _ in range(8):
            register = (register << 1) ^ (0x04C11DB7 if register & 0x80000000 else 0)
            register &= 0xFFFFFFFF
    return register ^ 0xFFFFFFFF


class KeyFunctionTests(unittest.TestCase):
    def test_crc_is_the_non_reflected_crc32_over_the_key_and_its_nul(self) -> None:
        self.assertEqual(_bitwise_crc(b"123456789"), 0xFC891918)  # CRC-32/BZIP2 check
        for key in (b"", b"123456789", b"Avatar : Farewell.", bytes(range(1, 256))):
            with self.subTest(key=key[:12]):
                self.assertEqual(key_crc(key), _bitwise_crc(key + b"\0"))

    def test_bucket_is_horner_base_64_with_unsigned_bytes(self) -> None:
        self.assertEqual(key_bucket(b"", 7), 0)
        self.assertEqual(key_bucket(b"AB", 1000), (64 * 65 + 66) % 1000)
        self.assertEqual(key_bucket(b"\xff", 7), 255 % 7)

    def test_rejects_embedded_nul_and_non_positive_bucket_counts(self) -> None:
        with self.assertRaisesRegex(ValueError, "NUL"):
            key_crc(b"a\0b")
        with self.assertRaisesRegex(ValueError, "positive"):
            key_bucket(b"a", 0)


class TableParseTests(unittest.TestCase):
    def test_smallest_tables_round_trip(self) -> None:
        for data in (_table_bytes([]), _table_bytes([[]]), _table_bytes([[(0, 1, 2)]])):
            self.assertEqual(U9TextKeyTable.from_bytes(data).to_bytes(), data)

    def test_records_offsets_positions_and_trailing_bytes(self) -> None:
        data = _table_bytes([[], [(1, 5, 9), (1, 6, 10)]], trailing=b"\x01\x02")
        table = U9TextKeyTable.from_bytes(data)
        self.assertEqual(table.bucket_count, 2)
        self.assertEqual(table.buckets[1].offset, 8)
        second = table.buckets[1].items[1]
        self.assertEqual(
            (second.position, second.offset, second.text_index), (1, 24, 10)
        )
        self.assertEqual(table.trailing_data, b"\x01\x02")
        self.assertEqual(table.to_bytes(), data)

    def test_rejects_truncation_at_every_boundary(self) -> None:
        data = _table_bytes([[(0, 1, 2)], [(1, 3, 4), (1, 5, 6)]])
        for size in range(len(data)):
            with self.subTest(size=size):
                with self.assertRaises(U9TextKeyTableError):
                    U9TextKeyTable.from_bytes(data[:size])

    def test_rejects_negative_and_oversized_counts(self) -> None:
        with self.assertRaisesRegex(U9TextKeyTableError, "negative"):
            U9TextKeyTable.from_bytes(struct.pack("<i", -1))
        with self.assertRaisesRegex(U9TextKeyTableError, "cannot fit"):
            U9TextKeyTable.from_bytes(struct.pack("<iI", 2, 0))
        with self.assertRaisesRegex(U9TextKeyTableError, "claims"):
            U9TextKeyTable.from_bytes(struct.pack("<iI", 1, 0x80000000))

    def test_keeps_unsigned_extremes(self) -> None:
        data = _table_bytes([[(0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)]])
        item = U9TextKeyTable.from_bytes(data).items[0]
        self.assertEqual(
            (item.stored_hash, item.stored_crc, item.text_index), (0xFFFFFFFF,) * 3
        )


class LookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = U9TextKeyTable.from_bytes(_table_bytes(_rows_for(KEYS, 7)))

    def test_every_key_finds_its_line(self) -> None:
        for index, key in KEYS.items():
            item = self.table.lookup(key)
            assert item is not None
            self.assertEqual(item.text_index, index)

    def test_not_found_and_empty_key(self) -> None:
        self.assertIsNone(self.table.lookup("Raven : Goodbye."))
        self.assertIsNone(self.table.lookup(""))

    def test_empty_table_finds_nothing(self) -> None:
        self.assertIsNone(U9TextKeyTable.from_bytes(_table_bytes([])).lookup("x"))

    def test_first_matching_item_wins_and_later_duplicate_is_shadowed(self) -> None:
        raw = b"Avatar : Hi."
        bucket, crc = key_bucket(raw, 3), key_crc(raw)
        rows: list[list[tuple[int, int, int]]] = [[], [], []]
        rows[bucket] = [(bucket, crc, 7), (bucket, crc, 8)]
        table = U9TextKeyTable.from_bytes(_table_bytes(rows))
        found = table.lookup_bytes(raw)
        assert found is not None
        self.assertEqual(found.text_index, 7)
        self.assertEqual(
            table.reachability(table.buckets[bucket].items[1]),
            "shadowed_by_earlier_item",
        )
        self.assertEqual(table.text_index_counts(), {7: 1, 8: 1})

    def test_item_in_the_wrong_bucket_is_kept_but_unreachable(self) -> None:
        raw = b"Avatar : Hi."
        bucket, crc = key_bucket(raw, 3), key_crc(raw)
        wrong = (bucket + 1) % 3
        rows: list[list[tuple[int, int, int]]] = [[], [], []]
        rows[wrong] = [(bucket, crc, 7)]
        data = _table_bytes(rows)
        table = U9TextKeyTable.from_bytes(data)
        self.assertIsNone(table.lookup_bytes(raw))
        self.assertEqual(
            table.reachability(table.items[0]), "unreachable_hash_mismatch"
        )
        self.assertEqual(table.to_bytes(), data)


class TextJoinTests(unittest.TestCase):
    def test_reference_status_and_key_recovery(self) -> None:
        rows = _rows_for(KEYS, 7)
        rows[0].append((0, 0, 5))  # empty slot in the six-slot archive
        rows[0].append((0, 0, 99))  # beyond the archive
        table = U9TextKeyTable.from_bytes(_table_bytes(rows))
        text = _text_archive()
        statuses = {
            item.text_index: text_reference_status(item, text) for item in table.items
        }
        self.assertEqual(statuses[5], "empty_slot")
        self.assertEqual(statuses[99], "out_of_range")
        self.assertEqual(statuses[1], "valid")

        recovered = reconstruct_keys(table, text)
        by_index = {
            item.text_index: recovered[(item.bucket, item.position)]
            for item in table.items
            if (item.bucket, item.position) in recovered
        }
        self.assertEqual({i: k.text for i, k in by_index.items()}, KEYS)
        self.assertEqual(by_index[0].method, "file_marker")
        self.assertEqual(by_index[1].method, "block_speaker")
        self.assertEqual(
            (by_index[2].speaker, by_index[2].method), ("Avatar", "other_speaker")
        )
        self.assertEqual((by_index[3].speaker, by_index[3].method), ("UI", "ui_prefix"))

    def test_extra_speaker_is_needed_for_an_unlisted_name(self) -> None:
        keys = {1: "Zanthor : Hello there."}
        table = U9TextKeyTable.from_bytes(_table_bytes(_rows_for(keys, 5)))
        text = _text_archive()
        self.assertEqual(reconstruct_keys(table, text), {})
        found = reconstruct_keys(table, text, ["Zanthor"])
        self.assertEqual([k.text for k in found.values()], ["Zanthor : Hello there."])

    def test_npc_names_replace_block_names_as_speakers(self) -> None:
        keys = {1: "GenericGuard : Hello there.", 3: "UI : Raven is in the tower."}
        table = U9TextKeyTable.from_bytes(_table_bytes(_rows_for(keys, 5)))
        text = _text_archive()
        found = reconstruct_keys(table, text, npc_names=["GenericGuard", "Avatar"])
        methods = {k.text: k.method for k in found.values()}
        self.assertEqual(
            methods,
            {
                "GenericGuard : Hello there.": "npc_name",
                "UI : Raven is in the tower.": "ui_prefix",
            },
        )
        # Block names are not tried once NPC names are supplied.
        block_keyed = U9TextKeyTable.from_bytes(
            _table_bytes(_rows_for({1: "Raven : Hello there."}, 5))
        )
        self.assertEqual(reconstruct_keys(block_keyed, text, npc_names=["Avatar"]), {})


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dat = self.root / "text.dat"
        self.dat.write_bytes(_table_bytes(_rows_for(KEYS, 7)))
        self.flx = self.root / "text.flx"
        self.flx.write_bytes(
            build_flx({i: _string(t) for i, t in LINES.items()}, count=6)
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_info_lookup_and_export(self) -> None:
        self.assertEqual(
            cmd_text_keys_info(
                SimpleNamespace(
                    file=str(self.dat), text=str(self.flx), speakers=None, npcs=None
                )
            ),
            0,
        )
        self.assertEqual(
            cmd_text_key_lookup(
                SimpleNamespace(file=str(self.dat), key=KEYS[2], text=str(self.flx))
            ),
            0,
        )
        self.assertEqual(
            cmd_text_key_lookup(
                SimpleNamespace(file=str(self.dat), key="nope", text=None)
            ),
            1,
        )
        out = self.root / "keys.csv"
        self.assertEqual(
            cmd_text_keys_export(
                SimpleNamespace(
                    file=str(self.dat),
                    text=str(self.flx),
                    speakers=None,
                    npcs=None,
                    output=str(out),
                )
            ),
            0,
        )
        with out.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(tuple(rows[0]), TEXT_KEY_CSV_COLUMNS)
        self.assertEqual(len(rows), len(KEYS))
        self.assertTrue(all(row["key_status"] == "verified" for row in rows))
        self.assertEqual({row["key"] for row in rows}, set(KEYS.values()))

    def test_export_without_text_marks_joins_not_checked(self) -> None:
        out = self.root / "raw.csv"
        cmd_text_keys_export(
            SimpleNamespace(
                file=str(self.dat), text=None, speakers=None, npcs=None, output=str(out)
            )
        )
        with out.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual({row["key_status"] for row in rows}, {"not_checked"})
        self.assertEqual(
            {row["text_reference_status"] for row in rows}, {"not_checked"}
        )


@unittest.skipUnless(
    (CORPUS / "text.dat").is_file(), "retail static/text.dat not available"
)
class RetailCorpusTests(unittest.TestCase):
    def test_round_trip_joins_and_key_recovery(self) -> None:
        data = (CORPUS / "text.dat").read_bytes()
        table = U9TextKeyTable.from_bytes(data)
        self.assertEqual(table.to_bytes(), data)
        self.assertEqual(
            (table.bucket_count, len(table.items), table.trailing_data),
            (7649, 7656, b""),
        )
        self.assertEqual(
            {table.reachability(item) for item in table.items}, {"reachable"}
        )
        self.assertEqual(sorted(table.text_index_counts()), list(range(7656)))

        text = U9TextArchive.from_file(CORPUS / "text.flx")
        self.assertEqual(
            {text_reference_status(item, text) for item in table.items}, {"valid"}
        )
        keys = reconstruct_keys(table, text)
        self.assertGreaterEqual(len(keys), 7514)
        for (bucket, position), key in keys.items():
            found = table.lookup(key.text)
            assert found is not None
            self.assertEqual((found.bucket, found.position), (bucket, position))

    @unittest.skipUnless(
        (CORPUS.parent / "runtime" / "NPC.FLX").is_file(),
        "retail NPC.FLX not available",
    )
    def test_npc_record_names_are_the_speakers(self) -> None:
        table = U9TextKeyTable.from_file(CORPUS / "text.dat")
        text = U9TextArchive.from_file(CORPUS / "text.flx")
        names = [
            npc.name
            for npc in U9Npcs.from_file(CORPUS.parent / "runtime" / "NPC.FLX")
            if npc.name
        ]
        keys = reconstruct_keys(table, text, npc_names=names)
        self.assertGreaterEqual(len(keys), 7595)
        self.assertEqual(
            {key.method for key in keys.values()},
            {"npc_name", "ui_prefix", "file_marker"},
        )


if __name__ == "__main__":
    unittest.main()
