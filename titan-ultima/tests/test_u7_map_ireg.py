"""Integration tests for titan.u7.map's IREG parsing: proves the wiring
between U7MapRenderer.parse_ireg_deep/parse_ireg and the shared
titan.u7.ireg decoder works end-to-end against a real byte stream on
disk, not just the decoder function in isolation (see test_u7_ireg.py).
"""

from __future__ import annotations

import os
import tempfile
import unittest

from titan.u7.map import U7MapRenderer
from titan.u7.typeflag import U7TypeFlags


def _tfa_with_quality_flags_shape(shape_num: int) -> U7TypeFlags:
    """Synthetic TFA marking one shape as shape_class=quality_flags (5),
    matching real shape 756 (caltrops) in both BG and SI."""
    base = bytearray(3 * 1024)
    base[shape_num * 3 + 1] = U7TypeFlags.SHAPE_CLASS_QUALITY_FLAGS
    return U7TypeFlags.parse(bytes(base) + bytes(512))


def _shape_frame_bytes(shape: int, frame: int = 0) -> tuple[int, int]:
    return shape & 0xFF, ((shape >> 8) & 0x03) | ((frame & 0x3F) << 2)


def _build_ireg_stream() -> bytes:
    """One invisible-caltrops simple entry + one invisible container
    holding one plain (non-invisible) child -- mirrors the real BG data
    shape used in titanWork.md's test scenarios.
    """
    shape_lo, shape_hi = _shape_frame_bytes(756)
    caltrops = bytes([6, 0x01, 0x02, shape_lo, shape_hi, 0x00, 0x01])

    c_shape_lo, c_shape_hi = _shape_frame_bytes(522)
    container_payload = bytes([
        0x01, 0x02,       # tile
        c_shape_lo, c_shape_hi,
        0x01, 0x00,       # type_val (has children)
        0x00,             # unused
        0x05,             # quality
        0x00,             # unused
        0x30,             # lift byte (lift=3)
        0x00,             # unused
        0x01,             # flag byte: invisible
    ])
    container_entry = bytes([12]) + container_payload

    child_shape_lo, child_shape_hi = _shape_frame_bytes(100)
    child_entry = bytes([6, 0x00, 0x00, child_shape_lo, child_shape_hi, 0x00, 0x00])
    end_of_container = bytes([0x01])

    return caltrops + container_entry + child_entry + end_of_container


class ParseIregDeepIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "u7ireg00")
        with open(self.path, "wb") as f:
            f.write(_build_ireg_stream())

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_two_top_level_objects(self):
        objs = U7MapRenderer.parse_ireg_deep(self.path, schunk_num=0)
        self.assertEqual(len(objs), 2)

    def test_invisible_caltrops_decoded_with_tfa(self):
        tfa = _tfa_with_quality_flags_shape(756)
        objs = U7MapRenderer.parse_ireg_deep(self.path, schunk_num=0, tfa=tfa)
        caltrops = objs[0]
        self.assertEqual(caltrops.shape, 756)
        self.assertTrue(caltrops.is_invisible)
        self.assertEqual(caltrops.tx, 1)
        self.assertEqual(caltrops.ty, 2)

    def test_caltrops_without_tfa_keeps_raw_quality_unreinterpreted(self):
        # Without a TFA shape_class lookup, simple entries can't be told
        # apart as quantity/quality_flags -- quality_raw is preserved but
        # not reinterpreted as a flag bit (graceful degradation).
        objs = U7MapRenderer.parse_ireg_deep(self.path, schunk_num=0)
        caltrops = objs[0]
        self.assertFalse(caltrops.is_invisible)
        self.assertEqual(caltrops.raw_quality, 0x01)

    def test_container_and_child_decoded(self):
        objs = U7MapRenderer.parse_ireg_deep(self.path, schunk_num=0)
        container = objs[1]
        self.assertEqual(container.shape, 522)
        self.assertTrue(container.is_invisible)
        self.assertEqual(container.quality, 5)
        self.assertEqual(container.tz, 3)
        self.assertEqual(len(container.children), 1)

    def test_child_does_not_inherit_container_invisibility(self):
        objs = U7MapRenderer.parse_ireg_deep(self.path, schunk_num=0)
        child = objs[1].children[0]
        self.assertEqual(child.shape, 100)
        self.assertFalse(child.is_invisible)

    def test_shallow_parse_ireg_wrapper_matches_top_level(self):
        deep = U7MapRenderer.parse_ireg_deep(self.path, schunk_num=0)
        shallow = U7MapRenderer.parse_ireg(self.path, schunk_num=0)
        self.assertEqual(len(shallow), len(deep))
        self.assertEqual([o.shape for o in shallow], [o.shape for o in deep])
        self.assertEqual(shallow[1].is_invisible, deep[1].is_invisible)

    def test_missing_file_returns_empty(self):
        self.assertEqual(
            U7MapRenderer.parse_ireg_deep(os.path.join(self.tmpdir.name, "nope"), 0), []
        )
        self.assertEqual(
            U7MapRenderer.parse_ireg(os.path.join(self.tmpdir.name, "nope"), 0), []
        )


if __name__ == "__main__":
    unittest.main()
