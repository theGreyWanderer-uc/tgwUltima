"""Tests for the shared UU2 special-instance placement and material rules.

Every rule here is transcribed from the UnderworldGodot reference and checked
against the shipped levels; see reference/uw2/uw2-3d-model-work-plan.md for the
per-rule evidence. These tests exist mainly so the 2.5D cutaway, the standalone
model tools, and the 3D scene builder cannot drift apart again — the rules
previously lived as two partial, divergent copies.
"""

from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

from titan.uw2.instances import (
    BRIDGE_ITEM,
    CONTROL_FIRST,
    CONTROL_LAST,
    FLOOR_ROLE,
    LEVER_ITEM,
    REMOVABLE_WALL_ITEM,
    SWITCH_ITEM,
    THIN_WALL_ITEM,
    TMFLAT,
    TMOBJ,
    WALL_ROLE,
    WRITING_ITEM,
    BED_PILLOW_MIN_Y,
    bed_face_palette,
    bed_palette_indices,
    heading_vector,
    is_wall_mounted,
    object_material,
    object_material_for,
    special_model_index,
    terrain_texture_id,
    writing_message_index,
    writing_prefix_index,
)


def _level(entries: list[int]) -> dict:
    return {"texture_mapping": {"entries": entries}}


class UW2OrdinaryMaterialTests(unittest.TestCase):
    """The six item-selected TMOBJ rules that predate the shared resolver."""

    def test_fixed_and_flag_selected_object_textures(self) -> None:
        for item_id, flags, expected in (
            (0x0158, 0, 32),  # table
            (0x015C, 0, 38),  # chair
            (0x0160, 3, 3),  # pillar
            (0x0163, 2, 44),  # painting
            (0x0165, 1, 29),  # gravestone
            (0x0169, 1, 37),  # shelf
        ):
            with self.subTest(item=item_id):
                reference = object_material(item_id, flags)
                self.assertEqual(reference.source, TMOBJ)
                self.assertEqual(reference.index, expected)

    def test_items_without_a_rule_resolve_to_nothing(self) -> None:
        self.assertIsNone(object_material(0x0167))
        self.assertIsNone(object_material(0x0001))


class UW2RotaryTests(unittest.TestCase):
    def test_lever_and_switch_take_eight_consecutive_images(self) -> None:
        lever = [object_material(LEVER_ITEM, f).index for f in range(8)]
        switch = [object_material(SWITCH_ITEM, f).index for f in range(8)]

        self.assertEqual(lever, list(range(4, 12)))
        self.assertEqual(switch, list(range(12, 20)))

    def test_position_is_masked_to_three_bits(self) -> None:
        # The reference clamps flags & 0x07. Without the mask a lever with the
        # enchantment bit set would index into the switch's image range.
        self.assertEqual(object_material(LEVER_ITEM, 8).index, 4)
        self.assertEqual(object_material(LEVER_ITEM, 12).index, 8)
        self.assertEqual(object_material(SWITCH_ITEM, 15).index, 19)


class UW2ControlTests(unittest.TestCase):
    def test_controls_use_the_low_item_nibble_against_tmflat(self) -> None:
        for item_id in (CONTROL_FIRST, 0x0175, CONTROL_LAST):
            with self.subTest(item=item_id):
                reference = object_material(item_id)
                self.assertEqual(reference.source, TMFLAT)
                self.assertEqual(reference.index, item_id & 0x0F)

    def test_the_eight_offset_pair_selects_a_different_image(self) -> None:
        # Activating a control shifts its item ID by eight to the other state.
        self.assertNotEqual(
            object_material(0x0171).index, object_material(0x0179).index
        )


class UW2WritingTests(unittest.TestCase):
    def test_texture_masks_to_three_bits(self) -> None:
        self.assertEqual(object_material(WRITING_ITEM, 0).index, 20)
        self.assertEqual(object_material(WRITING_ITEM, 7).index, 27)
        # Bit 3 is the enchantment flag and selects nothing here, so flags 0
        # and 8 share one image.
        self.assertEqual(object_material(WRITING_ITEM, 8).index, 20)

    def test_prefix_index_also_masks_to_three_bits(self) -> None:
        self.assertEqual(writing_prefix_index(0), 368)
        self.assertEqual(writing_prefix_index(8), 368)
        self.assertEqual(writing_prefix_index(5), 373)

    def test_message_index_is_the_link_less_the_bias(self) -> None:
        self.assertEqual(writing_message_index({"special_property_value": 70}), 70)
        self.assertEqual(writing_message_index({"quantity_or_link": 582}), 70)

    def test_message_index_is_absent_without_a_link(self) -> None:
        self.assertIsNone(writing_message_index({}))
        self.assertIsNone(writing_message_index({"quantity_or_link": 12}))


class UW2BridgeTests(unittest.TestCase):
    def test_low_flags_use_the_object_texture_archive(self) -> None:
        for flags, expected in ((0, 30), (1, 31)):
            with self.subTest(flags=flags):
                reference = object_material(BRIDGE_ITEM, flags)
                self.assertEqual(reference.source, TMOBJ)
                self.assertEqual(reference.index, expected)

    def test_higher_flags_borrow_a_level_floor_texture(self) -> None:
        reference = object_material(BRIDGE_ITEM, 5)

        self.assertTrue(reference.is_terrain)
        self.assertEqual(reference.role, FLOOR_ROLE)
        self.assertEqual(reference.index, 3)

    def test_terrain_reference_resolves_through_the_level_mapping(self) -> None:
        reference = object_material(BRIDGE_ITEM, 5)
        level = _level([100, 101, 102, 223, 104])

        self.assertEqual(terrain_texture_id(reference, level), 223)

    def test_mapped_index_stays_inside_the_floor_range(self) -> None:
        # flags is four bits, so the mapped index reaches at most 13 - inside
        # the 0-15 floor slots that tiles themselves use.
        highest = object_material(BRIDGE_ITEM, 15)
        self.assertEqual(highest.index, 13)


class UW2SpecialWallTests(unittest.TestCase):
    def test_walls_borrow_a_wall_mapping_entry_named_by_owner(self) -> None:
        for item_id in (THIN_WALL_ITEM, REMOVABLE_WALL_ITEM):
            with self.subTest(item=item_id):
                reference = object_material(item_id, flags=0, owner=16)
                self.assertTrue(reference.is_terrain)
                self.assertEqual(reference.role, WALL_ROLE)
                self.assertEqual(reference.index, 16)

    def test_owner_indexes_the_mapping_not_the_texture_id(self) -> None:
        reference = object_material(THIN_WALL_ITEM, owner=2)
        level = _level([10, 11, 222, 13])

        self.assertEqual(terrain_texture_id(reference, level), 222)

    def test_out_of_range_mapping_entry_resolves_to_nothing(self) -> None:
        reference = object_material(THIN_WALL_ITEM, owner=40)

        self.assertIsNone(terrain_texture_id(reference, _level([1, 2, 3])))

    def test_non_terrain_reference_has_no_mapping_resolution(self) -> None:
        self.assertIsNone(terrain_texture_id(object_material(0x0158), _level([1])))


class UW2ObjectRecordTests(unittest.TestCase):
    def test_resolver_reads_a_decoded_object_record(self) -> None:
        reference = object_material_for(
            {"item_id": THIN_WALL_ITEM, "flags": 0, "owner": 7}
        )

        self.assertEqual(reference.index, 7)
        self.assertEqual(reference.role, WALL_ROLE)

    def test_missing_fields_default_safely(self) -> None:
        self.assertIsNone(object_material_for({}))


class UW2ModelSlotTests(unittest.TestCase):
    def test_special_classes_map_to_their_executable_slots(self) -> None:
        self.assertEqual(special_model_index(LEVER_ITEM), 0x10)
        self.assertEqual(special_model_index(SWITCH_ITEM), 0x11)
        self.assertEqual(special_model_index(WRITING_ITEM), 0x12)
        self.assertEqual(special_model_index(BRIDGE_ITEM), 0x02)

    def test_both_texture_map_classes_take_the_full_tile_quad(self) -> None:
        """A tmap panel is one tile square and one tile high, either class.

        ``0x016E`` also has a quarter-tile slot at ``0x14``, and using it left
        the throne room's banners as fragments: they hang as two panels 32
        height units apart, so each has to be a whole tile tall to meet. UA
        draws both classes the same way, in ``RenderTmapObject``.
        """
        self.assertEqual(special_model_index(THIN_WALL_ITEM), 0x16)
        self.assertEqual(special_model_index(REMOVABLE_WALL_ITEM), 0x16)

    def test_every_control_shares_the_quad_slot(self) -> None:
        slots = {
            special_model_index(item) for item in range(CONTROL_FIRST, CONTROL_LAST + 1)
        }

        self.assertEqual(slots, {0x10})

    def test_ordinary_items_have_no_special_slot(self) -> None:
        self.assertIsNone(special_model_index(0x0158))

    def test_wall_mounted_membership(self) -> None:
        self.assertTrue(is_wall_mounted(WRITING_ITEM))
        self.assertTrue(is_wall_mounted(0x0177))
        self.assertTrue(is_wall_mounted(THIN_WALL_ITEM))
        self.assertFalse(is_wall_mounted(BRIDGE_ITEM))
        self.assertFalse(is_wall_mounted(0x0158))


class UW2HeadingTests(unittest.TestCase):
    def test_headings_are_clockwise_45_degree_steps(self) -> None:
        x, y = heading_vector(0)
        self.assertAlmostEqual(x, 1.0)
        self.assertAlmostEqual(y, 0.0)

        x, y = heading_vector(2)
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(y, -1.0)

    def test_every_heading_is_a_unit_vector(self) -> None:
        for heading in range(8):
            with self.subTest(heading=heading):
                x, y = heading_vector(heading)
                self.assertAlmostEqual(math.hypot(x, y), 1.0)

    def test_heading_wraps_at_eight(self) -> None:
        self.assertEqual(heading_vector(8), heading_vector(0))


class UW2BedPaletteTests(unittest.TestCase):
    def test_sheet_and_pillow_follow_the_owner_formula(self) -> None:
        self.assertEqual(bed_palette_indices(5), (25, 20))
        self.assertEqual(bed_palette_indices(48), (197, 192))

    def test_high_owner_wraps_rather_than_overflowing(self) -> None:
        # The reference casts the palette index to a byte; owner 63 yields 257,
        # which wraps to 1. One bed in the shipped game depends on this.
        self.assertEqual(bed_palette_indices(63), (1, 252))

    def test_every_owner_stays_inside_the_palette(self) -> None:
        for owner in range(64):
            with self.subTest(owner=owner):
                sheet, pillow = bed_palette_indices(owner)
                self.assertTrue(0 <= sheet <= 255)
                self.assertTrue(0 <= pillow <= 255)


class UW2BedFaceTests(unittest.TestCase):
    """Quilt and pillow share colour group 77 and split by position.

    Confirmed against the game: the quilt takes ``4 * owner + 5`` and the
    pillow, the raised box at the head, takes ``4 * owner``.
    """

    @staticmethod
    def _face(palette_index: int, centre_y: float):
        vertex = SimpleNamespace(y=centre_y)
        return SimpleNamespace(
            palette_index=palette_index, vertices=(vertex, vertex, vertex)
        )

    def test_quilt_takes_the_sheet_colour(self) -> None:
        face = self._face(77, BED_PILLOW_MIN_Y - 0.1)

        self.assertEqual(bed_face_palette(face, 24), 101)

    def test_pillow_takes_the_plain_owner_colour(self) -> None:
        face = self._face(77, BED_PILLOW_MIN_Y + 0.1)

        self.assertEqual(bed_face_palette(face, 24), 96)

    def test_frame_and_mattress_keep_their_own_colours(self) -> None:
        self.assertIsNone(bed_face_palette(self._face(49, 0.0), 24))
        self.assertIsNone(bed_face_palette(self._face(198, 0.0), 24))

    def test_high_owner_wraps_on_bedding_too(self) -> None:
        quilt = self._face(77, BED_PILLOW_MIN_Y - 0.1)

        self.assertEqual(bed_face_palette(quilt, 63), 1)


class UW2InstanceColourTests(unittest.TestCase):
    """Classes whose look comes off the placed object rather than the model.

    UnderworldGodot's per-object ``ModelColour`` overrides are the list of these
    (``src/objects/*.cs``); each is checked against the shipped levels here.
    """

    def test_a_moongate_is_tinted_by_its_own_link(self) -> None:
        """``uwobject.link - 512``, which is how the Void gets a gate per zone.

        The shipped gates span the spectrum: red 0x21, blue 0x4F, yellow 0x10,
        orange 0x2D, purple 0x5A and 0x5B, green 0xAB, white 0xC2.
        """
        from titan.uw2.instances import MOONGATE_ITEM, moongate_palette

        for link, expected in ((545, 0x21), (591, 0x4F), (528, 0x10), (706, 0xC2)):
            with self.subTest(link=link):
                obj = {"item_id": MOONGATE_ITEM, "quantity_or_link": link}
                self.assertEqual(moongate_palette(obj), expected)

    def test_a_moongate_without_a_link_has_no_tint(self) -> None:
        from titan.uw2.instances import MOONGATE_ITEM, moongate_palette

        self.assertIsNone(moongate_palette({"item_id": MOONGATE_ITEM}))

    def test_only_moongates_are_tinted_this_way(self) -> None:
        from titan.uw2.instances import moongate_palette

        self.assertIsNone(
            moongate_palette({"item_id": 0x0158, "quantity_or_link": 545})
        )

    def test_a_link_outside_the_palette_is_ignored(self) -> None:
        from titan.uw2.instances import MOONGATE_ITEM, moongate_palette

        for link in (0, 511, 768, 4096):
            with self.subTest(link=link):
                obj = {"item_id": MOONGATE_ITEM, "quantity_or_link": link}
                self.assertIsNone(moongate_palette(obj))

    def test_a_table_surface_follows_its_flags(self) -> None:
        """32 and 34 plank, 33 is marble, 35 stone; 30 of 74 tables set them."""
        from titan.uw2.instances import TABLE_ITEM, TMOBJ, MaterialRef

        for flags, expected in ((0, 32), (1, 33), (2, 34), (3, 35)):
            with self.subTest(flags=flags):
                reference = object_material_for({"item_id": TABLE_ITEM, "flags": flags})
                self.assertEqual(reference, MaterialRef(TMOBJ, expected))


if __name__ == "__main__":
    unittest.main()
