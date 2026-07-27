"""Tests for titan.u6.cli's command implementations.

Follows this project's established CLI-test convention (see
test_u7_shape_export_cli.py): call the ``cmd_*`` implementation functions
directly with a hand-built ``SimpleNamespace``, bypassing Typer's parsing
layer entirely, against synthetic fixtures on disk -- no real game files.

The gamedir fixture deliberately fills MASKTYPE.VGA/MAPTILES.VGA with a
non-zero constant byte so they fail titan.u6.lzw's LZW magic-number check
and pass straight through unchanged (real MASKTYPE.VGA/MAPTILES.VGA are
LZW-compressed, but titan.u6.tile.U6Tiles.from_directory doesn't care --
it just calls U6Lzw.decompress_file, which handles both cases).
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from types import SimpleNamespace

import struct

from PIL import Image

from titan.u6.actor import OFFSET_TALK_FLAGS
from titan.u6.actor import REQUIRED_SIZE as ACTOR_REQUIRED_SIZE
from titan.u6.cli import (
    cmd_actor_list,
    cmd_book_dump,
    cmd_converse_dump,
    cmd_egg_list,
    cmd_flags_compare,
    cmd_flags_dump,
    cmd_flags_set,
    cmd_font_export,
    cmd_gamestate_dump,
    cmd_lib_extract,
    cmd_lib_extract_all,
    cmd_lib_list,
    cmd_look_dump,
    cmd_lzw_decompress,
    cmd_map_audit_zorder,
    cmd_map_render,
    cmd_object_list,
    cmd_palette_export,
    cmd_schedule_dump,
    cmd_tile_export,
    cmd_tile_export_all,
    cmd_tileflag_dump,
    _parse_region,
    _parse_tile_num,
    _u6_gamedir,
)
from titan.u6.font import FILE_SIZE as FONT_FILE_SIZE
from titan.u6.gamestate import OFFSET_NUM_IN_PARTY, OFFSET_PARTY_NAMES, OFFSET_PARTY_ROSTER
from titan.u6.gamestate import REQUIRED_SIZE as GAMESTATE_REQUIRED_SIZE
from titan.u6.map import DUNGEON_LEVELS, SURFACE_SIDE_SUPERCHUNKS, SURFACE_SUPERCHUNKS
from titan.u6.object import EGG_OBJ_N, pack_position
from titan.u6.tile import NUM_TILES


def _make_synthetic_gamedir(dirpath: str) -> None:
    num_maptiles = 512
    num_objtiles = NUM_TILES - num_maptiles
    with open(os.path.join(dirpath, "MASKTYPE.VGA"), "wb") as f:
        f.write(bytes([0]) * NUM_TILES)  # all "plain" format
    with open(os.path.join(dirpath, "MAPTILES.VGA"), "wb") as f:
        f.write(bytes([5]) * (num_maptiles * 256))
    with open(os.path.join(dirpath, "OBJTILES.VGA"), "wb") as f:
        f.write(bytes([7]) * (num_objtiles * 256))
    with open(os.path.join(dirpath, "U6PAL"), "wb") as f:
        f.write(bytes(1024))
    with open(os.path.join(dirpath, "MAP"), "wb") as f:
        f.write(bytes(32256))  # all-zero -> every chunk ref decodes to chunk 0
    with open(os.path.join(dirpath, "CHUNKS"), "wb") as f:
        f.write(bytes([9]) * 64)  # one chunk, uniformly tile 9
    with open(os.path.join(dirpath, "ANIMDATA"), "wb") as f:
        f.write(bytes(194))  # numtiles=0, no animated placeholders
    with open(os.path.join(dirpath, "BASETILE"), "wb") as f:
        f.write(bytes(2048))  # 1024 words, all BASETILE[n] = 0
    with open(os.path.join(dirpath, "TILEFLAG"), "wb") as f:
        f.write(bytes(7168))  # all-zero -> no tile is double-sized

    # One real object at (1, 1, 0) in surface block 0, then 63 empty
    # surface blocks; 5 empty dungeon blocks followed by an all-zero
    # objlist tail (large enough for U6Actors.parse to accept).
    b0, b1, b2 = pack_position(1, 1, 0)
    record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 3, 0, 1, 0)  # status=on-map, obj_n=3
    block0 = struct.pack("<H", 1) + record
    with open(os.path.join(dirpath, "LZOBJBLK"), "wb") as f:
        f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))
    with open(os.path.join(dirpath, "LZDNGBLK"), "wb") as f:
        f.write(bytes(2) * DUNGEON_LEVELS + bytes(ACTOR_REQUIRED_SIZE))


def _make_synthetic_savegame(dirpath: str, objlist: bytes) -> None:
    """Build a minimal real-save-shaped SAVEGAME/ folder: all-empty OBJBLKxx files + OBJLIST."""
    empty_block = struct.pack("<H", 0)
    for row in range(SURFACE_SIDE_SUPERCHUNKS):
        for col in range(SURFACE_SIDE_SUPERCHUNKS):
            filename = f"OBJBLK{chr(ord('A') + col)}{chr(ord('A') + row)}"
            with open(os.path.join(dirpath, filename), "wb") as f:
                f.write(empty_block)
    for level in range(DUNGEON_LEVELS):
        filename = f"OBJBLK{chr(ord('A') + level)}I"
        with open(os.path.join(dirpath, filename), "wb") as f:
            f.write(empty_block)
    with open(os.path.join(dirpath, "OBJLIST"), "wb") as f:
        f.write(objlist)


class HelperTests(unittest.TestCase):
    def test_parse_tile_num_decimal(self):
        self.assertEqual(_parse_tile_num("42"), 42)

    def test_parse_tile_num_hex(self):
        self.assertEqual(_parse_tile_num("0x1F8"), 0x1F8)

    def test_parse_region_valid(self):
        self.assertEqual(_parse_region("1,2,3,4"), (1, 2, 3, 4))

    def test_parse_region_wrong_arity_exits(self):
        with self.assertRaises(SystemExit):
            _parse_region("1,2,3")

    def test_parse_region_non_integer_exits(self):
        with self.assertRaises(SystemExit):
            _parse_region("a,b,c,d")

    def test_u6_gamedir_prefers_explicit(self):
        self.assertEqual(_u6_gamedir("/explicit/path"), "/explicit/path")

    def test_u6_gamedir_none_without_config_or_explicit(self):
        self.assertIsNone(_u6_gamedir(None))


class LzwCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_file_returns_error(self):
        rc = cmd_lzw_decompress(SimpleNamespace(file="/nope/missing", output=None))
        self.assertEqual(rc, 1)

    def test_decompresses_raw_file_passthrough(self):
        path = os.path.join(self.tmpdir.name, "SOMEFILE")
        with open(path, "wb") as f:
            f.write(b"not lzw data")
        outdir = os.path.join(self.tmpdir.name, "out")
        rc = cmd_lzw_decompress(SimpleNamespace(file=path, output=outdir))
        self.assertEqual(rc, 0)
        with open(os.path.join(outdir, "SOMEFILE.bin"), "rb") as f:
            self.assertEqual(f.read(), b"not lzw data")


class LibraryCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        # 2-item lib_32: entry0 offset=8 flag=0 (uncompressed "AB"), entry1 offset=10 flag=0 ("CDE")
        table = (8).to_bytes(4, "little") + (10).to_bytes(4, "little")
        self.path = os.path.join(self.tmpdir.name, "TESTLIB")
        with open(self.path, "wb") as f:
            f.write(table + b"AB" + b"CDE")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_lib_list_missing_file(self):
        rc = cmd_lib_list(SimpleNamespace(file="/nope", entry_size=4, size_header=False))
        self.assertEqual(rc, 1)

    def test_lib_list_succeeds(self):
        rc = cmd_lib_list(SimpleNamespace(file=self.path, entry_size=4, size_header=False))
        self.assertEqual(rc, 0)

    def test_lib_extract_out_of_range(self):
        rc = cmd_lib_extract(SimpleNamespace(
            file=self.path, item=99, entry_size=4, size_header=False, output=None,
        ))
        self.assertEqual(rc, 1)

    def test_lib_extract_writes_item(self):
        outdir = os.path.join(self.tmpdir.name, "out")
        rc = cmd_lib_extract(SimpleNamespace(
            file=self.path, item=0, entry_size=4, size_header=False, output=outdir,
        ))
        self.assertEqual(rc, 0)
        with open(os.path.join(outdir, "TESTLIB_0000.bin"), "rb") as f:
            self.assertEqual(f.read(), b"AB")

    def test_lib_extract_all_writes_every_item(self):
        outdir = os.path.join(self.tmpdir.name, "out_all")
        rc = cmd_lib_extract_all(SimpleNamespace(
            file=self.path, entry_size=4, size_header=False, output=outdir,
        ))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(outdir, "0000_TESTLIB.bin")))
        self.assertTrue(os.path.isfile(os.path.join(outdir, "0001_TESTLIB.bin")))


class TileflagCliTests(unittest.TestCase):
    def test_missing_file(self):
        rc = cmd_tileflag_dump(SimpleNamespace(file="/nope", output=None))
        self.assertEqual(rc, 1)

    def test_dumps_successfully(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "TILEFLAG")
            with open(path, "wb") as f:
                f.write(bytes(7168))
            outdir = os.path.join(tmp, "out")
            rc = cmd_tileflag_dump(SimpleNamespace(file=path, output=outdir))
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.isfile(os.path.join(outdir, "tileflag_dump.txt")))


class PaletteCliTests(unittest.TestCase):
    def test_missing_file(self):
        rc = cmd_palette_export(SimpleNamespace(file="/nope", output=None))
        self.assertEqual(rc, 1)

    def test_exports_successfully(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "U6PAL")
            with open(path, "wb") as f:
                f.write(bytes(1024))
            outdir = os.path.join(tmp, "out")
            rc = cmd_palette_export(SimpleNamespace(file=path, output=outdir))
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.isfile(os.path.join(outdir, "U6PAL_palette.png")))
            self.assertTrue(os.path.isfile(os.path.join(outdir, "U6PAL_palette.txt")))


class TileExportCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_gamedir_errors(self):
        with self.assertRaises(SystemExit):
            cmd_tile_export(SimpleNamespace(tile_num=0, gamedir=None, palette=None, output=None))

    def test_out_of_range_tile(self):
        rc = cmd_tile_export(SimpleNamespace(
            tile_num=99999, gamedir=self.tmpdir.name, palette=None, output=None,
        ))
        self.assertEqual(rc, 1)

    def test_exports_one_tile(self):
        outdir = os.path.join(self.tmpdir.name, "out")
        rc = cmd_tile_export(SimpleNamespace(
            tile_num=0, gamedir=self.tmpdir.name, palette=None, output=outdir,
        ))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(outdir, "tile_0000.png")))

    def test_exports_all_in_range(self):
        outdir = os.path.join(self.tmpdir.name, "out_all")
        rc = cmd_tile_export_all(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, start=0, end=3, output=outdir,
        ))
        self.assertEqual(rc, 0)
        for i in range(4):
            self.assertTrue(os.path.isfile(os.path.join(outdir, f"tile_{i:04d}.png")))
        self.assertFalse(os.path.isfile(os.path.join(outdir, "tile_0004.png")))


class MapRenderCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _args(self, **overrides):
        base = dict(
            gamedir=self.tmpdir.name, palette=None, region=None, dungeon=None,
            full=False, tick=0, objects=False, output=None,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_missing_gamedir_errors(self):
        with self.assertRaises(SystemExit):
            cmd_map_render(self._args(gamedir=None))

    def test_no_scope_selected_errors(self):
        rc = cmd_map_render(self._args())
        self.assertEqual(rc, 1)

    def test_region_renders_successfully(self):
        outdir = os.path.join(self.tmpdir.name, "out")
        out_path = os.path.join(outdir, "region.png")
        rc = cmd_map_render(self._args(region="0,0,4,4", output=out_path))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(out_path))

    def test_dungeon_renders_successfully(self):
        outdir = os.path.join(self.tmpdir.name, "out")
        out_path = os.path.join(outdir, "dungeon.png")
        rc = cmd_map_render(self._args(dungeon=0, output=out_path))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(out_path))

    def test_invalid_dungeon_level_errors(self):
        rc = cmd_map_render(self._args(dungeon=9))
        self.assertEqual(rc, 1)

    def test_full_renders_successfully(self):
        outdir = os.path.join(self.tmpdir.name, "out")
        out_path = os.path.join(outdir, "full.png")
        rc = cmd_map_render(self._args(full=True, output=out_path))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(out_path))

    def test_objects_overlay_renders_successfully(self):
        outdir = os.path.join(self.tmpdir.name, "out")
        out_path = os.path.join(outdir, "with_objects.png")
        rc = cmd_map_render(self._args(region="0,0,4,4", objects=True, output=out_path))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(out_path))

    def test_objects_missing_lzobjblk_errors(self):
        os.remove(os.path.join(self.tmpdir.name, "LZOBJBLK"))
        rc = cmd_map_render(self._args(region="0,0,4,4", objects=True))
        self.assertEqual(rc, 1)

    def test_objects_missing_tileflag_errors(self):
        os.remove(os.path.join(self.tmpdir.name, "TILEFLAG"))
        rc = cmd_map_render(self._args(region="0,0,4,4", objects=True))
        self.assertEqual(rc, 1)


class MapAuditZorderCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] -> tnum 20 ("apple"), BASETILE[11] -> tnum 21 ("banana"):
        # both plain/opaque MAPTILES-range tiles (MASKTYPE all-zero "plain"
        # format, TILEFLAG all-zero -> neither background/foreground/
        # supporting, so both land in the same "plain" layer tier).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 20)
        struct.pack_into("<H", basetile, 11 * 2, 21)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))
        with open(os.path.join(self.tmpdir.name, "LOOK.LZD"), "wb") as f:
            f.write(struct.pack("<H", 20) + b"apple\x00" + struct.pack("<H", 21) + b"banana\x00")

        # Two distinct objects (obj_n=10, obj_n=11) at the identical position
        # (5,5,0) -- a genuine same-tier tie, replacing the base fixture's
        # single obj_n=3 object.
        rec_a = struct.pack("<BBBBBBBB", 0x00, *pack_position(5, 5, 0), 10, 0, 1, 0)
        rec_b = struct.pack("<BBBBBBBB", 0x00, *pack_position(5, 5, 0), 11, 0, 1, 0)
        block0 = struct.pack("<H", 2) + rec_a + rec_b
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def _args(self, **overrides):
        base = dict(
            gamedir=self.tmpdir.name, min_winner_opacity=0.60, min_loser_opacity=0.10,
            limit=200, dungeons=False,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_missing_gamedir_errors(self):
        with self.assertRaises(SystemExit):
            cmd_map_audit_zorder(self._args(gamedir=None))

    def test_missing_look_lzd_errors(self):
        os.remove(os.path.join(self.tmpdir.name, "LOOK.LZD"))
        rc = cmd_map_audit_zorder(self._args())
        self.assertEqual(rc, 1)

    def test_detects_the_seeded_tie(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_map_audit_zorder(self._args())
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("total true-tie candidates: 1", output)
        self.assertIn("apple", output)
        self.assertIn("banana", output)

    def test_dungeons_flag_does_not_crash(self):
        rc = cmd_map_audit_zorder(self._args(dungeons=True))
        self.assertEqual(rc, 0)


class DoubleSizeObjectRenderTests(unittest.TestCase):
    """A double-sized object's extra cell(s) must actually be composited (see titan.u6.tileflag)."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 600 -> an OBJTILES-range tile (num_maptiles=512 in
        # the synthetic fixture), so the object renders with the OBJTILES
        # fill byte (7), not the MAPTILES fill byte (5).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 600)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        # Tile 600's TileFlag byte (TILEFLAG offset 0x800 + 600): both
        # double bits set, so its footprint is a 2x2 block.
        tileflag_path = os.path.join(self.tmpdir.name, "TILEFLAG")
        with open(tileflag_path, "rb") as f:
            tileflag = bytearray(f.read())
        tileflag[0x800 + 600] = 0xC0
        with open(tileflag_path, "wb") as f:
            f.write(bytes(tileflag))

        # Palette: index 7 (OBJTILES fill) -> bright red; index 5 (MAPTILES
        # fill) stays black, so object-covered pixels are visibly distinct
        # from terrain-only pixels.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # One on-map object at (10, 10, 0): obj_n=10 -> tile 600.
        b0, b1, b2 = pack_position(10, 10, 0)
        record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        block0 = struct.pack("<H", 1) + record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_extra_cell_is_composited(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        red = (255, 0, 0)
        black = (0, 0, 0)
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5) within it.
        self.assertEqual(img.getpixel((5 * 16, 5 * 16)), red)  # anchor cell
        self.assertEqual(img.getpixel((4 * 16, 5 * 16)), red)  # is_double_h: cell to the left
        self.assertEqual(img.getpixel((5 * 16, 4 * 16)), red)  # is_double_v: cell above
        self.assertEqual(img.getpixel((4 * 16, 4 * 16)), red)  # both: top-left cell
        self.assertEqual(img.getpixel((3 * 16, 5 * 16)), black)  # untouched terrain, sanity check


class OverlappingObjectForegroundOrderTests(unittest.TestCase):
    """
    Two objects placed at the same coordinate (e.g. a canopy bed's curtain
    frame stacked on its bed frame) must resolve their overlap by TILEFLAG's
    is_foreground ("toptile") bit, not by which one happens to come later in
    LZOBJBLK's file order. Confirmed against a real in-game screenshot: the
    curtain (foreground) drapes over the bed, not the reverse.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 600 (foreground, "curtain"), BASETILE[11] = 601 (not, "bed").
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 600)
        struct.pack_into("<H", basetile, 11 * 2, 601)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        # Tile 600: is_foreground (0x10). Tile 601: no flags at all.
        tileflag_path = os.path.join(self.tmpdir.name, "TILEFLAG")
        with open(tileflag_path, "rb") as f:
            tileflag = bytearray(f.read())
        tileflag[0x800 + 600] = 0x10
        tileflag[0x800 + 601] = 0x00
        with open(tileflag_path, "wb") as f:
            f.write(bytes(tileflag))

        # Give tile 601 its own distinct pixel fill (8), separate from the
        # fixture's uniform OBJTILES fill (7) that tile 600 keeps.
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        tile_601_offset = (601 - 512) * 256
        objtiles[tile_601_offset:tile_601_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (tile 600, foreground/"curtain") -> red; index 8
        # (tile 601, not foreground/"bed") -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both objects on-map at the identical coordinate (10, 10, 0). The
        # foreground "curtain" (obj_n=10) is written FIRST -- a plain
        # file-order composite would let the "bed" (obj_n=11), written
        # second, paint over it and win instead.
        b0, b1, b2 = pack_position(10, 10, 0)
        fg_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        bg_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 11, 0, 1, 0)
        block0 = struct.pack("<H", 2) + fg_record + bg_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_foreground_object_wins_regardless_of_file_order(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5) within it.
        self.assertEqual(img.getpixel((5 * 16, 5 * 16)), (255, 0, 0))


class SupportingObjectLayerOrderTests(unittest.TestCase):
    """
    An item resting on a supporting object (e.g. a knife on a table) must
    render on top of it, not the reverse -- found from a real render where
    tools/tableware placed on a table (TILEFLAG's is_supporting, "other
    objects can be placed on top of this one") were hidden underneath it
    because the table happened to come later in LZOBJBLK's file order.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 600 ("knife"), BASETILE[11] = 601 (is_supporting, "table").
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 600)
        struct.pack_into("<H", basetile, 11 * 2, 601)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        # Tile 600: no flags at all. Tile 601: is_supporting (extra byte 0x02).
        tileflag_path = os.path.join(self.tmpdir.name, "TILEFLAG")
        with open(tileflag_path, "rb") as f:
            tileflag = bytearray(f.read())
        tileflag[0x1400 + 601] = 0x02
        with open(tileflag_path, "wb") as f:
            f.write(bytes(tileflag))

        # Give tile 601 its own distinct pixel fill (8), separate from the
        # fixture's uniform OBJTILES fill (7) that tile 600 keeps.
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        tile_601_offset = (601 - 512) * 256
        objtiles[tile_601_offset:tile_601_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (tile 600, "knife") -> red; index 8 (tile 601,
        # "table") -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both objects on-map at the identical coordinate (10, 10, 0). The
        # supporting "table" (obj_n=11) is written LAST -- a plain
        # file-order composite would let it paint over the "knife" (obj_n=10)
        # and hide it instead.
        b0, b1, b2 = pack_position(10, 10, 0)
        item_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        table_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 11, 0, 1, 0)
        block0 = struct.pack("<H", 2) + table_record + item_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_item_on_table_wins_regardless_of_file_order(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5) within it.
        self.assertEqual(img.getpixel((5 * 16, 5 * 16)), (255, 0, 0))


class AnchorBeatsOverflowCellTests(unittest.TestCase):
    """
    An object's own anchor cell must win over a *different* object's
    overflow/secondary cell landing on the same spot, even if that overflow
    cell is is_foreground -- found from a real render where a hammer
    (anchored on its own tile) was hidden under a forge hood's overhanging
    secondary cell, which is flagged is_foreground for an unrelated reason
    (the hood's own top surface). Foreground only settles ties when the
    cell in question isn't outclassed by someone's actual anchor placement.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 600 ("hammer"), BASETILE[11] = 650 ("hood", double_h).
        # The hood's is_double_h footprint pulls tile 649 for its secondary
        # (dx=-1) cell, landing on the hammer's own anchor tile (10, 10).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 600)
        struct.pack_into("<H", basetile, 11 * 2, 650)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        # Tile 600 ("hammer"): no flags. Tile 650 (hood anchor): is_double_h
        # + is_foreground. Tile 649 (hood's secondary/overflow cell): also
        # is_foreground, same as the real hood's every cell.
        tileflag_path = os.path.join(self.tmpdir.name, "TILEFLAG")
        with open(tileflag_path, "rb") as f:
            tileflag = bytearray(f.read())
        tileflag[0x800 + 650] = 0x90  # is_double_h (0x80) | is_foreground (0x10)
        tileflag[0x800 + 649] = 0x10  # is_foreground
        with open(tileflag_path, "wb") as f:
            f.write(bytes(tileflag))

        # Give tile 649 (the overflow cell) its own distinct pixel fill (8),
        # separate from the fixture's uniform OBJTILES fill (7) that the
        # hammer's tile 600 keeps.
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        tile_649_offset = (649 - 512) * 256
        objtiles[tile_649_offset:tile_649_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (tile 600, "hammer") -> red; index 8 (tile 649,
        # hood's overflow cell) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Hammer on-map at (10, 10, 0); hood on-map at (11, 10, 0), whose
        # overflow cell lands on the hammer's tile. The hammer is written
        # FIRST -- a plain file-order composite would let the hood's later
        # overflow cell paint over it and hide it instead.
        hb0, hb1, hb2 = pack_position(10, 10, 0)
        hood_b0, hood_b1, hood_b2 = pack_position(11, 10, 0)
        hammer_record = struct.pack("<BBBBBBBB", 0x00, hb0, hb1, hb2, 10, 0, 1, 0)
        hood_record = struct.pack("<BBBBBBBB", 0x00, hood_b0, hood_b1, hood_b2, 11, 0, 1, 0)
        block0 = struct.pack("<H", 2) + hammer_record + hood_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_anchor_wins_over_foreign_overflow_cell(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5) within it.
        self.assertEqual(img.getpixel((5 * 16, 5 * 16)), (255, 0, 0))


class OverflowCellsPreserveForegroundOrderTests(unittest.TestCase):
    """
    Two objects' overflow cells landing on the same spot must still resolve
    by TILEFLAG's own is_foreground/is_supporting ranking *among
    themselves*, even when a third object's anchor also lands there and
    wins overall -- found from a real render where a forge hood's overflow
    cell (is_foreground) is supposed to stay visually above the fire's
    overflow cell beneath it, but an earlier version of the fix collapsed
    every non-anchor cell to one flat "loses to anchor" tier, letting file
    order decide hood vs. fire and sometimes drawing the fire on top.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 600 ("hammer", mostly transparent, opaque only at
        # its top-left pixel). BASETILE[11] = 650 ("hood", double_h, whose
        # overflow cell is tile 649). BASETILE[12] = 700 ("fire", double_h,
        # anchored at the *same* spot as the hood, whose overflow cell is
        # tile 699) -- both overflow cells land on the hammer's tile.
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 600)
        struct.pack_into("<H", basetile, 11 * 2, 650)
        struct.pack_into("<H", basetile, 12 * 2, 700)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        tileflag_path = os.path.join(self.tmpdir.name, "TILEFLAG")
        with open(tileflag_path, "rb") as f:
            tileflag = bytearray(f.read())
        tileflag[0x800 + 650] = 0x80  # hood anchor: is_double_h
        tileflag[0x800 + 649] = 0x10  # hood overflow cell: is_foreground
        tileflag[0x800 + 700] = 0x80  # fire anchor: is_double_h
        tileflag[0x800 + 699] = 0x00  # fire overflow cell: plain
        with open(tileflag_path, "wb") as f:
            f.write(bytes(tileflag))

        # Tile 600 ("hammer"): fully transparent (0xFF) except one opaque
        # pixel at (0, 0), matching the real hammer sprite's mostly-empty
        # background. Tile 649 (hood overflow): solid green. Tile 699 (fire
        # overflow): solid blue.
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        hammer_offset = (600 - 512) * 256
        objtiles[hammer_offset:hammer_offset + 256] = bytes([0xFF]) * 256
        objtiles[hammer_offset] = 9  # top-left pixel only
        hood_overflow_offset = (649 - 512) * 256
        objtiles[hood_overflow_offset:hood_overflow_offset + 256] = bytes([7]) * 256
        fire_overflow_offset = (699 - 512) * 256
        objtiles[fire_overflow_offset:fire_overflow_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (hood overflow) -> green; index 8 (fire
        # overflow) -> blue; index 9 (hammer's one opaque pixel) -> yellow.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([0, 63, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        pal[9 * 3:9 * 3 + 3] = bytes([63, 63, 0])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Hammer at (10, 10, 0); hood and fire both anchored at (11, 10, 0)
        # -- matching the real forge, where the hood and fire are two
        # separate double-sized objects sharing one anchor coordinate.
        hb0, hb1, hb2 = pack_position(10, 10, 0)
        shared_b0, shared_b1, shared_b2 = pack_position(11, 10, 0)
        hammer_record = struct.pack("<BBBBBBBB", 0x00, hb0, hb1, hb2, 10, 0, 1, 0)
        hood_record = struct.pack("<BBBBBBBB", 0x00, shared_b0, shared_b1, shared_b2, 11, 0, 1, 0)
        fire_record = struct.pack("<BBBBBBBB", 0x00, shared_b0, shared_b1, shared_b2, 12, 0, 1, 0)
        block0 = struct.pack("<H", 3) + hammer_record + hood_record + fire_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_hood_overflow_still_beats_fire_overflow_under_hammer(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (255, 255, 0))  # hammer's own opaque pixel wins
        self.assertEqual(img.getpixel((88, 88)), (0, 255, 0))  # hammer transparent here: hood (green), not fire (blue)


class WarmObjectYieldsToAnchoredItemTests(unittest.TestCase):
    """
    A heat/light source (is_warm, e.g. a forge's fire) anchored at the same
    coordinate as an unrelated item (e.g. a pair of pliers set down next to
    it) must render underneath that item, not over it -- found from two
    real forges where the fire and the pliers are anchored at the
    *identical* spot; with neither flagged supporting/foreground, both fell
    into the same plain tier, and the fire (92% opaque in the real data)
    happened to win the file-order tiebreak and completely hid the pliers
    (21% opaque) underneath it.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 600 ("fire", is_warm, fills its whole tile).
        # BASETILE[11] = 601 ("pliers", plain, mostly transparent with one
        # opaque pixel at its top-left corner).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 600)
        struct.pack_into("<H", basetile, 11 * 2, 601)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        tileflag_path = os.path.join(self.tmpdir.name, "TILEFLAG")
        with open(tileflag_path, "rb") as f:
            tileflag = bytearray(f.read())
        tileflag[0x1400 + 600] = 0x01  # fire: is_warm
        with open(tileflag_path, "wb") as f:
            f.write(bytes(tileflag))

        # Tile 600 ("fire"): solid fill (7). Tile 601 ("pliers"): fully
        # transparent (0xFF) except one opaque pixel (8) at (0, 0).
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        fire_offset = (600 - 512) * 256
        objtiles[fire_offset:fire_offset + 256] = bytes([7]) * 256
        pliers_offset = (601 - 512) * 256
        objtiles[pliers_offset:pliers_offset + 256] = bytes([0xFF]) * 256
        objtiles[pliers_offset] = 8
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (fire) -> blue; index 8 (pliers) -> red.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([0, 0, 63])
        pal[8 * 3:8 * 3 + 3] = bytes([63, 0, 0])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both on-map at the identical coordinate (10, 10, 0). Pliers
        # written FIRST, fire written LAST -- a plain file-order composite
        # would let the fire paint over the pliers and hide it.
        b0, b1, b2 = pack_position(10, 10, 0)
        pliers_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 11, 0, 1, 0)
        fire_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        block0 = struct.pack("<H", 2) + pliers_record + fire_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_pliers_stay_visible_over_the_fire(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (255, 0, 0))  # pliers' opaque pixel wins over the fire
        self.assertEqual(img.getpixel((88, 88)), (0, 0, 255))  # pliers transparent here: the fire still shows through


class BackgroundAnchorYieldsToForeignOverflowCellTests(unittest.TestCase):
    """
    An is_background anchor cell (a rug's individually-anchored floor tile)
    must not out-rank a *different* object's is_foreground overflow cell
    landing on the same spot, even though rule 1 normally lets any anchor
    beat a foreign overflow cell -- found from a real "big bed" whose
    is_foreground curtain-fabric overflow cells were being completely
    swallowed by an underlying carpet's individually-anchored, is_background
    fill tiles, because the carpet's anchor status alone was winning
    regardless of either side's flags.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 650 ("bed", double_h). Its is_double_h footprint
        # pulls tile 649 for its secondary (dx=-1) cell, landing on the
        # carpet's own anchor tile (10, 10). BASETILE[11] = 700 ("carpet",
        # plain, is_background, anchored at (10, 10) directly).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 650)
        struct.pack_into("<H", basetile, 11 * 2, 700)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        tileflag_path = os.path.join(self.tmpdir.name, "TILEFLAG")
        with open(tileflag_path, "rb") as f:
            tileflag = bytearray(f.read())
        tileflag[0x800 + 650] = 0x80  # bed anchor: is_double_h
        tileflag[0x800 + 649] = 0x10  # bed overflow cell: is_foreground
        tileflag[0x1400 + 700] = 0x20  # carpet: is_background
        with open(tileflag_path, "wb") as f:
            f.write(bytes(tileflag))

        # Tile 649 (bed overflow, "fabric"): solid fill (7). Tile 700
        # (carpet): solid fill (8).
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        fabric_offset = (649 - 512) * 256
        objtiles[fabric_offset:fabric_offset + 256] = bytes([7]) * 256
        carpet_offset = (700 - 512) * 256
        objtiles[carpet_offset:carpet_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (bed fabric) -> red; index 8 (carpet) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Carpet on-map at (10, 10, 0); bed on-map at (11, 10, 0), whose
        # overflow cell lands on the carpet's own anchor tile.
        carpet_b0, carpet_b1, carpet_b2 = pack_position(10, 10, 0)
        bed_b0, bed_b1, bed_b2 = pack_position(11, 10, 0)
        carpet_record = struct.pack("<BBBBBBBB", 0x00, carpet_b0, carpet_b1, carpet_b2, 11, 0, 1, 0)
        bed_record = struct.pack("<BBBBBBBB", 0x00, bed_b0, bed_b1, bed_b2, 10, 0, 1, 0)
        block0 = struct.pack("<H", 2) + carpet_record + bed_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_bed_fabric_stays_visible_over_the_carpet(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (255, 0, 0))  # bed fabric wins over the carpet's anchor


class CarpetObjTypeIsAlwaysBackgroundTests(unittest.TestCase):
    """
    Every carpet (obj_n=303) frame must be treated as background, even when
    that specific frame's own TILEFLAG byte isn't flagged is_background --
    found from a real carpet where only 2 of its 18 frames (the
    heavily-repeated fill piece) carry the flag; the many border/corner
    frames don't, even though they're the same floor-covering object. A
    table+candle pair anchored on one of those unflagged corner frames was
    still getting covered by the carpet underneath it.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 601 ("candle", plain). BASETILE[303] = 750 ("carpet
        # corner", deliberately left with NO TILEFLAG bits set at all --
        # only obj_n identifies it as carpet).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 601)
        struct.pack_into("<H", basetile, 303 * 2, 750)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        # Tile 601 ("candle"): solid fill (7). Tile 750 ("carpet corner"):
        # solid fill (8).
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        candle_offset = (601 - 512) * 256
        objtiles[candle_offset:candle_offset + 256] = bytes([7]) * 256
        carpet_offset = (750 - 512) * 256
        objtiles[carpet_offset:carpet_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (candle) -> red; index 8 (carpet) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both on-map at the identical coordinate (10, 10, 0). Candle
        # written FIRST, carpet (obj_n=303) written LAST -- a plain
        # file-order composite would let the carpet paint over the candle
        # and hide it, same as an unflagged corner frame did for real.
        b0, b1, b2 = pack_position(10, 10, 0)
        candle_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        # obj_n=303 split across obj_n_lo (0x2F) and obj_n_hi's low 2 bits (0x01).
        carpet_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 0x2F, 0x01, 1, 0)
        block0 = struct.pack("<H", 2) + candle_record + carpet_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_candle_stays_visible_over_unflagged_carpet_frame(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (255, 0, 0))  # candle wins over the unflagged carpet frame


class AnimatedPlaceholderObjectCellTests(unittest.TestCase):
    """
    A placed object's cell can itself be an ANIMDATA placeholder (a
    drawbridge crank/chain, or a clock's second frame) -- the same
    substitution mechanism already applied to terrain must also apply to
    object cells. Found from a crank and chain that rendered as fully
    transparent, because their tile numbers are literal 100%-transparent
    ANIMDATA placeholders whose real content lives at a different,
    tick-selected tile that the --objects overlay never looked up.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 600 ("crank"): a placeholder tile with no pixel
        # content of its own. ANIMDATA maps placeholder 600 -> real content
        # at tile 601, unconditionally (and_mask=0 -> always frame 0).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 600)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        n = 0x20  # ANIMDATA_MAX_ENTRIES
        tile_to_animate = [600] + [0] * (n - 1)
        first_anim_frame = [601] + [0] * (n - 1)
        and_masks = [0] * n
        shift_values = [0] * n
        animdata = (
            struct.pack("<H", 1)
            + struct.pack(f"<{n}H", *tile_to_animate)
            + struct.pack(f"<{n}H", *first_anim_frame)
            + struct.pack(f"<{n}B", *and_masks)
            + struct.pack(f"<{n}B", *shift_values)
        )
        with open(os.path.join(self.tmpdir.name, "ANIMDATA"), "wb") as f:
            f.write(animdata)

        # Tile 600 (placeholder): fully transparent. Tile 601 (its real
        # animated content): solid fill (7) -> red.
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        placeholder_offset = (600 - 512) * 256
        objtiles[placeholder_offset:placeholder_offset + 256] = bytes([0xFF]) * 256
        real_offset = (601 - 512) * 256
        objtiles[real_offset:real_offset + 256] = bytes([7]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        b0, b1, b2 = pack_position(10, 10, 0)
        record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        block0 = struct.pack("<H", 1) + record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_placeholder_object_cell_resolves_to_its_real_frame(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (255, 0, 0))  # resolved to tile 601, not left blank


class MisflaggedCookfireTileTests(unittest.TestCase):
    """
    Tiles 1132-1133 are one specific cookfire orientation that LOOK.LZD
    names identically to its sibling orientation (which IS flagged
    is_foreground), but TILEFLAG omits the flag on this pair -- a one-off
    data omission, not a pattern covering the whole object (its own "logs"
    frame, same obj_n, correctly isn't foreground). Found from a cookfire
    that rendered underneath the logs it should appear to burn on top of.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 1132 ("cookfire", deliberately left unflagged, like
        # the real data). BASETILE[11] = 600 ("logs", plain).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 1132)
        struct.pack_into("<H", basetile, 11 * 2, 600)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        cookfire_offset = (1132 - 512) * 256
        objtiles[cookfire_offset:cookfire_offset + 256] = bytes([7]) * 256
        logs_offset = (600 - 512) * 256
        objtiles[logs_offset:logs_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (cookfire) -> red; index 8 (logs) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both on-map at the identical coordinate (10, 10, 0). Cookfire
        # written FIRST, logs written LAST -- a plain file-order composite
        # would let the logs paint over the cookfire and hide it.
        b0, b1, b2 = pack_position(10, 10, 0)
        cookfire_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        logs_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 11, 0, 1, 0)
        block0 = struct.pack("<H", 2) + cookfire_record + logs_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_cookfire_stays_visible_over_the_logs(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (255, 0, 0))  # cookfire wins over the logs


class MisflaggedForegroundGroundClutterWinnerTests(unittest.TestCase):
    """
    Ground clutter found in a dungeon loot pile, none of it flagged
    anything at all in TILEFLAG, so ties there were decided by file-order
    coincidence. A first attempt demoted the *losing* side (pile of bones,
    dead gargoyle, armor) to background/tier 0, but that regressed two
    other confirmed cases -- a leather armor piece hidden under a table,
    and a pile of bones hidden under an altar's overflow cell -- since a
    table/altar's own is_supporting tier is *also* 0, so the demoted loser
    stopped being able to win against supporting furniture it should
    still show on top of. Promoting the specific *winning* tile to
    foreground instead avoids that: real tile numbers are used here (not
    synthetic placeholders) since the fix is keyed to exact tile numbers,
    not obj_n.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 1262 (a real "dead body" tile, promoted to
        # foreground). BASETILE[11] = 1271 (the real "pile of bones" tile,
        # left plain).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 1262)
        struct.pack_into("<H", basetile, 11 * 2, 1271)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        # Tile 1262 ("dead body"): solid fill (7). Tile 1271 ("pile of
        # bones"): solid fill (8).
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        body_offset = (1262 - 512) * 256
        objtiles[body_offset:body_offset + 256] = bytes([7]) * 256
        bones_offset = (1271 - 512) * 256
        objtiles[bones_offset:bones_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (dead body) -> red; index 8 (pile of bones) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both on-map at the identical coordinate (10, 10, 0). Dead body
        # written FIRST, pile of bones written LAST -- a plain file-order
        # composite would let the bones paint over the body and hide it.
        b0, b1, b2 = pack_position(10, 10, 0)
        body_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        bones_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 11, 0, 1, 0)
        block0 = struct.pack("<H", 2) + body_record + bones_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_dead_body_stays_visible_over_the_bones(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (255, 0, 0))  # dead body wins over the bones


class MisflaggedForegroundUtensilOverBloodTests(unittest.TestCase):
    """
    A butcher-room cleaver/knife (obj_n=113/114, tiles 637-639) and blood
    splatter (obj_n=338, tiles 1259-1261) are both unflagged in TILEFLAG,
    so they tie at the plain tier and file order decides -- confirmed via
    a real screenshot crop showing blood pixels bleeding onto the
    cleaver's blade. Blood is meant to show on tables and on carcass
    parts, but not on top of hand tools/utensils, so the utensil tile is
    the one promoted to foreground (not blood demoted, per the
    promote-the-winner lesson from the ground-clutter regression).
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 1259 (the real "blood" tile, plain). BASETILE[11]
        # = 637 (the real "cleaver" tile, promoted to foreground).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 1259)
        struct.pack_into("<H", basetile, 11 * 2, 637)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        # Tile 1259 ("blood"): solid fill (7). Tile 637 ("cleaver"): solid
        # fill (8).
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        blood_offset = (1259 - 512) * 256
        objtiles[blood_offset:blood_offset + 256] = bytes([7]) * 256
        cleaver_offset = (637 - 512) * 256
        objtiles[cleaver_offset:cleaver_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (blood) -> red; index 8 (cleaver) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both on-map at the identical coordinate (10, 10, 0). Blood
        # written LAST -- a plain file-order composite would let it paint
        # over the cleaver and hide it.
        b0, b1, b2 = pack_position(10, 10, 0)
        cleaver_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 11, 0, 1, 0)
        blood_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        block0 = struct.pack("<H", 2) + cleaver_record + blood_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_cleaver_stays_visible_over_the_blood(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (0, 0, 255))  # cleaver (foreground) wins over blood (plain)


class MisflaggedForegroundBowOverMapTests(unittest.TestCase):
    """
    A dungeon2 loot pile's "magic bow" (tile 565) and "part of a map"
    (tile 1757) share an exact coordinate and are both unflagged in
    TILEFLAG, so they tie at the plain tier -- confirmed by rendering the
    full dungeon 2 map at the reported coordinates (149, 5) and finding
    the map fragment's own tile winning the coin flip, completely hiding
    the bow the user was searching for underneath it.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 1757 (the real "part of a map" tile, plain).
        # BASETILE[11] = 565 (the real "magic bow" tile, promoted to
        # foreground).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 1757)
        struct.pack_into("<H", basetile, 11 * 2, 565)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        # Tile 1757 ("part of a map"): solid fill (7). Tile 565 ("magic
        # bow"): solid fill (8).
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        map_offset = (1757 - 512) * 256
        objtiles[map_offset:map_offset + 256] = bytes([7]) * 256
        bow_offset = (565 - 512) * 256
        objtiles[bow_offset:bow_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (map) -> red; index 8 (bow) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both on-map at the identical coordinate (10, 10, 0). Bow
        # written FIRST, map written LAST -- a plain file-order composite
        # would let the map paint over the bow and hide it.
        b0, b1, b2 = pack_position(10, 10, 0)
        bow_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 11, 0, 1, 0)
        map_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        block0 = struct.pack("<H", 2) + bow_record + map_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_bow_stays_visible_over_the_map(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (0, 0, 255))  # bow (foreground) wins over the map (plain)


class SignNorthLosesToPostOnlyAtDoublePlaqueCoordsTests(unittest.TestCase):
    """
    Sign plaque tile 1243 ("north") appears at 11 real-map coordinates; at
    9 of them it's the only plaque on its post and must beat the post
    like any other plaque (obj_n=332 frame 3 has no TILEFLAG bits set, so
    without an explicit rule it ties the post -- but its *actual* LZOBJBLK
    seq happens to be higher than the post's at all 11 spots, so left
    alone it already wins everywhere). At exactly 2 of those coordinates
    (294,407 and 284,410, real-world bones_altar-room signposts) it's
    paired with a second, winning plaque ("south", tile 1241, promoted to
    foreground) sharing the same post: confirmed against a real
    screenshot that only one plank should show there, with the post
    visible in the gaps, not two side-by-side planks. A global tile-based
    demotion of 1243 would fix those 2 but break the other 9, so the fix
    is a (world_x, world_y) coordinate override
    (SIGN_NORTH_LOSES_TO_POST_AT) applied only at those exact spots.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 1246 (signpost, plain). BASETILE[11] = 1243 ("north" plaque, plain).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 1246)
        struct.pack_into("<H", basetile, 11 * 2, 1243)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        post_offset = (1246 - 512) * 256
        objtiles[post_offset:post_offset + 256] = bytes([7]) * 256
        sign_offset = (1243 - 512) * 256
        objtiles[sign_offset:sign_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (post) -> red; index 8 (north plaque) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Post written FIRST, plaque written LAST at BOTH world coordinates -- matching
        # tile 1243's real, verified higher seq than the post's at every real placement.
        b0, b1, b2 = pack_position(294, 407, 0)
        post_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        sign_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 11, 0, 1, 0)
        c0, c1, c2 = pack_position(50, 50, 0)
        post_record2 = struct.pack("<BBBBBBBB", 0x00, c0, c1, c2, 10, 0, 1, 0)
        sign_record2 = struct.pack("<BBBBBBBB", 0x00, c0, c1, c2, 11, 0, 1, 0)
        block0 = struct.pack("<H", 4) + post_record + sign_record + post_record2 + sign_record2
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_north_plaque_loses_to_post_at_the_real_double_plaque_coordinate(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="290,403,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region (290,403,10,10) -> world (294,407) is pixel-tile (4,4), origin (64, 64).
        self.assertEqual(img.getpixel((64, 64)), (255, 0, 0))  # post wins over the north plaque

    def test_north_plaque_still_beats_post_at_an_unrelated_coordinate(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="45,45,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region (45,45,10,10) -> world (50,50) is pixel-tile (5,5), origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (0, 0, 255))  # north plaque wins over the post here


class MisflaggedForegroundSignSouthOverNorthTests(unittest.TestCase):
    """
    A directional-sign puzzle room has two sign coordinates (both on the
    bones_altar room's east/west signpost) where sign frame 1241
    ("south"-facing) and 1243 ("north"-facing) share the exact same tile,
    both unflagged in TILEFLAG, tying at the plain tier. Confirmed against
    a real screenshot: the north frame was winning the coin flip at both
    coordinates, but south is correct. These are the only 2 coordinates
    on the whole map (surface + all 5 dungeons) where 1241/1243 tie, so
    promoting 1241 is a safe global fix.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 1243 (the real "north" sign tile, plain).
        # BASETILE[11] = 1241 (the real "south" sign tile, promoted to
        # foreground).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 1243)
        struct.pack_into("<H", basetile, 11 * 2, 1241)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        # Tile 1243 ("north"): solid fill (7). Tile 1241 ("south"): solid
        # fill (8).
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        north_offset = (1243 - 512) * 256
        objtiles[north_offset:north_offset + 256] = bytes([7]) * 256
        south_offset = (1241 - 512) * 256
        objtiles[south_offset:south_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (north) -> red; index 8 (south) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both on-map at the identical coordinate (10, 10, 0). North
        # written LAST -- a plain file-order composite would let it paint
        # over the south frame and win.
        b0, b1, b2 = pack_position(10, 10, 0)
        south_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 11, 0, 1, 0)
        north_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        block0 = struct.pack("<H", 2) + south_record + north_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_south_sign_stays_visible_over_the_north_sign(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (0, 0, 255))  # south (foreground) wins over north (plain)


class ClutterStillLosesToSupportingFurnitureTests(unittest.TestCase):
    """
    The ground-clutter regression itself: a plain-tier object (a dropped
    piece of armor, a pile of bones) that also happens to be a confirmed
    "loser" against some other plain-tier rival must still win against
    is_supporting furniture it's placed on/in, the same as any other plain
    object -- it must NOT be demoted to background/tier 0 globally just
    because it loses one specific matchup. Found from a leather armor
    piece hidden under a table, and a pile of bones hidden under an
    altar's overflow cell, after a first (wrong) fix demoted both tiles.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 529 (the real "leather armor" tile, plain).
        # BASETILE[11] = 600 ("table", is_supporting).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 529)
        struct.pack_into("<H", basetile, 11 * 2, 600)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        tileflag_path = os.path.join(self.tmpdir.name, "TILEFLAG")
        with open(tileflag_path, "rb") as f:
            tileflag = bytearray(f.read())
        tileflag[0x1400 + 600] = 0x02  # table: is_supporting
        with open(tileflag_path, "wb") as f:
            f.write(bytes(tileflag))

        # Tile 529 ("leather armor"): solid fill (7). Tile 600 ("table"):
        # solid fill (8).
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        armor_offset = (529 - 512) * 256
        objtiles[armor_offset:armor_offset + 256] = bytes([7]) * 256
        table_offset = (600 - 512) * 256
        objtiles[table_offset:table_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (armor) -> red; index 8 (table) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both on-map at the identical coordinate (10, 10, 0). Armor
        # written FIRST, table written LAST -- if armor were still
        # (wrongly) demoted to background, the table's is_supporting tier
        # would tie it and file order could hide the armor.
        b0, b1, b2 = pack_position(10, 10, 0)
        armor_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        table_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 11, 0, 1, 0)
        block0 = struct.pack("<H", 2) + armor_record + table_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_armor_stays_visible_over_the_table(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (255, 0, 0))  # armor (plain) wins over the table (supporting)


class MisflaggedBasketTileTests(unittest.TestCase):
    """
    A basket (obj_n=191, tile 758 specifically -- the same obj_n's other
    frames are "open crate"/"crate"/"small jug"/"milk bottle") must be
    treated as supporting even though TILEFLAG doesn't flag it: its
    contents should show on top of it. Confirmed against a real screenshot
    showing baskets and a bunch of grapes as distinct, both-visible
    objects, not grapes nested invisibly inside a basket, which is what
    six placements sharing a basket's coordinate with a grapes anchor were
    rendering.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 600 ("grapes", plain). BASETILE[11] = 758
        # ("basket", deliberately left with NO TILEFLAG bits set -- only
        # its tile number identifies it here).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 600)
        struct.pack_into("<H", basetile, 11 * 2, 758)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        # Tile 600 ("grapes"): solid fill (7). Tile 758 ("basket"): solid
        # fill (8).
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        grapes_offset = (600 - 512) * 256
        objtiles[grapes_offset:grapes_offset + 256] = bytes([7]) * 256
        basket_offset = (758 - 512) * 256
        objtiles[basket_offset:basket_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (grapes) -> red; index 8 (basket) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both on-map at the identical coordinate (10, 10, 0). Grapes
        # written FIRST, basket written LAST -- a plain file-order
        # composite would let the basket paint over the grapes and hide
        # them, same as the 6 real instances found.
        b0, b1, b2 = pack_position(10, 10, 0)
        grapes_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        basket_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 11, 0, 1, 0)
        block0 = struct.pack("<H", 2) + grapes_record + basket_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_grapes_stay_visible_over_the_basket(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (255, 0, 0))  # grapes win over the basket


class MisflaggedSignpostTileTests(unittest.TestCase):
    """
    A sign plaque (obj_n=332 frames 0/1/2, tiles 1240-1242) must beat its
    own signpost (frame 6, tile 1246) even though TILEFLAG flags neither.
    Confirmed against a real screenshot showing a plaque and its post as
    distinct, both-visible shapes -- not the plaque completely erased by
    its own post, which is what 26 placements sharing a signpost's
    coordinate with a plaque anchor were rendering. (Demoting the post
    to supporting instead, rather than promoting the plaque, was tried
    first and reverted: it also let sign "north", tile 1243 -- the
    *losing* plaque at the 2 coordinates that pair two plaques on one
    post -- win its own now-uncontested tie against the post, producing
    an unwanted second plank. See MisflaggedForegroundSignSouthOverNorthTests.)
    A 4th plaque frame (frame 7, tile 1247) was found the same way after
    the fact, at 4 more real coordinates -- see
    Frame7SignPlaqueAlsoBeatsSignpostTests.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 1242 ("sign" plaque, plain). BASETILE[11] = 1246
        # ("signpost", deliberately left with NO TILEFLAG bits set -- only
        # its tile number identifies it here).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 1242)
        struct.pack_into("<H", basetile, 11 * 2, 1246)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        # Tile 1242 ("sign"): solid fill (7). Tile 1246 ("signpost"):
        # solid fill (8).
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        sign_offset = (1242 - 512) * 256
        objtiles[sign_offset:sign_offset + 256] = bytes([7]) * 256
        post_offset = (1246 - 512) * 256
        objtiles[post_offset:post_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (sign) -> red; index 8 (signpost) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both on-map at the identical coordinate (10, 10, 0). Sign
        # written FIRST, signpost written LAST -- a plain file-order
        # composite would let the post paint over the sign and hide it,
        # same as the 26 real instances found.
        b0, b1, b2 = pack_position(10, 10, 0)
        sign_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        post_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 11, 0, 1, 0)
        block0 = struct.pack("<H", 2) + sign_record + post_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_sign_stays_visible_over_the_signpost(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (255, 0, 0))  # sign wins over the signpost


class Frame7SignPlaqueAlsoBeatsSignpostTests(unittest.TestCase):
    """
    obj_n=332 frame 7 (tile 1247) is a 4th plain-horizontal sign plaque,
    found after the fact at 4 more real coordinates (375,599),
    (570,348), (905,394), and dungeon2's (66,234,3), each paired only
    with its own signpost (no second plaque) -- same "post wins file
    order and erases the plaque" bug as frames 0-2, confirmed the post's
    seq is lower than the plaque's at all 4.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 1247 ("sign" plaque, plain). BASETILE[11] = 1246
        # ("signpost", deliberately left with NO TILEFLAG bits set).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 1247)
        struct.pack_into("<H", basetile, 11 * 2, 1246)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        # Tile 1247 ("sign"): solid fill (7). Tile 1246 ("signpost"):
        # solid fill (8).
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        sign_offset = (1247 - 512) * 256
        objtiles[sign_offset:sign_offset + 256] = bytes([7]) * 256
        post_offset = (1246 - 512) * 256
        objtiles[post_offset:post_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (sign) -> red; index 8 (signpost) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both on-map at the identical coordinate (10, 10, 0). Sign
        # written FIRST, signpost written LAST -- matching tile 1247's
        # real, verified lower seq than the post's at all 4 placements.
        b0, b1, b2 = pack_position(10, 10, 0)
        sign_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        post_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 11, 0, 1, 0)
        block0 = struct.pack("<H", 2) + sign_record + post_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_frame7_sign_stays_visible_over_the_signpost(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (255, 0, 0))  # sign wins over the signpost


class SecretDoorObjTypeIsAlwaysBackgroundTests(unittest.TestCase):
    """
    A secret door (obj_n=334) must be treated as background even though
    TILEFLAG never flags it is_background -- it's drawn 100% opaque and
    wall-colored by design (the whole point is to be indistinguishable
    from a normal wall), so an unrelated decoration anchored on the same
    tile (e.g. a picture hung to mark/disguise the door) always lost the
    plain-tier tie to it and became completely invisible.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 601 ("picture", plain). BASETILE[334] = 750
        # ("secret door", deliberately left with NO TILEFLAG bits set,
        # fully opaque -- only obj_n identifies it).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 601)
        struct.pack_into("<H", basetile, 334 * 2, 750)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        # Tile 601 ("picture"): solid fill (7). Tile 750 ("secret door"):
        # solid fill (8).
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        picture_offset = (601 - 512) * 256
        objtiles[picture_offset:picture_offset + 256] = bytes([7]) * 256
        door_offset = (750 - 512) * 256
        objtiles[door_offset:door_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (picture) -> red; index 8 (secret door) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both on-map at the identical coordinate (10, 10, 0). Picture
        # written FIRST, secret door (obj_n=334) written LAST -- a plain
        # file-order composite would let the fully-opaque door paint over
        # the picture and hide it completely.
        b0, b1, b2 = pack_position(10, 10, 0)
        picture_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        # obj_n=334 split across obj_n_lo (0x4E) and obj_n_hi's low 2 bits (0x01).
        door_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 0x4E, 0x01, 1, 0)
        block0 = struct.pack("<H", 2) + picture_record + door_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_picture_stays_visible_over_the_secret_door(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (255, 0, 0))  # picture wins over the secret door


class DoorwayObjTypeIsAlwaysBackgroundTests(unittest.TestCase):
    """
    A doorway (obj_n=301) must be treated as background even though its
    own TILEFLAG entry is is_foreground, same as the door that fills it --
    a 1990s U6 level-design reference (it-he.org's "List of Useful
    Objects") says to place the doorway first and put the door on top, but
    a whole-map audit found 30+ doorways winning that tie by file-order
    coincidence instead, nearly erasing their own door.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 601 ("door", is_foreground). BASETILE[301] = 750
        # ("doorway", also is_foreground in the real data -- only obj_n
        # distinguishes it here).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 601)
        struct.pack_into("<H", basetile, 301 * 2, 750)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        tileflag_path = os.path.join(self.tmpdir.name, "TILEFLAG")
        with open(tileflag_path, "rb") as f:
            tileflag = bytearray(f.read())
        tileflag[0x800 + 601] = 0x10  # door: is_foreground
        tileflag[0x800 + 750] = 0x10  # doorway: is_foreground too
        with open(tileflag_path, "wb") as f:
            f.write(bytes(tileflag))

        # Tile 601 ("door"): solid fill (7). Tile 750 ("doorway"): solid
        # fill (8).
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        door_offset = (601 - 512) * 256
        objtiles[door_offset:door_offset + 256] = bytes([7]) * 256
        doorway_offset = (750 - 512) * 256
        objtiles[doorway_offset:doorway_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (door) -> red; index 8 (doorway) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both on-map at the identical coordinate (10, 10, 0). Door written
        # FIRST, doorway (obj_n=301) written LAST -- a plain file-order
        # composite would let the doorway paint over the door and hide it,
        # same as the 30+ real instances the audit found.
        b0, b1, b2 = pack_position(10, 10, 0)
        door_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        doorway_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 301 & 0xFF, (301 >> 8) & 0x03, 1, 0)
        block0 = struct.pack("<H", 2) + door_record + doorway_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_door_stays_visible_over_the_doorway(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (255, 0, 0))  # door wins over the doorway


class WallMountObjTypeIsAlwaysSupportingTests(unittest.TestCase):
    """
    A wall mount (obj_n=140) must be treated as supporting even though
    TILEFLAG never flags it is_supporting -- it's a rack a decorative sword
    or shield hangs on, the same "things get placed on top of this" role
    as a table, but a decorative sword anchored on the exact same tile as
    its wall mount tied at the plain tier and lost to it, hiding the sword
    entirely.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[10] = 601 ("decorative sword", plain). BASETILE[140] =
        # 750 ("wall mount", deliberately left with NO TILEFLAG bits set --
        # only obj_n identifies it).
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 10 * 2, 601)
        struct.pack_into("<H", basetile, 140 * 2, 750)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))

        # Tile 601 ("sword"): solid fill (7). Tile 750 ("wall mount"):
        # solid fill (8).
        objtiles_path = os.path.join(self.tmpdir.name, "OBJTILES.VGA")
        with open(objtiles_path, "rb") as f:
            objtiles = bytearray(f.read())
        sword_offset = (601 - 512) * 256
        objtiles[sword_offset:sword_offset + 256] = bytes([7]) * 256
        mount_offset = (750 - 512) * 256
        objtiles[mount_offset:mount_offset + 256] = bytes([8]) * 256
        with open(objtiles_path, "wb") as f:
            f.write(bytes(objtiles))

        # Palette: index 7 (sword) -> red; index 8 (wall mount) -> blue.
        pal_path = os.path.join(self.tmpdir.name, "U6PAL")
        with open(pal_path, "rb") as f:
            pal = bytearray(f.read())
        pal[7 * 3:7 * 3 + 3] = bytes([63, 0, 0])
        pal[8 * 3:8 * 3 + 3] = bytes([0, 0, 63])
        with open(pal_path, "wb") as f:
            f.write(bytes(pal))

        # Both on-map at the identical coordinate (10, 10, 0). Wall mount
        # (obj_n=140) written FIRST, sword written LAST is the easy case;
        # write the mount LAST instead, so a plain file-order composite
        # would let it paint over the sword and hide it.
        b0, b1, b2 = pack_position(10, 10, 0)
        sword_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 10, 0, 1, 0)
        mount_record = struct.pack("<BBBBBBBB", 0x00, b0, b1, b2, 140 & 0xFF, (140 >> 8) & 0x03, 1, 0)
        block0 = struct.pack("<H", 2) + sword_record + mount_record
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_sword_stays_visible_over_the_wall_mount(self):
        out_path = os.path.join(self.tmpdir.name, "out.png")
        rc = cmd_map_render(SimpleNamespace(
            gamedir=self.tmpdir.name, palette=None, region="5,5,10,10", dungeon=None,
            full=False, tick=0, objects=True, output=out_path,
        ))
        self.assertEqual(rc, 0)

        img = Image.open(out_path).convert("RGB")
        # region is (5,5,10,10) -> world (10,10) is pixel-tile (5,5), i.e.
        # pixel origin (80, 80).
        self.assertEqual(img.getpixel((80, 80)), (255, 0, 0))  # sword wins over the wall mount


class EggListCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

        # BASETILE[50] = 600, so the spawn target resolves to a real tile;
        # LOOK.LZD names that tile "wolf" for a human-readable report.
        basetile = bytearray(2048)
        struct.pack_into("<H", basetile, 50 * 2, 600)
        with open(os.path.join(self.tmpdir.name, "BASETILE"), "wb") as f:
            f.write(bytes(basetile))
        with open(os.path.join(self.tmpdir.name, "LOOK.LZD"), "wb") as f:
            f.write(struct.pack("<H", 600) + b"wolf\x00")

        # One egg (75% chance) whose sole contained object is the spawn
        # template: obj_n=50, max count 8, quality 8.
        egg_obj_n_lo = EGG_OBJ_N & 0xFF
        egg_obj_n_hi = (EGG_OBJ_N >> 8) & 0x03  # frame_n=0, so no high bits to OR in
        egg = struct.pack(
            "<BBBBBBBB", 0x00, *pack_position(20, 20, 0), egg_obj_n_lo, egg_obj_n_hi, 75, 4,
        )
        spawn = struct.pack("<BBBBBBBB", 0x08, 0, 0, 0, 50, 0, 8, 8)  # container index 0 -> the egg
        block0 = struct.pack("<H", 2) + egg + spawn
        with open(os.path.join(self.tmpdir.name, "LZOBJBLK"), "wb") as f:
            f.write(block0 + bytes(2) * (SURFACE_SUPERCHUNKS - 1))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_gamedir_errors(self):
        with self.assertRaises(SystemExit):
            cmd_egg_list(SimpleNamespace(gamedir=None, block=None, dungeon=None, limit=200))

    def test_missing_look_lzd_errors(self):
        os.remove(os.path.join(self.tmpdir.name, "LOOK.LZD"))
        rc = cmd_egg_list(SimpleNamespace(gamedir=self.tmpdir.name, block=None, dungeon=None, limit=200))
        self.assertEqual(rc, 1)

    def test_lists_the_seeded_egg_with_its_spawn_target(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_egg_list(SimpleNamespace(gamedir=self.tmpdir.name, block=0, dungeon=None, limit=200))
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("1 egg(s)", output)
        self.assertIn("75%", output)
        self.assertIn("wolf", output)

    def test_invalid_dungeon_errors(self):
        rc = cmd_egg_list(SimpleNamespace(gamedir=self.tmpdir.name, block=None, dungeon=9, limit=200))
        self.assertEqual(rc, 1)


class ObjectListCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_gamedir_errors(self):
        with self.assertRaises(SystemExit):
            cmd_object_list(SimpleNamespace(gamedir=None, block=None, dungeon=None, limit=200))

    def test_lists_surface_block_with_the_one_seeded_object(self):
        rc = cmd_object_list(SimpleNamespace(gamedir=self.tmpdir.name, block=0, dungeon=None, limit=200))
        self.assertEqual(rc, 0)

    def test_invalid_block_errors(self):
        rc = cmd_object_list(SimpleNamespace(gamedir=self.tmpdir.name, block=9999, dungeon=None, limit=200))
        self.assertEqual(rc, 1)

    def test_invalid_dungeon_errors(self):
        rc = cmd_object_list(SimpleNamespace(gamedir=self.tmpdir.name, block=None, dungeon=9, limit=200))
        self.assertEqual(rc, 1)

    def test_dungeon_level_lists_successfully(self):
        rc = cmd_object_list(SimpleNamespace(gamedir=self.tmpdir.name, block=None, dungeon=0, limit=200))
        self.assertEqual(rc, 0)

    def test_no_filter_lists_all_surface_blocks(self):
        rc = cmd_object_list(SimpleNamespace(gamedir=self.tmpdir.name, block=None, dungeon=None, limit=200))
        self.assertEqual(rc, 0)


class ActorListCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_gamedir_errors(self):
        with self.assertRaises(SystemExit):
            cmd_actor_list(SimpleNamespace(gamedir=None, all=False))

    def test_active_only_is_empty_for_all_zero_objlist(self):
        # Every synthetic actor has obj_n == 0 -> none are "active".
        rc = cmd_actor_list(SimpleNamespace(gamedir=self.tmpdir.name, all=False))
        self.assertEqual(rc, 0)

    def test_all_shows_every_slot(self):
        rc = cmd_actor_list(SimpleNamespace(gamedir=self.tmpdir.name, all=True))
        self.assertEqual(rc, 0)


class GamestateDumpCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        _make_synthetic_gamedir(self.tmpdir.name)
        # objlist_tail must reach gamestate.REQUIRED_SIZE (bigger than
        # actor.REQUIRED_SIZE), with one seeded party member.
        tail = bytearray(GAMESTATE_REQUIRED_SIZE)
        tail[OFFSET_NUM_IN_PARTY] = 1
        name = b"Avatar\x00"
        tail[OFFSET_PARTY_NAMES:OFFSET_PARTY_NAMES + len(name)] = name
        tail[OFFSET_PARTY_ROSTER] = 1
        with open(os.path.join(self.tmpdir.name, "LZDNGBLK"), "wb") as f:
            f.write(bytes(2) * DUNGEON_LEVELS + bytes(tail))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_gamedir_errors(self):
        with self.assertRaises(SystemExit):
            cmd_gamestate_dump(SimpleNamespace(gamedir=None))

    def test_missing_lzdngblk_errors(self):
        os.remove(os.path.join(self.tmpdir.name, "LZDNGBLK"))
        rc = cmd_gamestate_dump(SimpleNamespace(gamedir=self.tmpdir.name))
        self.assertEqual(rc, 1)

    def test_dumps_successfully(self):
        rc = cmd_gamestate_dump(SimpleNamespace(gamedir=self.tmpdir.name))
        self.assertEqual(rc, 0)


class FlagsCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir_a = tempfile.TemporaryDirectory()
        self.tmpdir_b = tempfile.TemporaryDirectory()
        tail_a = bytearray(GAMESTATE_REQUIRED_SIZE)
        tail_b = bytearray(GAMESTATE_REQUIRED_SIZE)
        tail_b[OFFSET_TALK_FLAGS + 5] = 0b00000001  # actor 5 now "met"
        _make_synthetic_savegame(self.tmpdir_a.name, bytes(tail_a))
        _make_synthetic_savegame(self.tmpdir_b.name, bytes(tail_b))

    def tearDown(self):
        self.tmpdir_a.cleanup()
        self.tmpdir_b.cleanup()

    def test_dump_from_savegame(self):
        rc = cmd_flags_dump(SimpleNamespace(source=self.tmpdir_b.name, all=False))
        self.assertEqual(rc, 0)

    def test_dump_missing_source_errors(self):
        with self.assertRaises(SystemExit):
            cmd_flags_dump(SimpleNamespace(source=self.tmpdir_a.name + "_nope", all=True))

    def test_compare_finds_the_seeded_difference(self):
        rc = cmd_flags_compare(SimpleNamespace(source_a=self.tmpdir_a.name, source_b=self.tmpdir_b.name))
        self.assertEqual(rc, 0)

    def test_compare_identical_sources_finds_nothing(self):
        rc = cmd_flags_compare(SimpleNamespace(source_a=self.tmpdir_a.name, source_b=self.tmpdir_a.name))
        self.assertEqual(rc, 0)

    def test_set_writes_new_file_by_default(self):
        rc = cmd_flags_set(SimpleNamespace(
            savegame=self.tmpdir_a.name, actor=9, flag=2, value=1,
            quest_flag=None, gargish=None, output=None, in_place=False,
        ))
        self.assertEqual(rc, 0)
        new_path = os.path.join(self.tmpdir_a.name, "OBJLIST.new")
        self.assertTrue(os.path.isfile(new_path))
        original_path = os.path.join(self.tmpdir_a.name, "OBJLIST")
        with open(original_path, "rb") as f:
            original = f.read()
        self.assertEqual(original[OFFSET_TALK_FLAGS + 9], 0)  # original untouched
        with open(new_path, "rb") as f:
            modified = f.read()
        self.assertEqual(modified[OFFSET_TALK_FLAGS + 9], 0b00000100)

    def test_set_in_place_backs_up_original(self):
        original_path = os.path.join(self.tmpdir_a.name, "OBJLIST")
        with open(original_path, "rb") as f:
            original = f.read()
        rc = cmd_flags_set(SimpleNamespace(
            savegame=self.tmpdir_a.name, actor=1, flag=0, value=1,
            quest_flag=None, gargish=None, output=None, in_place=True,
        ))
        self.assertEqual(rc, 0)
        backup_path = original_path + ".bak"
        self.assertTrue(os.path.isfile(backup_path))
        with open(backup_path, "rb") as f:
            self.assertEqual(f.read(), original)
        with open(original_path, "rb") as f:
            modified = f.read()
        self.assertEqual(modified[OFFSET_TALK_FLAGS + 1], 0b00000001)

    def test_set_quest_flag(self):
        rc = cmd_flags_set(SimpleNamespace(
            savegame=self.tmpdir_a.name, actor=None, flag=None, value=None,
            quest_flag=1, gargish=None, output=None, in_place=False,
        ))
        self.assertEqual(rc, 0)

    def test_set_missing_objlist_errors(self):
        rc = cmd_flags_set(SimpleNamespace(
            savegame=self.tmpdir_a.name + "_nope", actor=1, flag=0, value=1,
            quest_flag=None, gargish=None, output=None, in_place=False,
        ))
        self.assertEqual(rc, 1)

    def test_set_actor_without_flag_and_value_errors(self):
        rc = cmd_flags_set(SimpleNamespace(
            savegame=self.tmpdir_a.name, actor=1, flag=None, value=None,
            quest_flag=None, gargish=None, output=None, in_place=False,
        ))
        self.assertEqual(rc, 1)

    def test_set_nothing_specified_errors(self):
        rc = cmd_flags_set(SimpleNamespace(
            savegame=self.tmpdir_a.name, actor=None, flag=None, value=None,
            quest_flag=None, gargish=None, output=None, in_place=False,
        ))
        self.assertEqual(rc, 1)


class ConverseDumpCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        # A tiny lib_32 with one item: a SIDENT + name script (0xff, 0x02, "Dupre").
        script = bytes([0xFF, 0x02]) + b"Dupre"
        table = (8).to_bytes(4, "little")
        self.path = os.path.join(self.tmpdir.name, "CONVERSE.A")
        with open(self.path, "wb") as f:
            f.write(table + script)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_file_errors(self):
        rc = cmd_converse_dump(SimpleNamespace(
            file="/nope", item=None, entry_size=4, size_header=False, output=None,
        ))
        self.assertEqual(rc, 1)

    def test_out_of_range_item_errors(self):
        rc = cmd_converse_dump(SimpleNamespace(
            file=self.path, item=99, entry_size=4, size_header=False, output=None,
        ))
        self.assertEqual(rc, 1)

    def test_dumps_single_item_to_stdout(self):
        rc = cmd_converse_dump(SimpleNamespace(
            file=self.path, item=0, entry_size=4, size_header=False, output=None,
        ))
        self.assertEqual(rc, 0)

    def test_dumps_all_items_to_output_dir(self):
        outdir = os.path.join(self.tmpdir.name, "out")
        rc = cmd_converse_dump(SimpleNamespace(
            file=self.path, item=None, entry_size=4, size_header=False, output=outdir,
        ))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(outdir, "0000_CONVERSE.A.txt")))


class FontExportCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "U6.CH")
        with open(self.path, "wb") as f:
            f.write(bytes(FONT_FILE_SIZE))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_file_errors(self):
        rc = cmd_font_export(SimpleNamespace(file="/nope", text=None, scale=3, output=None))
        self.assertEqual(rc, 1)

    def test_exports_both_font_sheets(self):
        outdir = os.path.join(self.tmpdir.name, "out")
        rc = cmd_font_export(SimpleNamespace(file=self.path, text=None, scale=1, output=outdir))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(outdir, "font_english.png")))
        self.assertTrue(os.path.isfile(os.path.join(outdir, "font_runic_gargoyle.png")))

    def test_exports_sample_text_when_given(self):
        outdir = os.path.join(self.tmpdir.name, "out")
        rc = cmd_font_export(SimpleNamespace(file=self.path, text="HI", scale=1, output=outdir))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(outdir, "text_english.png")))
        self.assertTrue(os.path.isfile(os.path.join(outdir, "text_runic_gargoyle.png")))


class LookDumpCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "LOOK.LZD")
        with open(self.path, "wb") as f:
            f.write(struct.pack("<H", 1) + b"grass\x00")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_file_errors(self):
        rc = cmd_look_dump(SimpleNamespace(file="/nope", output=None))
        self.assertEqual(rc, 1)

    def test_dumps_successfully(self):
        outdir = os.path.join(self.tmpdir.name, "out")
        rc = cmd_look_dump(SimpleNamespace(file=self.path, output=outdir))
        self.assertEqual(rc, 0)
        with open(os.path.join(outdir, "look_dump.txt"), encoding="utf-8") as f:
            self.assertIn("grass", f.read())


class BookDumpCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "BOOK.DAT")
        table = (2).to_bytes(2, "little")
        with open(self.path, "wb") as f:
            f.write(table + b"A sign.\x00")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_file_errors(self):
        rc = cmd_book_dump(SimpleNamespace(file="/nope", book=None, output=None))
        self.assertEqual(rc, 1)

    def test_single_book_out_of_range_errors(self):
        rc = cmd_book_dump(SimpleNamespace(file=self.path, book=99, output=None))
        self.assertEqual(rc, 1)

    def test_single_book_prints_text(self):
        rc = cmd_book_dump(SimpleNamespace(file=self.path, book=0, output=None))
        self.assertEqual(rc, 0)

    def test_all_books_dumped_to_file(self):
        outdir = os.path.join(self.tmpdir.name, "out")
        rc = cmd_book_dump(SimpleNamespace(file=self.path, book=None, output=outdir))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(outdir, "book_dump.txt")))


class ScheduleDumpCliTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "SCHEDULE")
        with open(self.path, "wb") as f:
            f.write(bytes(256 * 2 + 2))  # valid, trivial: every actor has zero entries

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_file_errors(self):
        rc = cmd_schedule_dump(SimpleNamespace(file="/nope", actor=None, output=None))
        self.assertEqual(rc, 1)

    def test_out_of_range_actor_errors(self):
        rc = cmd_schedule_dump(SimpleNamespace(file=self.path, actor=9999, output=None))
        self.assertEqual(rc, 1)

    def test_all_actors_prints_to_stdout(self):
        rc = cmd_schedule_dump(SimpleNamespace(file=self.path, actor=None, output=None))
        self.assertEqual(rc, 0)

    def test_dump_to_file(self):
        outdir = os.path.join(self.tmpdir.name, "out")
        rc = cmd_schedule_dump(SimpleNamespace(file=self.path, actor=None, output=outdir))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(outdir, "schedule_dump.txt")))


if __name__ == "__main__":
    unittest.main()
