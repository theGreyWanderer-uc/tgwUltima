"""Tests for titan.u6.tileflag's TILEFLAG parser.

No real game files are used here -- the fixture is a hand-built 7168-byte
buffer matching the four-region layout confirmed directly against the
decompiled GAME.EXE source (u6-decompiled/SRC/seg_0903.c:227-233 and
u6.h:179-244): TerrainType[0x800] + TileFlag[0x800] + TypeWeight[0x400]
+ D_B3EF[0x800].
"""

from __future__ import annotations

import unittest

from titan.u6.tileflag import U6TileFlags, U6TileFlagsError

TERRAIN_SIZE = 0x800
FLAGS_SIZE = 0x800
WEIGHT_SIZE = 0x400
EXTRA_SIZE = 0x800


def _make_tileflag_bytes(terrain: dict, flags: dict, weight: dict, extra: dict) -> bytes:
    t = bytearray(TERRAIN_SIZE)
    f = bytearray(FLAGS_SIZE)
    w = bytearray(WEIGHT_SIZE)
    e = bytearray(EXTRA_SIZE)
    for i, v in terrain.items():
        t[i] = v
    for i, v in flags.items():
        f[i] = v
    for i, v in weight.items():
        w[i] = v
    for i, v in extra.items():
        e[i] = v
    return bytes(t) + bytes(f) + bytes(w) + bytes(e)


class ParseTests(unittest.TestCase):
    def test_rejects_short_data(self):
        with self.assertRaises(U6TileFlagsError):
            U6TileFlags.parse(b"\x00" * 100)

    def test_correct_tile_count(self):
        data = _make_tileflag_bytes({}, {}, {}, {})
        entries = U6TileFlags.parse(data)
        self.assertEqual(len(entries), 0x800)

    def test_weight_zero_beyond_object_range(self):
        # TypeWeight only covers tiles 0-0x3FF; anything at or beyond 0x400
        # must read as 0 regardless of what garbage sits in that region of
        # the buffer, since real TypeWeight is only 0x400 bytes long.
        data = _make_tileflag_bytes({}, {}, {}, {})
        entries = U6TileFlags.parse(data)
        self.assertEqual(entries[0x3FF].weight, 0)  # untouched but in-range
        self.assertEqual(entries[0x400].weight, 0)  # out of TypeWeight's range


class TerrainTypeBitTests(unittest.TestCase):
    """Bit-to-name mapping per u6.h TERRAIN_FLAG_* (0x01=Wet .. 0x80=[N])."""

    def test_wet_impassable_wall_damaging(self):
        data = _make_tileflag_bytes({5: 0x01 | 0x08}, {}, {}, {})
        entry = U6TileFlags.parse(data)[5]
        self.assertTrue(entry.is_wet)
        self.assertFalse(entry.is_impassable)
        self.assertFalse(entry.is_wall)
        self.assertTrue(entry.is_damaging)

    def test_wall_direction_nibble_matches_decompiled_source(self):
        # u6.h:188-195: bit4=W, bit5=S, bit6=E, bit7=N
        data = _make_tileflag_bytes({7: 0x10 | 0x80}, {}, {}, {})
        entry = U6TileFlags.parse(data)[7]
        self.assertTrue(entry.wall_west)
        self.assertFalse(entry.wall_south)
        self.assertFalse(entry.wall_east)
        self.assertTrue(entry.wall_north)

    def test_movement_impedance_is_high_nibble(self):
        data = _make_tileflag_bytes({9: 0xA3}, {}, {}, {})
        entry = U6TileFlags.parse(data)[9]
        self.assertEqual(entry.movement_impedance, 0xA)


class TileFlagBitTests(unittest.TestCase):
    """Bit-to-name mapping per u6.h TILE_FLAG1_* (light/opa/win/for/nos/double)."""

    def test_light_level_and_opaque_window(self):
        data = _make_tileflag_bytes({}, {3: 0x03 | 0x04 | 0x08}, {}, {})
        entry = U6TileFlags.parse(data)[3]
        self.assertEqual(entry.light_level, 3)
        self.assertTrue(entry.is_opaque)
        self.assertTrue(entry.is_window)

    def test_foreground_and_no_shoot_through(self):
        data = _make_tileflag_bytes({}, {4: 0x10 | 0x20}, {}, {})
        entry = U6TileFlags.parse(data)[4]
        self.assertTrue(entry.is_foreground)
        self.assertTrue(entry.no_shoot_through)

    def test_double_bits(self):
        data = _make_tileflag_bytes({}, {6: 0xC0}, {}, {})
        entry = U6TileFlags.parse(data)[6]
        self.assertTrue(entry.is_double_v)
        self.assertTrue(entry.is_double_h)
        self.assertTrue(entry.is_double)

    def test_not_double_when_bits_clear(self):
        data = _make_tileflag_bytes({}, {6: 0x00}, {}, {})
        entry = U6TileFlags.parse(data)[6]
        self.assertFalse(entry.is_double)


class DoubleSizeFootprintTests(unittest.TestCase):
    def test_ordinary_tile_is_a_single_cell(self):
        data = _make_tileflag_bytes({}, {6: 0x00}, {}, {})
        entry = U6TileFlags.parse(data)[6]
        self.assertEqual(entry.double_size_footprint(500), [(0, 0, 500)])

    def test_horizontal_double_is_two_cells_right_to_left(self):
        data = _make_tileflag_bytes({}, {6: 0x80}, {}, {})  # is_double_h only
        entry = U6TileFlags.parse(data)[6]
        self.assertEqual(entry.double_size_footprint(500), [(0, 0, 500), (-1, 0, 499)])

    def test_vertical_double_is_two_cells_bottom_to_top(self):
        data = _make_tileflag_bytes({}, {6: 0x40}, {}, {})  # is_double_v only
        entry = U6TileFlags.parse(data)[6]
        self.assertEqual(entry.double_size_footprint(500), [(0, 0, 500), (0, -1, 499)])

    def test_2x2_double_visits_bottom_row_then_top_row(self):
        data = _make_tileflag_bytes({}, {6: 0xC0}, {}, {})  # both double flags
        entry = U6TileFlags.parse(data)[6]
        self.assertEqual(
            entry.double_size_footprint(500),
            [(0, 0, 500), (-1, 0, 499), (0, -1, 498), (-1, -1, 497)],
        )


class WeightAndExtraTests(unittest.TestCase):
    def test_weight_passthrough(self):
        data = _make_tileflag_bytes({}, {}, {10: 200}, {})
        entry = U6TileFlags.parse(data)[10]
        self.assertEqual(entry.weight, 200)

    def test_extra_bits_and_article(self):
        # u6.h TILE_FLAG2_*: 0x01 Wa, 0x02 Su, 0x04 Br, 0x08 Ge, 0x10 Ig, 0x20 Ba, 0xC0 article
        data = _make_tileflag_bytes({}, {}, {}, {20: 0x01 | 0x02 | 0x04 | 0xC0})
        entry = U6TileFlags.parse(data)[20]
        self.assertTrue(entry.is_warm)
        self.assertTrue(entry.is_supporting)
        self.assertTrue(entry.is_breakthrough)
        self.assertFalse(entry.is_generic)
        self.assertEqual(entry.article, 3)
        self.assertEqual(entry.article_word, "the")

    def test_article_word_table(self):
        for value, word in enumerate(["", "a", "an", "the"]):
            data = _make_tileflag_bytes({}, {}, {}, {21: value << 6})
            entry = U6TileFlags.parse(data)[21]
            self.assertEqual(entry.article_word, word)


if __name__ == "__main__":
    unittest.main()
