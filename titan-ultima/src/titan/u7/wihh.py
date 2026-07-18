"""Ultima 7 weapon-in-hand hotspot offsets from ``WIHH.DAT``."""

from __future__ import annotations

__all__ = ["U7WeaponInHandOffsets", "U7WeaponOffsetFrame"]

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from titan.u7.names import U7ShapeNames

_DEFAULT_SHAPE_COUNT = 1024
_MIN_RECORD_OFFSET = 2048
_FRAME_COUNT = 32
_RECORD_SIZE = _FRAME_COUNT * 2


@dataclass
class U7WeaponOffsetFrame:
    """Weapon draw offset for one actor shape frame."""

    shape: int
    frame: int
    x: int
    y: int
    raw_x: int
    raw_y: int

    @property
    def draw_weapon(self) -> bool:
        return self.x != 255 and self.y != 255


class U7WeaponInHandOffsets:
    """Decoded ``wihh.dat`` actor weapon-in-hand offset table."""

    def __init__(
        self,
        offsets: list[int],
        frames_by_shape: dict[int, list[U7WeaponOffsetFrame]],
        source_size: int,
    ) -> None:
        self.offsets = offsets
        self.frames_by_shape = frames_by_shape
        self.source_size = source_size

    @classmethod
    def from_dir(
        cls,
        static_dir: str,
        shape_count: int | None = None,
    ) -> "U7WeaponInHandOffsets":
        for name in ("wihh.dat", "WIHH.DAT"):
            path = Path(static_dir) / name
            if path.is_file():
                return cls.from_file(str(path), shape_count=shape_count)
        return cls([], {}, 0)

    @classmethod
    def from_file(
        cls,
        filepath: str,
        shape_count: int | None = None,
    ) -> "U7WeaponInHandOffsets":
        return cls.from_bytes(Path(filepath).read_bytes(), shape_count=shape_count)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        shape_count: int | None = None,
    ) -> "U7WeaponInHandOffsets":
        if len(data) < 2:
            return cls([], {}, len(data))

        count = shape_count or _DEFAULT_SHAPE_COUNT
        table_count = min(count, _DEFAULT_SHAPE_COUNT, len(data) // 2)
        offsets = [
            int.from_bytes(data[index * 2 : index * 2 + 2], "little")
            for index in range(table_count)
        ]

        frames_by_shape: dict[int, list[U7WeaponOffsetFrame]] = {}
        for shape, offset in enumerate(offsets):
            if (
                offset == 0
                or offset < _MIN_RECORD_OFFSET
                or offset > len(data) - _RECORD_SIZE
            ):
                continue
            frames: list[U7WeaponOffsetFrame] = []
            for frame in range(_FRAME_COUNT):
                pos = offset + frame * 2
                raw_x = data[pos]
                raw_y = data[pos + 1]
                x = raw_x
                y = raw_y
                if x > 63 or y > 63:
                    x = y = 255
                frames.append(
                    U7WeaponOffsetFrame(
                        shape=shape,
                        frame=frame,
                        x=x,
                        y=y,
                        raw_x=raw_x,
                        raw_y=raw_y,
                    )
                )
            frames_by_shape[shape] = frames
        return cls(offsets, frames_by_shape, len(data))

    def __len__(self) -> int:
        return len(self.offsets)

    @property
    def shape_count_with_offsets(self) -> int:
        return len(self.frames_by_shape)

    @property
    def drawable_frame_count(self) -> int:
        return sum(
            1
            for frames in self.frames_by_shape.values()
            for frame in frames
            if frame.draw_weapon
        )

    def get(self, shape: int) -> list[U7WeaponOffsetFrame]:
        return self.frames_by_shape.get(shape, [])

    def dump_summary(self) -> str:
        return "\n".join(
            [
                f"WIHH table entries: {len(self.offsets)}",
                f"Source size: {self.source_size} bytes",
                f"Shapes with weapon offsets: {self.shape_count_with_offsets}",
                f"Drawable frame offsets: {self.drawable_frame_count}",
            ]
        )

    def dump_csv(
        self,
        shape_names: U7ShapeNames | None = None,
        include_empty: bool = False,
    ) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "shape",
                "shape_hex",
                "shape_name",
                "offset",
                "frame",
                "x",
                "y",
                "raw_x",
                "raw_y",
                "draw_weapon",
                "has_offset",
            ]
        )
        for shape, offset in enumerate(self.offsets):
            frames = self.frames_by_shape.get(shape)
            if not frames:
                if include_empty:
                    writer.writerow(
                        [
                            shape,
                            f"0x{shape:04X}",
                            shape_names.get(shape) if shape_names else "",
                            offset,
                            "",
                            "",
                            "",
                            "",
                            "",
                            0,
                            0,
                        ]
                    )
                continue
            for frame in frames:
                writer.writerow(
                    [
                        shape,
                        f"0x{shape:04X}",
                        shape_names.get(shape) if shape_names else "",
                        offset,
                        frame.frame,
                        frame.x,
                        frame.y,
                        frame.raw_x,
                        frame.raw_y,
                        int(frame.draw_weapon),
                        1,
                    ]
                )
        return buf.getvalue()
