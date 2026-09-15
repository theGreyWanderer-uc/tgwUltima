"""Tests for runtime-compatible U9 rigid-hierarchy pose evaluation."""

from __future__ import annotations

import unittest

from titan.u9.animation import U9Animation, U9AnimationFrame, U9AnimationPart
from titan.u9.animation_pose import U9AnimationPoseError, pose_model
from titan.u9.model import U9Limb, U9Model


def _frame(
    time_ms: int,
    *,
    rotation: tuple[float, float, float, float],
    position: tuple[float, float, float],
) -> U9AnimationFrame:
    return U9AnimationFrame(time_ms, rotation, position, (2.0, 2.0, 2.0))


def _model(record_format: str = "hierarchical") -> U9Model:
    limbs = (
        U9Limb(1, 0, (1.0, 1.0, 1.0), (10.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), ()),
        U9Limb(2, 1, (1.0, 1.0, 1.0), (0.0, 5.0, 0.0), (1.0, 0.0, 0.0, 0.0), ()),
        U9Limb(3, 2, (1.0, 1.0, 1.0), (0.0, 2.0, 0.0), (1.0, 0.0, 0.0, 0.0), ()),
        U9Limb(4, 3, (1.0, 1.0, 1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0, 0.0), ()),
    )
    return U9Model(
        model_id=7,
        cylinder_base_center=(0.0, 0.0, 0.0),
        cylinder_base_height=0.0,
        cylinder_base_radius=0.0,
        sphere_center=(0.0, 0.0, 0.0),
        sphere_radius=0.0,
        min_bounds=(0.0, 0.0, 0.0),
        max_bounds=(0.0, 0.0, 0.0),
        lod_thresholds=(0, 0, 0, 0),
        center_of_mass=(0.0, 0.0, 0.0),
        limbs=limbs,
        record_format=record_format,
    )


def _animation() -> U9Animation:
    parts = (
        U9AnimationPart(
            1,
            "BIP01",
            (_frame(0, rotation=(0.0, 1.0, 0.0, 0.0), position=(13.0, 0.0, 0.0)),),
        ),
        U9AnimationPart(
            2,
            "PELVIS",
            (_frame(0, rotation=(0.0, 0.0, 1.0, 0.0), position=(0.0, 8.0, 0.0)),),
        ),
        U9AnimationPart(
            3,
            "TORSO",
            (_frame(0, rotation=(0.0, 0.0, 0.0, 1.0), position=(99.0, 99.0, 99.0)),),
        ),
        U9AnimationPart(
            99,
            "CAMERA",
            (_frame(0, rotation=(1.0, 0.0, 0.0, 0.0), position=(0.0, 0.0, 0.0)),),
        ),
    )
    return U9Animation(172, 0, 0, 1, 30, 33, "test", (1, 2, 3, 99), parts, ())


class AnimationPoseTests(unittest.TestCase):
    def test_pose_uses_rotation_everywhere_but_translation_only_on_pelvis(
        self,
    ) -> None:
        result = pose_model(_model(), _animation(), 0)
        root, pelvis, torso, unmatched = result.model.limbs

        self.assertEqual(root.position, (10.0, 0.0, 0.0))
        self.assertEqual(root.rotation, (0.0, 1.0, 0.0, 0.0))
        self.assertEqual(pelvis.position, (0.0, 8.0, 0.0))
        self.assertEqual(torso.position, (0.0, 2.0, 0.0))
        self.assertEqual(torso.rotation, (0.0, 0.0, 0.0, 1.0))
        self.assertEqual(torso.scale, (1.0, 1.0, 1.0))
        self.assertEqual(unmatched, _model().limbs[3])
        self.assertEqual(result.root_motion_delta, (3.0, 0.0, 0.0))
        self.assertEqual(result.matched_part_ids, (1, 2, 3))
        self.assertEqual(result.authoring_only_part_ids, (99,))
        self.assertEqual(result.model_only_limb_ids, (4,))

    def test_pose_rejects_indexed_models_and_unrelated_tracks(self) -> None:
        with self.assertRaisesRegex(U9AnimationPoseError, "indexed"):
            pose_model(_model("indexed"), _animation(), 0)

        unrelated = U9Animation(
            1,
            0,
            0,
            1,
            30,
            33,
            "x",
            (99,),
            (_animation().parts[-1],),
            (),
        )
        with self.assertRaisesRegex(U9AnimationPoseError, "no shared"):
            pose_model(_model(), unrelated, 0)


if __name__ == "__main__":
    unittest.main()
