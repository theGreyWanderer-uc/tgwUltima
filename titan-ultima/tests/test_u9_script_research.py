"""Tests for the Ghidra-oriented U9 script evidence bundle."""

from __future__ import annotations

import csv
import json
import struct
import tempfile
import unittest
from pathlib import Path

from titan.u9.activity import U9Activities
from titan.u9.flx_archive import U9FlxArchive
from titan.u9.script_research import export_script_research_bundle
from titan.u9.triggers import U9Triggers

FLX_DIR_OFFSET = 0x80


def _archive(entries: dict[int, bytes], count: int = 4) -> U9FlxArchive:
    header = bytearray(FLX_DIR_OFFSET + count * 8)
    payload = b""
    for index in range(count):
        blob = entries.get(index, b"")
        if blob:
            struct.pack_into(
                "<II",
                header,
                FLX_DIR_OFFSET + index * 8,
                len(header) + len(payload),
                len(blob),
            )
            payload += blob
    struct.pack_into("<I", header, 0x50, count)
    struct.pack_into("<I", header, 0x54, 2)
    struct.pack_into("<I", header, 0x58, len(header) + len(payload))
    return U9FlxArchive(bytes(header) + payload)


def _trigger_record(opcode: int, arg0: int, arg1: int, arg2: int) -> bytes:
    return struct.pack("<BBHH", opcode, arg0, arg1, arg2)


def _activity_entry() -> bytes:
    name = b"Walk\x00".ljust(15, b"\xcd")
    step = bytes((0x01,)) + struct.pack("<HHHH", 10, 20, 0, 0)
    terminator = bytes((0xFF,)) + b"\x00" * 8
    body = bytes((2,)) + name + step + terminator
    return struct.pack("<II", 1, len(body)) + body


class ScriptResearchExportTests(unittest.TestCase):
    def test_bundle_contains_occurrences_summaries_links_and_manifest(self) -> None:
        trigger_blob = (
            _trigger_record(0x31, 0x10, 1, 0xAB02)
            + _trigger_record(0xFF, 0x10, 0, 0)
            + _trigger_record(0x04, 0, 0, 0)
        )
        triggers = U9Triggers(_archive({3: trigger_blob}))
        activities = U9Activities(_archive({1: _activity_entry()}))

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.flx"
            source.write_bytes(b"fixture")
            paths = export_script_research_bundle(
                triggers,
                activities,
                Path(temporary) / "out",
                source_files={"fixture": source},
            )

            self.assertEqual(len(paths), 6)
            self.assertTrue(all(path.is_file() for path in paths))

            with (Path(temporary) / "out/trigger_occurrences.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(
                [row["stream_role"] for row in rows], ["body", "terminator", "slack"]
            )
            self.assertEqual([row["entry_offset"] for row in rows], ["0", "6", "12"])

            with (Path(temporary) / "out/trigger_activity_links.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                links = list(csv.DictReader(stream))
            self.assertEqual(links[0]["record_name"], "Walk")
            self.assertEqual(links[0]["resolved"], "1")
            self.assertEqual(links[0]["arg2_high"], str(0xAB))

            manifest = json.loads(
                (Path(temporary) / "out/script_research_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["known_cross_links"]["resolved"], 1)
            self.assertEqual(manifest["triggers"]["body_records"], 1)
            self.assertEqual(len(manifest["sources"]["fixture"]["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
