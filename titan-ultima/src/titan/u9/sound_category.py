"""Decode the master sound-category table from ``sound/sfxcat.flx``.

The archive has 128 slots. Each used slot contains one fixed 40-byte record;
the slot index and the record's stored category ID are normally identical.
"""

from __future__ import annotations

__all__ = [
    "CATEGORY_RECORD_SIZE",
    "MASTER_CATEGORY_REPRESENTATION",
    "U9SoundCategories",
    "U9SoundCategory",
    "U9SoundCategoryError",
]

import os
import struct
from dataclasses import dataclass

from titan.u9.flx_archive import U9FlxArchive

CATEGORY_RECORD_SIZE = 40
MASTER_CATEGORY_REPRESENTATION = "master_category_record"
_DISPLAY_NAME_OFFSET = 1
_DISPLAY_NAME_SIZE = 33
_ALIGNMENT_OFFSET = 34
_REFERENCE_COUNT_OFFSET = 36


class U9SoundCategoryError(Exception):
    """Raised when a ``sfxcat.flx`` category record is malformed."""


@dataclass(frozen=True)
class U9SoundCategory:
    """One sound action category and its fixed-width archival fields."""

    archive_index: int
    category_id: int
    display_name: str
    name_field: bytes
    alignment_bytes: bytes
    sound_reference_count: int
    raw: bytes

    @property
    def id_matches_index(self) -> bool:
        """Whether the stored category ID agrees with its FLX slot index."""
        return self.category_id == self.archive_index

    @property
    def record_representation(self) -> str:
        """Titan label for this archive-context-specific record layout."""
        return MASTER_CATEGORY_REPRESENTATION

    @property
    def name_is_terminated(self) -> bool:
        """Whether the fixed name cell contains its expected NUL terminator."""
        return b"\x00" in self.name_field

    @property
    def name_padding_bytes(self) -> bytes:
        """Return retained bytes after the first name terminator."""
        _, separator, padding = self.name_field.partition(b"\x00")
        return padding if separator else b""

    @property
    def warnings(self) -> tuple[str, ...]:
        """Report unusual-but-retained values in the master archive context."""
        warnings: list[str] = []
        if not self.id_matches_index:
            warnings.append("stored_id_differs_from_archive_index")
        if not self.name_is_terminated:
            warnings.append("unterminated_display_name")
        if any(self.name_padding_bytes):
            warnings.append("nonzero_name_padding")
        if any(self.alignment_bytes):
            warnings.append("nonzero_alignment_bytes")
        if self.sound_reference_count:
            warnings.append("inactive_reference_count_nonzero")
        return tuple(warnings)


def _parse_sound_category(archive_index: int, data: bytes) -> U9SoundCategory:
    if len(data) != CATEGORY_RECORD_SIZE:
        raise U9SoundCategoryError(
            f"sfxcat.flx entry {archive_index} is {len(data)} bytes; "
            f"expected exactly {CATEGORY_RECORD_SIZE}"
        )

    name_field = bytes(
        data[_DISPLAY_NAME_OFFSET : _DISPLAY_NAME_OFFSET + _DISPLAY_NAME_SIZE]
    )
    display_name = name_field.split(b"\x00", 1)[0].decode("ascii", errors="replace")
    return U9SoundCategory(
        archive_index=archive_index,
        category_id=data[0],
        display_name=display_name,
        name_field=name_field,
        alignment_bytes=bytes(data[_ALIGNMENT_OFFSET:_REFERENCE_COUNT_OFFSET]),
        sound_reference_count=struct.unpack_from("<I", data, _REFERENCE_COUNT_OFFSET)[
            0
        ],
        raw=bytes(data),
    )


class U9SoundCategories:
    """Master sound-category lookup decoded from ``sound/sfxcat.flx``."""

    def __init__(self, archive: U9FlxArchive) -> None:
        self.archive_slot_count = archive.num_entries
        self.categories = tuple(
            _parse_sound_category(entry.index, data)
            for entry in archive.entries
            if (data := archive.read_entry(entry.index))
        )
        self._by_id: dict[int, U9SoundCategory] = {}
        for category in self.categories:
            if category.category_id in self._by_id:
                raise U9SoundCategoryError(
                    f"duplicate stored sound category ID {category.category_id}"
                )
            self._by_id[category.category_id] = category

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9SoundCategories:
        """Read the master sound-category table from a U9 FLX archive."""
        return cls(U9FlxArchive.from_file(filepath))

    def category(self, category_id: int) -> U9SoundCategory | None:
        """Return one category by its stored ID, or ``None``."""
        return self._by_id.get(category_id)

    def name_for(self, category_id: int) -> str | None:
        """Return one category's display label, or ``None``."""
        category = self.category(category_id)
        return category.display_name if category else None

    def __len__(self) -> int:
        return len(self.categories)

    def __iter__(self):
        return iter(self.categories)
