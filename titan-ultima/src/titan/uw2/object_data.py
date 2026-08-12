"""UU2 COMOBJ.DAT rendering metadata and OBJECTS.DAT animation records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

COMMON_OBJECT_HEADER_SIZE = 2
COMMON_OBJECT_RECORD_SIZE = 11
ANIMATION_TABLE_OFFSET = 0xDA2
ANIMATION_RECORD_SIZE = 4
ANIMATION_ITEM_FIRST = 0x1C0
ANIMATION_ITEM_LAST = 0x1CF

RENDER_TYPE_NAMES = {
    0: "sprite",
    1: "npc",
    2: "3d_model",
    3: "texture",
}


class UW2ObjectDataError(ValueError):
    """Raised when UU2 object metadata is incomplete or invalid."""


@dataclass(frozen=True)
class UW2CommonObject:
    """One 11-byte COMOBJ.DAT item record with rendering fields decoded."""

    item_id: int
    height: int
    radius: int
    is_animated: bool
    mass_tenths: int
    can_place_item: bool
    is_usable: bool
    is_temporary: bool
    is_decal: bool
    can_put_in_inventory: bool
    can_link: bool
    is_container: bool
    monetary_value: int
    is_solid: bool
    activate_on_impact: bool
    quality_class: int
    can_pick_up: bool
    can_be_owned: bool
    render_type: int
    render_type_name: str
    culling_priority: int
    quality_type: int
    look_at_detail: bool

    def to_dict(self) -> dict[str, object]:
        """Return JSON-ready common object metadata."""
        return asdict(self)


@dataclass(frozen=True)
class UW2Animation:
    """One OBJECTS.DAT animation descriptor for item IDs 448..463."""

    item_id: int
    animation_type: int
    unknown: int
    start_frame: int
    frame_count: int

    @property
    def end_frame(self) -> int:
        """Return inclusive ANIMO.GR ending frame."""
        return self.start_frame + self.frame_count - 1

    def to_dict(self) -> dict[str, int]:
        """Return JSON-ready animation metadata."""
        result = asdict(self)
        result["end_frame"] = self.end_frame
        return result


class UW2CommonObjectTable:
    """All fixed-size item records from UU2 COMOBJ.DAT."""

    def __init__(self, records: tuple[UW2CommonObject, ...]) -> None:
        self.records = records

    @classmethod
    def from_file(cls, path: str | Path) -> UW2CommonObjectTable:
        """Read ``COMOBJ.DAT``."""
        return cls.from_data(Path(path).read_bytes())

    @classmethod
    def from_data(cls, data: bytes) -> UW2CommonObjectTable:
        """Decode all complete COMOBJ.DAT records after 2-byte header."""
        if len(data) < COMMON_OBJECT_HEADER_SIZE + COMMON_OBJECT_RECORD_SIZE:
            raise UW2ObjectDataError(f"UW2 COMOBJ.DAT too small: {len(data)} bytes")
        payload_size = len(data) - COMMON_OBJECT_HEADER_SIZE
        if payload_size % COMMON_OBJECT_RECORD_SIZE:
            raise UW2ObjectDataError(
                f"UW2 COMOBJ.DAT size misaligned: {len(data)} bytes, "
                f"{payload_size % COMMON_OBJECT_RECORD_SIZE} trailing bytes"
            )
        records = tuple(
            _decode_common_object(
                item_id, data[offset : offset + COMMON_OBJECT_RECORD_SIZE]
            )
            for item_id, offset in enumerate(
                range(COMMON_OBJECT_HEADER_SIZE, len(data), COMMON_OBJECT_RECORD_SIZE)
            )
        )
        return cls(records)

    def get(self, item_id: int) -> UW2CommonObject:
        """Return metadata by UU2 item ID."""
        if item_id < 0 or item_id >= len(self.records):
            raise UW2ObjectDataError(
                f"UW2 item ID {item_id} outside COMOBJ.DAT range 0..{len(self.records) - 1}"
            )
        return self.records[item_id]


class UW2AnimationTable:
    """Sixteen animation descriptors stored near end of UU2 OBJECTS.DAT."""

    def __init__(self, records: tuple[UW2Animation, ...]) -> None:
        self.records = records

    @classmethod
    def from_file(cls, path: str | Path) -> UW2AnimationTable:
        """Read animation descriptors from ``OBJECTS.DAT``."""
        return cls.from_data(Path(path).read_bytes())

    @classmethod
    def from_data(cls, data: bytes) -> UW2AnimationTable:
        """Decode item 448..463 animation records at offset 0xDA2."""
        required = ANIMATION_TABLE_OFFSET + 16 * ANIMATION_RECORD_SIZE
        if len(data) < required:
            raise UW2ObjectDataError(
                f"UW2 OBJECTS.DAT too small for animation table: {len(data)} bytes, need {required}"
            )
        records = []
        for subclass_index in range(16):
            offset = ANIMATION_TABLE_OFFSET + subclass_index * ANIMATION_RECORD_SIZE
            animation_type, unknown, start_frame, frame_count = data[
                offset : offset + 4
            ]
            records.append(
                UW2Animation(
                    item_id=ANIMATION_ITEM_FIRST + subclass_index,
                    animation_type=animation_type,
                    unknown=unknown,
                    start_frame=start_frame,
                    frame_count=frame_count,
                )
            )
        return cls(tuple(records))

    def get(self, item_id: int) -> UW2Animation:
        """Return animation descriptor for item ID 448..463."""
        if item_id < ANIMATION_ITEM_FIRST or item_id > ANIMATION_ITEM_LAST:
            raise UW2ObjectDataError(
                f"UW2 animation item ID must be 448..463: {item_id}"
            )
        return self.records[item_id - ANIMATION_ITEM_FIRST]


def _decode_common_object(item_id: int, record: bytes) -> UW2CommonObject:
    mass_word = int.from_bytes(record[1:3], "little")
    flags = record[3]
    property_flags = record[6]
    ownership_flags = record[7]
    render_flags = record[9]
    detail_flags = record[10]
    render_type = render_flags & 0x03
    return UW2CommonObject(
        item_id=item_id,
        height=record[0] * 2,
        radius=mass_word & 0x07,
        is_animated=bool(mass_word & 0x08),
        mass_tenths=mass_word >> 4,
        can_place_item=bool(flags & 0x02),
        is_usable=bool(flags & 0x04),
        is_temporary=bool(flags & 0x08),
        is_decal=bool(flags & 0x10),
        can_put_in_inventory=bool(flags & 0x20),
        can_link=bool(flags & 0x40),
        is_container=bool(flags & 0x80),
        monetary_value=int.from_bytes(record[4:6], "little"),
        is_solid=bool(property_flags & 0x01),
        activate_on_impact=bool(property_flags & 0x02),
        quality_class=(property_flags >> 2) & 0x03,
        can_pick_up=bool(ownership_flags & 0x20),
        can_be_owned=bool(ownership_flags & 0x80),
        render_type=render_type,
        render_type_name=RENDER_TYPE_NAMES[render_type],
        culling_priority=render_flags >> 2,
        quality_type=detail_flags & 0x0F,
        look_at_detail=bool(detail_flags & 0x10),
    )
