"""How an executable model's flat faces get their colours.

A model carries a small colour table in ``UW2.EXE``'s model info entry, and its
nodes name a slot in it by byte offset. UnderworldAdventures hand-transcribed
the same 32 tables (``ModelDecoder.cpp``: ``uw2_paletteIndices``); reading them
out of the executable instead agrees on 30. The two that differ are both ours to
keep: the table (``0x18``) is a duplicated line in UA's list - it gives ``0x18``
and ``0x19`` the same ``{0x8E, 0xCA}`` where the bytes read ``0x8C`` and
``0x8E``, and the game's tables are the lighter tan - and the pillar (``0x0A``)
declares nine colours where four bytes follow, surplus nothing reads because it
draws no flat-coloured face.

Two things here are not derivable from the bytes and are pinned so they cannot
drift: what an out-of-range slot means, and the moongate's placeholder colour.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from titan.uw2.exe_models import (
    BLACKROCK_GEM_COLOR,
    CHEST_COLOR_SLOT,
    CHEST_MODEL,
    BLACKROCK_GEM_MODEL,
    INFO_INDIRECT_FIRST_COLOR,
    MODEL_PALETTE_MAX,
    MOONGATE_FIRST_COLOR,
    _ModelParser,
    shaded_palette_index,
)


class _Colours(_ModelParser):
    """Just enough of a parser to exercise the colour lookup."""

    def __init__(self, palette, model_index=0):
        self.palette = palette
        self.model_index = model_index


def _lookup(palette, offset, model_index=0):
    return _Colours(palette, model_index)._color(offset)


class ColourSlotTests(unittest.TestCase):
    def test_a_slot_inside_the_table_is_read_straight(self) -> None:
        table = (0x8E, 0xCA)
        self.assertEqual(_lookup(table, 0x2680), 0x8E)
        self.assertEqual(_lookup(table, 0x2682), 0xCA)

    def test_a_slot_past_the_table_is_black_for_most_models(self) -> None:
        """Everything that reaches out, bar the gem, has a one-entry table."""
        for offset in (0x2686, 0x2698, 0x26A0):
            with self.subTest(offset=hex(offset)):
                self.assertEqual(_lookup((0x8F,), offset), 0)

    def test_the_gem_reaches_past_its_table_for_its_facet_colour(self) -> None:
        """It asks a two-entry table for slots 3 and 12 to 16.

        Wrapping painted 55 of its 64 faces white and palette 0 turned them
        black; in the game they are blue, the engine supplying the colour from
        quest state. At the start of a game every facet is 0x52.
        """
        table = (0xCC, 0x02)
        for offset in (0x2686, 0x2698, 0x269A, 0x269C, 0x269E, 0x26A0):
            with self.subTest(offset=hex(offset)):
                self.assertEqual(
                    _lookup(table, offset, BLACKROCK_GEM_MODEL), BLACKROCK_GEM_COLOR
                )

    def test_the_gem_still_reads_its_own_table_where_it_has_one(self) -> None:
        table = (0xCC, 0x02)
        self.assertEqual(_lookup(table, 0x2680, BLACKROCK_GEM_MODEL), 0xCC)
        self.assertEqual(_lookup(table, 0x2682, BLACKROCK_GEM_MODEL), 0x02)

    def test_a_slot_before_the_table_is_black(self) -> None:
        self.assertEqual(_lookup((0x8E, 0xCA), 0x267E), 0)

    def test_the_first_slot_of_a_one_colour_table_still_reads(self) -> None:
        self.assertEqual(_lookup((0x8F,), 0x2680), 0x8F)
        self.assertEqual(_lookup((0x8F,), 0x2682), 0)


class ModelInfoTableTests(unittest.TestCase):
    def test_the_table_holds_at_most_four_colours(self) -> None:
        """The bed declares and uses four; reading three lost its bedding."""
        self.assertEqual(MODEL_PALETTE_MAX, 4)

    def test_the_indirect_flag_is_the_top_bit(self) -> None:
        self.assertEqual(INFO_INDIRECT_FIRST_COLOR, 0x80)

    def test_the_gem_facet_colour_is_the_dark_end_of_the_blue_ramp(self) -> None:
        """0x4C to 0x52 runs lavender down to deep blue; 0x52 is the default."""
        self.assertEqual(BLACKROCK_GEM_MODEL, 0x1E)
        self.assertEqual(BLACKROCK_GEM_COLOR, 0x52)

    def test_the_moongate_placeholder_resolves_to_its_recorded_colour(self) -> None:
        """Index 0x21 is the one palette entry that is red in some palettes and
        blue in others - the two moongates the game shows, from one model."""
        self.assertEqual(MOONGATE_FIRST_COLOR, 0x21)


class FaceShadeTests(unittest.TestCase):
    """A face's colour is a point on a ramp, and its shade steps down it.

    A ``0x00BC`` node carries a colour and, in the word after it, a shade -
    "the same calculations and palette indexing rules apply here" as for the
    Gouraud table (``uw-formats.txt``). The palette runs in short darkening
    ramps, so the step is the next entries along. Faces of one model use
    different steps: the chest spans six, which is the modelling that made it
    read as a box rather than a silhouette.
    """

    # a grey ramp and the start of whatever follows it
    RAMP = [(96, 96, 96), (80, 80, 80), (68, 68, 68), (52, 52, 52), (252, 200, 200)]

    def test_no_shade_leaves_the_colour_alone(self) -> None:
        self.assertEqual(shaded_palette_index(self.RAMP, 0, 0), 0)

    def test_a_shade_steps_down_the_ramp(self) -> None:
        for shade, expected in ((1, 1), (2, 2), (3, 3)):
            with self.subTest(shade=shade):
                self.assertEqual(shaded_palette_index(self.RAMP, 0, shade), expected)

    def test_a_step_that_would_lighten_is_refused(self) -> None:
        """Nothing marks where a ramp ends; three faces of the arrow run off one."""
        self.assertEqual(shaded_palette_index(self.RAMP, 3, 1), 3)

    def test_a_step_past_the_palette_is_refused(self) -> None:
        self.assertEqual(shaded_palette_index(self.RAMP, 4, 3), 4)

    def test_a_negative_shade_is_ignored(self) -> None:
        self.assertEqual(shaded_palette_index(self.RAMP, 2, -1), 2)


class GouraudFaceTests(unittest.TestCase):
    """A Gouraud face shades across its corners; a part here is one colour.

    ``0x00D4`` gives every vertex its own step down the colour's ramp and
    ``0x00D6`` switches the following faces onto it - 14 of the 32 models do,
    covering 1035 of the 1205 flat faces in the set, so leaving it out dropped
    most of the modelling. The face takes the mean of its corners, which on the
    boulders, shrine and furniture that use it is close enough; a gradient drawn
    across one large panel still flattens.
    """

    def _parser(self, dark):
        parser = _ModelParser.__new__(_ModelParser)
        parser.state = SimpleNamespace(vertex_dark=dict(dark))
        return parser

    def test_a_face_takes_the_mean_of_its_corners(self) -> None:
        parser = self._parser({0: 1, 1: 3, 2: 5})
        self.assertEqual(parser._face_dark([0, 1, 2], 0), 3)

    def test_the_mean_is_rounded(self) -> None:
        parser = self._parser({0: 1, 1: 2})
        self.assertEqual(parser._face_dark([0, 1], 0), 2)  # 1.5 rounds even -> 2

    def test_corners_missing_from_the_table_are_skipped(self) -> None:
        parser = self._parser({0: 4, 5: 2})
        self.assertEqual(parser._face_dark([0, 5, 9], 0), 3)

    def test_a_face_with_no_table_entry_keeps_the_flat_shade(self) -> None:
        parser = self._parser({0: 4})
        self.assertEqual(parser._face_dark([7, 8], 2), 2)

    def test_an_empty_table_keeps_the_flat_shade(self) -> None:
        self.assertEqual(self._parser({})._face_dark([0, 1, 2], 5), 5)


class ChestColourTests(unittest.TestCase):
    """The chest is drawn in the colour it declares first, not the one it calls.

    Its face nodes ask for slot 1, the grey, twenty-one times. The game shows a
    brown chest, all forty in the shipped levels carry no instance fields that
    could be choosing, and UnderworldGodot gives its chest a brown body by hand.
    UnderworldAdventures' table agrees with the bytes but shares our arithmetic,
    so it is not a second opinion. Recorded rather than decoded.
    """

    def test_every_face_takes_the_first_declared_colour(self) -> None:
        table = (0x8E, 0xCA)
        for offset in (0x2680, 0x2682, 0x2684):
            with self.subTest(offset=hex(offset)):
                self.assertEqual(_lookup(table, offset, CHEST_MODEL), 0x8E)

    def test_the_slot_is_the_first_one(self) -> None:
        self.assertEqual(CHEST_MODEL, 0x19)
        self.assertEqual(CHEST_COLOR_SLOT, 0)

    def test_no_other_model_is_pinned_this_way(self) -> None:
        """The mechanism is right everywhere else; only the chest deviates."""
        table = (0x8E, 0xCA)
        self.assertEqual(_lookup(table, 0x2682, 0x1D), 0xCA)
        self.assertEqual(_lookup(table, 0x2682, 0x1C), 0xCA)


if __name__ == "__main__":
    unittest.main()
