"""Tests for exporting independent U9 actor animation clip sets."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.test_u9_animated_model_bundle import _animation, _model
from titan.u9.animation_selection import resolve_animation_selector
from titan.u9.animated_model_set import (
    ANIMATED_MODEL_SET_SCHEMA,
    U9AnimatedModelSetError,
    export_animated_model_set,
)


class AnimatedModelSetTests(unittest.TestCase):
    def test_exports_independent_clips_and_neutral_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_archive = root / "model.bin"
            animation_archive = root / "animation.bin"
            model_archive.write_bytes(b"model")
            animation_archive.write_bytes(b"animation")
            breathe = _animation()
            walk = replace(
                breathe,
                animation_id=174,
                source_name="avatar_walk_forward",
            )

            result = export_animated_model_set(
                _model(),
                (
                    (resolve_animation_selector("avatar:breathe"), breathe),
                    (resolve_animation_selector("avatar:walk"), walk),
                ),
                root / "set",
                model_archive_path=model_archive,
                animation_archive_path=animation_archive,
            )
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(manifest["schema"], ANIMATED_MODEL_SET_SCHEMA)
            self.assertEqual(manifest["model"]["actor"], "avatar")
            self.assertEqual(manifest["clip_count"], 2)
            self.assertEqual(
                [clip["animation_id"] for clip in manifest["clips"]], [172, 174]
            )
            self.assertEqual(
                manifest["clips"][1]["selection"]["movement_slot"], "forward"
            )
            self.assertFalse(manifest["timeline"]["authored"])
            self.assertEqual(len(result.clip_sidecar_paths), 2)
            self.assertEqual(len(result.clip_glb_paths), 2)
            self.assertTrue(all(path.is_file() for path in result.clip_sidecar_paths))
            self.assertTrue(all(path.is_file() for path in result.clip_glb_paths))

    def test_rejects_duplicate_or_mismatched_clip_ids(self) -> None:
        selection = resolve_animation_selector("avatar:breathe")
        animation = _animation()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_archive = root / "model.bin"
            animation_archive = root / "animation.bin"
            model_archive.write_bytes(b"model")
            animation_archive.write_bytes(b"animation")
            with self.assertRaisesRegex(U9AnimatedModelSetError, "duplicate"):
                export_animated_model_set(
                    _model(),
                    ((selection, animation), (selection, animation)),
                    root / "duplicate",
                    model_archive_path=model_archive,
                    animation_archive_path=animation_archive,
                )
            with self.assertRaisesRegex(U9AnimatedModelSetError, "but clip 173"):
                export_animated_model_set(
                    _model(),
                    ((selection, replace(animation, animation_id=173)),),
                    root / "mismatch",
                    model_archive_path=model_archive,
                    animation_archive_path=animation_archive,
                )


if __name__ == "__main__":
    unittest.main()
