"""Tests for titan.u8.cli music/sound export naming."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from titan.u8.cli import cmd_music_export, cmd_shape_batch, cmd_shape_export, cmd_sound_export_all

DIR_OFFSET = 0x80


def _build_flx(comment: bytes, entries_data: list[bytes | None]) -> bytes:
    count = len(entries_data)
    dir_size = count * 8
    header = bytearray(DIR_OFFSET)
    header[:0x52] = b"\x1A" * 0x52
    header[0:len(comment)] = comment
    struct.pack_into("<I", header, 0x54, count)
    struct.pack_into("<I", header, 0x58, 1)

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

    file_size = DIR_OFFSET + len(directory) + len(payload)
    struct.pack_into("<I", header, 0x5C, file_size)
    return bytes(header) + bytes(directory) + bytes(payload)


def _sound_name_table(*names: str) -> bytes:
    return b"".join(name.encode("ascii").ljust(8, b"\x00") for name in names)


class U8MusicExportNamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.music_path = os.path.join(self.tmpdir.name, "MUSIC.FLX")
        playlist = b"intro.xmi 1 10 5\r\nbattle.xmi 1 20 5\r\n#\r\n"
        data = _build_flx(b"MUSIC.FLX", [playlist, b"FORMdemo1", b"FORMdemo2"])
        with open(self.music_path, "wb") as f:
            f.write(data)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_music_export_uses_playlist_names(self) -> None:
        outdir = os.path.join(self.tmpdir.name, "midi")
        with patch("titan.u8.cli.XMIDIConverter.convert", return_value=b"MThd"):
            rc = cmd_music_export(SimpleNamespace(file=self.music_path, output=outdir))
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(os.listdir(outdir)), ["0001_intro.mid", "0002_battle.mid"])


class U8SoundExportNamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sound_path = os.path.join(self.tmpdir.name, "SOUND.FLX")
        data = _build_flx(
            b"SOUND.FLX",
            [_sound_name_table("GRUNT7A", "WHOA3A"), b"\x01", b"\x02"],
        )
        with open(self.sound_path, "wb") as f:
            f.write(data)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_sound_export_all_uses_embedded_sfx_names(self) -> None:
        outdir = os.path.join(self.tmpdir.name, "wav")
        with (
            patch(
                "titan.u8.cli.SonarcDecoder.decode_file",
                side_effect=[None, (b"\x00\x01", 22050), (b"\x00\x01", 22050)],
            ),
            patch("titan.u8.cli.SonarcDecoder.pcm_to_wav", return_value=b"RIFF"),
        ):
            rc = cmd_sound_export_all(SimpleNamespace(file=self.sound_path, output=outdir))
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(os.listdir(outdir)), ["0001_GRUNT7A.wav", "0002_WHOA3A.wav"])


class U8ShapeExportNamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_shape_export_uses_bundled_class_name_for_numeric_stem(self) -> None:
        shp_path = os.path.join(self.tmpdir.name, "0068.shp")
        with open(shp_path, "wb") as f:
            f.write(b"dummy")

        outdir = os.path.join(self.tmpdir.name, "png")
        image = Image.new("RGBA", (2, 2), (255, 0, 0, 255))
        fake_shape = type(
            "FakeShape",
            (),
            {
                "frames": [object()],
                "to_pngs": lambda self, pal, transparent=True: [image],
            },
        )()

        with patch("titan.u8.cli.U8Shape.from_file", return_value=fake_shape):
            rc = cmd_shape_export(SimpleNamespace(file=shp_path, palette=None, output=outdir))

        self.assertEqual(rc, 0)
        self.assertEqual(sorted(os.listdir(outdir)), ["0068_DOOR_NS_f0000.png"])

    def test_shape_batch_accepts_u8shapes_flx_and_uses_class_names(self) -> None:
        flx_path = os.path.join(self.tmpdir.name, "U8SHAPES.FLX")
        with open(flx_path, "wb") as f:
            f.write(b"dummy")

        outdir = os.path.join(self.tmpdir.name, "png")
        image = Image.new("RGBA", (2, 2), (0, 255, 0, 255))
        fake_archive = type("FakeArchive", (), {"records": [b"", b"", b"", b"", b"", b"\x01"]})()
        fake_shape = type(
            "FakeShape",
            (),
            {
                "frames": [object()],
                "to_pngs": lambda self, pal, transparent=True: [image],
            },
        )()

        with (
            patch("titan.u8.cli.FlexArchive.from_file", return_value=fake_archive),
            patch("titan.u8.cli.U8Shape.from_data", return_value=fake_shape),
        ):
            rc = cmd_shape_batch(SimpleNamespace(directory=flx_path, palette=None, output=outdir))

        self.assertEqual(rc, 0)
        self.assertEqual(sorted(os.listdir(outdir)), ["0005_FLOATORS_f0000.png"])


if __name__ == "__main__":
    unittest.main()
