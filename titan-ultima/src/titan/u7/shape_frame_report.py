"""Combined U7 shape-frame origin, hotspot, and WIHH reporting.

The report keeps Exult Studio Origin X/Y, top-left-relative drawing hotspots,
and WIHH.DAT weapon attachment coordinates in separate, explicitly named
columns. Raw 8x8 tile frames have no RLE extent header, so their origin and
hotspot columns are null rather than synthetic values.
"""

from __future__ import annotations

__all__ = [
    "U7ShapeFrameReport",
    "U7ShapeFrameReportRow",
    "build_u7_shape_frame_report",
]

import csv
import io
import json
import struct
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

from titan.u7.flex import U7FlexArchive
from titan.u7.shape import FIRST_OBJ_SHAPE, U7Shape
from titan.u7.wihh import U7WeaponAttachmentFrame, U7WeaponInHandOffsets


@dataclass(frozen=True)
class U7ShapeFrameReportRow:
    """One decoded frame, or one diagnostic row for a frame-less record."""

    shape: int
    shape_hex: str
    record_size: int
    shape_status: str
    parse_error: Optional[str]
    frame: Optional[int]
    frame_count: int
    is_tile: Optional[bool]
    width: Optional[int]
    height: Optional[int]
    origin_x: Optional[int]
    origin_y: Optional[int]
    hotspot_x_from_left: Optional[int]
    hotspot_y_from_top: Optional[int]
    wihh_offset: Optional[int]
    has_wihh_record: bool
    attachment_x: Optional[int]
    attachment_y: Optional[int]
    raw_attachment_x: Optional[int]
    raw_attachment_y: Optional[int]
    draw_weapon: Optional[bool]


@dataclass(frozen=True)
class U7ShapeFrameReport:
    """Complete frame report for every record in one U7 shape Flex archive."""

    archive_path: str
    archive_title: str
    wihh_path: Optional[str]
    rows: list[U7ShapeFrameReportRow]
    shape_count: int
    populated_shape_count: int
    empty_shape_count: int
    frame_count: int
    parse_error_count: int

    def to_csv(self) -> str:
        """Serialize report rows as CSV with stable, explicit column names."""
        output = io.StringIO()
        column_names = [field.name for field in fields(U7ShapeFrameReportRow)]
        writer = csv.DictWriter(output, fieldnames=column_names, lineterminator="\n")
        writer.writeheader()
        for row in self.rows:
            writer.writerow(asdict(row))
        return output.getvalue()

    def to_json(self) -> str:
        """Serialize report metadata and rows as formatted JSON."""
        payload = {
            "archive_path": self.archive_path,
            "archive_title": self.archive_title,
            "wihh_path": self.wihh_path,
            "shape_count": self.shape_count,
            "populated_shape_count": self.populated_shape_count,
            "empty_shape_count": self.empty_shape_count,
            "frame_count": self.frame_count,
            "parse_error_count": self.parse_error_count,
            "rows": [asdict(row) for row in self.rows],
        }
        return json.dumps(payload, indent=2)


def _shape_wihh_values(
    wihh: Optional[U7WeaponInHandOffsets],
    shape_index: int,
) -> tuple[Optional[int], bool, list[U7WeaponAttachmentFrame]]:
    """Return the raw WIHH offset, record presence, and decoded frame table."""
    if wihh is None:
        return None, False, []
    offset = wihh.offsets[shape_index] if shape_index < len(wihh.offsets) else None
    frames = wihh.get(shape_index)
    return offset, bool(frames), frames


def _diagnostic_row(
    *,
    shape_index: int,
    record_size: int,
    status: str,
    error: Optional[str],
    wihh_offset: Optional[int],
    has_wihh_record: bool,
) -> U7ShapeFrameReportRow:
    """Create a coverage row for an empty, frame-less, or invalid record."""
    return U7ShapeFrameReportRow(
        shape=shape_index,
        shape_hex=f"0x{shape_index:04X}",
        record_size=record_size,
        shape_status=status,
        parse_error=error,
        frame=None,
        frame_count=0,
        is_tile=None,
        width=None,
        height=None,
        origin_x=None,
        origin_y=None,
        hotspot_x_from_left=None,
        hotspot_y_from_top=None,
        wihh_offset=wihh_offset,
        has_wihh_record=has_wihh_record,
        attachment_x=None,
        attachment_y=None,
        raw_attachment_x=None,
        raw_attachment_y=None,
        draw_weapon=None,
    )


def build_u7_shape_frame_report(
    archive: U7FlexArchive,
    *,
    archive_path: str = "",
    wihh: Optional[U7WeaponInHandOffsets] = None,
    wihh_path: Optional[str] = None,
) -> U7ShapeFrameReport:
    """Decode every U7 Flex record and combine its frames with WIHH data.

    Records below 150 are forced to raw terrain tiles only when the source is
    named SHAPES.VGA. Other archives use record-level tile/RLE detection, so a
    custom archive may validly contain an RLE shape at a low record index.
    Empty and malformed records remain visible as diagnostic rows, ensuring
    that every archive record is represented in the report.
    """
    rows: list[U7ShapeFrameReportRow] = []
    populated_shape_count = 0
    empty_shape_count = 0
    decoded_frame_count = 0
    parse_error_count = 0
    is_shapes_vga = Path(archive_path).name.casefold() == "shapes.vga"

    for shape_index, record in enumerate(archive.records):
        wihh_offset, has_wihh_record, attachment_frames = _shape_wihh_values(
            wihh, shape_index
        )
        if not record:
            empty_shape_count += 1
            rows.append(
                _diagnostic_row(
                    shape_index=shape_index,
                    record_size=0,
                    status="empty",
                    error=None,
                    wihh_offset=wihh_offset,
                    has_wihh_record=has_wihh_record,
                )
            )
            continue

        populated_shape_count += 1
        try:
            shape = U7Shape.from_data(
                record,
                is_tile=is_shapes_vga and shape_index < FIRST_OBJ_SHAPE,
            )
        except (IndexError, struct.error, ValueError) as exc:
            parse_error_count += 1
            rows.append(
                _diagnostic_row(
                    shape_index=shape_index,
                    record_size=len(record),
                    status="parse_error",
                    error=str(exc),
                    wihh_offset=wihh_offset,
                    has_wihh_record=has_wihh_record,
                )
            )
            continue

        frame_count = len(shape.frames)
        if frame_count == 0:
            rows.append(
                _diagnostic_row(
                    shape_index=shape_index,
                    record_size=len(record),
                    status="no_frames",
                    error=None,
                    wihh_offset=wihh_offset,
                    has_wihh_record=has_wihh_record,
                )
            )
            continue

        decoded_frame_count += frame_count
        for frame_index, frame in enumerate(shape.frames):
            attachment = (
                attachment_frames[frame_index]
                if frame_index < len(attachment_frames)
                else None
            )
            # Raw tiles have no RLE xright/xleft/yabove/ybelow header. Do not
            # report the synthetic values U7Shape uses internally for them.
            origin_x = None if frame.is_tile else frame.origin_x
            origin_y = None if frame.is_tile else frame.origin_y
            hotspot_x = None if frame.is_tile else frame.hotspot_x_from_left
            hotspot_y = None if frame.is_tile else frame.hotspot_y_from_top
            rows.append(
                U7ShapeFrameReportRow(
                    shape=shape_index,
                    shape_hex=f"0x{shape_index:04X}",
                    record_size=len(record),
                    shape_status="ok",
                    parse_error=None,
                    frame=frame_index,
                    frame_count=frame_count,
                    is_tile=frame.is_tile,
                    width=frame.width,
                    height=frame.height,
                    origin_x=origin_x,
                    origin_y=origin_y,
                    hotspot_x_from_left=hotspot_x,
                    hotspot_y_from_top=hotspot_y,
                    wihh_offset=wihh_offset,
                    has_wihh_record=has_wihh_record,
                    attachment_x=(attachment.attachment_x if attachment else None),
                    attachment_y=(attachment.attachment_y if attachment else None),
                    raw_attachment_x=(
                        attachment.raw_attachment_x if attachment else None
                    ),
                    raw_attachment_y=(
                        attachment.raw_attachment_y if attachment else None
                    ),
                    draw_weapon=attachment.draw_weapon if attachment else None,
                )
            )

    return U7ShapeFrameReport(
        archive_path=archive_path,
        archive_title=archive.title,
        wihh_path=wihh_path,
        rows=rows,
        shape_count=len(archive.records),
        populated_shape_count=populated_shape_count,
        empty_shape_count=empty_shape_count,
        frame_count=decoded_frame_count,
        parse_error_count=parse_error_count,
    )
