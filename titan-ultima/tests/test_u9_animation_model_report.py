"""Tests for the U9 animation-to-model candidate report."""

from __future__ import annotations

import csv
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from titan.u9.animation_model_report import build_animation_model_report
from titan.u9.cli import cmd_animation_model_report
from titan.u9.types_dat import EXPECTED_SIZE, RECORD_SIZE, RECORD_STRUCT

FLX_DIRECTORY_OFFSET = 0x80
MODEL_HEADER_SIZE = 0x90
LIMB_HEADER_SIZE = 0x30


def _build_flx(entries: list[bytes | None]) -> bytes:
    header = bytearray(FLX_DIRECTORY_OFFSET)
    struct.pack_into("<I", header, 0x50, len(entries))
    struct.pack_into("<I", header, 0x54, 2)
    cursor = FLX_DIRECTORY_OFFSET + len(entries) * 8
    directory = bytearray()
    payload = bytearray()
    for entry in entries:
        if entry is None:
            directory += struct.pack("<II", 0, 0)
            continue
        directory += struct.pack("<II", cursor, len(entry))
        payload += entry
        cursor += len(entry)
    return bytes(header + directory + payload)


def _animation_part(part_id: int, name: str) -> bytes:
    encoded_name = name.encode("ascii")
    frame = struct.pack("<I10f", 0, 1, 0, 0, 0, 0, 0, 0, 1, 1, 1)
    return (
        struct.pack("<II", part_id, len(encoded_name))
        + encoded_name
        + struct.pack("<I", 1)
        + frame
    )


def _animation_entry() -> bytes:
    animation_id = 3
    part_data = [
        _animation_part(1, "BIP01"),
        _animation_part(15, "HEAD"),
        _animation_part(99, "CAMERA"),
    ]
    part_ids = (1, 15, 99)
    source = rb"u:\art\motions\humanoid\idle\lws\breathe_avatar.lws"
    header_words = part_ids + (0,)
    return b"".join(
        [
            struct.pack("<7I", animation_id, 0, 0, 1, 30, 33, len(source)),
            source,
            struct.pack("<I", len(header_words)),
            struct.pack(f"<{len(header_words)}I", *header_words),
            struct.pack("<I", len(part_data)),
            *part_data,
            struct.pack("<I", 0),
        ]
    )


def _limb_header(limb_id: int, parent_id: int) -> bytes:
    return (
        struct.pack("<II", limb_id, parent_id)
        + struct.pack("<3f", 1, 1, 1)
        + struct.pack("<3f", 0, 0, 0)
        + struct.pack("<4f", 1, 0, 0, 0)
    )


def _model_entry() -> bytes:
    limb_pairs = ((1, 0), (15, 1))
    model_header = bytearray(MODEL_HEADER_SIZE)
    struct.pack_into("<II", model_header, 0, len(limb_pairs), 1)
    table_size = len(limb_pairs) * 8
    first_limb_offset = MODEL_HEADER_SIZE + table_size
    empty_lod_offset = first_limb_offset + len(limb_pairs) * LIMB_HEADER_SIZE
    table = b"".join(
        struct.pack(
            "<II", first_limb_offset + index * LIMB_HEADER_SIZE, empty_lod_offset
        )
        for index in range(len(limb_pairs))
    )
    limbs = b"".join(_limb_header(*pair) for pair in limb_pairs)
    return bytes(model_header) + table + limbs + struct.pack("<I", 0)


def _types_dat() -> bytes:
    data = bytearray(EXPECTED_SIZE)
    type_id = 1
    struct.pack_into(
        RECORD_STRUCT,
        data,
        8 + type_id * RECORD_SIZE,
        0,
        7,
        1,
        0x12,
        5,
        6,
        0,
        10,
        0,
    )
    return bytes(data)


class AnimationModelReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.static = Path(self.temp.name)
        (self.static / "anim.flx").write_bytes(
            _build_flx([None, None, None, _animation_entry()])
        )
        (self.static / "sappear.flx").write_bytes(_build_flx([None, _model_entry()]))
        (self.static / "registry.txt").write_text(
            "// generated\n1 BIP01\n15 HEAD\n99 CAMERA\n", encoding="ascii"
        )
        (self.static / "TYPES.DAT").write_bytes(_types_dat())
        typename = struct.pack("<IH", 0, 0x1B81) + b"Avatar\x00"
        (self.static / "TYPENAME.FLX").write_bytes(_build_flx([None, typename]))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_report_joins_registry_model_type_and_source_name_evidence(self) -> None:
        rows, warnings = build_animation_model_report(self.static / "anim.flx")

        self.assertEqual(warnings, [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["animation_id"], 3)
        self.assertEqual(row["animation_label"], "humanoid/idle/breathe_avatar")
        self.assertEqual(row["action_hint"], "breathe")
        self.assertEqual(row["registry_status"], "complete")
        self.assertEqual(row["registry_name_match_count"], 3)
        self.assertEqual(row["model_track_ids"], [1, 15])
        self.assertEqual(row["authoring_only_track_ids"], [99])
        self.assertEqual(row["candidate_status"], "full-structural")
        self.assertEqual(row["candidate_model_ids"], [1])
        self.assertEqual(row["candidate_models"][0]["missing_track_ids"], [])
        self.assertEqual(row["candidate_models"][0]["matched_track_ids"], [1, 15])
        self.assertEqual(row["source_name_candidate_count"], 1)
        source_candidate = row["source_name_candidate_models"][0]
        self.assertEqual(source_candidate["model_names"], ["Avatar"])
        self.assertEqual(source_candidate["type_ids"], [1])
        self.assertEqual(source_candidate["usecode_ids"], [7])

    def test_command_writes_csv(self) -> None:
        output = self.static / "animation-model.csv"
        result = cmd_animation_model_report(
            SimpleNamespace(
                file=str(self.static / "anim.flx"),
                output=str(output),
                animation=None,
                sappear=None,
                registry=None,
                types=None,
                typenames=None,
                format="csv",
            )
        )

        self.assertEqual(result, 0)
        with output.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["animation_id"], "3")
        self.assertEqual(rows[0]["candidate_status"], "full-structural")


if __name__ == "__main__":
    unittest.main()
