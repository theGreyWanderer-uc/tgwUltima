"""Tests for complete compatibility-labelled U9 Avatar animation libraries."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.test_u9_animated_model_bundle import _animation, _model
from titan.u9.animation import U9AnimationPart
from titan.u9.avatar_animation_library import (
    AVATAR_ANIMATION_LIBRARY_SCHEMA,
    U9AvatarAnimationLibraryError,
    export_avatar_animation_library,
)
from titan.u9.motion_ids import U9MotionIds


MOTION_IDS = U9MotionIds.parse(
    """
    HUMANOID_IDLE_BREATHE_AVATAR = 172,
    HUMANOID_MOVEMENT_WALKFOWARD_AVATAR_NONE = 174,
    HUMANOID_COMBAT_ATTACK_AVATAR_BOWAA = 201,
    HUMANOID_IDLE_IDLE_AVATAR_NONEA = 202,
    DRAGON_DRAGON_FLY_FLAP = 840,
    """
)


class AvatarAnimationLibraryTests(unittest.TestCase):
    def test_exports_named_compatible_clips_and_reports_exclusions(self) -> None:
        breathe = _animation()
        walk = replace(breathe, animation_id=174, source_name="avatar_walk")
        incompatible = replace(
            breathe,
            animation_id=201,
            parts=(U9AnimationPart(900, "OTHER", breathe.parts[0].frames),),
        )
        unrelated = replace(breathe, animation_id=840, source_name="dragon")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_archive = root / "model.bin"
            animation_archive = root / "animation.bin"
            motion_table = root / "motions.txt"
            model_archive.write_bytes(b"model")
            animation_archive.write_bytes(b"animation")
            motion_table.write_text("motion table", encoding="ascii")

            result = export_avatar_animation_library(
                _model(),
                (breathe, walk, incompatible, unrelated),
                MOTION_IDS,
                root / "library",
                model_archive_path=model_archive,
                animation_archive_path=animation_archive,
                motion_table_path=motion_table,
                include_glb=False,
            )
            document = json.loads(
                result.export.sidecar_path.read_text(encoding="utf-8")
            )

            self.assertEqual(
                document["library"]["schema"], AVATAR_ANIMATION_LIBRARY_SCHEMA
            )
            self.assertEqual(result.candidate_motion_count, 4)
            self.assertEqual(result.exported_clip_count, 2)
            self.assertEqual(result.unused_motion_ids, (202,))
            self.assertEqual(result.incompatible_motion_ids, (201,))
            self.assertEqual(result.category_counts, (("idle", 1), ("movement", 1)))
            self.assertEqual(
                [clip["animation_id"] for clip in document["clips"]], [172, 174]
            )
            self.assertEqual(
                document["clips"][0]["catalogue"]["known_state"], "breathe"
            )
            self.assertEqual(
                document["clips"][1]["catalogue"]["known_aliases"],
                ["avatar:walk", "avatar:walk-forward"],
            )
            self.assertFalse(document["library"]["timeline"]["authored"])

    def test_category_filter_is_case_insensitive_and_rejects_empty_results(
        self,
    ) -> None:
        breathe = _animation()
        walk = replace(breathe, animation_id=174, source_name="avatar_walk")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_archive = root / "model.bin"
            animation_archive = root / "animation.bin"
            model_archive.write_bytes(b"model")
            animation_archive.write_bytes(b"animation")

            result = export_avatar_animation_library(
                _model(),
                (breathe, walk),
                MOTION_IDS,
                root / "movement",
                model_archive_path=model_archive,
                animation_archive_path=animation_archive,
                categories=("MOVEMENT",),
                include_glb=False,
            )
            self.assertEqual(result.exported_clip_count, 1)
            self.assertEqual(result.category_counts, (("movement", 1),))

            with self.assertRaisesRegex(
                U9AvatarAnimationLibraryError, "no repose animation"
            ):
                export_avatar_animation_library(
                    _model(),
                    (breathe, walk),
                    MOTION_IDS,
                    root / "missing",
                    model_archive_path=model_archive,
                    animation_archive_path=animation_archive,
                    categories=("repose",),
                    include_glb=False,
                )


if __name__ == "__main__":
    unittest.main()
