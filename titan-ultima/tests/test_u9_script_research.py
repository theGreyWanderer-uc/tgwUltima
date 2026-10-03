"""Tests for the U9 script-research evidence bundle."""

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
    step = bytes((0x01,)) + struct.pack("<HHHH", 10, 20, 720, 43)
    terminator = bytes((0xFF,)) + b"\x00" * 8
    body = bytes((2,)) + name + step + terminator
    return struct.pack("<II", 1, len(body)) + body


class ScriptResearchExportTests(unittest.TestCase):
    def test_special_action_export_distinguishes_noop_from_unknown_whole_word(
        self,
    ) -> None:
        blob = (
            _trigger_record(0x3D, 16, 0, 9)
            + _trigger_record(0x3D, 16, 0, 0x109)
            + _trigger_record(0xFF, 16, 0, 0)
        )
        triggers = U9Triggers(_archive({1: blob}))
        activities = U9Activities(_archive({}))
        with tempfile.TemporaryDirectory() as temporary:
            export_script_research_bundle(triggers, activities, temporary)
            with (Path(temporary) / "trigger_occurrences.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["special_action_meaning"], "reserved no-op")
        self.assertEqual(rows[1]["special_action_meaning"], "")
        self.assertEqual(
            bytes.fromhex(rows[1]["raw_hex"]), _trigger_record(0x3D, 16, 0, 0x109)
        )
        self.assertEqual(rows[2]["special_action_meaning"], "")

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
            self.assertEqual(rows[0]["semantic_name"], "choose NPC activity record")
            self.assertEqual(rows[0]["semantic_evidence"], "retail_archive_confirmed")
            self.assertEqual(rows[0]["raw_hex"], "3110010002ab")

            with (Path(temporary) / "out/trigger_opcodes.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                opcode_rows = list(csv.DictReader(stream))
            self.assertEqual(len(opcode_rows), 101)
            self.assertEqual(
                opcode_rows[31]["semantic_name"], "transition between maps"
            )
            self.assertEqual(opcode_rows[31]["observed_in_archive"], "0")
            self.assertEqual(opcode_rows[49]["observed_in_archive"], "1")

            with (Path(temporary) / "out/activity_occurrences.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                activity_rows = list(csv.DictReader(stream))
            self.assertEqual(
                activity_rows[0]["semantic_name"], "travel between navigation points"
            )
            self.assertEqual(activity_rows[0]["parameter_0"], "10")
            self.assertEqual(activity_rows[0]["parameter_1"], "20")
            self.assertEqual(activity_rows[0]["scheduled_minute"], "720")
            self.assertEqual(activity_rows[0]["duration_code"], "43")
            self.assertEqual(activity_rows[0]["duration_value"], "10")
            self.assertEqual(activity_rows[0]["duration_remainder"], "3")
            self.assertEqual(activity_rows[0]["movement_cautious"], "0")
            self.assertEqual(activity_rows[1]["stream_role"], "repeat_marker")

            with (Path(temporary) / "out/activity_opcodes.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                activity_opcode_rows = list(csv.DictReader(stream))
            self.assertEqual(len(activity_opcode_rows), 13)
            self.assertEqual(activity_opcode_rows[1]["observed_in_archive"], "1")
            self.assertEqual(activity_opcode_rows[8]["occurrences"], "0")
            self.assertEqual(
                activity_opcode_rows[8]["semantic_name"],
                "return from activity sequence",
            )

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
            self.assertEqual(manifest["activities"]["runtime_catalogue_opcodes"], 13)
            self.assertEqual(manifest["activities"]["catalogued_opcodes_observed"], 1)
            self.assertEqual(len(manifest["sources"]["fixture"]["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
