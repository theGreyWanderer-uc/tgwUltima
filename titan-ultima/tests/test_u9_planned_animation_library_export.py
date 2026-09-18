"""Tests for plan-driven U9 actor/skeleton animation-library exports."""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.test_u9_animation_model_report import (
    _animation_entry,
    _build_flx,
    _model_entry,
)
from titan.u9.animation import U9Animation
from titan.u9.animation_library_plan import (
    ANIMATION_LIBRARY_PLAN_SCHEMA,
    ANIMATION_LIBRARY_PLAN_SCHEMA_VERSION,
)
from titan.u9.animation_model_report import model_skeleton_fingerprint
from titan.u9.animated_model_bundle import ANIMATED_MODEL_SHARED_LIBRARY_SCHEMA
from titan.u9.model import U9Model
from titan.u9.planned_animation_library_export import (
    ANIMATION_LIBRARY_CATALOGUE_SCHEMA,
    ANIMATION_LIBRARY_EXPORT_SCHEMA,
    export_planned_animation_libraries,
)


def _animation(animation_id: int) -> U9Animation:
    entry = bytearray(_animation_entry())
    struct.pack_into("<I", entry, 0, animation_id)
    return U9Animation.parse(bytes(entry), animation_id)


def _plan_library(
    library_id: str,
    animation_id: int,
    fingerprint: str,
    *,
    track_ids: list[int],
    review: bool = False,
) -> dict[str, object]:
    return {
        "library_id": library_id,
        "actor_hint": "critter",
        "confidence": "partial" if review else "strong",
        "runtime_binding_status": "unresolved",
        "track_signature": library_id,
        "model_track_ids": track_ids,
        "animation_count": 1,
        "animations": [
            {
                "animation_id": animation_id,
                "motion_name": f"CRITTER_ACTION_{animation_id}",
                "animation_label": f"critter/action/{animation_id}",
                "category": "action",
                "action": str(animation_id),
                "duration_ms": 0,
                "track_count": 3,
                "model_track_count": len(track_ids),
                "authoring_only_track_count": 3 - len(track_ids),
                "event_count": 1,
                "actor_hint_basis": "test evidence",
            }
        ],
        "category_counts": {"action": 1},
        "candidate_statuses": ["partial-best" if review else "full-structural"],
        "common_structural_candidate_count": 1,
        "recommended_model_ids": [1],
        "representative_model_ids": [1],
        "model_selection_basis": "test",
        "skeleton_groups": [
            {
                "skeleton_fingerprint": fingerprint,
                "representative_model_id": 1,
                "model_variant_ids": [1],
                "named_models": [],
            }
        ],
        "requires_model_review": review,
    }


class PlannedAnimationLibraryExportTests(unittest.TestCase):
    def test_merges_actor_skeleton_and_keeps_raw_clips_in_one_catalogue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_blob = _model_entry()
            model_archive = root / "models.flx"
            model_archive.write_bytes(_build_flx([None, model_blob]))
            animation_archive = root / "animations.flx"
            animation_archive.write_bytes(b"animation archive")
            model = U9Model.parse(model_blob, model_id=1)
            fingerprint = model_skeleton_fingerprint(model)
            plan = {
                "schema": ANIMATION_LIBRARY_PLAN_SCHEMA,
                "schema_version": ANIMATION_LIBRARY_PLAN_SCHEMA_VERSION,
                "selection_policy": {},
                "summary": {},
                "libraries": [
                    _plan_library("critter-a", 3, fingerprint, track_ids=[1]),
                    _plan_library("critter-b", 4, fingerprint, track_ids=[1, 15]),
                    _plan_library(
                        "critter-review",
                        5,
                        fingerprint,
                        track_ids=[1, 15],
                        review=True,
                    ),
                ],
            }
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            first = _animation(3)
            second = replace(
                _animation(4),
                source_name=r"u:\art\motions\critter\action\second",
            )

            result = export_planned_animation_libraries(
                plan_path,
                (first, second),
                model_archive,
                animation_archive,
                root / "export",
                include_glb=False,
            )

            self.assertEqual(result.exported_animation_count, 2)
            self.assertEqual(len(result.libraries), 1)
            self.assertEqual(
                result.libraries[0].plan_library_ids,
                ("critter-a", "critter-b"),
            )
            self.assertEqual(result.skipped_library_ids, ("critter-review",))

            catalogue = json.loads(result.catalogue_path.read_text(encoding="utf-8"))
            self.assertEqual(catalogue["schema"], ANIMATION_LIBRARY_CATALOGUE_SCHEMA)
            self.assertEqual(catalogue["clip_count"], 2)
            self.assertEqual(
                [clip["animation_id"] for clip in catalogue["clips"]], [3, 4]
            )
            self.assertIn("frames", catalogue["clips"][0]["tracks"][0])

            sidecar = json.loads(
                result.libraries[0].sidecar_path.read_text(encoding="utf-8")
            )
            self.assertEqual(sidecar["schema"], ANIMATED_MODEL_SHARED_LIBRARY_SCHEMA)
            self.assertNotIn("clips", sidecar)
            self.assertEqual(sidecar["clip_count"], 2)
            self.assertEqual(
                [binding["animation_id"] for binding in sidecar["clip_bindings"]],
                [3, 4],
            )
            self.assertEqual(
                sidecar["shared_catalogue"]["path"],
                "../../animation_catalogue.u9anim.json",
            )

            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], ANIMATION_LIBRARY_EXPORT_SCHEMA)
            self.assertEqual(manifest["summary"]["approved_plan_library_count"], 2)
            self.assertEqual(manifest["summary"]["exported_skeleton_library_count"], 1)
            self.assertTrue(manifest["interchange"]["raw_animation_data_is_shared"])


if __name__ == "__main__":
    unittest.main()
