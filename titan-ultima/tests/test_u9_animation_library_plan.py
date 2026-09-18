"""Tests for compact U9 animation library discovery plans."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_u9_animation_model_report import (
    _animation_entry,
    _build_flx,
    _model_entry,
    _types_dat,
)
from titan.u9.animation_library_plan import (
    ANIMATION_LIBRARY_PLAN_SCHEMA,
    build_animation_library_plan,
    write_animation_library_plan,
)
from titan.u9.cli import cmd_animation_library_plan


class AnimationLibraryPlanTests(unittest.TestCase):
    def test_groups_actor_and_track_signature_with_one_recommended_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            static = Path(directory)
            (static / "anim.flx").write_bytes(
                _build_flx([None, None, None, _animation_entry()])
            )
            (static / "sappear.flx").write_bytes(_build_flx([None, _model_entry()]))
            (static / "registry.txt").write_text(
                "1 BIP01\n15 HEAD\n99 CAMERA\n", encoding="ascii"
            )
            (static / "TYPES.DAT").write_bytes(_types_dat())
            typename = b"\x00\x00\x00\x00\x81\x1bAvatar\x00"
            (static / "TYPENAME.FLX").write_bytes(_build_flx([None, typename]))
            motion_table = static / "motions.txt"
            motion_table.write_text(
                "HUMANOID_IDLE_BREATHE_AVATAR = 3,\n", encoding="ascii"
            )

            plan = build_animation_library_plan(
                static / "anim.flx", motion_ids_path=motion_table
            )
            output = write_animation_library_plan(plan, static / "plan.json")
            document = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(document["schema"], ANIMATION_LIBRARY_PLAN_SCHEMA)
            self.assertEqual(document["summary"]["animation_count"], 1)
            self.assertEqual(document["summary"]["library_count"], 1)
            library = document["libraries"][0]
            self.assertEqual(library["library_id"], "avatar")
            self.assertEqual(library["confidence"], "strong")
            self.assertEqual(library["recommended_model_ids"], [1])
            self.assertEqual(library["representative_model_ids"], [1])
            self.assertEqual(library["animations"][0]["animation_id"], 3)
            self.assertEqual(
                len(library["skeleton_groups"][0]["skeleton_fingerprint"]), 16
            )
            self.assertEqual(len(plan.diagnostics), 1)

    def test_command_writes_plan_without_redundant_diagnostics_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            static = Path(directory)
            (static / "anim.flx").write_bytes(
                _build_flx([None, None, None, _animation_entry()])
            )
            (static / "sappear.flx").write_bytes(_build_flx([None, _model_entry()]))
            (static / "registry.txt").write_text(
                "1 BIP01\n15 HEAD\n99 CAMERA\n", encoding="ascii"
            )
            motion_table = static / "motions.txt"
            motion_table.write_text(
                "HUMANOID_IDLE_BREATHE_AVATAR = 3,\n", encoding="ascii"
            )
            output = static / "plan.json"

            result = cmd_animation_library_plan(
                SimpleNamespace(
                    file=str(static / "anim.flx"),
                    output=str(output),
                    sappear=None,
                    registry=None,
                    types=None,
                    typenames=None,
                    motion_ids=str(motion_table),
                    diagnostics=None,
                    diagnostics_format="csv",
                )
            )

            self.assertEqual(result, 0)
            self.assertTrue(output.is_file())
            self.assertEqual(list(static.glob("*.csv")), [])

    def test_partial_structural_candidates_require_review(self) -> None:
        row = {
            "animation_id": 7,
            "source_actor_hint": "behemoth",
            "source_actor_hint_basis": "authoring label",
            "model_track_ids": [1, 2],
            "candidate_status": "partial-best",
            "candidate_model_ids": [5],
            "candidate_models": [
                {
                    "model_id": 5,
                    "model_names": ["Behemoth"],
                    "skeleton_fingerprint": "0123456789abcdef",
                }
            ],
            "source_name_candidate_models": [],
            "part_count": 2,
        }
        with patch(
            "titan.u9.animation_library_plan.build_animation_model_report",
            return_value=([row], []),
        ):
            plan = build_animation_library_plan("unused.flx")

        library = plan.document["libraries"][0]
        self.assertEqual(library["confidence"], "partial")
        self.assertEqual(library["recommended_model_ids"], [5])
        self.assertTrue(library["requires_model_review"])
        self.assertEqual(plan.document["summary"]["auto_export_library_count"], 0)

    def test_named_model_anchors_only_its_exact_skeleton_variants(self) -> None:
        candidates = [
            {
                "model_id": 1,
                "model_names": ["Critter"],
                "skeleton_fingerprint": "aaaaaaaaaaaaaaaa",
            },
            {
                "model_id": 2,
                "model_names": ["Critter variant"],
                "skeleton_fingerprint": "aaaaaaaaaaaaaaaa",
            },
            {
                "model_id": 3,
                "model_names": ["Unrelated"],
                "skeleton_fingerprint": "bbbbbbbbbbbbbbbb",
            },
        ]
        row = {
            "animation_id": 7,
            "source_actor_hint": "critter",
            "source_actor_hint_basis": "authoring label",
            "model_track_ids": [1, 2],
            "candidate_status": "full-structural",
            "candidate_model_ids": [1, 2, 3],
            "candidate_models": candidates,
            "source_name_candidate_models": [candidates[0]],
            "part_count": 2,
        }
        with patch(
            "titan.u9.animation_library_plan.build_animation_model_report",
            return_value=([row], []),
        ):
            plan = build_animation_library_plan("unused.flx")

        library = plan.document["libraries"][0]
        self.assertEqual(library["recommended_model_ids"], [1, 2])
        self.assertEqual(len(library["skeleton_groups"]), 1)
        self.assertEqual(library["skeleton_groups"][0]["model_variant_ids"], [1, 2])
        self.assertEqual(library["skeleton_groups"][0]["actor_anchor_model_ids"], [1])


if __name__ == "__main__":
    unittest.main()
