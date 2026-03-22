"""
Flex archive format handler for Ultima 8.

Provides :class:`FlexArchive` for reading, writing, and manipulating the
Flex (.flx) indexed archive format, plus helpers for content-type detection.

Example::

    from titan.flex import FlexArchive

    archive = FlexArchive.from_file("U8SHAPES.FLX")
    print(archive.summary())
    for i, record in enumerate(archive.records):
        if record:
            print(f"Record {i}: {len(record)} bytes")

    # Round-trip: extract then rebuild
    archive = FlexArchive.from_file("GLOB.FLX")
    archive.save("GLOB_COPY.FLX")
"""

from __future__ import annotations

__all__ = [
    # Constants
    "FLEX_HEADER_SIZE",
    "FLEX_COMMENT_LEN",
    "FLEX_MAGIC_OFFSET",
    "FLEX_COUNT_OFFSET",
    "FLEX_UNK_OFFSET",
    "FLEX_FILESIZE_OFFSET",
    "FLEX_TABLE_OFFSET",
    "FLEX_RECORD_ENTRY_SIZE",
    "FLEX_FILL_BYTE",
    "FLEX_NAME_MAX_LEN",
    "KNOWN_FLEX_FILES",
    "CONTENT_EXT_MAP",
    # Classes
    "FlexArchive",
    # Functions
    "detect_record_type",
    "get_extension_for_flex",
]

import os
import struct
import sys
from pathlib import Path
from typing import Optional

from titan._version import TITAN_VERSION

# ---------------------------------------------------------------------------
# Flex file format constants (little-endian throughout)
# ---------------------------------------------------------------------------
# Header layout:
#   0x00..0x51  (82 bytes)  Comment/title field (ASCII, padded with 0x1A)
#   0x52..0x53  (2 bytes)   Continuation of 0x1A padding (magic sentinel)
#   0x54..0x57  (4 bytes)   Record count (uint32 LE)
#   0x58..0x5B  (4 bytes)   Unknown field (often 0x00000001)
#   0x5C..0x5F  (4 bytes)   Total file size (uint32 LE)
#   0x60..0x7F  (32 bytes)  Reserved (zeros)
#   0x80+                   Record table: count * 8 bytes (offset:u32, size:u32)
#   After table              Raw record data

FLEX_HEADER_SIZE: int = 0x80          # 128 bytes total header before record table
FLEX_COMMENT_LEN: int = 0x52         # 82 bytes for the comment block
FLEX_MAGIC_OFFSET: int = 0x52        # Where 0x1A padding must exist
FLEX_COUNT_OFFSET: int = 0x54        # uint32 record count
FLEX_UNK_OFFSET: int = 0x58          # uint32 unknown (usually 1)
FLEX_FILESIZE_OFFSET: int = 0x5C     # uint32 total file size
FLEX_TABLE_OFFSET: int = 0x80        # Start of the offset/size table
FLEX_RECORD_ENTRY_SIZE: int = 8      # Each record entry: 4 bytes offset + 4 bytes size
FLEX_FILL_BYTE: int = 0x1A           # Sentinel/fill byte used in header
FLEX_NAME_MAX_LEN: int = 32          # Max characters used from name table for filenames

# Known Flex file names and their typical content descriptions.
KNOWN_FLEX_FILES: dict[str, dict] = {
    "U8SHAPES.FLX":  {"desc": "World object shapes (RLE compressed sprites)",
                       "content": "shape"},
    "U8GUMPS.FLX":   {"desc": "GUI/menu graphics (gump shapes)",
                       "content": "shape"},
    "U8FONTS.FLX":   {"desc": "Bitmap fonts (shape-based glyphs)",
                       "content": "shape"},
    "GLOB.FLX":      {"desc": "Global object definitions",
                       "content": "data"},
    "SOUND.FLX":     {"desc": "Sound effects (Sonarc compressed audio)",
                       "content": "audio"},
    "MUSIC.FLX":     {"desc": "Music tracks (XMIDI format)",
                       "content": "xmidi"},
    "EUSECODE.FLX":  {"desc": "Usecode bytecode (game scripts)",
                       "content": "usecode"},
    "SPEECH.FLX":    {"desc": "Speech audio samples",
                       "content": "audio"},
    "DTABLE.FLX":    {"desc": "Data tables",
                       "content": "data"},
    "GUMPAGE.FLX":   {"desc": "Gump page graphics",
                       "content": "shape"},
}

# Extension mapping for extracted records based on content type
CONTENT_EXT_MAP: dict[str, str] = {
    "shape":   ".shp",
    "audio":   ".raw",
    "xmidi":   ".xmi",
    "usecode": ".uc",
    "data":    ".dat",
    "unknown": ".bin",
}


# ============================================================================
# FLEX FILE FORMAT HANDLER
# ============================================================================

class FlexArchive:
    """
    Reader/writer for the Flex (.flx) archive format used by Ultima 8.

    Flex is an indexed container: a fixed-size header followed by a table of
    (offset, size) pairs pointing to raw record blobs packed sequentially.

    Binary layout (all little-endian uint32 unless noted)::

        Offset  Size    Description
        0x00    0x52    ASCII comment (padded to end with 0x1A bytes)
        0x52    0x02    0x1A 0x1A (continuation of padding / magic)
        0x54    0x04    Record count
        0x58    0x04    Unknown (typically 1)
        0x5C    0x04    Total file size
        0x60    0x20    Reserved (zeros)
        0x80    N*8     Record table (offset uint32, size uint32) per record
        0x80+N*8 ...    Record data
    """

    def __init__(self) -> None:
        self.comment: str = ""
        self.records: list[bytes] = []
        self.record_names: list[str] = []
        self.unknown_field: int = 1
        self._source_path: Optional[str] = None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def is_flex(filepath: str) -> bool:
        """Check whether a file looks like a valid Flex archive."""
        try:
            with open(filepath, "rb") as f:
                header = f.read(FLEX_HEADER_SIZE)
                if len(header) < FLEX_HEADER_SIZE:
                    return False
                return FlexArchive._validate_header(header)
        except OSError:
            return False

    @staticmethod
    def _validate_header(header: bytes) -> bool:
        """
        Validate a Flex header per Pentagram's FlexFile::isFlexFile logic.

        Scan bytes 0x00..0x51 to find the first 0x1A. From that point
        through 0x51, every byte must be 0x1A.
        """
        comment_region = header[:FLEX_COMMENT_LEN]
        first_1a = -1
        for i, b in enumerate(comment_region):
            if b == FLEX_FILL_BYTE:
                first_1a = i
                break

        if first_1a < 0:
            return False

        # Every byte from first_1a to end of comment region must be 0x1A
        for i in range(first_1a, FLEX_COMMENT_LEN):
            if comment_region[i] != FLEX_FILL_BYTE:
                return False

        return True

    # ------------------------------------------------------------------
    # Reading / Extraction
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, filepath: str) -> FlexArchive:
        """Load a Flex archive from disk."""
        archive = cls()
        archive._source_path = filepath

        with open(filepath, "rb") as f:
            data = f.read()

        if len(data) < FLEX_HEADER_SIZE:
            raise ValueError(f"File too small to be a Flex archive: {filepath}")

        if not cls._validate_header(data[:FLEX_HEADER_SIZE]):
            raise ValueError(f"Invalid Flex header in: {filepath}")

        # Extract comment (everything before first 0x1A)
        comment_bytes = data[:FLEX_COMMENT_LEN]
        end = comment_bytes.find(FLEX_FILL_BYTE)
        if end < 0:
            end = FLEX_COMMENT_LEN
        archive.comment = comment_bytes[:end].decode("ascii", errors="replace").rstrip("\x00")

        # Read record count
        count = struct.unpack_from("<I", data, FLEX_COUNT_OFFSET)[0]

        # Read unknown field
        archive.unknown_field = struct.unpack_from("<I", data, FLEX_UNK_OFFSET)[0]

        # Read record table and extract record data
        archive.records = []
        for i in range(count):
            table_pos = FLEX_TABLE_OFFSET + i * FLEX_RECORD_ENTRY_SIZE
            offset, size = struct.unpack_from("<II", data, table_pos)
            if size > 0 and offset > 0:
                record_data = data[offset:offset + size]
                if len(record_data) != size:
                    print(f"  WARNING: Record {i} truncated "
                          f"(expected {size}, got {len(record_data)})",
                          file=sys.stderr)
                archive.records.append(record_data)
            else:
                # Empty/null record — preserve index position
                archive.records.append(b"")

        archive._parse_name_table(flex_name=os.path.basename(filepath))
        return archive

    @classmethod
    def from_bytes(cls, data: bytes) -> FlexArchive:
        """Load a Flex archive from raw bytes (same logic as from_file)."""
        archive = cls()
        if len(data) < FLEX_HEADER_SIZE:
            raise ValueError("Data too small to be a Flex archive")
        if not cls._validate_header(data[:FLEX_HEADER_SIZE]):
            raise ValueError("Invalid Flex header in data")
        comment_bytes = data[:FLEX_COMMENT_LEN]
        end = comment_bytes.find(FLEX_FILL_BYTE)
        if end < 0:
            end = FLEX_COMMENT_LEN
        archive.comment = comment_bytes[:end].decode("ascii", errors="replace").rstrip("\x00")
        count = struct.unpack_from("<I", data, FLEX_COUNT_OFFSET)[0]
        archive.unknown_field = struct.unpack_from("<I", data, FLEX_UNK_OFFSET)[0]
        archive.records = []
        for i in range(count):
            table_pos = FLEX_TABLE_OFFSET + i * FLEX_RECORD_ENTRY_SIZE
            offset, size = struct.unpack_from("<II", data, table_pos)
            if size > 0 and offset > 0:
                record_data = data[offset:offset + size]
                archive.records.append(record_data)
            else:
                archive.records.append(b"")
        archive._parse_name_table()
        return archive

    def get_record(self, index: int) -> bytes:
        """Return raw bytes for a record by index."""
        if 0 <= index < len(self.records):
            return self.records[index]
        raise IndexError(f"Record index {index} out of range (0..{len(self.records) - 1})")

    # ------------------------------------------------------------------
    # Name-table parsing
    # ------------------------------------------------------------------

    def _parse_name_table(self, flex_name: str = "") -> None:
        """
        Detect and parse a name table from record 0, populating
        :attr:`record_names` with one entry per record.

        Recognised formats:

        * **SOUND.FLX style** — record 0 is pure ASCII with fixed 8-byte
          entries (each name padded with NUL).  Names map to records 1..N.
        * **MUSIC.FLX style** — record 0 is a text playlist where each
          non-comment line starts with a filename.  Names map to records 1..N.
        """
        self.record_names = [""] * len(self.records)
        if not self.records or not self.records[0]:
            return

        rec0 = self.records[0]
        upper = flex_name.upper()

        # --- MUSIC.FLX: text playlist ----------------------------------
        if upper == "MUSIC.FLX":
            self._parse_music_playlist(rec0)
            return

        # --- Fixed 8-byte ASCII name table (SOUND.FLX, etc.) -----------
        if self._is_ascii_nul_data(rec0) and len(rec0) >= 8 and len(rec0) % 8 == 0:
            self._parse_fixed_name_table(rec0, entry_size=8)
            return

    @staticmethod
    def _is_ascii_nul_data(data: bytes) -> bool:
        """Return True if *data* consists only of printable ASCII + NUL."""
        for b in data:
            if b == 0:
                continue
            if b < 0x20 or b > 0x7E:
                return False
        return True

    def _parse_fixed_name_table(self, rec0: bytes, entry_size: int) -> None:
        """Parse a fixed-width name table from record 0.

        Names at index *i* are assigned to ``record_names[i + 1]`` because
        record 0 holds the table itself.
        """
        num_entries = len(rec0) // entry_size
        for i in range(num_entries):
            raw = rec0[i * entry_size:(i + 1) * entry_size]
            name = raw.rstrip(b"\x00").decode("ascii", errors="replace")
            rec_idx = i + 1
            if rec_idx < len(self.record_names):
                self.record_names[rec_idx] = name

    def _parse_music_playlist(self, rec0: bytes) -> None:
        """Parse MUSIC.FLX's text playlist from record 0.

        Each line before the first ``#`` marker provides a track filename
        (e.g. ``intro.xmi 1 10 5``).  The stem is used as the record name.
        """
        text = rec0.decode("ascii", errors="replace")
        lines = text.replace("\r\n", "\n").split("\n")
        rec_idx = 1
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                break
            parts = line.split()
            if parts:
                # Strip extension to get a clean name
                stem = Path(parts[0]).stem
                if rec_idx < len(self.record_names):
                    self.record_names[rec_idx] = stem
                rec_idx += 1

    def get_record_name(self, index: int) -> str:
        """Return the name for a record, or empty string if none."""
        if 0 <= index < len(self.record_names):
            return self.record_names[index]
        return ""

    # ------------------------------------------------------------------
    # Convenience extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_filename(name: str, max_len: int = FLEX_NAME_MAX_LEN) -> str:
        """Sanitise a name-table entry for use as a filename stem.

        Truncates to *max_len* characters and strips anything that is
        not alphanumeric, hyphen, underscore, or dot.
        """
        # Keep only filesystem-safe characters
        cleaned = "".join(c for c in name if c.isalnum() or c in "-_.")
        return cleaned[:max_len]

    def extract_all(self, outdir: str, *, flex_name: str = "") -> int:
        """
        Extract all non-empty records to *outdir*, returning the count.

        When the archive contains a name table, each file is named
        ``NNNN_NAME<ext>`` and a companion ``NNNN_NAME.txt`` metadata
        file is written alongside it.  Falls back to ``NNNN<ext>`` when
        no name is available.
        """
        os.makedirs(outdir, exist_ok=True)
        extracted = 0
        for i, record in enumerate(self.records):
            if not record:
                continue
            ext = get_extension_for_flex(flex_name, record)
            name = self.get_record_name(i)
            safe = self._safe_filename(name) if name else ""

            if safe:
                stem = f"{i:04d}_{safe}"
            else:
                stem = f"{i:04d}"

            out_path = os.path.join(outdir, f"{stem}{ext}")
            with open(out_path, "wb") as f:
                f.write(record)

            # Write companion metadata file
            self._write_record_metadata(
                outdir, stem, i, name, record, flex_name
            )

            extracted += 1
        return extracted

    @staticmethod
    def _write_record_metadata(outdir: str, stem: str,
                                index: int, name: str,
                                record: bytes, flex_name: str) -> None:
        """Write a ``.txt`` sidecar with record metadata."""
        meta_path = os.path.join(outdir, f"{stem}.txt")
        content_type = detect_record_type(record)
        lines = [
            f"Flex source:    {flex_name or '(unknown)'}",
            f"Record index:   {index}",
            f"Record name:    {name or '(none)'}",
            f"Record size:    {len(record):,} bytes",
            f"Content type:   {content_type}",
            f"Header preview: {record[:16].hex(' ')}",
        ]

        # Content-specific details
        if content_type == "audio" and len(record) >= 0x24:
            total_len = struct.unpack_from("<I", record, 0)[0]
            sample_rate = struct.unpack_from("<H", record, 4)[0]
            lines.append(f"Sonarc length:  {total_len} samples")
            lines.append(f"Sample rate:    {sample_rate} Hz")
        elif content_type == "xmidi" and len(record) >= 8:
            form_size = struct.unpack_from(">I", record, 4)[0]
            lines.append(f"FORM size:      {form_size}")
        elif content_type == "shape" and len(record) >= 6:
            frame_count = struct.unpack_from("<H", record, 4)[0]
            lines.append(f"Frame count:    {frame_count}")

        with open(meta_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # ------------------------------------------------------------------
    # Writing / Reconstruction
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Serialize this archive to Flex format bytes."""
        count = len(self.records)

        # --- Build header ---
        header = bytearray(FLEX_HEADER_SIZE)

        # Comment (ASCII, padded with 0x1A to fill 0x52 bytes)
        comment_encoded = self.comment.encode("ascii", errors="replace")[:FLEX_COMMENT_LEN]
        header[:len(comment_encoded)] = comment_encoded
        # Fill remainder of comment region with 0x1A
        for i in range(len(comment_encoded), FLEX_COMMENT_LEN):
            header[i] = FLEX_FILL_BYTE

        # Replicate Pentagram's FlexWriter::writeHead exactly:
        #   for i in 0..19: write4(0x1A1A1A1A)  -> bytes 0x00..0x4F all 0x1A
        #   write4(0x00001A1A)  -> bytes 0x50=0x1A, 0x51=0x1A, 0x52=0x00, 0x53=0x00
        for i in range(FLEX_COMMENT_LEN):
            header[i] = FLEX_FILL_BYTE
        # 0x52 and 0x53 = 0x00 (from the 0x00001A1A dword at 0x50)
        header[0x52] = 0x00
        header[0x53] = 0x00

        # Record count at 0x54
        struct.pack_into("<I", header, FLEX_COUNT_OFFSET, count)

        # Unknown field at 0x58 (typically 1)
        struct.pack_into("<I", header, FLEX_UNK_OFFSET, self.unknown_field)

        # File size at 0x5C — compute later
        # Reserved 0x60..0x7F already zeroed

        # --- Build record table ---
        table_size = count * FLEX_RECORD_ENTRY_SIZE
        table = bytearray(table_size)

        data_start = FLEX_HEADER_SIZE + table_size
        current_offset = data_start

        data_blobs = bytearray()
        for i, record in enumerate(self.records):
            if record and len(record) > 0:
                struct.pack_into("<I", table, i * FLEX_RECORD_ENTRY_SIZE, current_offset)
                struct.pack_into("<I", table, i * FLEX_RECORD_ENTRY_SIZE + 4, len(record))
                data_blobs.extend(record)
                current_offset += len(record)
            else:
                # Empty record: offset=0, size=0
                struct.pack_into("<I", table, i * FLEX_RECORD_ENTRY_SIZE, 0)
                struct.pack_into("<I", table, i * FLEX_RECORD_ENTRY_SIZE + 4, 0)

        # Total file size
        total_size = FLEX_HEADER_SIZE + table_size + len(data_blobs)
        struct.pack_into("<I", header, FLEX_FILESIZE_OFFSET, total_size)

        return bytes(header) + bytes(table) + bytes(data_blobs)

    def save(self, filepath: str) -> None:
        """Write this archive to a file."""
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(self.to_bytes())
        print(f"Wrote Flex archive: {filepath} "
              f"({len(self.records)} records, "
              f"{os.path.getsize(filepath):,} bytes)")

    @classmethod
    def from_directory(cls, dirpath: str, comment: str = "") -> FlexArchive:
        """
        Build a Flex archive from numbered files in a directory.

        Files should be named with a numeric index (e.g., 0000.bin, 0001.shp,
        or 0001_ARMHIT1A.raw).  The leading digits determine record position.
        Gaps are filled with empty records.  Companion ``.txt`` metadata
        files are ignored.
        """
        archive = cls()
        archive.comment = comment or f"Rebuilt by TITAN v{TITAN_VERSION}"

        dirpath_p = Path(dirpath)
        if not dirpath_p.is_dir():
            raise FileNotFoundError(f"Directory not found: {dirpath_p}")

        # Discover files with numeric prefix (skip .txt metadata sidecars)
        indexed_files: dict[int, Path] = {}
        for entry in sorted(dirpath_p.iterdir()):
            if entry.is_file() and entry.suffix.lower() != ".txt":
                stem = entry.stem
                # Accept "0001" or "0001_ARMHIT1A" — extract leading digits
                num_part = stem.split("_", 1)[0]
                try:
                    idx = int(num_part)
                    indexed_files[idx] = entry
                except ValueError:
                    continue

        if not indexed_files:
            print(f"WARNING: No numerically named files found in {dirpath_p}",
                  file=sys.stderr)
            return archive

        max_index = max(indexed_files.keys())
        archive.records = []
        for i in range(max_index + 1):
            if i in indexed_files:
                archive.records.append(indexed_files[i].read_bytes())
            else:
                archive.records.append(b"")  # Preserve index gaps

        return archive

    # ------------------------------------------------------------------
    # Utility / Info
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Return a human-readable summary of the archive."""
        non_empty = sum(1 for r in self.records if r)
        total_data = sum(len(r) for r in self.records)
        named = sum(1 for n in self.record_names if n)
        lines = [
            "Flex Archive Summary",
            f"  Source:        {self._source_path or '(in-memory)'}",
            f"  Comment:       {self.comment!r}",
            f"  Record count:  {len(self.records)}",
            f"  Non-empty:     {non_empty}",
            f"  Named records: {named}",
            f"  Total data:    {total_data:,} bytes",
            f"  Unknown field: 0x{self.unknown_field:08X}",
        ]
        return "\n".join(lines)

    def record_table(self) -> str:
        """Return a formatted table of all records."""
        lines = [f"{'Index':>6}  {'Name':<12}  {'Size':>12}  {'Preview'}"]
        lines.append("-" * 65)
        for i, record in enumerate(self.records):
            name = self.get_record_name(i)
            name_col = name[:12] if name else ""
            if record:
                preview = record[:16].hex(" ")
                if len(record) > 16:
                    preview += " ..."
                lines.append(f"{i:>6}  {name_col:<12}  {len(record):>12,}  {preview}")
            else:
                lines.append(f"{i:>6}  {name_col:<12}  {'(empty)':>12}")
        return "\n".join(lines)


# ============================================================================
# CONTENT-TYPE DETECTION HELPERS
# ============================================================================

def detect_record_type(data: bytes) -> str:
    """
    Attempt to identify the content type of a raw Flex record.

    Returns a type string key from :data:`CONTENT_EXT_MAP`.
    """
    if not data or len(data) < 4:
        return "unknown"

    # XMIDI detection: starts with "FORM"
    if data[:4] == b"FORM":
        return "xmidi"

    # Shape detection heuristic (from Pentagram's Shape::DetectShapeFormat)
    if len(data) >= 8:
        _, _, frame_count = struct.unpack_from("<HHH", data, 0)
        if 0 < frame_count <= 10000:
            expected_min = 6 + frame_count * 6
            if len(data) >= expected_min:
                if frame_count > 0 and len(data) >= 9:
                    frame0_offset = struct.unpack_from("<I", data, 6)[0] & 0x00FFFFFF
                    if 0 < frame0_offset < len(data):
                        return "shape"

    # Sonarc audio: first 4 bytes = decompressed length, next 2 = sample rate
    if len(data) >= 0x24:
        srate = struct.unpack_from("<H", data, 4)[0]
        if srate in (11111, 22222, 11025, 22050):
            return "audio"

    return "unknown"


def get_extension_for_flex(flex_name: str, record_data: bytes) -> str:
    """
    Determine the best file extension for an extracted record.

    Uses the Flex filename for context and falls back to content detection.
    """
    base = os.path.basename(flex_name).upper()

    # Check if we know this flex
    if base in KNOWN_FLEX_FILES:
        content_type = KNOWN_FLEX_FILES[base]["content"]
        return CONTENT_EXT_MAP.get(content_type, ".bin")

    # Fall back to content-based detection
    content_type = detect_record_type(record_data)
    return CONTENT_EXT_MAP.get(content_type, ".bin")
