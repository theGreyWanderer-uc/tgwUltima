"""Tests for creating a standalone U7 SHP from alphabetically sorted PNGs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from titan.u7.cli import cmd_shape_import
from titan.u7.shape import U7Shape


def _write_test_palette(path: Path) -> None:
    colors = bytearray(256 * 3)
    colors[1 * 3 : 1 * 3 + 3] = bytes((255, 0, 0))
    colors[2 * 3 : 2 * 3 + 3] = bytes((0, 255, 0))
    colors[3 * 3 : 3 * 3 + 3] = bytes((0, 0, 255))
    path.write_bytes(colors)


def _write_rgba_frame(path: Path, color: tuple[int, int, int, int]) -> None:
    Image.new("RGBA", (2, 3), color).save(path)


class ShapeImportCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.frames_dir = self.root / "frames"
        self.frames_dir.mkdir()
        self.palette_path = self.root / "palette.pal"
        self.output_path = self.root / "actor.shp"
        _write_test_palette(self.palette_path)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _run_import(self) -> int:
        return cmd_shape_import(
            SimpleNamespace(
                directory=str(self.frames_dir),
                palette=str(self.palette_path),
                palette_index=0,
                output=str(self.output_path),
            )
        )

    def test_imports_png_frames_in_case_insensitive_filename_order(self) -> None:
        _write_rgba_frame(self.frames_dir / "frame_C.png", (0, 0, 255, 255))
        _write_rgba_frame(self.frames_dir / "Frame_a.PNG", (255, 0, 0, 255))
        _write_rgba_frame(self.frames_dir / "frame_b.png", (0, 255, 0, 255))

        self.assertEqual(self._run_import(), 0)

        shape = U7Shape.from_file(str(self.output_path))
        self.assertEqual(len(shape.frames), 3)
        self.assertTrue(all(frame.pixels is not None for frame in shape.frames))
        first_pixels: list[int] = []
        for frame in shape.frames:
            pixels = frame.pixels
            if pixels is None:
                self.fail("Imported frame has no pixel data")
            first_pixels.append(int(pixels[0, 0]))
        self.assertEqual(first_pixels, [1, 2, 3])

    def test_sorts_numeric_filename_parts_like_windows_explorer(self) -> None:
        _write_rgba_frame(self.frames_dir / "frame10.png", (0, 255, 0, 255))
        _write_rgba_frame(self.frames_dir / "frame2.png", (255, 0, 0, 255))

        self.assertEqual(self._run_import(), 0)

        shape = U7Shape.from_file(str(self.output_path))
        first_pixels: list[int] = []
        for frame in shape.frames:
            pixels = frame.pixels
            if pixels is None:
                self.fail("Imported frame has no pixel data")
            first_pixels.append(int(pixels[0, 0]))
        self.assertEqual(first_pixels, [1, 2])

    def test_uses_bottom_right_hotspot_and_alpha_transparency(self) -> None:
        image = Image.new("RGBA", (2, 3), (255, 0, 0, 255))
        image.putpixel((0, 0), (0, 0, 0, 0))
        image.save(self.frames_dir / "frame.png")

        self.assertEqual(self._run_import(), 0)

        frame = U7Shape.from_file(str(self.output_path)).frames[0]
        self.assertIsNotNone(frame.pixels)
        pixels = frame.pixels
        if pixels is None:
            self.fail("Imported frame has no pixel data")
        self.assertEqual((frame.width, frame.height), (2, 3))
        self.assertEqual((frame.xoff, frame.yoff), (1, 2))
        self.assertEqual(int(pixels[0, 0]), 0xFF)
        self.assertEqual(int(pixels[0, 1]), 1)

    def test_rejects_directory_without_png_frames(self) -> None:
        (self.frames_dir / "notes.txt").write_text("not a frame", encoding="utf-8")

        self.assertEqual(self._run_import(), 1)
        self.assertFalse(self.output_path.exists())

    def test_rejects_flex_archive_output_path(self) -> None:
        _write_rgba_frame(self.frames_dir / "frame.png", (255, 0, 0, 255))
        archive_path = self.root / "SHAPES.VGA"

        result = cmd_shape_import(
            SimpleNamespace(
                directory=str(self.frames_dir),
                palette=str(self.palette_path),
                palette_index=0,
                output=str(archive_path),
            )
        )

        self.assertEqual(result, 1)
        self.assertFalse(archive_path.exists())


if __name__ == "__main__":
    unittest.main()
