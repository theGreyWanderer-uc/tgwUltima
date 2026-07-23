"""Regression test for a real bug found while investigating why shape 177
(translucent + TFA frame-animated) exported gold instead of grey via
`shape-animate`: cmd_shape_animate's "frames" mode branch called
shape.to_pngs(pal) with no translucency arguments at all, even though
is_translucent/translucency were already computed correctly a few lines
earlier -- only the "cycle" mode branch (single-frame colour-cycle
preview) passed them through. This builds a minimal but real on-disk
STATIC dir (no real game files) to exercise cmd_shape_animate's actual
CLI wiring end-to-end, not just the pure shape_animation.py functions
already covered by test_u7_shape_animation.py.
"""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageSequence

from titan.u7.cli import cmd_shape_animate
from titan.u7.flex import U7FlexArchive
from titan.u7.shape import U7Shape

_SHAPE_NUM = 200  # > FIRST_OBJ_SHAPE (150), so it's treated as an RLE sprite
_TRANSLUCENT_INDEX = 254  # xfstart with a single BLENDS.DAT record
_RAW_PALETTE_COLOR = (0, 255, 0)  # what index 254 looks like if NOT blended
_BLEND_RGBA = (255, 0, 0, 255)  # BLENDS.DAT record for index 254
_EXPECTED_PREVIEW = tuple(_BLEND_RGBA[:3])  # composite_rgba_preview: raw, undivided blend RGB


def _write_tfa(static_dir: str) -> None:
    base = bytearray(3 * 1024)
    off = _SHAPE_NUM * 3
    base[off] = 0x04  # is_animated
    base[off + 2] = 0x80  # has_translucency
    anim_table = bytearray(512)
    byte_idx, is_hi = divmod(_SHAPE_NUM, 2)
    anim_table[byte_idx] = (1 << 4) if is_hi else 1  # explicit nibble = 1 (timesynched)
    with open(os.path.join(static_dir, "TFA.DAT"), "wb") as f:
        f.write(bytes(base) + bytes(anim_table))


def _write_palette(static_dir: str) -> None:
    data = bytearray(768)
    r, g, b = _RAW_PALETTE_COLOR
    # 6-bit palette bytes (0-63); index 254's raw colour, scaled down.
    data[_TRANSLUCENT_INDEX * 3 : _TRANSLUCENT_INDEX * 3 + 3] = bytes(
        [r >> 2, g >> 2, b >> 2]
    )
    archive = U7FlexArchive()
    archive.title = "Synthetic test palette"
    archive.records = [bytes(data)]
    archive.save(os.path.join(static_dir, "PALETTES.FLX"))


def _write_blends(static_dir: str) -> None:
    r, g, b, a = _BLEND_RGBA
    data = bytes([1, r, g, b, a])  # count=1, one (r,g,b,alpha) record
    with open(os.path.join(static_dir, "BLENDS.DAT"), "wb") as f:
        f.write(data)


def _write_shapes_vga(static_dir: str) -> str:
    shape = U7Shape()
    for step in range(2):  # 2 *distinct* frames -> genuine frame-sequence
        # animation; identical frames would get deduped by the GIF encoder.
        frame = U7Shape.Frame()
        frame.width, frame.height = 4, 4
        frame.xoff, frame.yoff = 1, 1
        pixels = np.full((4, 4), 0xFF, dtype=np.uint8)  # transparent
        pixels[1:3, 1:3] = _TRANSLUCENT_INDEX  # a translucent patch
        pixels[0, step] = 1  # a distinguishing opaque marker pixel per frame
        frame.pixels = pixels
        frame.is_tile = False
        shape.frames.append(frame)

    archive = U7FlexArchive()
    archive.title = "Synthetic test shape"
    archive.records = [b""] * _SHAPE_NUM + [shape.to_bytes()]
    path = os.path.join(static_dir, "SHAPES.VGA")
    archive.save(path)
    return path


class ShapeAnimateFramesModeTranslucencyTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.static_dir = self.tmpdir.name
        _write_tfa(self.static_dir)
        _write_palette(self.static_dir)
        _write_blends(self.static_dir)
        self.shapes_vga = _write_shapes_vga(self.static_dir)
        self.gif_path = os.path.join(self.static_dir, "out.gif")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run(self):
        rc = cmd_shape_animate(
            SimpleNamespace(
                file=self.shapes_vga,
                palette=os.path.join(self.static_dir, "PALETTES.FLX"),
                output=self.gif_path,
                shape=_SHAPE_NUM,
                frame=None,
                static=self.static_dir,
                mode="auto",
                steps=None,
                duration=None,
                hour_start=None,
            )
        )
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(self.gif_path))

    def _dominant_colors(self, frame_img: Image.Image) -> set:
        arr = np.array(frame_img.convert("RGBA"))
        mask = arr[..., 3] > 0
        return {tuple(c) for c in arr[mask][:, :3].tolist()}

    def test_uses_frames_mode(self):
        # Sanity check: this fixture must exercise the "frames" branch
        # (2 real TFA-animated frames), not the "cycle" branch, or the
        # test wouldn't be covering the bug at all.
        self._run()
        with Image.open(self.gif_path) as img:
            n_frames = getattr(img, "n_frames", 1)
        self.assertGreaterEqual(n_frames, 2)

    def test_translucent_pixels_are_blend_composited_not_raw_palette(self):
        self._run()
        with Image.open(self.gif_path) as img:
            per_frame_colors = [
                self._dominant_colors(frame) for frame in ImageSequence.Iterator(img)
            ]
        for i, colors in enumerate(per_frame_colors):
            with self.subTest(frame=i):
                self.assertNotIn(
                    _RAW_PALETTE_COLOR, colors,
                    "translucent pixel rendered as raw unblended palette colour "
                    "(the frames-mode to_pngs() call is missing translucency args)",
                )
                # GIF palette quantization can shift the exact value by a
                # step or two; allow a small tolerance instead of exact match.
                self.assertTrue(
                    any(
                        all(abs(c - e) <= 4 for c, e in zip(color, _EXPECTED_PREVIEW))
                        for color in colors
                    ),
                    f"no colour near expected blend preview {_EXPECTED_PREVIEW} in {colors}",
                )


if __name__ == "__main__":
    unittest.main()
