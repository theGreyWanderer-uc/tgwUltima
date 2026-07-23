"""Tests for titan.u7.typeflag's animation-type defaulting: Exult treats
a shape flagged is_animated with no explicit nonzero animation nibble as
animation type 0 (TIMESYNCHED), not "no animation" -- confirmed against
Exult's shapes/shapeinf.cc:217-223 and objs/animate.cc:273,334, and
cross-checked against a real Black Gate SHAPES.VGA inventory (66 total
is_animated shapes, 40 of them with a zero nibble).
"""

from __future__ import annotations

import unittest

from titan.u7.typeflag import U7TypeFlags

FLAG_IS_ANIMATED = 0x04


def _make_tfa_bytes(flags_by_shape: dict, nibble_by_shape: dict, num_shapes: int = 4) -> bytes:
    """Build synthetic TFA.DAT bytes matching the real fixed layout: the
    full 3072-byte shape-record block (1024 shapes x 3 bytes, zero-filled
    except the shapes under test) followed by the 512-byte packed
    animation-nibble table at its real fixed offset -- the nibble table's
    position does not shift just because fewer shapes are populated.
    """
    del num_shapes  # kept for call-site clarity; layout is always fixed-size
    base = bytearray(3 * 1024)
    for shnum, byte0 in flags_by_shape.items():
        base[shnum * 3] = byte0

    anim_table = bytearray(512)
    for shnum, nibble in nibble_by_shape.items():
        byte_idx, is_hi = divmod(shnum, 2)
        if is_hi:
            anim_table[byte_idx] = (anim_table[byte_idx] & 0x0F) | (nibble << 4)
        else:
            anim_table[byte_idx] = (anim_table[byte_idx] & 0xF0) | nibble

    return bytes(base) + bytes(anim_table)


class AnimTypeDefaultingTests(unittest.TestCase):
    def test_is_animated_with_zero_nibble_defaults_to_type_0(self):
        tfa_bytes = _make_tfa_bytes(
            flags_by_shape={0: FLAG_IS_ANIMATED},
            nibble_by_shape={},  # nibble left at 0 for shape 0
        )
        tfa = U7TypeFlags.parse(tfa_bytes)
        entry = tfa.get(0)
        self.assertTrue(entry.is_animated)
        self.assertEqual(entry.anim_type, 0)
        self.assertEqual(entry.anim_type_name, "timesynched")

    def test_is_animated_with_explicit_nibble_keeps_it(self):
        tfa_bytes = _make_tfa_bytes(
            flags_by_shape={1: FLAG_IS_ANIMATED},
            nibble_by_shape={1: 9},
        )
        tfa = U7TypeFlags.parse(tfa_bytes)
        entry = tfa.get(1)
        self.assertTrue(entry.is_animated)
        self.assertEqual(entry.anim_type, 9)

    def test_not_animated_with_leftover_nibble_keeps_raw_value(self):
        # A handful of real Black Gate shapes carry a nonzero animation
        # nibble despite is_animated being false -- Exult's
        # Frame_animator bails out immediately for these
        # (objs/animate.cc:273) and never consults the nibble, but Titan
        # still reports the raw value rather than discarding it.
        tfa_bytes = _make_tfa_bytes(
            flags_by_shape={2: 0x00},
            nibble_by_shape={2: 9},
        )
        tfa = U7TypeFlags.parse(tfa_bytes)
        entry = tfa.get(2)
        self.assertFalse(entry.is_animated)
        self.assertEqual(entry.anim_type, 9)

    def test_not_animated_with_zero_nibble_stays_unset(self):
        tfa_bytes = _make_tfa_bytes(
            flags_by_shape={3: 0x00},
            nibble_by_shape={},
        )
        tfa = U7TypeFlags.parse(tfa_bytes)
        entry = tfa.get(3)
        self.assertFalse(entry.is_animated)
        self.assertEqual(entry.anim_type, -1)

    def test_hi_and_lo_nibbles_in_same_byte_both_default_correctly(self):
        # Shapes 4 and 5 share animation-table byte index 2 (4//2==5//2).
        tfa_bytes = _make_tfa_bytes(
            flags_by_shape={4: FLAG_IS_ANIMATED, 5: FLAG_IS_ANIMATED},
            nibble_by_shape={4: 0, 5: 3},
            num_shapes=6,
        )
        tfa = U7TypeFlags.parse(tfa_bytes)
        self.assertEqual(tfa.get(4).anim_type, 0)
        self.assertEqual(tfa.get(5).anim_type, 3)


def _make_tfa_bytes_full(byte012_by_shape: dict) -> bytes:
    """Like ``_make_tfa_bytes`` but sets all three raw TFA bytes per shape."""
    base = bytearray(3 * 1024)
    for shnum, (b0, b1, b2) in byte012_by_shape.items():
        base[shnum * 3] = b0
        base[shnum * 3 + 1] = b1
        base[shnum * 3 + 2] = b2
    return bytes(base) + bytes(512)


class ContactEffectAliasTests(unittest.TestCase):
    def test_has_contact_effect_is_tfa1_bit4(self):
        tfa_bytes = _make_tfa_bytes_full({756: (0x00, 0x15, 0x00)})  # class=5, bit4 set
        entry = U7TypeFlags.parse(tfa_bytes).get(756)
        self.assertTrue(entry.has_contact_effect)
        self.assertEqual(entry.shape_class, 5)

    def test_is_poisonous_and_is_field_alias_has_contact_effect(self):
        tfa_bytes = _make_tfa_bytes_full({10: (0x00, 0x10, 0x00)})
        entry = U7TypeFlags.parse(tfa_bytes).get(10)
        self.assertTrue(entry.has_contact_effect)
        self.assertTrue(entry.is_poisonous)
        self.assertTrue(entry.is_field)

    def test_contact_effect_false_when_bit_unset(self):
        tfa_bytes = _make_tfa_bytes_full({11: (0x00, 0x05, 0x00)})  # class=5, bit4 clear
        entry = U7TypeFlags.parse(tfa_bytes).get(11)
        self.assertFalse(entry.has_contact_effect)
        self.assertFalse(entry.is_poisonous)
        self.assertFalse(entry.is_field)


class ShapeClassHelperTests(unittest.TestCase):
    CASES = [
        (U7TypeFlags.SHAPE_CLASS_QUALITY, "has_quality"),
        (U7TypeFlags.SHAPE_CLASS_QUANTITY, "has_quantity"),
        (U7TypeFlags.SHAPE_CLASS_HAS_HP, "has_hp"),
        (U7TypeFlags.SHAPE_CLASS_QUALITY_FLAGS, "has_quality_flags"),
        (U7TypeFlags.SHAPE_CLASS_CONTAINER, "is_container"),
        (U7TypeFlags.SHAPE_CLASS_EGG, "is_hatchable"),
        (U7TypeFlags.SHAPE_CLASS_SPELLBOOK, "is_spellbook"),
        (U7TypeFlags.SHAPE_CLASS_BARGE, "is_barge"),
        (U7TypeFlags.SHAPE_CLASS_VIRTUE_STONE, "is_virtue_stone"),
        (U7TypeFlags.SHAPE_CLASS_MONSTER, "is_monster"),
        (U7TypeFlags.SHAPE_CLASS_HUMAN, "is_human"),
        (U7TypeFlags.SHAPE_CLASS_BUILDING, "is_building"),
    ]

    def test_each_shape_class_sets_only_its_own_helper(self):
        all_props = [name for _, name in self.CASES]
        for shape_class, prop_name in self.CASES:
            with self.subTest(prop=prop_name):
                tfa_bytes = _make_tfa_bytes_full({20: (0x00, shape_class, 0x00)})
                entry = U7TypeFlags.parse(tfa_bytes).get(20)
                for other_prop in all_props:
                    expected = other_prop == prop_name
                    self.assertEqual(
                        getattr(entry, other_prop), expected,
                        f"{other_prop} for shape_class={shape_class}",
                    )

    def test_unusable_class_sets_no_helper(self):
        tfa_bytes = _make_tfa_bytes_full({21: (0x00, 0x00, 0x00)})
        entry = U7TypeFlags.parse(tfa_bytes).get(21)
        for _, prop_name in self.CASES:
            self.assertFalse(getattr(entry, prop_name))


if __name__ == "__main__":
    unittest.main()
