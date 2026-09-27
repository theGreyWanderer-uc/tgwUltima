"""Tests for the ``static/anim.flx`` animation reader."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
from types import SimpleNamespace
from typing import cast

from titan.u9.animation import (
    U9Animation,
    U9AnimationError,
    U9AnimationFrame,
    U9AnimationPart,
    U9Animations,
)
from titan.u9.cli import cmd_animation_list, cmd_animation_show
from titan.u9.flx_archive import U9FlxArchive

FLX_DIR_OFFSET = 0x80
FLX_COUNT_OFFSET = 0x50
FLX_VERSION_OFFSET = 0x54


def _frame(
    time_ms: int,
    rotation: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> bytes:
    return struct.pack("<i10f", time_ms, *rotation, *position, *scale)


def _part(part_id: int, name: str, frames: list[bytes]) -> bytes:
    raw_name = name.encode("ascii")
    return (
        struct.pack("<ii", part_id, len(raw_name))
        + raw_name
        + struct.pack("<i", len(frames))
        + b"".join(frames)
    )


def _entry(
    animation_id: int = 3,
    *,
    start_frame: int = 0,
    end_frame: int = 1,
    parts: list[bytes] | None = None,
    part_ids: list[int] | None = None,
    suffixes: list[tuple[int, int, int]] | None = None,
) -> bytes:
    if parts is None:
        parts = [
            _part(
                1,
                "ROOT",
                [
                    _frame(0, position=(1.0, 2.0, 3.0)),
                    _frame(
                        33,
                        rotation=(0.5, -0.5, 0.5, -0.5),
                        position=(4.0, 5.0, 6.0),
                    ),
                ],
            ),
            _part(15, "HEAD", [_frame(0), _frame(33)]),
        ]
    if part_ids is None:
        part_ids = [1, 15]
    if suffixes is None:
        suffixes = [(33, 4, 2)]

    source = b"u:\\art\\motions\\test"
    total_frames = end_frame - start_frame + 1
    header_words = part_ids + [-559038737, 0]
    return b"".join(
        [
            struct.pack(
                "<7i",
                animation_id,
                start_frame,
                end_frame,
                total_frames,
                30,
                33,
                len(source),
            ),
            source,
            struct.pack("<i", len(header_words)),
            struct.pack(f"<{len(header_words)}i", *header_words),
            struct.pack("<i", len(parts)),
            *parts,
            struct.pack("<i", len(suffixes)),
            *(struct.pack("<iII", *suffix) for suffix in suffixes),
        ]
    )


def _archive_data(entries: dict[int, bytes], count: int = 8) -> bytes:
    header = bytearray(FLX_DIR_OFFSET + count * 8)
    payload = bytearray()
    for index in range(count):
        blob = entries.get(index, b"")
        if blob:
            struct.pack_into(
                "<II",
                header,
                FLX_DIR_OFFSET + index * 8,
                len(header) + len(payload),
                len(blob),
            )
            payload += blob
    struct.pack_into("<I", header, FLX_COUNT_OFFSET, count)
    struct.pack_into("<I", header, FLX_VERSION_OFFSET, 2)
    return bytes(header + payload)


def _archive(entries: dict[int, bytes], count: int = 8) -> U9FlxArchive:
    return U9FlxArchive(_archive_data(entries, count))


class AnimationRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.animations = U9Animations(_archive({3: _entry()}))

    def test_parses_header_parts_frames_and_events(self) -> None:
        animation = cast(U9Animation, self.animations.animation(3))

        self.assertEqual(animation.animation_id, 3)
        self.assertEqual((animation.start_frame, animation.end_frame), (0, 1))
        self.assertEqual(animation.frame_count, 2)
        self.assertEqual(animation.source_fps, 30)
        self.assertEqual(animation.frame_interval_ms, 33)
        self.assertEqual(animation.source_name, r"u:\art\motions\test")
        self.assertEqual(animation.header_words[:2], (1, 15))
        self.assertEqual(animation.part_ids, (1, 15))
        self.assertEqual([part.name for part in animation.parts], ["ROOT", "HEAD"])
        self.assertEqual(animation.suffixes[0].values, (33, 4, 2))
        self.assertEqual(animation.part_registry, animation.header_words)
        self.assertEqual(animation.active_part_registry, (1, 15))
        self.assertEqual(animation.part_registry_residue, (-559038737, 0))
        self.assertEqual(animation.part_registry_status, "matches_parts")
        self.assertEqual(animation.events, animation.suffixes)
        self.assertEqual(animation.events[0].time_ms, 33)
        self.assertEqual(animation.events[0].event_name, "footstep")
        self.assertEqual(animation.events[0].parameter, 2)
        self.assertEqual(animation.stored_animation_id, 3)
        self.assertEqual(animation.stored_id_status, "matches_entry")
        self.assertEqual(animation.frame_range_status, "matches_count")
        self.assertEqual(animation.runtime_timing_status, "valid")
        self.assertEqual(animation.part_frame_count_status, "matches_clip")
        self.assertEqual(animation.timestamp_status, "monotonic")
        self.assertEqual(animation.transform_status, "finite")
        self.assertEqual(animation.event_order_status, "monotonic")
        self.assertEqual(animation.source_name_raw, b"u:\\art\\motions\\test")

    def test_frame_order_is_time_rotation_position_scale(self) -> None:
        animation = cast(U9Animation, self.animations.animation(3))
        frame = animation.parts[0].frames[1]

        self.assertEqual(frame.time_ms, 33)
        self.assertEqual(frame.rotation, (0.5, -0.5, 0.5, -0.5))
        self.assertEqual(frame.position, (4.0, 5.0, 6.0))
        self.assertEqual(frame.scale, (1.0, 1.0, 1.0))

    def test_part_records_have_no_unknown_word_before_frames(self) -> None:
        animation = cast(U9Animation, self.animations.animation(3))

        self.assertEqual(animation.parts[0].frame_count, 2)
        self.assertEqual(animation.parts[1].part_id, 15)
        self.assertEqual(animation.parts[1].name, "HEAD")

    def test_nonzero_authoring_frame_range_is_supported(self) -> None:
        frames = [_frame(0), _frame(33)]
        entry = _entry(
            start_frame=54,
            end_frame=55,
            parts=[_part(38, "ROOT", frames)],
            part_ids=[38],
        )
        animation = cast(U9Animation, U9Animations(_archive({3: entry})).animation(3))
        self.assertEqual(animation.frame_count, 2)
        self.assertEqual((animation.start_frame, animation.end_frame), (54, 55))

    def test_part_lookup_and_duration(self) -> None:
        animation = cast(U9Animation, self.animations.animation(3))
        self.assertEqual(animation.duration_ms, 33)
        self.assertEqual(animation.last_sample_time_ms, 33)
        self.assertEqual(animation.runtime_length_ms, 66)
        head = animation.part(15)
        self.assertIsNotNone(head)
        self.assertEqual(head.name if head is not None else None, "HEAD")
        self.assertIsNone(animation.part(999))

    def test_part_sample_clamps_and_interpolates_transforms(self) -> None:
        animation = cast(U9Animation, self.animations.animation(3))
        root = cast(U9AnimationPart, animation.part(1))
        before = cast(U9AnimationFrame, root.sample(-1))
        after = cast(U9AnimationFrame, root.sample(100))
        sampled = cast(U9AnimationFrame, root.sample(16))
        self.assertEqual(before.time_ms, 0)
        self.assertEqual(after.time_ms, 33)
        self.assertEqual(sampled.time_ms, 16)
        self.assertAlmostEqual(sampled.position[0], 1.0 + 3.0 * 16.0 / 33.0)
        self.assertAlmostEqual(sum(value * value for value in sampled.rotation), 1.0)

    def test_part_sample_preserves_the_runtime_opposite_quaternion_branch(self) -> None:
        part = U9AnimationPart(
            1,
            "ROOT",
            (
                U9AnimationFrame(
                    0,
                    (0.5, 0.5, 0.5, 0.5),
                    (0.0, 0.0, 0.0),
                    (1.0, 1.0, 1.0),
                ),
                U9AnimationFrame(
                    10,
                    (-0.5, -0.5, -0.5, -0.5),
                    (0.0, 0.0, 0.0),
                    (1.0, 1.0, 1.0),
                ),
            ),
        )
        sampled = cast(U9AnimationFrame, part.sample(5))
        self.assertEqual(sampled.rotation[0], 0.5)
        self.assertAlmostEqual(sampled.rotation[1], 0.0)
        self.assertAlmostEqual(sampled.rotation[2], 2**-0.5)
        self.assertAlmostEqual(sampled.rotation[3], 0.0)


class AnimationArchiveTests(unittest.TestCase):
    def test_unused_slots_and_used_ids(self) -> None:
        animations = U9Animations(_archive({3: _entry()}))
        self.assertEqual(animations.used_animation_ids(), [3])
        self.assertIsNone(animations.animation(2))
        self.assertEqual([a.animation_id for a in animations.animations()], [3])

    def test_out_of_range_id_raises(self) -> None:
        animations = U9Animations(_archive({3: _entry()}))
        with self.assertRaises(U9AnimationError):
            animations.animation(99)


class AnimationValidationTests(unittest.TestCase):
    def test_record_index_mismatch_is_preserved_and_flagged(self) -> None:
        animations = U9Animations(_archive({3: _entry(animation_id=4)}))
        animation = cast(U9Animation, animations.animation(3))
        self.assertEqual(animation.animation_id, 3)
        self.assertEqual(animation.stored_animation_id, 4)
        self.assertEqual(animation.stored_id_status, "mismatch")

    def test_part_registry_mismatch_is_preserved_and_flagged(self) -> None:
        animations = U9Animations(_archive({3: _entry(part_ids=[1, 99])}))
        animation = cast(U9Animation, animations.animation(3))
        self.assertEqual(animation.part_registry_status, "mismatch")

    def test_truncated_frame_array_raises(self) -> None:
        part = _part(1, "ROOT", [_frame(0), _frame(33)])
        truncated = _entry(parts=[part], part_ids=[1], suffixes=[])[:-20]
        animations = U9Animations(_archive({3: truncated}))
        with self.assertRaisesRegex(U9AnimationError, "frame array"):
            animations.animation(3)

    def test_frame_range_mismatch_is_preserved_and_flagged(self) -> None:
        malformed = bytearray(_entry())
        struct.pack_into("<i", malformed, 0x0C, 999)
        animations = U9Animations(_archive({3: bytes(malformed)}))
        animation = cast(U9Animation, animations.animation(3))
        self.assertEqual(animation.frame_count, 999)
        self.assertEqual(animation.frame_range_status, "mismatch")
        self.assertEqual(animation.part_frame_count_status, "mismatch")

    def test_trailing_bytes_are_preserved_losslessly(self) -> None:
        entry = _entry() + b"TAIL"
        animation = cast(U9Animation, U9Animations(_archive({3: entry})).animation(3))
        self.assertEqual(animation.trailing_data, b"TAIL")
        self.assertEqual(animation.to_bytes(), entry)

    def test_negative_timestamp_and_nonfinite_transform_are_flagged(self) -> None:
        part = _part(1, "ROOT", [_frame(-1, position=(float("nan"), 0.0, 0.0))])
        entry = _entry(end_frame=0, parts=[part], part_ids=[1], suffixes=[])
        animation = cast(U9Animation, U9Animations(_archive({3: entry})).animation(3))
        self.assertEqual(animation.parts[0].frames[0].time_ms, -1)
        self.assertEqual(animation.transform_status, "nonfinite")

    def test_source_record_round_trips_exactly(self) -> None:
        entry = _entry()
        animation = cast(U9Animation, U9Animations(_archive({3: entry})).animation(3))
        self.assertEqual(animation.to_bytes(), entry)


class AnimationCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "anim.flx")
        with open(self.path, "wb") as f:
            f.write(_archive_data({3: _entry()}))

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_animation_list_succeeds(self) -> None:
        self.assertEqual(
            cmd_animation_list(SimpleNamespace(file=self.path, limit=None)),
            0,
        )

    def test_animation_show_can_dump_one_part(self) -> None:
        self.assertEqual(
            cmd_animation_show(SimpleNamespace(file=self.path, id=3, part=15, limit=1)),
            0,
        )

    def test_animation_show_rejects_an_unknown_part(self) -> None:
        self.assertEqual(
            cmd_animation_show(
                SimpleNamespace(file=self.path, id=3, part=999, limit=None)
            ),
            1,
        )

    def test_animation_list_missing_file_errors(self) -> None:
        self.assertEqual(
            cmd_animation_list(
                SimpleNamespace(
                    file=os.path.join(self.tmpdir.name, "missing.flx"),
                    limit=None,
                )
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
