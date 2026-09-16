"""Tests for confirmed U9 actor-state animation selection."""

from __future__ import annotations

import unittest

from titan.u9.animation_selection import (
    U9AnimationSelectionError,
    resolve_animation_selector,
)
from titan.u9.motion_ids import U9MotionIds


MOTION_IDS = U9MotionIds.parse(
    """
    HUMANOID_IDLE_BREATHE_AVATAR = 172,
    HUMANOID_MOVEMENT_WALKFOWARD_AVATAR_NONE = 174,
    DRAGON_DRAGON_FLY_FLAP = 840,
    """
)


class AnimationSelectionTests(unittest.TestCase):
    def test_resolves_confirmed_avatar_state_aliases(self) -> None:
        breathe = resolve_animation_selector("Avatar:Idle", MOTION_IDS)
        walk = resolve_animation_selector("avatar:walk", MOTION_IDS)

        self.assertEqual(breathe.animation_id, 172)
        self.assertEqual(breathe.motion_name, "HUMANOID_IDLE_BREATHE_AVATAR")
        if breathe.rule is None:
            self.fail("Avatar idle should resolve through an actor-state rule")
        self.assertEqual(breathe.rule.state, "breathe")
        self.assertEqual(walk.animation_id, 174)
        if walk.rule is None:
            self.fail("Avatar walk should resolve through an actor-state rule")
        self.assertEqual(walk.rule.lockset, "lower")
        self.assertEqual(walk.rule.root_translation_axes, ("x", "z"))

    def test_resolves_numeric_and_exact_motion_name_selectors(self) -> None:
        numeric = resolve_animation_selector("0x348", MOTION_IDS)
        named = resolve_animation_selector("dragon_dragon_fly_flap", MOTION_IDS)

        self.assertEqual(numeric.animation_id, 840)
        self.assertEqual(numeric.resolution, "animation-id")
        self.assertEqual(named.animation_id, 840)
        self.assertEqual(named.resolution, "motion-name")

    def test_semantic_selection_detects_motion_table_disagreement(self) -> None:
        mismatched = U9MotionIds.parse("HUMANOID_IDLE_BREATHE_AVATAR = 999,\n")
        with self.assertRaisesRegex(U9AnimationSelectionError, "disagrees"):
            resolve_animation_selector("avatar:breathe", mismatched)

    def test_rejects_unknown_or_empty_selectors(self) -> None:
        for selector in ("", "avatar:dance", "dragon fly"):
            with self.subTest(selector=selector):
                with self.assertRaises(U9AnimationSelectionError):
                    resolve_animation_selector(selector, MOTION_IDS)


if __name__ == "__main__":
    unittest.main()
