"""Tests for the ``static/anim.flx`` animation reader."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
from types import SimpleNamespace
from typing import cast

from titan.u9.animation import U9Animation, U9AnimationError, U9Animations
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
    return struct.pack("<I10f", time_ms, *rotation, *position, *scale)


def _part(part_id: int, name: str, frames: list[bytes]) -> bytes:
    raw_name = name.encode("ascii")
    return (
        struct.pack("<II", part_id, len(raw_name))
        + raw_name
        + struct.pack("<I", len(frames))
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

    source = b"u:\\art\\motions\\test.lws"
    total_frames = end_frame - start_frame + 1
    header_words = part_ids + [0xDEADBEEF, 0]
    return b"".join(
        [
            struct.pack(
                "<7I",
                animation_id,
                start_frame,
                end_frame,
                total_frames,
                30,
                33,
                len(source),
            ),
            source,
            struct.pack("<I", len(header_words)),
            struct.pack(f"<{len(header_words)}I", *header_words),
            struct.pack("<I", len(parts)),
            *parts,
            struct.pack("<I", len(suffixes)),
            *(struct.pack("<III", *suffix) for suffix in suffixes),
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

    def test_parses_header_parts_frames_and_suffixes(self) -> None:
        animation = cast(U9Animation, self.animations.animation(3))

        self.assertEqual(animation.animation_id, 3)
        self.assertEqual((animation.start_frame, animation.end_frame), (0, 1))
        self.assertEqual(animation.frame_count, 2)
        self.assertEqual(animation.source_fps, 30)
        self.assertEqual(animation.frame_interval_ms, 33)
        self.assertEqual(animation.source_name, r"u:\art\motions\test.lws")
        self.assertEqual(animation.header_words[:2], (1, 15))
        self.assertEqual(animation.part_ids, (1, 15))
        self.assertEqual([part.name for part in animation.parts], ["ROOT", "HEAD"])
        self.assertEqual(animation.suffixes[0].values, (33, 4, 2))

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
        head = animation.part(15)
        self.assertIsNotNone(head)
        self.assertEqual(head.name if head is not None else None, "HEAD")
        self.assertIsNone(animation.part(999))


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
    def test_record_index_must_match_flx_index(self) -> None:
        animations = U9Animations(_archive({3: _entry(animation_id=4)}))
        with self.assertRaisesRegex(U9AnimationError, "record index"):
            animations.animation(3)

    def test_part_ids_must_match_header_manifest(self) -> None:
        animations = U9Animations(_archive({3: _entry(part_ids=[1, 99])}))
        with self.assertRaisesRegex(U9AnimationError, "part ID manifest"):
            animations.animation(3)

    def test_truncated_frame_array_raises(self) -> None:
        part = _part(1, "ROOT", [_frame(0), _frame(33)])
        truncated = _entry(parts=[part], part_ids=[1], suffixes=[])[:-20]
        animations = U9Animations(_archive({3: truncated}))
        with self.assertRaisesRegex(U9AnimationError, "frame array"):
            animations.animation(3)

    def test_frame_range_must_match_declared_count(self) -> None:
        malformed = bytearray(_entry())
        struct.pack_into("<I", malformed, 0x0C, 999)
        animations = U9Animations(_archive({3: bytes(malformed)}))
        with self.assertRaisesRegex(U9AnimationError, "frame range"):
            animations.animation(3)


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
