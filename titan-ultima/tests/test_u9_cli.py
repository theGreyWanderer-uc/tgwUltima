"""Tests for titan.u9.cli's flx-list/flx-extract/flx-extract-all/typename-dump commands."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
from types import SimpleNamespace

from titan.u9.cli import (
    PALETTE_FILENAME,
    _find_palette,
    cmd_flx_extract,
    cmd_flx_extract_all,
    cmd_flx_list,
    cmd_palette_export,
    cmd_palette_info,
    cmd_sound_extract_pcm,
    cmd_sound_list,
    cmd_texture_export,
    cmd_texture_info,
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
    struct.pack_into("<I", header, 0x54, 2)  # FLX format-version word

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


def _build_u9_palette(colors: list[tuple[int, int, int]]) -> bytes:
    """Build the 256 four-byte RGB+reserved entries used by ankh.pal."""
    return b"".join(bytes((*color, 0)) for color in colors)


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


def _texture_entry() -> bytes:
    """A 2x2 8-bit base image plus a stored 1x1 mip."""
    width = height = 2
    payload = bytes((1, 2, 3, 4, 9))
    frame_header = struct.pack("<2H4I", 0x00D1, 0x6000, width, height, 0, 0)
    row_table = struct.pack("<2I", 28, 30)
    frame_data = frame_header + row_table + payload
    set_header = struct.pack("<4H2I", width, 1, height, 0, 1, 0x00066000)
    directory = struct.pack("<2I", 0x18, len(frame_data))
    return set_header + directory + frame_data


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


class PaletteDiscoveryTests(unittest.TestCase):
    """``ankh.pal`` sits beside the archive, so it is found without being asked for.

    Decoding an 8-bit frame with no palette does not fail -- it silently
    produces a scrambled greyscale image, because the palette is ordered by hue
    rather than by brightness. A whole-game extraction was published with all
    6,597 ``bitmapsh.flx`` entries wrong that way, which is why discovery is
    automatic rather than merely warned about.
    """

    @staticmethod
    def _touch(*paths: str) -> None:
        for path in paths:
            with open(path, "wb") as f:
                f.write(b"x")

    def test_finds_the_palette_beside_the_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "bitmapsh.flx")
            palette = os.path.join(tmp, PALETTE_FILENAME)
            self._touch(archive, palette)
            found, auto = _find_palette(None, archive)
            self.assertEqual(found, palette)
            self.assertTrue(auto)

    def test_match_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "bitmapsh.flx")
            self._touch(archive, os.path.join(tmp, "ANKH.PAL"))
            found, auto = _find_palette(None, archive)
            self.assertIsNotNone(found)
            self.assertTrue(auto)

    def test_explicit_palette_wins_over_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "bitmapsh.flx")
            chosen = os.path.join(tmp, "other.pal")
            self._touch(archive, os.path.join(tmp, PALETTE_FILENAME), chosen)
            found, auto = _find_palette(chosen, archive)
            self.assertEqual(found, chosen)
            self.assertFalse(auto)

    def test_no_palette_beside_the_archive_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "bitmapsh.flx")
            self._touch(archive)
            self.assertEqual(_find_palette(None, archive), (None, False))

    def test_missing_directory_is_not_an_error(self) -> None:
        missing = os.path.join(tempfile.gettempdir(), "no_such_titan_dir", "x.flx")
        self.assertEqual(_find_palette(None, missing), (None, False))

    def test_no_archive_path_returns_none(self) -> None:
        self.assertEqual(_find_palette(None, None), (None, False))


class PaletteCliCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.palette_path = os.path.join(self.tmpdir.name, "ankh.pal")
        colors = [(index, index, index) for index in range(256)]
        colors[254] = colors[247]
        with open(self.palette_path, "wb") as file:
            file.write(_build_u9_palette(colors))

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_palette_info_reports_duplicate_summary(self) -> None:
        result = cmd_palette_info(
            SimpleNamespace(file=self.palette_path, duplicates=True)
        )
        self.assertEqual(result, 0)

    def test_palette_export_writes_swatch_and_text(self) -> None:
        output = os.path.join(self.tmpdir.name, "out")
        result = cmd_palette_export(
            SimpleNamespace(file=self.palette_path, output=output, swatch_size=2)
        )
        self.assertEqual(result, 0)
        self.assertTrue(os.path.isfile(os.path.join(output, "ankh_palette.png")))
        text_path = os.path.join(output, "ankh_palette.txt")
        self.assertTrue(os.path.isfile(text_path))
        with open(text_path, encoding="utf-8") as file:
            text = file.read()
        self.assertIn("254    247  247  247", text)
        self.assertIn("      0      0  #F7F7F7", text)

    def test_palette_commands_reject_bad_input(self) -> None:
        missing = os.path.join(self.tmpdir.name, "missing.pal")
        self.assertEqual(
            cmd_palette_info(SimpleNamespace(file=missing, duplicates=False)),
            1,
        )
        self.assertEqual(
            cmd_palette_export(
                SimpleNamespace(
                    file=self.palette_path,
                    output=self.tmpdir.name,
                    swatch_size=0,
                )
            ),
            1,
        )


class TextureCliCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.archive_path = os.path.join(self.tmpdir.name, "Texture8.14")
        with open(self.archive_path, "wb") as file:
            file.write(_build_flx(b"terrain panels", [_texture_entry()]))

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_texture_info_accepts_terrain_panel_archive(self) -> None:
        result = cmd_texture_info(
            SimpleNamespace(textures=self.archive_path, entry_id=0)
        )
        self.assertEqual(result, 0)

    def test_texture_export_writes_selected_mip(self) -> None:
        output = os.path.join(self.tmpdir.name, "out")
        result = cmd_texture_export(
            SimpleNamespace(
                textures=self.archive_path,
                entry_id=0,
                frame=0,
                mip_level=1,
                palette=None,
                output=output,
            )
        )
        self.assertEqual(result, 0)
        self.assertTrue(
            os.path.isfile(os.path.join(output, "texture_00000_frame_000_mip_01.png"))
        )

    def test_texture_export_rejects_missing_mip(self) -> None:
        result = cmd_texture_export(
            SimpleNamespace(
                textures=self.archive_path,
                entry_id=0,
                frame=0,
                mip_level=2,
                palette=None,
                output=self.tmpdir.name,
            )
        )
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
