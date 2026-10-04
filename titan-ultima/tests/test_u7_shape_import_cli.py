"""Tests for creating a standalone U7 SHP from alphabetically sorted PNGs."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
import numpy as np

from titan.u7.cli import cmd_shape_import
from titan.u7.palette import U7Palette
from titan.u7.shape import U7Shape
from titan.u7.shape_import import quantize_u7_rgba_frame


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

    def _run_import(self, *, allow_cycling: bool = False, flat: bool = False) -> int:
        return cmd_shape_import(
            SimpleNamespace(
                directory=str(self.frames_dir),
                palette=str(self.palette_path),
                palette_index=0,
                output=str(self.output_path),
                game="bg",
                allow_cycling=allow_cycling,
                flat=flat,
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

    def test_uses_exult_studio_zero_origin_and_alpha_transparency(self) -> None:
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
        self.assertEqual((frame.origin_x, frame.origin_y), (0, 0))
        self.assertEqual((frame.hotspot_x_from_left, frame.hotspot_y_from_top), (1, 2))
        self.assertEqual(int(pixels[0, 0]), 0xFF)
        self.assertEqual(int(pixels[0, 1]), 1)

    def test_rejects_directory_without_png_frames(self) -> None:
        (self.frames_dir / "notes.txt").write_text("not a frame", encoding="utf-8")

        self.assertEqual(self._run_import(), 1)
        self.assertFalse(self.output_path.exists())

    def test_preserves_matching_indexed_png_with_duplicate_palette_colours(
        self,
    ) -> None:
        palette = U7Palette.from_file(str(self.palette_path))
        image = Image.new("P", (4, 1))
        image.putpalette([value for color in palette.colors for value in color])
        image.putdata([0, 224, 231, 255])
        image.save(self.frames_dir / "indexed.png")

        self.assertEqual(self._run_import(), 0)
        pixels = U7Shape.from_file(str(self.output_path)).frames[0].pixels
        np.testing.assert_array_equal(pixels, [[0, 224, 231, 255]])

    def test_matching_indexed_png_respects_transparency_on_other_indices(self) -> None:
        palette = U7Palette.from_file(str(self.palette_path))
        image = Image.new("P", (3, 1))
        image.putpalette([value for color in palette.colors for value in color])
        image.putdata([1, 224, 231])
        image.save(self.frames_dir / "indexed.png", transparency=224)

        self.assertEqual(self._run_import(), 0)
        pixels = U7Shape.from_file(str(self.output_path)).frames[0].pixels
        np.testing.assert_array_equal(pixels, [[1, 255, 231]])

    def test_quantizes_indexed_png_when_used_colours_do_not_match(self) -> None:
        palette = U7Palette.from_file(str(self.palette_path))
        image = Image.new("P", (1, 1), 224)
        colors = [value for color in palette.colors for value in color]
        colors[224 * 3 : 224 * 3 + 3] = [255, 0, 0]
        image.putpalette(colors)
        image.save(self.frames_dir / "indexed.png")

        self.assertEqual(self._run_import(), 0)
        pixels = U7Shape.from_file(str(self.output_path)).frames[0].pixels
        np.testing.assert_array_equal(pixels, [[1]])

    def test_quantizes_opaque_index_255_in_an_unrelated_png_palette(self) -> None:
        palette = U7Palette.from_file(str(self.palette_path))
        image = Image.new("P", (1, 1), 255)
        colors = [value for color in palette.colors for value in color]
        colors[255 * 3 : 255 * 3 + 3] = [255, 0, 0]
        image.putpalette(colors)
        image.save(self.frames_dir / "indexed.png")

        self.assertEqual(self._run_import(), 0)
        pixels = U7Shape.from_file(str(self.output_path)).frames[0].pixels
        np.testing.assert_array_equal(pixels, [[1]])

    def test_batched_conversion_matches_nearest_colour_and_alpha_threshold(
        self,
    ) -> None:
        palette = U7Palette.from_file(str(self.palette_path))
        rng = np.random.default_rng(42)
        rgba = rng.integers(0, 256, size=(17, 19, 4), dtype=np.uint8)
        image = Image.fromarray(rgba)
        rgb = rgba[:, :, :3].astype(np.int32)
        differences = rgb[:, :, None, :] - np.asarray(palette.colors[:224])
        expected = np.argmin(np.sum(differences * differences, axis=3), axis=2)
        expected[rgba[:, :, 3] < 128] = 255

        with patch("titan.u7.shape_import.U7_QUANTIZE_BATCH_PIXELS", 37):
            actual = quantize_u7_rgba_frame(image, palette)

        np.testing.assert_array_equal(actual, expected)

    def test_rgb_conversion_only_uses_cycling_colours_when_enabled(self) -> None:
        colors = bytearray(256 * 3)
        colors[224 * 3 : 224 * 3 + 3] = bytes((255, 0, 0))
        self.palette_path.write_bytes(colors)
        _write_rgba_frame(self.frames_dir / "frame.png", (255, 0, 0, 255))
        for allow_cycling, expected in ((False, 0), (True, 224)):
            with self.subTest(allow_cycling=allow_cycling):
                self.assertEqual(self._run_import(allow_cycling=allow_cycling), 0)
                pixels = U7Shape.from_file(str(self.output_path)).frames[0].pixels
                np.testing.assert_array_equal(pixels, np.full((3, 2), expected))

    def test_flat_import_writes_raw_8x8_frames_and_preserves_opaque_255(self) -> None:
        palette = U7Palette.from_file(str(self.palette_path))
        image = Image.new("P", (8, 8), 255)
        image.putpalette([value for color in palette.colors for value in color])
        image.save(self.frames_dir / "frame.png")
        self.assertEqual(self._run_import(flat=True), 0)
        self.assertEqual(self.output_path.read_bytes(), bytes([255] * 64))
        frame = U7Shape.from_file(str(self.output_path)).frames[0]
        self.assertTrue(frame.is_tile)

    def test_flat_import_rejects_wrong_size_or_transparent_source_before_writing(
        self,
    ) -> None:
        for size, alpha in (((9, 8), 255), ((8, 9), 255), ((8, 8), 0), ((8, 8), 128)):
            with self.subTest(size=size, alpha=alpha):
                Image.new("RGBA", size, (255, 0, 0, alpha)).save(
                    self.frames_dir / "frame.png"
                )
                self.output_path.write_bytes(b"keep existing shape")
                self.assertEqual(self._run_import(flat=True), 1)
                self.assertEqual(self.output_path.read_bytes(), b"keep existing shape")

    def test_normal_8x8_import_remains_an_rle_object(self) -> None:
        Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(self.frames_dir / "frame.png")
        self.assertEqual(self._run_import(), 0)
        frame = U7Shape.from_file(str(self.output_path)).frames[0]
        self.assertFalse(frame.is_tile)
        self.assertEqual((frame.width, frame.height), (8, 8))

    def test_cli_flat_flags_encode_and_insert_into_slot_zero(self) -> None:
        from typer.testing import CliRunner
        from titan.cli import app
        from titan.u7.flex import U7FlexArchive

        Image.new("RGB", (8, 8), (255, 0, 0)).save(self.frames_dir / "frame.png")
        archive_path = self.root / "SHAPES-copy.VGA"
        U7FlexArchive().save(str(archive_path))
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "u7",
                "shape-import",
                str(self.frames_dir),
                "-p",
                str(self.palette_path),
                "-o",
                str(self.output_path),
                "--flat",
            ],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        result = runner.invoke(
            app,
            [
                "u7",
                "flex-add-shape",
                str(archive_path),
                str(self.output_path),
                "--flat",
                "--in-place",
            ],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            U7FlexArchive.from_file(str(archive_path)).records, [bytes([1] * 64)]
        )

    def test_cli_allow_cycling_flag_selects_the_effect_colour(self) -> None:
        from typer.testing import CliRunner
        from titan.cli import app

        colors = bytearray(256 * 3)
        colors[224 * 3 : 224 * 3 + 3] = bytes((255, 0, 0))
        self.palette_path.write_bytes(colors)
        _write_rgba_frame(self.frames_dir / "frame.png", (255, 0, 0, 255))
        result = CliRunner().invoke(
            app,
            [
                "u7",
                "shape-import",
                str(self.frames_dir),
                "-p",
                str(self.palette_path),
                "-o",
                str(self.output_path),
                "--allow-cycling",
            ],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        np.testing.assert_array_equal(
            U7Shape.from_file(str(self.output_path)).frames[0].pixels,
            np.full((3, 2), 224),
        )

    def test_warns_above_72_pixels_without_resizing(self) -> None:
        for size in ((73, 2), (2, 73), (72, 72)):
            with self.subTest(size=size):
                Image.new("RGBA", size, (255, 0, 0, 255)).save(
                    self.frames_dir / "frame.png"
                )
                stderr = StringIO()
                with redirect_stderr(stderr):
                    self.assertEqual(self._run_import(), 0)
                frame = U7Shape.from_file(str(self.output_path)).frames[0]
                self.assertEqual((frame.width, frame.height), size)
                self.assertEqual("WARNING:" in stderr.getvalue(), max(size) > 72)
                if max(size) > 72:
                    self.assertIn(f"{size[0]}x{size[1]}", stderr.getvalue())
                    self.assertIn("72x72", stderr.getvalue())

    def test_accepts_full_screen_size_with_warning_without_resizing(self) -> None:
        Image.new("RGBA", (320, 200), (255, 0, 0, 255)).save(
            self.frames_dir / "frame.png"
        )
        stderr = StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(self._run_import(), 0)
        frame = U7Shape.from_file(str(self.output_path)).frames[0]
        self.assertEqual((frame.width, frame.height), (320, 200))
        self.assertIn("72x72", stderr.getvalue())

    def test_rejects_oversized_png_before_conversion_and_preserves_output(self) -> None:
        for size in ((321, 1), (1, 201), (256, 256), (321, 201)):
            with self.subTest(size=size):
                Image.new("RGBA", size, (255, 0, 0, 255)).save(
                    self.frames_dir / "oversized.png"
                )
                self.output_path.write_bytes(b"keep existing shape")
                stderr = StringIO()
                with patch("titan.u7.shape_import.quantize_u7_rgba_frame") as convert:
                    with redirect_stderr(stderr):
                        self.assertEqual(self._run_import(), 1)
                    convert.assert_not_called()
                self.assertEqual(self.output_path.read_bytes(), b"keep existing shape")
                self.assertIn("oversized.png", stderr.getvalue())
                self.assertIn(f"{size[0]}x{size[1]}", stderr.getvalue())
                self.assertIn("320x200", stderr.getvalue())

    def test_rejects_flex_archive_output_path(self) -> None:
        _write_rgba_frame(self.frames_dir / "frame.png", (255, 0, 0, 255))
        archive_path = self.root / "SHAPES.VGA"

        result = cmd_shape_import(
            SimpleNamespace(
                directory=str(self.frames_dir),
                palette=str(self.palette_path),
                palette_index=0,
                output=str(archive_path),
                game="bg",
            )
        )

        self.assertEqual(result, 1)
        self.assertFalse(archive_path.exists())

    def test_resolves_palette_from_selected_game_config(self) -> None:
        _write_rgba_frame(self.frames_dir / "frame.png", (255, 0, 0, 255))

        with patch(
            "titan.u7.cli._resolve_u7_paths",
            return_value=(str(self.root), str(self.palette_path)),
        ) as resolve_paths:
            result = cmd_shape_import(
                SimpleNamespace(
                    directory=str(self.frames_dir),
                    palette=None,
                    palette_index=0,
                    output=str(self.output_path),
                    game="si",
                )
            )

        self.assertEqual(result, 0)
        resolve_paths.assert_called_once_with("si")
        self.assertTrue(self.output_path.is_file())

    def test_explicit_palette_overrides_selected_game_config(self) -> None:
        _write_rgba_frame(self.frames_dir / "frame.png", (255, 0, 0, 255))

        with patch("titan.u7.cli._resolve_u7_paths") as resolve_paths:
            result = self._run_import()

        self.assertEqual(result, 0)
        resolve_paths.assert_not_called()

    def test_rejects_missing_explicit_and_configured_palette(self) -> None:
        _write_rgba_frame(self.frames_dir / "frame.png", (255, 0, 0, 255))

        with patch("titan.u7.cli._resolve_u7_paths", return_value=(None, None)):
            result = cmd_shape_import(
                SimpleNamespace(
                    directory=str(self.frames_dir),
                    palette=None,
                    palette_index=0,
                    output=str(self.output_path),
                    game="bg",
                )
            )

        self.assertEqual(result, 1)
        self.assertFalse(self.output_path.exists())


if __name__ == "__main__":
    unittest.main()
