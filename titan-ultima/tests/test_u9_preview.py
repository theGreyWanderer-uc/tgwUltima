"""Tests for titan.u9.preview's optional pyvista-based render.

``render_preview()`` depends on ``pyvista``/``vtk``, which are not core
`titan-ultima` dependencies -- see the module docstring for why (and
why it's driven through ``vtkOBJImporter`` rather than a plain
``pyvista.read()``: confirmed on a real 16-material export that the
naive approach renders only one material's texture and leaves every
other material flat gray). Actual rendered pixel output (both the
default-angle and 180-degree-rotated shots -- confirmed on a real
model that the rotated shot shows the front of a figure whose default
angle showed its back) is validated manually against real model-export
folders, not re-checked here -- these tests only cover error handling
that doesn't require a real render.
"""

from __future__ import annotations

import tempfile
import unittest

from titan.u9.preview import PreviewError, render_preview


class RenderPreviewErrorTests(unittest.TestCase):
    def test_missing_obj_raises_preview_error(self) -> None:
        # checked before pyvista is even imported, so this raises the same way
        # regardless of whether the optional dependency is installed.
        with tempfile.TemporaryDirectory() as empty_dir:
            with self.assertRaises(PreviewError):
                render_preview(empty_dir)


if __name__ == "__main__":
    unittest.main()
