"""Decode U9 object labels and UI references from ``static/TYPENAME.FLX``.

The FLX slot index is the object type ID. Every used entry begins with a
signed readable-text reference and an object-icon reference, followed by an
optional NUL-terminated ASCII display label. The shipped archive has 8,192
used entries; entries without a label contain only the six-byte header.
"""

from __future__ import annotations

__all__ = [
    "CURRENT_TYPE_NAME_REPRESENTATION",
    "DEFAULT_OBJECT_ICON_ID",
    "U9TypeNameEntry",
    "U9TypeNameError",
    "U9TypeNames",
]

import os
import struct
from dataclasses import dataclass

from titan.u9.flx_archive import U9FlxArchive

RECORD_HEADER_SIZE = 6
RECORD_HEADER_STRUCT = "<iH"
DEFAULT_OBJECT_ICON_ID = 7041
CURRENT_TYPE_NAME_REPRESENTATION = "six_byte_header"


class U9TypeNameError(Exception):
    """Raised when a ``TYPENAME.FLX`` entry is structurally malformed."""


@dataclass(frozen=True)
class U9TypeNameEntry:
    """One object type's readable-text link, icon link, and display label."""

    type_id: int
    readable_text_id: int
    object_icon_id: int
    display_name: str | None
    trailing_bytes: bytes
    raw: bytes

    @property
    def record_representation(self) -> str:
        """Titan label for the decoded entry layout."""
        return CURRENT_TYPE_NAME_REPRESENTATION

    @property
    def warnings(self) -> tuple[str, ...]:
        """Report unusual-but-retained values in a structurally valid entry."""
        warnings: list[str] = []
        if self.trailing_bytes:
            warnings.append("post_terminator_bytes_present")
        if self.display_name and "\ufffd" in self.display_name:
            warnings.append("non_ascii_display_name")
        return tuple(warnings)

    @property
    def has_readable_text(self) -> bool:
        """Whether the object opens linked readable text (positive IDs only)."""
        return self.readable_text_id > 0

    @property
    def uses_default_icon(self) -> bool:
        """Whether the object uses the shipped generic/unknown object icon."""
        return self.object_icon_id == DEFAULT_OBJECT_ICON_ID

    # Compatibility views for Titan's earlier partial decoder. The old names
    # described observations rather than the fields' now-confirmed meanings.
    @property
    def reserved(self) -> int:
        """Compatibility alias for :attr:`readable_text_id`."""
        return self.readable_text_id

    @property
    def marker(self) -> int:
        """Compatibility alias for :attr:`object_icon_id`."""
        return self.object_icon_id

    @property
    def name(self) -> str | None:
        """Compatibility alias for :attr:`display_name`."""
        return self.display_name


def _parse_type_name_entry(type_id: int, data: bytes) -> U9TypeNameEntry:
    if len(data) < RECORD_HEADER_SIZE:
        legacy_hint = (
            "; this may be an unsupported older two-byte-header archive"
            if len(data) >= 2
            else ""
        )
        raise U9TypeNameError(
            f"TYPENAME.FLX entry {type_id} is {len(data)} bytes; "
            f"expected at least {RECORD_HEADER_SIZE}{legacy_hint}"
        )

    readable_text_id, object_icon_id = struct.unpack_from(RECORD_HEADER_STRUCT, data)
    text_storage = data[RECORD_HEADER_SIZE:]
    display_name: str | None = None
    trailing_bytes = b""
    if text_storage:
        terminator = text_storage.find(b"\x00")
        if terminator < 0:
            raise U9TypeNameError(
                f"TYPENAME.FLX entry {type_id} has unterminated display text"
            )
        display_bytes = text_storage[:terminator]
        trailing_bytes = text_storage[terminator + 1 :]
        if display_bytes:
            display_name = display_bytes.decode("ascii", errors="replace")

    return U9TypeNameEntry(
        type_id=type_id,
        readable_text_id=readable_text_id,
        object_icon_id=object_icon_id,
        display_name=display_name,
        trailing_bytes=trailing_bytes,
        raw=bytes(data),
    )


class U9TypeNames:
    """Object-type metadata decoded from ``static/TYPENAME.FLX``."""

    def __init__(self, archive: U9FlxArchive) -> None:
        self.record_representation = CURRENT_TYPE_NAME_REPRESENTATION
        self.entries = tuple(
            _parse_type_name_entry(entry.index, data)
            for entry in archive.entries
            if (data := archive.read_entry(entry.index))
        )
        self._by_id = {entry.type_id: entry for entry in self.entries}

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9TypeNames:
        """Read object-type metadata from a U9 FLX archive."""
        return cls(U9FlxArchive.from_file(filepath))

    def entry_for(self, type_id: int) -> U9TypeNameEntry | None:
        """Return all metadata for one object type, or ``None``."""
        return self._by_id.get(type_id)

    def name_for(self, type_id: int) -> str | None:
        """Return one object type's optional display label."""
        entry = self.entry_for(type_id)
        return entry.display_name if entry else None

    def readable_text_id_for(self, type_id: int) -> int | None:
        """Return one object type's readable-text reference, or ``None``."""
        entry = self.entry_for(type_id)
        return entry.readable_text_id if entry else None

    def object_icon_id_for(self, type_id: int) -> int | None:
        """Return one object type's object-icon reference, or ``None``."""
        entry = self.entry_for(type_id)
        return entry.object_icon_id if entry else None

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)
