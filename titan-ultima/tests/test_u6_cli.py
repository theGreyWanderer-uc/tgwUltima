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
