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
    def from_file(cls, filepath: str) -> U8SaveArchive:
        """Load a U8 save archive from disk."""
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> U8SaveArchive:
        """Parse a U8 save archive from raw bytes."""
        if len(data) < 0x1A:
            raise ValueError("File too small for U8 save format")
        if data[:len(cls.SIGNATURE)] != cls.SIGNATURE:
            raise ValueError("Not a U8 save file (signature mismatch)")
        count = struct.unpack_from("<H", data, 0x18)[0]
        entries: dict[str, tuple[int, int]] = {}
        pos = 0x1A
        for _ in range(count):
            if pos + 4 > len(data):
                break
            name_len = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            name = data[pos:pos + name_len].split(b'\x00')[0].decode('ascii')
            pos += name_len
            if pos + 4 > len(data):
                break
            size = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            entries[name] = (pos, size)
            pos += size
        return cls(entries, data)

    @staticmethod
    def is_save_file(data: bytes) -> bool:
        """Check if data starts with U8 save signature."""
        return data[:len(U8SaveArchive.SIGNATURE)] == U8SaveArchive.SIGNATURE

    def list_entries(self) -> list[tuple[str, int]]:
        """Return list of ``(name, size)`` tuples."""
        return [(name, size) for name, (_, size) in self.entries.items()]

    def get_data(self, name: str) -> Optional[bytes]:
        """Extract a named entry's data. Returns ``None`` if not found."""
        if name not in self.entries:
            return None
        offset, size = self.entries[name]
        return self._data[offset:offset + size]
