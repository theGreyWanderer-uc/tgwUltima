"""Tests for U9 actor-state animation selection."""

from __future__ import annotations

import unittest

from titan.u9.animation_labels import U9AnimationLabels
from titan.u9.animation_selection import (
    U9AnimationSelectionError,
    resolve_animation_selector,
)


LABELS = U9AnimationLabels(
    {
        172: "humanoid/idle/breathe_avatar",
        174: "humanoid/movement/walkfoward_avatar_none",
        840: "dragon/dragon_fly_begin",
        936: "humanoid/combat/attack_avatar_handoneaa",
        209: "humanoid/combat/attack_avatar_handoneaa",
    }
)


class AnimationSelectionTests(unittest.TestCase):
    def test_resolves_avatar_state_aliases(self) -> None:
        breathe = resolve_animation_selector("Avatar:Idle", LABELS)
        walk = resolve_animation_selector("avatar:walk", LABELS)

        self.assertEqual(breathe.animation_id, 172)
        self.assertEqual(breathe.animation_label, "humanoid/idle/breathe_avatar")
        if breathe.rule is None:
            self.fail("Avatar idle should resolve through an actor-state rule")
        self.assertEqual(breathe.rule.state, "breathe")
        self.assertEqual(walk.animation_id, 174)
        self.assertEqual(walk.resolution, "actor-state")

    def test_aliases_resolve_without_an_archive(self) -> None:
        walk = resolve_animation_selector("avatar:walk-forward")

        self.assertEqual(walk.animation_id, 174)
        self.assertEqual(
            walk.animation_label, "humanoid/movement/walkfoward_avatar_none"
        )

    def test_resolves_numeric_and_label_selectors(self) -> None:
        numeric = resolve_animation_selector("0x348", LABELS)
        labelled = resolve_animation_selector("Dragon\\dragon_fly_begin", LABELS)

        self.assertEqual(numeric.animation_id, 840)
        self.assertEqual(numeric.resolution, "animation-id")
        self.assertEqual(numeric.animation_label, "dragon/dragon_fly_begin")
        self.assertEqual(labelled.animation_id, 840)
        self.assertEqual(labelled.resolution, "animation-label")

    def test_shared_label_asks_for_an_id(self) -> None:
        with self.assertRaisesRegex(U9AnimationSelectionError, "209, 936"):
            resolve_animation_selector("humanoid/combat/attack_avatar_handoneaa", LABELS)

    def test_alias_detects_archive_disagreement(self) -> None:
        moved = U9AnimationLabels({172: "humanoid/idle/look_avatar"})
        with self.assertRaisesRegex(U9AnimationSelectionError, "archive holds"):
            resolve_animation_selector("avatar:breathe", moved)

    def test_rejects_unknown_or_empty_selectors(self) -> None:
        for selector in ("", "avatar:dance", "dragon fly"):
            with self.subTest(selector=selector):
                with self.assertRaises(U9AnimationSelectionError):
                    resolve_animation_selector(selector, LABELS)


if __name__ == "__main__":
    unittest.main()
