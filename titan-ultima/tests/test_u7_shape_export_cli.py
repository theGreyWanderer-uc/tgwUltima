"""Regression test for cmd_shape_export auto-detecting TFA translucency.

Before this fix, --shape N + --static DIR gave shape-export everything it
needed to know a shape is TFA-translucent, but it never actually looked it
up -- has_translucency was only ever set from the literal --translucent
flag. That silently exported translucent shapes (e.g. real shape 177) with
raw, unblended palette colours instead of the real BLENDS.DAT composite.
shape-animate already auto-detected this correctly; shape-export now does
too.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np
from PIL import Image

from titan.u7.cli import cmd_shape_export
from titan.u7.flex import U7FlexArchive
from titan.u7.shape import U7Shape

_TRANSLUCENT_SHAPE = 200  # > FIRST_OBJ_SHAPE (150), so it's an RLE sprite
_PLAIN_SHAPE = 201
_TRANSLUCENT_INDEX = 254  # xfstart with a single BLENDS.DAT record
_RAW_PALETTE_COLOR = (0, 255, 0)  # what index 254 looks like if NOT blended
_BLEND_RGBA = (255, 0, 0, 255)  # BLENDS.DAT record for index 254
_EXPECTED_PREVIEW = tuple(_BLEND_RGBA[:3])  # composite_rgba_preview: raw, undivided blend RGB


def _write_tfa(static_dir: str) -> None:
    base = bytearray(3 * 1024)
    off = _TRANSLUCENT_SHAPE * 3
    base[off + 2] = 0x80  # has_translucency
    # _PLAIN_SHAPE's record is left all-zero -- not translucent.
    with open(os.path.join(static_dir, "TFA.DAT"), "wb") as f:
        f.write(bytes(base) + bytes(512))


def _write_palette(static_dir: str) -> None:
    data = bytearray(768)
    r, g, b = _RAW_PALETTE_COLOR
    data[_TRANSLUCENT_INDEX * 3 : _TRANSLUCENT_INDEX * 3 + 3] = bytes(
        [r >> 2, g >> 2, b >> 2]
    )
    archive = U7FlexArchive()
    archive.title = "Synthetic test palette"
    archive.records = [bytes(data)]
    archive.save(os.path.join(static_dir, "PALETTES.FLX"))


def _write_blends(static_dir: str) -> None:
    r, g, b, a = _BLEND_RGBA
    with open(os.path.join(static_dir, "BLENDS.DAT"), "wb") as f:
        f.write(bytes([1, r, g, b, a]))


def _make_frame() -> U7Shape.Frame:
    frame = U7Shape.Frame()
    frame.width, frame.height = 4, 4
    frame.xoff, frame.yoff = 1, 1
    pixels = np.full((4, 4), 0xFF, dtype=np.uint8)  # transparent
    pixels[1:3, 1:3] = _TRANSLUCENT_INDEX
    frame.pixels = pixels
    frame.is_tile = False
    return frame


def _write_shapes_vga(static_dir: str) -> str:
    shape_a = U7Shape()
    shape_a.frames.append(_make_frame())
    shape_b = U7Shape()
    shape_b.frames.append(_make_frame())

    archive = U7FlexArchive()
    archive.title = "Synthetic test shapes"
    records = [b""] * (_PLAIN_SHAPE + 1)
    records[_TRANSLUCENT_SHAPE] = shape_a.to_bytes()
    records[_PLAIN_SHAPE] = shape_b.to_bytes()
    archive.records = records
    path = os.path.join(static_dir, "SHAPES.VGA")
    archive.save(path)
    return path


class ShapeExportAutoDetectTranslucencyTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.static_dir = self.tmpdir.name
        _write_tfa(self.static_dir)
        _write_palette(self.static_dir)
        _write_blends(self.static_dir)
        self.shapes_vga = _write_shapes_vga(self.static_dir)
        self.outdir = os.path.join(self.static_dir, "out")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run(self, shape_num: int, *, translucent: bool = False, static: bool = True):
        return cmd_shape_export(
            SimpleNamespace(
                file=self.shapes_vga,
                palette=os.path.join(self.static_dir, "PALETTES.FLX"),
                output=self.outdir,
                shape=shape_num,
                frame=None,
                indexed=False,
                cycle_phase=0,
                translucent=translucent,
                translucent_bg=None,
                static=self.static_dir if static else None,
            )
        )

    def _colors(self) -> set:
        path = os.path.join(self.outdir, f"shape_{self._exported_shape:04d}_f0000.png")
        img = Image.open(path).convert("RGBA")
        arr = np.array(img)
        mask = arr[..., 3] > 0
        return {tuple(c) for c in arr[mask][:, :3].tolist()}

    def test_auto_detects_translucent_shape_without_flag(self):
        self._exported_shape = _TRANSLUCENT_SHAPE
        rc = self._run(_TRANSLUCENT_SHAPE)
        self.assertEqual(rc, 0)
        colors = self._colors()
        self.assertNotIn(
            _RAW_PALETTE_COLOR, colors,
            "translucent shape exported with raw unblended palette colour "
            "even though --static + --shape gave enough info to auto-detect it",
        )
        self.assertTrue(
            any(
                all(abs(c - e) <= 4 for c, e in zip(color, _EXPECTED_PREVIEW))
                for color in colors
            ),
            f"no colour near expected blend preview {_EXPECTED_PREVIEW} in {colors}",
        )

    def test_plain_shape_not_falsely_treated_as_translucent(self):
        self._exported_shape = _PLAIN_SHAPE
        rc = self._run(_PLAIN_SHAPE)
        self.assertEqual(rc, 0)
        colors = self._colors()
        self.assertIn(_RAW_PALETTE_COLOR, colors)

    def test_without_static_dir_falls_back_to_raw_palette(self):
        # No TFA data available at all -- can't auto-detect, matches the
        # pre-existing (documented) behaviour for standalone .shp input.
        self._exported_shape = _TRANSLUCENT_SHAPE
        rc = self._run(_TRANSLUCENT_SHAPE, static=False)
        self.assertEqual(rc, 0)
        colors = self._colors()
        self.assertIn(_RAW_PALETTE_COLOR, colors)

    def test_explicit_translucent_flag_still_works(self):
        self._exported_shape = _TRANSLUCENT_SHAPE
        rc = self._run(_TRANSLUCENT_SHAPE, translucent=True)
        self.assertEqual(rc, 0)
        colors = self._colors()
        self.assertNotIn(_RAW_PALETTE_COLOR, colors)


if __name__ == "__main__":
    unittest.main()
