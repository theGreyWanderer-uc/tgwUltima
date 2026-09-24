"""Tests for the Ultima IX animation-name reader."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import cast

from titan.u9.motion_ids import U9MotionId, U9MotionIds, U9MotionIdsError


SOURCE = """
#ifndef _MOTION_ID_H
enum
{
    HUMANOID_IDLE_BREATHE_AVATAR = 172,
    DRAGON_DRAGON_FLY_FLAP = 0x348,
};
#endif
"""


class MotionIdsTests(unittest.TestCase):
    def test_parses_motion_symbols_and_families(self) -> None:
        motions = U9MotionIds.parse(SOURCE)
        dragon = cast(U9MotionId, motions.motion(840))
        avatar = cast(
            U9MotionId,
            motions.by_name("humanoid_idle_breathe_avatar"),
        )

        self.assertEqual(
            [entry.animation_id for entry in motions.entries],
            [172, 840],
        )
        self.assertEqual(motions.name(172), "HUMANOID_IDLE_BREATHE_AVATAR")
        self.assertEqual(dragon.family, "dragon")
        self.assertEqual(avatar.animation_id, 172)
        self.assertEqual(motions.missing_animation_ids([172, 999]), [999])
        self.assertEqual(motions.unused_motion_ids([172]), [840])

    def test_reads_latin1_header_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "animation_names.txt"
            path.write_text(SOURCE, encoding="latin-1")
            self.assertEqual(
                U9MotionIds.from_file(path).name(840),
                "DRAGON_DRAGON_FLY_FLAP",
            )

    def test_rejects_duplicate_ids(self) -> None:
        with self.assertRaisesRegex(U9MotionIdsError, "assigned to both"):
            U9MotionIds.parse("FIRST = 1,\nSECOND = 1,\n")

    def test_rejects_non_motion_header(self) -> None:
        with self.assertRaisesRegex(U9MotionIdsError, "no animation-name entries"):
            U9MotionIds.parse("int unrelated = 1;\n")


if __name__ == "__main__":
    unittest.main()
