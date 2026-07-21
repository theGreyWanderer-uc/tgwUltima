"""Synthetic byte-level fixtures for U7 palette/shape/translucency tests.

No real game files are used or required anywhere in this test suite --
every fixture here is built entirely from scratch on disk, matching the
real formats' documented byte layout (see titan.u7.flex, titan.u7.palette).
This mirrors the project's one prior (uncommitted) testing precedent:
hand-constructed synthetic binary records rather than bundled game assets.
"""

from __future__ import annotations

import struct

from titan.u7.flex import U7FlexArchive

PALETTE_SIZE = 768


def make_6bit_palette_bytes(seed: int = 0) -> bytes:
    """A deterministic, structurally sane 768-byte 6-bit VGA palette.

    Index 0 is black; indices 1-254 step through a few brightness bands
    (so titan.u7.palette_transform.get_ramps finds something to detect);
    index 255 holds out-of-range "garbage" bytes (>63), matching what
    real U7 PALETTES.FLX archives are known to contain there.
    """
    data = bytearray(PALETTE_SIZE)
    for i in range(256):
        if i == 0:
            r = g = b = 0
        elif i == 255:
            r, g, b = 250, 64, 1
        else:
            v = (i + seed) % 64
            r, g, b = v, (v * 2) % 64, (v * 3) % 64
        data[i * 3] = r
        data[i * 3 + 1] = g
        data[i * 3 + 2] = b
    return bytes(data)


def make_8bit_palette_bytes(seed: int = 0) -> bytes:
    """A deterministic 768-byte palette using the full 8-bit 0-255 range
    (values intentionally exceed 63 so auto-detection reports "8bit")."""
    data = bytearray(PALETTE_SIZE)
    for i in range(256):
        v = (i * 3 + seed) % 256
        data[i * 3] = v
        data[i * 3 + 1] = (v + 64) % 256
        data[i * 3 + 2] = (v + 128) % 256
    return bytes(data)


def _build_archive(occupancy: dict, slot_count: int, title: str) -> U7FlexArchive:
    archive = U7FlexArchive()
    archive.title = title
    archive.records = [occupancy.get(i, b"") for i in range(slot_count)]
    return archive


def make_bg_shaped_archive(path: str) -> str:
    """16 declared slots, 12 populated (0-8, 10-12) -- matches the real
    Black Gate PALETTES.FLX occupancy pattern found in production data."""
    occupancy = {i: make_6bit_palette_bytes(seed=i) for i in list(range(9)) + [10, 11, 12]}
    archive = _build_archive(occupancy, 16, "Synthetic BG-shaped palette archive")
    archive.save(path)
    return path


def make_si_shaped_archive(path: str) -> str:
    """16 declared slots, 13 populated (0-12) -- matches the real Serpent
    Isle PALETTES.FLX occupancy pattern (Black Gate's set plus slot 9)."""
    occupancy = {i: make_6bit_palette_bytes(seed=i) for i in range(13)}
    archive = _build_archive(occupancy, 16, "Synthetic SI-shaped palette archive")
    archive.save(path)
    return path


def make_truncated_archive_bytes(good_palette: bytes) -> bytes:
    """A hand-crafted archive (U7FlexArchive's own writer never produces
    this) whose single record's declared length exceeds the actual file
    size."""
    header = bytearray(128)
    header[0x50:0x54] = b"\x00\x1a\xff\xff"
    struct.pack_into("<I", header, 0x54, 1)
    table = bytearray(8)
    struct.pack_into("<II", table, 0, 0x88, len(good_palette) + 100)
    return bytes(header) + bytes(table) + good_palette


def make_overlapping_archive_bytes(good_palette: bytes) -> bytes:
    """Two record-table entries whose byte ranges overlap -- also
    something U7FlexArchive's writer never produces on its own."""
    header = bytearray(128)
    header[0x50:0x54] = b"\x00\x1a\xff\xff"
    struct.pack_into("<I", header, 0x54, 2)
    table = bytearray(16)
    struct.pack_into("<II", table, 0, 0x90, len(good_palette))
    struct.pack_into("<II", table, 8, 0x90 + 100, len(good_palette))
    data = good_palette + good_palette
    return bytes(header) + bytes(table) + data
