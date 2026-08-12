"""Regression tests for frame-aware U7 map object footprints."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from titan.u7.flex import U7FlexArchive
from titan.u7.map import U7MapRenderer


SHAPE_376 = 376


def build_map_test_rle_shape_record(frame_count: int) -> bytes:
    """Build a header-only RLE shape with a searchable real frame count."""
    first_offset = 4 + frame_count * 4
    return struct.pack("<I", first_offset) + struct.pack(
        f"<{frame_count}I", *([first_offset] * frame_count)
    )


def build_map_test_tfa() -> bytes:
    """Build TFA metadata containing SI door shape 376 as 1x4x5."""
    data = bytearray(3 * 1024 + 512)
    offset = SHAPE_376 * 3
    data[offset : offset + 3] = bytes((0xA8, 0x22, 0x18))
    return bytes(data)


class MapShapeFrameBindingTests(unittest.TestCase):
    def test_renderer_uses_effective_archive_count_for_bit5_reflection(self):
        for frame_count, expected in ((32, (4, 1, 5)), (40, (1, 4, 5))):
            with (
                self.subTest(frame_count=frame_count),
                tempfile.TemporaryDirectory() as tmp,
            ):
                static_dir = Path(tmp)
                (static_dir / "TFA.DAT").write_bytes(build_map_test_tfa())

                archive = U7FlexArchive()
                archive.records = [b""] * (SHAPE_376 + 1)
                archive.records[SHAPE_376] = build_map_test_rle_shape_record(
                    frame_count
                )
                (static_dir / "SHAPES.VGA").write_bytes(archive.to_bytes())

                entry = U7MapRenderer(str(static_dir)).tfa.get(SHAPE_376)

                if entry is None:
                    self.fail("Shape 376 missing from renderer TFA metadata")
                self.assertEqual(entry.footpad_tiles(32), expected)


if __name__ == "__main__":
    unittest.main()
