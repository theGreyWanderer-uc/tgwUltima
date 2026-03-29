"""
Flex archive format handler for Ultima VII (Exult).

Provides :class:`U7FlexArchive` for reading, writing, and manipulating the
Flex archive format as used by Ultima VII (Black Gate / Serpent Isle) and
the Exult engine.

.. important::

    The U7/Exult Flex header is **NOT** the same as the U8/Pentagram Flex
    header.  U7 uses ``magic1 = 0xFFFF1A00`` at offset 0x50 with an 80-byte
    null-padded title.  U8 uses 0x1A fill bytes with a different layout.
    Using the wrong writer corrupts the file for the other engine.

Example::

    from titan.u7.flex import U7FlexArchive

    archive = U7FlexArchive.from_file("FONTS.VGA")
    archive.records[12] = new_font_data
    archive.save("FONTS_PATCHED.VGA")

Exult source reference: ``exult/files/Flex.h``, ``exult/files/Flex.cc``.
"""

from __future__ import annotations

__all__ = [
    "U7_FLEX_HEADER_LEN",
    "U7_FLEX_TITLE_LEN",
    "U7_FLEX_MAGIC1",
    "U7_FLEX_MAGIC2",
    "U7_FLEX_TABLE_OFFSET",
    "U7_FLEX_RECORD_ENTRY_SIZE",
    "U7FlexArchive",
]

import os
import struct
import sys
from pathlib import Path
from typing import Optional

from titan._version import TITAN_VERSION

# ---------------------------------------------------------------------------
# U7/Exult Flex format constants  (from exult/files/Flex.h)
# ---------------------------------------------------------------------------
#
# Binary layout (all little-endian)::
#
#   Offset  Size    Field
#   0x00    80      char title[80]          — null-padded ASCII title
#   0x50    4       uint32 magic1           — 0xFFFF1A00
#   0x54    4       uint32 count            — number of records
#   0x58    4       uint32 magic2           — 0x000000CC (orig)
#                                             or 0x0000CC00+ver (exult_v2)
#   0x5C    36      uint32 padding[9]       — all zeros
#   0x80    N*8     record table            — (offset:u32, size:u32) per record
#   0x80+N*8 ...    record data
#

U7_FLEX_HEADER_LEN: int = 128      # 0x80
U7_FLEX_TITLE_LEN: int = 80        # 0x50
U7_FLEX_MAGIC1: int = 0xFFFF1A00   # Required at offset 0x50
U7_FLEX_MAGIC2: int = 0x000000CC   # Original version marker at 0x58
U7_FLEX_EXULT_MAGIC2: int = 0x0000CC00  # Exult v2 base (+ version byte)
U7_FLEX_HEADER_PADDING: int = 9    # 9 × uint32 zeros (0x5C..0x7F)
U7_FLEX_TABLE_OFFSET: int = 0x80
U7_FLEX_RECORD_ENTRY_SIZE: int = 8


class U7FlexArchive:
    """
    Reader/writer for the Flex archive format used by Ultima VII / Exult.

    Binary layout (all little-endian uint32 unless noted)::

        Offset  Size    Description
        0x00    0x50    Title (ASCII, null-padded to 80 bytes)
        0x50    0x04    magic1 = 0xFFFF1A00
        0x54    0x04    Record count
        0x58    0x04    magic2 = 0x000000CC (original) or 0x0000CC00+ver
        0x5C    0x24    Padding (9 × uint32 zeros)
        0x80    N*8     Record table (offset uint32, size uint32) per record
        0x80+N*8 ...    Record data
    """

    def __init__(self) -> None:
        self.title: str = ""
        self.records: list[bytes] = []
        self.magic2: int = U7_FLEX_MAGIC2
        self._source_path: Optional[str] = None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def is_u7_flex(filepath: str) -> bool:
        """Check whether a file is a valid U7/Exult Flex archive."""
        try:
            with open(filepath, "rb") as f:
                header = f.read(U7_FLEX_HEADER_LEN)
                if len(header) < U7_FLEX_HEADER_LEN:
                    return False
                magic = struct.unpack_from("<I", header, U7_FLEX_TITLE_LEN)[0]
                return magic == U7_FLEX_MAGIC1
        except OSError:
            return False

    @staticmethod
    def _validate_header(header: bytes) -> bool:
        """Validate a U7 Flex header by checking magic1 at offset 0x50."""
        if len(header) < U7_FLEX_HEADER_LEN:
            return False
        magic = struct.unpack_from("<I", header, U7_FLEX_TITLE_LEN)[0]
        return magic == U7_FLEX_MAGIC1

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, filepath: str) -> U7FlexArchive:
        """Load a U7 Flex archive from disk."""
        archive = cls()
        archive._source_path = filepath

        with open(filepath, "rb") as f:
            data = f.read()

        if len(data) < U7_FLEX_HEADER_LEN:
            raise ValueError(
                f"File too small for a U7 Flex archive: {filepath}"
            )

        if not cls._validate_header(data[:U7_FLEX_HEADER_LEN]):
            magic = struct.unpack_from("<I", data, U7_FLEX_TITLE_LEN)[0]
            raise ValueError(
                f"Invalid U7 Flex header in {filepath}: "
                f"magic1=0x{magic:08X}, expected 0x{U7_FLEX_MAGIC1:08X}"
            )

        # Title: 80 bytes null-padded ASCII
        archive.title = (
            data[:U7_FLEX_TITLE_LEN]
            .split(b"\x00", 1)[0]
            .decode("ascii", errors="replace")
        )

        # Record count at 0x54
        count = struct.unpack_from("<I", data, 0x54)[0]

        # Magic2 / version at 0x58
        archive.magic2 = struct.unpack_from("<I", data, 0x58)[0]

        # Record table at 0x80
        archive.records = []
        for i in range(count):
            table_pos = U7_FLEX_TABLE_OFFSET + i * U7_FLEX_RECORD_ENTRY_SIZE
            if table_pos + 8 > len(data):
                print(
                    f"  WARNING: Record table truncated at entry {i}",
                    file=sys.stderr,
                )
                break
            offset, size = struct.unpack_from("<II", data, table_pos)
            if size > 0 and offset > 0:
                record_data = data[offset : offset + size]
                if len(record_data) != size:
                    print(
                        f"  WARNING: Record {i} truncated "
                        f"(expected {size}, got {len(record_data)})",
                        file=sys.stderr,
                    )
                archive.records.append(record_data)
            else:
                archive.records.append(b"")

        return archive

    @classmethod
    def from_bytes(cls, data: bytes) -> U7FlexArchive:
        """Load a U7 Flex archive from raw bytes."""
        archive = cls()
        if len(data) < U7_FLEX_HEADER_LEN:
            raise ValueError("Data too small for a U7 Flex archive")
        if not cls._validate_header(data[:U7_FLEX_HEADER_LEN]):
            raise ValueError("Invalid U7 Flex header in data")

        archive.title = (
            data[:U7_FLEX_TITLE_LEN]
            .split(b"\x00", 1)[0]
            .decode("ascii", errors="replace")
        )
        count = struct.unpack_from("<I", data, 0x54)[0]
        archive.magic2 = struct.unpack_from("<I", data, 0x58)[0]

        archive.records = []
        for i in range(count):
            table_pos = U7_FLEX_TABLE_OFFSET + i * U7_FLEX_RECORD_ENTRY_SIZE
            offset, size = struct.unpack_from("<II", data, table_pos)
            if size > 0 and offset > 0:
                archive.records.append(data[offset : offset + size])
            else:
                archive.records.append(b"")

        return archive

    def get_record(self, index: int) -> bytes:
        """Return raw bytes for a record by index."""
        if 0 <= index < len(self.records):
            return self.records[index]
        raise IndexError(
            f"Record index {index} out of range (0..{len(self.records) - 1})"
        )

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Serialize this archive to U7/Exult Flex format bytes.

        Produces a header with ``magic1 = 0xFFFF1A00`` at offset 0x50,
        matching the format that Exult's ``Flex_header::read()`` expects.
        """
        count = len(self.records)

        # --- Header (128 bytes) ---
        header = bytearray(U7_FLEX_HEADER_LEN)

        # Title: 80 bytes null-padded (matches Exult's Flex_header::write)
        title_bytes = self.title.encode("ascii", errors="replace")[
            :U7_FLEX_TITLE_LEN
        ]
        header[: len(title_bytes)] = title_bytes
        # Remaining title bytes stay 0x00 (already zeroed)

        # magic1 at 0x50
        struct.pack_into("<I", header, 0x50, U7_FLEX_MAGIC1)

        # count at 0x54
        struct.pack_into("<I", header, 0x54, count)

        # magic2 at 0x58
        struct.pack_into("<I", header, 0x58, self.magic2)

        # padding[9] at 0x5C..0x7F — already zeroed

        # --- Record table (8 * count bytes) ---
        table_size = count * U7_FLEX_RECORD_ENTRY_SIZE
        table = bytearray(table_size)

        data_start = U7_FLEX_HEADER_LEN + table_size
        current_offset = data_start

        data_blobs = bytearray()
        for i, record in enumerate(self.records):
            if record and len(record) > 0:
                struct.pack_into(
                    "<I", table, i * U7_FLEX_RECORD_ENTRY_SIZE, current_offset
                )
                struct.pack_into(
                    "<I",
                    table,
                    i * U7_FLEX_RECORD_ENTRY_SIZE + 4,
                    len(record),
                )
                data_blobs.extend(record)
                current_offset += len(record)
            else:
                # Empty record: offset=0, size=0 (already zeroed)
                pass

        return bytes(header) + bytes(table) + bytes(data_blobs)

    def save(self, filepath: str) -> None:
        """Write this archive to a file."""
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(self.to_bytes())
        print(
            f"Wrote U7 Flex archive: {filepath} "
            f"({len(self.records)} records, "
            f"{os.path.getsize(filepath):,} bytes)"
        )

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_directory(cls, dirpath: str, title: str = "") -> U7FlexArchive:
        """Build a U7 Flex archive from numbered files in a directory.

        Files should be named with a numeric index (e.g., ``0000.bin``,
        ``0001.shp``).  The leading digits determine record position.
        Gaps are filled with empty records.
        """
        archive = cls()
        archive.title = title or f"Written by TITAN v{TITAN_VERSION}"

        dirpath_p = Path(dirpath)
        if not dirpath_p.is_dir():
            raise FileNotFoundError(f"Directory not found: {dirpath_p}")

        indexed_files: dict[int, Path] = {}
        for entry in sorted(dirpath_p.iterdir()):
            if not entry.is_file():
                continue
            if entry.name.endswith(".meta.txt"):
                continue
            num_part = entry.stem.split("_", 1)[0]
            try:
                idx = int(num_part)
                indexed_files[idx] = entry
            except ValueError:
                continue

        if not indexed_files:
            print(
                f"WARNING: No numerically named files found in {dirpath_p}",
                file=sys.stderr,
            )
            return archive

        max_index = max(indexed_files.keys())
        archive.records = []
        for i in range(max_index + 1):
            if i in indexed_files:
                archive.records.append(indexed_files[i].read_bytes())
            else:
                archive.records.append(b"")

        return archive

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Return a human-readable summary of the archive."""
        non_empty = sum(1 for r in self.records if r)
        total_data = sum(len(r) for r in self.records)
        vers = "exult_v2" if (self.magic2 & 0xFFFFFF00) == U7_FLEX_EXULT_MAGIC2 else "orig"
        lines = [
            "U7 Flex Archive Summary",
            f"  Source:       {self._source_path or '(in-memory)'}",
            f"  Title:        {self.title!r}",
            f"  Records:      {len(self.records)}",
            f"  Non-empty:    {non_empty}",
            f"  Total data:   {total_data:,} bytes",
            f"  magic2:       0x{self.magic2:08X} ({vers})",
        ]
        return "\n".join(lines)

    def record_table(self) -> str:
        """Return a formatted table of all records."""
        lines = [f"{'Index':>6}  {'Size':>12}  {'Preview'}"]
        lines.append("-" * 50)
        for i, record in enumerate(self.records):
            if record:
                preview = record[:16].hex(" ")
                if len(record) > 16:
                    preview += " ..."
                lines.append(f"{i:>6}  {len(record):>12,}  {preview}")
            else:
                lines.append(f"{i:>6}  {'(empty)':>12}")
        return "\n".join(lines)
