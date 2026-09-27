"""Tests for U9 FLX, metadata, sound, palette, and texture CLI commands."""

from __future__ import annotations

import csv
import os
import struct
import tempfile
import unittest
from types import SimpleNamespace

from PIL import Image

from titan.u9.cli import (
    PALETTE_FILENAME,
    _find_palette,
    cmd_flx_extract,
    cmd_flx_extract_all,
    cmd_flx_list,
    cmd_npc_csv,
    cmd_palette_export,
    cmd_palette_info,
    cmd_sound_extract_pcm,
    cmd_sound_association_csv,
    cmd_sound_category_csv,
    cmd_sound_category_list,
    cmd_sound_environment_csv,
    cmd_sound_environment_list,
    cmd_sound_list,
    cmd_sound_template_csv,
    cmd_texture_export,
    cmd_texture_import,
    cmd_texture_info,
    cmd_types_csv,
    cmd_typename_csv,
    cmd_typename_dump,
)

DIR_OFFSET = 0x80
DEFAULT_ICON_ID = 7041


def _build_flx(comment: bytes, entries_data: list[bytes | None]) -> bytes:
    count = len(entries_data)
    dir_size = count * 8
    header = bytearray(DIR_OFFSET)
    header[0 : len(comment)] = comment
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


def _typename_entry(
    name: str | None,
    *,
    readable_text_id: int = 0,
    object_icon_id: int = DEFAULT_ICON_ID,
) -> bytes:
    header = struct.pack("<iH", readable_text_id, object_icon_id)
    if name is None:
        return header
    return header + name.encode("ascii") + b"\x00"


def _sound_category_entry(category_id: int, display_name: str) -> bytes:
    record = bytearray(40)
    record[0] = category_id
    encoded = display_name.encode("ascii")
    record[1 : 1 + len(encoded)] = encoded
    return bytes(record)


def _sound_template_entry(template_id: int, sound_id: int) -> bytes:
    record = bytearray(0x38)
    struct.pack_into("<I", record, 0, template_id)
    record[4:11] = b"Example"
    struct.pack_into("<III", record, 0x28, 1, 360, 360)
    record[0x34:0x36] = bytes([1, 25])
    record += bytes([2]) + b"Movement\x00".ljust(33, b"\x00") + b"\x00\x00"
    record += struct.pack("<I", 1)
    record += b"\x01\x00\x00\x00" + struct.pack("<I", sound_id)
    record += bytes([100, 70, 0, 0, 5, 2, 0, 0])
    return bytes(record)


def _npc_record(name: str) -> bytes:
    record = bytearray(0x13C)
    encoded = name.encode("ascii")
    record[0x04 : 0x04 + len(encoded)] = encoded
    record[0x28:0x2C] = bytes.fromhex("00 64 64 64")
    record[0x124:0x128] = bytes.fromhex("c8 00 00 00")
    return bytes(record)


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


def _texture_entry(frame_count: int = 1) -> bytes:
    """One or more 2x2 8-bit images, each with a stored 1x1 mip."""
    width = height = 2
    set_header = struct.pack("<4H2I", width, 1, height, 0, frame_count, 0x00066000)
    frame_offset = len(set_header) + frame_count * 8
    directory = bytearray()
    frames = bytearray()
    for frame_index in range(frame_count):
        payload = bytes((1, 2, 3, 4, 9))
        frame_header = struct.pack("<2H4I", 0x00D1, 0x6000, width, height, 0, 0)
        row_table = struct.pack("<2I", 28, 30)
        frame_data = frame_header + row_table + payload
        directory += struct.pack("<2I", frame_offset, len(frame_data))
        frames += frame_data
        frame_offset += len(frame_data)
    return set_header + directory + frames


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
        rc = cmd_flx_list(
            SimpleNamespace(file=os.path.join(self.tmpdir.name, "nope.flx"))
        )
        self.assertEqual(rc, 1)

    def test_flx_extract_writes_entry_payload(self) -> None:
        outdir = os.path.join(self.tmpdir.name, "out")
        rc = cmd_flx_extract(
            SimpleNamespace(file=self.flx_path, index=0, output=outdir)
        )
        self.assertEqual(rc, 0)
        out_path = os.path.join(outdir, "test_00000.bin")
        self.assertTrue(os.path.isfile(out_path))
        with open(out_path, "rb") as f:
            self.assertEqual(f.read(), b"HELLO")

    def test_flx_extract_out_of_range_errors(self) -> None:
        rc = cmd_flx_extract(
            SimpleNamespace(file=self.flx_path, index=99, output=self.tmpdir.name)
        )
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
        data = _build_flx(
            b"TYPENAME.FLX",
            [
                _typename_entry(None),
                _typename_entry(
                    "Lord British", readable_text_id=326, object_icon_id=7264
                ),
            ],
        )
        with open(self.flx_path, "wb") as f:
            f.write(data)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_typename_dump_succeeds(self) -> None:
        rc = cmd_typename_dump(SimpleNamespace(file=self.flx_path))
        self.assertEqual(rc, 0)

    def test_typename_dump_missing_file_errors(self) -> None:
        rc = cmd_typename_dump(
            SimpleNamespace(file=os.path.join(self.tmpdir.name, "nope.flx"))
        )
        self.assertEqual(rc, 1)

    def test_typename_csv_exports_all_metadata_fields(self) -> None:
        output = os.path.join(self.tmpdir.name, "typenames.csv")
        rc = cmd_typename_csv(SimpleNamespace(file=self.flx_path, output=output))
        self.assertEqual(rc, 0)
        with open(output, newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["readable_text_id"], "326")
        self.assertEqual(rows[1]["object_icon_id"], "7264")
        self.assertEqual(rows[1]["display_name"], "Lord British")
        self.assertEqual(rows[1]["record_representation"], "six_byte_header")
        self.assertEqual(rows[1]["warnings"], "")
        self.assertEqual(
            len(rows[1]["raw_hex"]),
            len(
                _typename_entry(
                    "Lord British", readable_text_id=326, object_icon_id=7264
                )
            )
            * 2
            + 2,
        )


class TypesDatCsvCliTests(unittest.TestCase):
    @staticmethod
    def _types_data() -> bytes:
        record = struct.Struct("<IHHHBBBBH")
        active = [
            record.pack(0, 0, 0, 0, 0, 0, 0, 0, 0),
            record.pack(0xCDCDCDCD, 1, 1805, 0x0208, 255, 12, 0, 7, 0),
        ]
        filler = record.pack(0, 0, 0, 0, 254, 0, 0, 0, 0)
        return struct.pack("<II", 2, 1) + b"".join(active + [filler] * 8190)

    def test_exports_active_records_with_forensic_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "TYPES.DAT")
            output_path = os.path.join(temp_dir, "types.csv")
            with open(input_path, "wb") as file:
                file.write(self._types_data())

            result = cmd_types_csv(
                SimpleNamespace(
                    file=input_path,
                    output=output_path,
                    typenames=None,
                    all_slots=False,
                )
            )

            self.assertEqual(result, 0)
            with open(output_path, newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["slot_state"], "active")
            self.assertEqual(rows[1]["base_type_id"], "1")
            self.assertEqual(rows[1]["runtime_pointer_state"], "debug_fill")
            self.assertEqual(rows[1]["unmapped_object_flag_bits_hex"], "0x0200")
            self.assertEqual(len(rows[1]["raw_hex"]), 34)

    def test_all_slots_includes_retained_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "TYPES.DAT")
            output_path = os.path.join(temp_dir, "types.csv")
            with open(input_path, "wb") as file:
                file.write(self._types_data())

            result = cmd_types_csv(
                SimpleNamespace(
                    file=input_path,
                    output=output_path,
                    typenames=None,
                    all_slots=True,
                )
            )

            self.assertEqual(result, 0)
            with open(output_path, newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 8192)
            self.assertEqual(rows[2]["slot_state"], "inactive_capacity")


class NpcCsvCliTests(unittest.TestCase):
    def test_exports_signed_level_codes_status_and_raw_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = os.path.join(temp_dir, "NPC.FLX")
            output = os.path.join(temp_dir, "npcs.csv")
            with open(archive, "wb") as file:
                file.write(_build_flx(b"NPC.FLX", [_npc_record("Test NPC")]))

            result = cmd_npc_csv(
                SimpleNamespace(file=archive, output=output, save=False, all=True)
            )

            self.assertEqual(result, 0)
            with open(output, newline="", encoding="utf-8") as file:
                row = next(csv.DictReader(file))
            self.assertEqual(row["might_code"], "1684300800")
            self.assertEqual(row["might_status"], "out_of_range")
            self.assertEqual(row["might_raw_hex"], "0x00646464")
            self.assertEqual(row["unarmed_skill_code"], "200")
            self.assertEqual(row["unarmed_skill_status"], "out_of_range")
            self.assertEqual(row["unarmed_skill_raw_hex"], "0xc8000000")
            self.assertEqual(row["health_status"], "")
            self.assertEqual(row["health_raw_hex"], "0x000000000000")


class SoundCategoryCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.flx_path = os.path.join(self.tmpdir.name, "sfxcat.flx")
        with open(self.flx_path, "wb") as file:
            file.write(
                _build_flx(
                    b"sfxcat.flx",
                    [
                        _sound_category_entry(0, "Attack"),
                        None,
                        _sound_category_entry(2, "Movement"),
                    ],
                )
            )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_sound_category_list_succeeds(self) -> None:
        self.assertEqual(
            cmd_sound_category_list(SimpleNamespace(file=self.flx_path)), 0
        )

    def test_sound_category_csv_exports_complete_records(self) -> None:
        output = os.path.join(self.tmpdir.name, "categories.csv")
        result = cmd_sound_category_csv(
            SimpleNamespace(file=self.flx_path, output=output)
        )
        self.assertEqual(result, 0)
        with open(output, newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["archive_index"], "2")
        self.assertEqual(rows[1]["category_id"], "2")
        self.assertEqual(rows[1]["display_name"], "Movement")
        self.assertEqual(rows[1]["record_representation"], "master_category_record")
        self.assertEqual(rows[1]["warnings"], "")
        self.assertEqual(len(rows[1]["raw_hex"]), 82)


class AcousticPresetCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.flx_path = os.path.join(self.tmpdir.name, "sfxenv.flx")
        name_field = bytearray(64)
        name_field[:15] = b"Standard - Room"
        name_field[16:23] = b"RESIDUE"
        record = struct.pack("<I3f", 2, 0.417, 0.4, 0.666) + bytes(name_field)
        entries: list[bytes | None] = [None, None, record]
        entries.extend([None] * (512 - len(entries)))
        with open(self.flx_path, "wb") as file:
            file.write(_build_flx(b"sfxenv.flx", entries))

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_sound_environment_list_succeeds(self) -> None:
        self.assertEqual(
            cmd_sound_environment_list(SimpleNamespace(file=self.flx_path)), 0
        )

    def test_sound_environment_csv_exports_complete_record(self) -> None:
        output = os.path.join(self.tmpdir.name, "environments.csv")
        result = cmd_sound_environment_csv(
            SimpleNamespace(file=self.flx_path, output=output)
        )
        self.assertEqual(result, 0)
        with open(output, newline="", encoding="utf-8") as file:
            row = next(csv.DictReader(file))
        self.assertEqual(row["archive_index"], "2")
        self.assertEqual(row["display_name"], "Standard - Room")
        self.assertEqual(row["acoustic_profile_code"], "2")
        self.assertEqual(row["acoustic_profile_name"], "Room")
        self.assertEqual(row["standard_preset_status"], "matches_factory_preset")
        self.assertEqual(row["name_residue_hex"], "0x52455349445545" + "00" * 41)
        self.assertEqual(len(row["raw_hex"]), 162)


class SoundAssociationCsvCliTests(unittest.TestCase):
    def test_exports_complete_direct_association_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = os.path.join(temp_dir, "sfxassoc.flx")
            output = os.path.join(temp_dir, "associations.csv")
            entries: list[bytes | None] = [None, struct.pack("<I", 437)]
            entries.extend([None] * (8192 - len(entries)))
            with open(archive, "wb") as file:
                file.write(_build_flx(b"sfxassoc.flx", entries))

            result = cmd_sound_association_csv(
                SimpleNamespace(
                    file=archive,
                    output=output,
                    templates=None,
                    types=None,
                    typenames=None,
                    effective=False,
                )
            )

            self.assertEqual(result, 0)
            with open(output, newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["object_type_id"], "1")
            self.assertEqual(rows[0]["sound_template_id"], "437")
            self.assertEqual(rows[0]["link_source"], "direct")
            self.assertEqual(
                rows[0]["record_representation"], "direct_object_sound_template_link"
            )
            self.assertEqual(rows[0]["raw_hex"], "0xb5010000")


class SoundTemplateCsvCliTests(unittest.TestCase):
    def test_exports_semantic_template_action_and_choice_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            templates_path = os.path.join(temp_dir, "SFXTMPL.FLX")
            categories_path = os.path.join(temp_dir, "sfxcat.flx")
            sounds_path = os.path.join(temp_dir, "sfx.flx")
            output = os.path.join(temp_dir, "templates.csv")

            template_entries: list[bytes | None] = [None, _sound_template_entry(1, 2)]
            template_entries.extend([None] * (8192 - len(template_entries)))
            with open(templates_path, "wb") as file:
                file.write(_build_flx(b"SFXTMPL.FLX", template_entries))
            with open(categories_path, "wb") as file:
                file.write(
                    _build_flx(
                        b"sfxcat.flx",
                        [None, None, _sound_category_entry(2, "Movement")],
                    )
                )
            with open(sounds_path, "wb") as file:
                file.write(
                    _build_flx(
                        b"sfx.flx",
                        [
                            None,
                            None,
                            _sound_entry(2, "step", 22050, 16, 1, 0, b"\x00\x00"),
                        ],
                    )
                )

            result = cmd_sound_template_csv(
                SimpleNamespace(
                    file=templates_path,
                    output=output,
                    categories=categories_path,
                    sounds=sounds_path,
                )
            )

            self.assertEqual(result, 0)
            with open(output, newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["row_kind"], "sound_choice")
            self.assertEqual(row["template_id"], "1")
            self.assertEqual(row["template_name"], "Example")
            self.assertEqual(row["inner_cone_angle_degrees"], "360")
            self.assertEqual(row["category_id"], "2")
            self.assertEqual(row["master_category_name"], "Movement")
            self.assertEqual(row["sound_id"], "2")
            self.assertEqual(row["sound_name"], "step")
            self.assertEqual(row["full_volume_percent"], "100")
            self.assertEqual(row["pitch_variation_percent"], "5")
            self.assertEqual(row["selection_weight"], "2")
            self.assertEqual(row["external_warnings"], "")
            self.assertTrue(row["template_raw_hex"].startswith("0x"))
            self.assertEqual(len(row["choice_raw_hex"]), 34)


class SoundCliCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.flx_path = os.path.join(self.tmpdir.name, "sfx.flx")
        data = _build_flx(
            b"sfx.flx",
            [
                _sound_entry(
                    0, "pcm_one.wav", 22050, 16, 1, 0, struct.pack("<2h", 10, -10)
                ),
                _sound_entry(1, "compressed.umt", 22050, 16, 1, 2, b"\x01\x02\x03\x04"),
            ],
        )
        with open(self.flx_path, "wb") as f:
            f.write(data)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_sound_list_succeeds(self) -> None:
        rc = cmd_sound_list(SimpleNamespace(file=self.flx_path))
        self.assertEqual(rc, 0)

    def test_sound_list_missing_file_errors(self) -> None:
        rc = cmd_sound_list(
            SimpleNamespace(file=os.path.join(self.tmpdir.name, "nope.flx"))
        )
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
            file.write(_build_flx(b"terrain panels", [_texture_entry(3)]))
        colors = [(index, index, index) for index in range(256)]
        colors[254] = colors[247]
        with open(os.path.join(self.tmpdir.name, PALETTE_FILENAME), "wb") as file:
            file.write(_build_u9_palette(colors))

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

    def test_texture_import_keeps_single_image_workflow(self) -> None:
        image_path = os.path.join(self.tmpdir.name, "replacement.png")
        output_path = os.path.join(self.tmpdir.name, "single.flx")
        Image.new("RGBA", (2, 2), (80, 80, 80, 255)).save(image_path)

        result = cmd_texture_import(
            SimpleNamespace(
                textures=self.archive_path,
                entry_id=0,
                image=image_path,
                frames_dir=None,
                frame=1,
                palette=None,
                output=output_path,
            )
        )

        self.assertEqual(result, 0)
        self.assertTrue(os.path.isfile(output_path))

    def test_texture_import_batches_numbered_png_frames(self) -> None:
        frames_dir = os.path.join(self.tmpdir.name, "sourceframes")
        os.makedirs(frames_dir)
        Image.new("RGBA", (2, 2), (20, 20, 20, 255)).save(
            os.path.join(frames_dir, "0.png")
        )
        Image.new("RGBA", (2, 2), (200, 200, 200, 255)).save(
            os.path.join(frames_dir, "2.png")
        )
        output_path = os.path.join(self.tmpdir.name, "batch.flx")

        result = cmd_texture_import(
            SimpleNamespace(
                textures=self.archive_path,
                entry_id=0,
                image=None,
                frames_dir=frames_dir,
                frame=0,
                palette=None,
                output=output_path,
            )
        )

        self.assertEqual(result, 0)
        self.assertTrue(os.path.isfile(output_path))

    def test_texture_import_rejects_nonnumeric_batch_png(self) -> None:
        frames_dir = os.path.join(self.tmpdir.name, "badframes")
        os.makedirs(frames_dir)
        Image.new("RGBA", (2, 2), (20, 20, 20, 255)).save(
            os.path.join(frames_dir, "frame.png")
        )
        output_path = os.path.join(self.tmpdir.name, "should_not_exist.flx")

        result = cmd_texture_import(
            SimpleNamespace(
                textures=self.archive_path,
                entry_id=0,
                image=None,
                frames_dir=frames_dir,
                frame=0,
                palette=None,
                output=output_path,
            )
        )

        self.assertEqual(result, 1)
        self.assertFalse(os.path.exists(output_path))


if __name__ == "__main__":
    unittest.main()
