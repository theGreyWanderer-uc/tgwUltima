"""Tests for titan.u7.ireg: the shared IREG per-instance object-flag
decoder, ported byte-for-byte from Exult's Game_map::read_ireg_objects
(gamemap.cc:900-1126) and Get_quality_flags (gamemap.cc:890-893).

Covers the 11 scenarios from titanWork.md's Object model, verified
against real Exult source during this session.
"""

from __future__ import annotations

import unittest

from titan.u7.ireg import (
    U7ObjectFlags,
    decode_ireg_payload,
    get_quality_flags,
    nibble_swap,
    read_lift,
)
from titan.u7.typeflag import U7TypeFlags

QUALITY_FLAGS = U7TypeFlags.SHAPE_CLASS_QUALITY_FLAGS  # 5
QUANTITY = U7TypeFlags.SHAPE_CLASS_QUANTITY  # 3
CONTAINER = U7TypeFlags.SHAPE_CLASS_CONTAINER  # 6


def _simple_payload(quality_byte: int, lift_nibble: int = 0, shape: int = 756, frame: int = 0) -> bytes:
    """Build a 6-byte simple IREG entry payload (testlen=6, no extension)."""
    b2 = shape & 0xFF
    b3 = ((shape >> 8) & 0x03) | ((frame & 0x3F) << 2)
    lift_byte = (lift_nibble & 0x0F) << 4
    return bytes([0x00, 0x00, b2, b3, lift_byte, quality_byte])


def _ten_byte_payload(quality_byte: int, temp_bit: int, shape: int = 756, frame: int = 0) -> bytes:
    """Build a 10-byte simple IREG entry payload (testlen=10)."""
    base = bytearray(_simple_payload(quality_byte, shape=shape, frame=frame))
    base += bytearray(4)
    base[6] = temp_bit & 0x01
    return bytes(base)


def _container_payload(quality: int, flag_byte: int, lift_nibble: int = 0, shape: int = 522, has_children: bool = True) -> bytes:
    """Build a 12-byte container IREG entry payload (testlen=12)."""
    buf = bytearray(12)
    buf[2] = shape & 0xFF
    buf[3] = (shape >> 8) & 0x03
    type_val = 1 if has_children else 0
    buf[4] = type_val & 0xFF
    buf[5] = (type_val >> 8) & 0xFF
    buf[7] = quality
    buf[9] = (lift_nibble & 0x0F) << 4
    buf[11] = flag_byte
    return bytes(buf)


def _body_payload(testlen: int, quality: int, flag_byte: int, lift_nibble: int = 0, shape: int = 415) -> bytes:
    """Build a 13-byte (extbody=1) or 14-byte (extbody=0) body payload."""
    extbody = 1 if testlen == 13 else 0
    buf = bytearray(testlen)
    buf[2] = shape & 0xFF
    buf[3] = (shape >> 8) & 0x03
    buf[4] = 1  # type_val low byte (has children)
    buf[7] = quality
    buf[9 + extbody] = (lift_nibble & 0x0F) << 4
    buf[11 + extbody] = flag_byte
    return bytes(buf)


class NibbleAndLiftTests(unittest.TestCase):
    def test_nibble_swap(self):
        self.assertEqual(nibble_swap(0x50), 0x05)
        self.assertEqual(nibble_swap(0xA3), 0x3A)

    def test_read_lift_non_extended_masks_to_4_bits(self):
        self.assertEqual(read_lift(0x53, extended_lift=False), 0x05)

    def test_read_lift_extended_uses_full_swapped_byte(self):
        self.assertEqual(read_lift(0x53, extended_lift=True), 0x35)


class GetQualityFlagsTests(unittest.TestCase):
    def test_bit0_invisible_bit3_okay_to_take(self):
        self.assertEqual(get_quality_flags(0x01), U7ObjectFlags.INVISIBLE)
        self.assertEqual(get_quality_flags(0x08), U7ObjectFlags.OKAY_TO_TAKE)
        self.assertEqual(
            get_quality_flags(0x09), U7ObjectFlags.INVISIBLE | U7ObjectFlags.OKAY_TO_TAKE
        )
        self.assertEqual(get_quality_flags(0x00), U7ObjectFlags.NONE)

    def test_other_bits_ignored(self):
        self.assertEqual(get_quality_flags(0xF6), U7ObjectFlags.NONE)


class InvisibleCaltropsTests(unittest.TestCase):
    """Scenario 1+2: shape 756 (caltrops), simple quality_flags class."""

    def test_invisible_caltrops(self):
        payload = _simple_payload(quality_byte=0x01, shape=756)
        result = decode_ireg_payload(
            payload, entlen=6, extended=False, extended_lift=False,
            shape_class=QUALITY_FLAGS,
        )
        self.assertEqual(result.shape, 756)
        self.assertTrue(result.object_flags & U7ObjectFlags.INVISIBLE)
        self.assertEqual(result.quality, 0)
        self.assertEqual(result.raw_quality, 0x01)

    def test_normal_placement_same_shape_byte_0x00(self):
        payload = _simple_payload(quality_byte=0x00, shape=756)
        result = decode_ireg_payload(
            payload, entlen=6, extended=False, extended_lift=False,
            shape_class=QUALITY_FLAGS,
        )
        self.assertFalse(result.object_flags & U7ObjectFlags.INVISIBLE)
        self.assertEqual(result.quality, 0)


class ContainerFlagTests(unittest.TestCase):
    """Scenario 3+4b: invisible chest / okay_to_take on a container."""

    def test_invisible_container(self):
        payload = _container_payload(quality=5, flag_byte=0x01)
        result = decode_ireg_payload(
            payload, entlen=12, extended=False, extended_lift=False,
            shape_class=CONTAINER,
        )
        self.assertTrue(result.object_flags & U7ObjectFlags.INVISIBLE)
        self.assertEqual(result.quality, 5)  # container quality untouched by flag byte
        self.assertEqual(result.raw_flag_byte, 0x01)

    def test_okay_to_take_container(self):
        payload = _container_payload(quality=0, flag_byte=0x08)
        result = decode_ireg_payload(
            payload, entlen=12, extended=False, extended_lift=False,
            shape_class=CONTAINER,
        )
        self.assertTrue(result.object_flags & U7ObjectFlags.OKAY_TO_TAKE)
        self.assertFalse(result.object_flags & U7ObjectFlags.INVISIBLE)

    def test_container_lift_decodes(self):
        payload = _container_payload(quality=0, flag_byte=0x00, lift_nibble=7)
        result = decode_ireg_payload(
            payload, entlen=12, extended=False, extended_lift=False,
            shape_class=CONTAINER,
        )
        self.assertEqual(result.lift, 7)


class QuantityMaskingTests(unittest.TestCase):
    """Scenario 4a+5: okay_to_take + quality masking on quantity-class simples."""

    def test_bit7_set_gives_okay_to_take_and_masks_quality(self):
        payload = _simple_payload(quality_byte=0x80 | 20)  # 20 arrows, okay_to_take
        result = decode_ireg_payload(
            payload, entlen=6, extended=False, extended_lift=False,
            shape_class=QUANTITY,
        )
        self.assertTrue(result.object_flags & U7ObjectFlags.OKAY_TO_TAKE)
        self.assertEqual(result.quality, 20)
        self.assertEqual(result.raw_quality, 0x80 | 20)

    def test_bit7_clear_no_okay_to_take_quality_unmasked(self):
        payload = _simple_payload(quality_byte=20)
        result = decode_ireg_payload(
            payload, entlen=6, extended=False, extended_lift=False,
            shape_class=QUANTITY,
        )
        self.assertFalse(result.object_flags & U7ObjectFlags.OKAY_TO_TAKE)
        self.assertEqual(result.quality, 20)

    def test_quantity_never_invisible(self):
        # Even with bit0 set (which would mean "invisible" for quality_flags),
        # quantity-class only ever inspects bit7 -- never sets invisible.
        payload = _simple_payload(quality_byte=0x81)
        result = decode_ireg_payload(
            payload, entlen=6, extended=False, extended_lift=False,
            shape_class=QUANTITY,
        )
        self.assertFalse(result.object_flags & U7ObjectFlags.INVISIBLE)


class TemporaryTenByteTests(unittest.TestCase):
    """Scenario 6: temporary flag on a 10-byte simple object, incl. the
    quality_flags-clobbers-temporary quirk (gamemap.cc:1014-1018 fully
    reassigns oflags, discarding the temporary bit set at line 980-982)."""

    def test_temporary_bit_set(self):
        payload = _ten_byte_payload(quality_byte=0, temp_bit=1)
        result = decode_ireg_payload(
            payload, entlen=10, extended=False, extended_lift=False,
            shape_class=None,
        )
        self.assertTrue(result.object_flags & U7ObjectFlags.TEMPORARY)

    def test_temporary_bit_clear(self):
        payload = _ten_byte_payload(quality_byte=0, temp_bit=0)
        result = decode_ireg_payload(
            payload, entlen=10, extended=False, extended_lift=False,
            shape_class=None,
        )
        self.assertFalse(result.object_flags & U7ObjectFlags.TEMPORARY)

    def test_quality_flags_class_discards_temporary_bit(self):
        payload = _ten_byte_payload(quality_byte=0x00, temp_bit=1)
        result = decode_ireg_payload(
            payload, entlen=10, extended=False, extended_lift=False,
            shape_class=QUALITY_FLAGS,
        )
        self.assertFalse(result.object_flags & U7ObjectFlags.TEMPORARY)


class BodyFlagOffsetTests(unittest.TestCase):
    """Scenario 7: body flag/quality/lift offsets for 13-byte (extended,
    2-byte-NPC/compact) vs 14-byte (legacy, 1-byte-NPC) forms."""

    def test_13_byte_body_offsets(self):
        payload = _body_payload(13, quality=3, flag_byte=0x09, lift_nibble=2)
        result = decode_ireg_payload(
            payload, entlen=13, extended=False, extended_lift=False,
            shape_class=None,
        )
        self.assertEqual(result.quality, 3)
        self.assertEqual(result.lift, 2)
        self.assertEqual(result.raw_flag_byte, 0x09)
        self.assertTrue(result.object_flags & U7ObjectFlags.INVISIBLE)
        self.assertTrue(result.object_flags & U7ObjectFlags.OKAY_TO_TAKE)

    def test_14_byte_body_offsets(self):
        payload = _body_payload(14, quality=3, flag_byte=0x08, lift_nibble=2)
        result = decode_ireg_payload(
            payload, entlen=14, extended=False, extended_lift=False,
            shape_class=None,
        )
        self.assertEqual(result.quality, 3)
        self.assertEqual(result.lift, 2)
        self.assertEqual(result.raw_flag_byte, 0x08)
        self.assertTrue(result.object_flags & U7ObjectFlags.OKAY_TO_TAKE)

    def test_13_vs_14_byte_use_different_flag_offsets(self):
        # Same flag_byte value placed at the 13-byte offset should NOT be
        # picked up by a 14-byte decode of equivalent-length data, proving
        # the offsets are genuinely different (not accidentally aliased).
        payload13 = _body_payload(13, quality=0, flag_byte=0x01)
        payload14 = bytearray(_body_payload(14, quality=0, flag_byte=0x00))
        payload14[11] = 0x01  # legacy 14-byte offset (extbody=0)
        r13 = decode_ireg_payload(payload13, entlen=13, extended=False, extended_lift=False)
        r14 = decode_ireg_payload(bytes(payload14), entlen=14, extended=False, extended_lift=False)
        self.assertTrue(r13.object_flags & U7ObjectFlags.INVISIBLE)
        self.assertTrue(r14.object_flags & U7ObjectFlags.INVISIBLE)


class NestedContainerInheritanceTests(unittest.TestCase):
    """Scenario 8: invisibility must not be inherited by container contents."""

    def test_invisible_container_child_inherit_flags_strips_invisible(self):
        payload = _container_payload(quality=0, flag_byte=0x09)  # invisible + okay_to_take
        result = decode_ireg_payload(
            payload, entlen=12, extended=False, extended_lift=False,
            shape_class=CONTAINER,
        )
        self.assertTrue(result.object_flags & U7ObjectFlags.INVISIBLE)
        self.assertFalse(result.child_inherit_flags & U7ObjectFlags.INVISIBLE)
        self.assertTrue(result.child_inherit_flags & U7ObjectFlags.OKAY_TO_TAKE)

    def test_simple_child_inherits_okay_to_take_from_parent(self):
        # A plain (non-quantity, non-quality_flags) simple child inside a
        # container inherits whatever flags the parent passed down.
        parent_payload = _container_payload(quality=0, flag_byte=0x08)
        parent = decode_ireg_payload(
            parent_payload, entlen=12, extended=False, extended_lift=False,
            shape_class=CONTAINER,
        )
        child_payload = _simple_payload(quality_byte=0)
        child = decode_ireg_payload(
            child_payload, entlen=6, extended=False, extended_lift=False,
            inherited_flags=parent.child_inherit_flags,
            shape_class=None,  # plain/unusable class -- no override
        )
        self.assertTrue(child.object_flags & U7ObjectFlags.OKAY_TO_TAKE)


class ExtendedRecordTests(unittest.TestCase):
    """Scenario 9: extended shape (2-byte shape#) and extended lift records."""

    def test_extended_shape_shifts_offsets(self):
        # entlen=7 (testlen=6, extended shape adds 1 byte): tx,ty,shlo,shhi,frame,lift,quality
        shape = 1500
        payload = bytes([0, 0, shape & 0xFF, (shape >> 8) & 0xFF, 3, 0x50, 0x02])
        result = decode_ireg_payload(
            payload, entlen=7, extended=True, extended_lift=False,
            shape_class=None,
        )
        self.assertEqual(result.shape, 1500)
        self.assertEqual(result.frame, 3)
        self.assertEqual(result.lift, 5)
        self.assertEqual(result.quality, 2)
        self.assertTrue(result.is_extended)

    def test_extended_lift_widens_lift_field(self):
        payload = _simple_payload(quality_byte=0, lift_nibble=0)
        buf = bytearray(payload)
        buf[4] = 0x53  # nibble_swap(0x53) = 0x35, unmasked under extended_lift
        result = decode_ireg_payload(
            bytes(buf), entlen=6, extended=False, extended_lift=True,
            shape_class=None,
        )
        self.assertEqual(result.lift, 0x35)


class LosslessPreservationTests(unittest.TestCase):
    """Scenario 10: raw bytes round-trip losslessly alongside decoded values."""

    def test_raw_quality_and_flag_byte_preserved(self):
        payload = _container_payload(quality=42, flag_byte=0x0D)
        result = decode_ireg_payload(
            payload, entlen=12, extended=False, extended_lift=False,
            shape_class=CONTAINER,
        )
        self.assertEqual(result.raw_quality, 42)
        self.assertEqual(result.raw_flag_byte, 0x0D)
        self.assertEqual(result.record_length, 12)
        self.assertFalse(result.is_extended)

    def test_simple_entry_has_no_raw_flag_byte(self):
        payload = _simple_payload(quality_byte=9)
        result = decode_ireg_payload(
            payload, entlen=6, extended=False, extended_lift=False,
            shape_class=None,
        )
        self.assertIsNone(result.raw_flag_byte)
        self.assertEqual(result.record_length, 6)


class InvalidPayloadTests(unittest.TestCase):
    def test_too_short_payload_returns_none(self):
        self.assertIsNone(
            decode_ireg_payload(b"\x00\x00", entlen=6, extended=False, extended_lift=False)
        )

    def test_unknown_testlen_returns_none(self):
        payload = bytes(9)
        self.assertIsNone(
            decode_ireg_payload(payload, entlen=9, extended=False, extended_lift=False)
        )


if __name__ == "__main__":
    unittest.main()
