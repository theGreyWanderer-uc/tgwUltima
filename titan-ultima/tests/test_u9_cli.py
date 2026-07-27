"""Tests for titan.u9.cli's flx-list/flx-extract/flx-extract-all/typename-dump commands."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
from types import SimpleNamespace

from titan.u9.cli import (
    cmd_flx_extract,
    cmd_flx_extract_all,
    cmd_flx_list,
    cmd_sound_extract_pcm,
    cmd_sound_list,
    cmd_typename_dump,
)

DIR_OFFSET = 0x80
MARKER = 0x1B81


def _build_flx(comment: bytes, entries_data: list[bytes | None]) -> bytes:
    count = len(entries_data)
    dir_size = count * 8
    header = bytearray(DIR_OFFSET)
    header[0:len(comment)] = comment
    struct.pack_into("<I", header, 0x50, count)

    payload = bytearray()
    dir_entries: list[tuple[int, int]] = []
    cursor = DIR_OFFSET + dir_size
    for data in entries_data:
        if data is None:
            dir_entries.append((0, 0))
            continue
        dir_entries.append((cursor, len(data)))
        payload += data
        cursor += len(data)

    directory = bytearray()
    for offset, length in dir_entries:
        directory += struct.pack("<II", offset, length)

    return bytes(header) + bytes(directory) + bytes(payload)


def _typename_entry(name: str | None) -> bytes:
    header = struct.pack("<IH", 0, MARKER)
    if name is None:
        return header
    return header + name.encode("ascii") + b"\x00"


def _sound_entry(
    sound_id: int,
    description: str,
    frequency: int,
    bits_per_sample: int,
    num_channels: int,
    encoding_type: int,
    payload: bytes,
) -> bytes:
    header = bytearray(0x3C)
    struct.pack_into("<I", header, 0x00, sound_id)
    desc_bytes = description.encode("ascii")
    header[0x04 : 0x04 + len(desc_bytes)] = desc_bytes
    struct.pack_into("<I", header, 0x28, len(payload))
    struct.pack_into("<I", header, 0x2C, frequency)
    struct.pack_into("<I", header, 0x30, bits_per_sample)
    struct.pack_into("<I", header, 0x34, num_channels)
    struct.pack_into("<I", header, 0x38, encoding_type)
    return bytes(header) + payload


class FlxCliCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.flx_path = os.path.join(self.tmpdir.name, "test.flx")
        with open(self.flx_path, "wb") as f:
            f.write(_build_flx(b"test archive", [b"HELLO", None, b"WORLD!!"]))

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_flx_list_reports_used_entries(self) -> None:
        rc = cmd_flx_list(SimpleNamespace(file=self.flx_path))
        self.assertEqual(rc, 0)

    def test_flx_list_missing_file_errors(self) -> None:
        rc = cmd_flx_list(SimpleNamespace(file=os.path.join(self.tmpdir.name, "nope.flx")))
        self.assertEqual(rc, 1)

    def test_flx_extract_writes_entry_payload(self) -> None:
        outdir = os.path.join(self.tmpdir.name, "out")
        rc = cmd_flx_extract(SimpleNamespace(file=self.flx_path, index=0, output=outdir))
        self.assertEqual(rc, 0)
        out_path = os.path.join(outdir, "test_00000.bin")
        self.assertTrue(os.path.isfile(out_path))
        with open(out_path, "rb") as f:
            self.assertEqual(f.read(), b"HELLO")

    def test_flx_extract_out_of_range_errors(self) -> None:
        rc = cmd_flx_extract(SimpleNamespace(file=self.flx_path, index=99, output=self.tmpdir.name))
        self.assertEqual(rc, 1)

    def test_flx_extract_all_skips_empty_slots(self) -> None:
        outdir = os.path.join(self.tmpdir.name, "all")
        rc = cmd_flx_extract_all(SimpleNamespace(file=self.flx_path, output=outdir))
        self.assertEqual(rc, 0)
        written = sorted(os.listdir(outdir))
        self.assertEqual(written, ["00000.bin", "00002.bin"])


class TypeNameDumpCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.flx_path = os.path.join(self.tmpdir.name, "TYPENAME.FLX")
        data = _build_flx(b"TYPENAME.FLX", [
            _typename_entry(None),
            _typename_entry("Lord British"),
        ])
        with open(self.flx_path, "wb") as f:
            f.write(data)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_typename_dump_succeeds(self) -> None:
        rc = cmd_typename_dump(SimpleNamespace(file=self.flx_path))
        self.assertEqual(rc, 0)

    def test_typename_dump_missing_file_errors(self) -> None:
        rc = cmd_typename_dump(SimpleNamespace(file=os.path.join(self.tmpdir.name, "nope.flx")))
        self.assertEqual(rc, 1)


class SoundCliCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.flx_path = os.path.join(self.tmpdir.name, "sfx.flx")
        data = _build_flx(b"sfx.flx", [
            _sound_entry(0, "pcm_one.wav", 22050, 16, 1, 0, struct.pack("<2h", 10, -10)),
            _sound_entry(1, "compressed.umt", 22050, 16, 1, 2, b"\x01\x02\x03\x04"),
        ])
        with open(self.flx_path, "wb") as f:
            f.write(data)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_sound_list_succeeds(self) -> None:
        rc = cmd_sound_list(SimpleNamespace(file=self.flx_path))
        self.assertEqual(rc, 0)

    def test_sound_list_missing_file_errors(self) -> None:
        rc = cmd_sound_list(SimpleNamespace(file=os.path.join(self.tmpdir.name, "nope.flx")))
        self.assertEqual(rc, 1)

    def test_sound_extract_pcm_only_writes_pcm_entries(self) -> None:
        outdir = os.path.join(self.tmpdir.name, "wav")
        rc = cmd_sound_extract_pcm(SimpleNamespace(file=self.flx_path, output=outdir))
        self.assertEqual(rc, 0)
        written = os.listdir(outdir)
        self.assertEqual(len(written), 1)
        self.assertIn("pcm_one.wav", written[0])


if __name__ == "__main__":
    unittest.main()
