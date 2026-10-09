"""
U8 save-game archive parser.

Provides :class:`U8SaveArchive` for reading Ultima 8 save-game files
(U8SAVE.000, etc.).

Example::

    from titan.save import U8SaveArchive

    save = U8SaveArchive.from_file("U8SAVE.000")
    for name, size in save.list_entries():
        print(f"{name}: {size} bytes")

    nonfixed = save.get_data("NONFIXED.DAT")
"""

from __future__ import annotations

__all__ = ["U8SaveArchive"]

import struct
from pathlib import Path
from typing import Optional


class U8SaveArchive:
    """
    Parser for Ultima 8 save-game archive files (U8SAVE.000, etc.).

    Format (from filesys/U8SaveFile.cpp)::

        0x00..0x16  "Ultima 8 SaveGame File." (23 bytes)
        0x17        null terminator
        0x18..0x19  uint16  entry count
        0x1A+       entries:
            uint32  name_length (includes null terminator)
            bytes   name (null-terminated ASCII)
            uint32  data_size
            bytes   data
    """

    SIGNATURE: bytes = b"Ultima 8 SaveGame File."

    def __init__(self, entries: dict[str, tuple[int, int]], data: bytes) -> None:
        self.entries: dict[str, tuple[int, int]] = entries  # name -> (offset, size)
        self._data: bytes = data

    @classmethod
    def from_file(cls, filepath: str | Path) -> U8SaveArchive:
        """Load a U8 save archive from disk."""
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> U8SaveArchive:
        """Parse a U8 save archive from raw bytes."""
        if len(data) < 0x1A:
            raise ValueError("File too small for U8 save format")
        if data[: len(cls.SIGNATURE)] != cls.SIGNATURE:
            raise ValueError("Not a U8 save file (signature mismatch)")
        if data[23] != 0:
            raise ValueError("U8 saved state: invalid save header terminator")
        count = struct.unpack_from("<H", data, 0x18)[0]
        entries: dict[str, tuple[int, int]] = {}
        names: set[str] = set()
        pos = 0x1A
        for _ in range(count):
            if pos + 4 > len(data):
                raise ValueError("U8 saved state: truncated entry name length")
            name_len = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            if name_len < 2 or pos + name_len + 4 > len(data):
                raise ValueError("U8 saved state: invalid entry name bounds")
            raw_name = data[pos : pos + name_len]
            if raw_name[-1] != 0 or b"\x00" in raw_name[:-1]:
                raise ValueError("U8 saved state: invalid entry name terminator")
            try:
                name = raw_name[:-1].decode("ascii")
            except UnicodeDecodeError as error:
                raise ValueError("U8 saved state: entry name must be ASCII") from error
            if (
                name in {".", ".."}
                or any(c in name for c in "/\\:")
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
            ):
                raise ValueError("U8 saved state: entry name must be a plain filename")
            if name.upper() in names:
                raise ValueError("U8 saved state: duplicate entry name")
            names.add(name.upper())
            pos += name_len
            size = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            if pos + size > len(data):
                raise ValueError("U8 saved state: truncated entry payload")
            entries[name] = (pos, size)
            pos += size
        return cls(entries, data)

    @staticmethod
    def is_save_file(data: bytes) -> bool:
        """Check if data starts with U8 save signature."""
        return data[: len(U8SaveArchive.SIGNATURE)] == U8SaveArchive.SIGNATURE

    def list_entries(self) -> list[tuple[str, int]]:
        """Return list of ``(name, size)`` tuples."""
        return [(name, size) for name, (_, size) in self.entries.items()]

    def get_data(self, name: str) -> Optional[bytes]:
        """Extract a named entry's data. Returns ``None`` if not found."""
        actual_name = next(
            (key for key in self.entries if key.upper() == name.upper()), None
        )
        if actual_name is None:
            return None
        offset, size = self.entries[actual_name]
        return self._data[offset : offset + size]
