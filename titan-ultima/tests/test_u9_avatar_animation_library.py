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


BREATHE_PATH = r"u:\art\motions\humanoid\idle\lws\breathe_avatar.lws"
WALK_PATH = r"u:\art\motions\humanoid\movement\lws\walkfoward_avatar_none.lws"
BOW_PATH = r"u:\art\motions\humanoid\combat\lws\attack_avatar_bowaa.lws"
DRAGON_PATH = r"u:\art\motions\dragon\dragon_fly_begin.lws"


def _clips():
    breathe = replace(_animation(), source_name=BREATHE_PATH)
    walk = replace(breathe, animation_id=174, source_name=WALK_PATH)
    return breathe, walk


class AvatarAnimationLibraryTests(unittest.TestCase):
    def test_exports_labelled_compatible_clips_and_reports_exclusions(self) -> None:
        breathe, walk = _clips()
        incompatible = replace(
            breathe,
            animation_id=201,
            source_name=BOW_PATH,
            parts=(U9AnimationPart(900, "OTHER", breathe.parts[0].frames),),
        )
        unrelated = replace(breathe, animation_id=840, source_name=DRAGON_PATH)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_archive = root / "model.bin"
            animation_archive = root / "animation.bin"
            model_archive.write_bytes(b"model")
            animation_archive.write_bytes(b"animation")

            result = export_avatar_animation_library(
                _model(),
                (breathe, walk, incompatible, unrelated),
                root / "library",
                model_archive_path=model_archive,
                animation_archive_path=animation_archive,
                include_glb=False,
            )
            document = json.loads(
                result.export.sidecar_path.read_text(encoding="utf-8")
            )

            self.assertEqual(
                document["library"]["schema"], AVATAR_ANIMATION_LIBRARY_SCHEMA
            )
            self.assertEqual(result.candidate_clip_count, 3)
            self.assertEqual(result.exported_clip_count, 2)
            self.assertEqual(result.incompatible_animation_ids, (201,))
            self.assertEqual(result.category_counts, (("idle", 1), ("movement", 1)))
            self.assertEqual(
                [clip["animation_id"] for clip in document["clips"]], [172, 174]
            )
            self.assertEqual(
                [clip["animation_label"] for clip in document["clips"]],
                [
                    "humanoid/idle/breathe_avatar",
                    "humanoid/movement/walkfoward_avatar_none",
                ],
            )
            breathe_catalogue = document["clips"][0]["catalogue"]
            self.assertEqual(breathe_catalogue["known_state"], "breathe")
            self.assertEqual(breathe_catalogue["action"], "breathe")
            walk_catalogue = document["clips"][1]["catalogue"]
            self.assertEqual(
                walk_catalogue["known_aliases"], ["avatar:walk", "avatar:walk-forward"]
            )
            self.assertEqual(walk_catalogue["equipment_hint"], "none")
            self.assertEqual(
                walk_catalogue["runtime_selection_semantics"], "not yet decoded"
            )
            self.assertFalse(document["library"]["timeline"]["authored"])

    def test_category_filter_is_case_insensitive_and_rejects_empty_results(
        self,
    ) -> None:
        breathe, walk = _clips()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_archive = root / "model.bin"
            animation_archive = root / "animation.bin"
            model_archive.write_bytes(b"model")
            animation_archive.write_bytes(b"animation")

            result = export_avatar_animation_library(
                _model(),
                (breathe, walk),
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
                    root / "missing",
                    model_archive_path=model_archive,
                    animation_archive_path=animation_archive,
                    categories=("repose",),
                    include_glb=False,
                )

    def test_classifies_weapon_variant_from_the_authoring_label(self) -> None:
        animation = replace(
            _animation(),
            animation_id=936,
            source_name=r"u:\art\motions\humanoid\combat\attack_avatar_handoneaa",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_archive = root / "model.bin"
            animation_archive = root / "animation.bin"
            model_archive.write_bytes(b"model")
            animation_archive.write_bytes(b"animation")

            result = export_avatar_animation_library(
                _model(),
                (animation,),
                root / "library",
                model_archive_path=model_archive,
                animation_archive_path=animation_archive,
                include_glb=False,
            )
            document = json.loads(
                result.export.sidecar_path.read_text(encoding="utf-8")
            )

            self.assertEqual(result.exported_clip_count, 1)
            catalogue = document["clips"][0]["catalogue"]
            self.assertEqual(catalogue["category"], "combat")
            self.assertEqual(catalogue["variant_label"], "handoneaa")
            self.assertEqual(catalogue["equipment_hint"], "handone")
            self.assertEqual(
                catalogue["selection_basis"],
                ["Avatar token in the authoring label"],
            )


if __name__ == "__main__":
    unittest.main()
