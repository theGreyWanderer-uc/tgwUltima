"""
FLX archive writer for Ultima 9: Ascension.

The counterpart to :mod:`titan.u9.flx_archive`. Builds the flat
directory-of-blobs container U9 uses throughout ``static/``, ``sound/`` and
``runtime/``, so an archive can be unpacked, edited and packed back.

This writes the **container only**. Entry payloads are passed through
byte-for-byte: repacking `text.flx`, `BOOKS-EN.FLX` or `sappear.flx` needs
nothing more, because their entries are opaque blobs as far as the container is
concerned. Re-encoding a *decoded* texture back into an entry is a separate
problem and is not solved here -- see :mod:`titan.u9.texture`, which decodes but
does not encode.

Header conventions were measured across all 25 shipped archives, which agree
exactly::

    0x00  comment    76 bytes, **space-filled** (0x20), not NUL-padded
    0x4C  unknown1   u32 = 0
    0x50  count      u32 -- directory slots
    0x54  unknown2   u32 = 2
    0x58  size       u32 = total file size
    0x5C  size2      u32 = total file size, the same value again
    0x60  reserved   32 bytes, zero except a 1 at 0x68
    0x80  directory  count * (offset u32, length u32)
          payload    packed, starting immediately after the directory

Every shipped archive puts the first payload byte at exactly the end of the
directory, with **zero gap between consecutive entries** (77,763 of 77,795
consecutive pairs) and no alignment padding -- only 52% of entry offsets are
even 4-aligned, so alignment is plainly not a requirement. This writer packs
the same way.

An unused slot is written as ``(0, 0)``. That is what the reader treats as
empty, and it is unambiguous because the archive's own header occupies real
offset 0, so no genuine entry can start there.

Payload order is *not* fixed by the format: 19 of the 25 shipped archives store
payloads in directory-index order and 6 do not. This writer always emits index
order, so repacking one of those 6 produces a file that differs byte-for-byte
from the original while holding identical entries. :func:`repack_equivalent`
checks that weaker, correct property.

Example::

    from titan.u9.flx_archive import U9FlxArchive
    from titan.u9.flx_writer import build_flx

    archive = U9FlxArchive.from_file("static/BOOKS-EN.FLX")
    entries = {i: archive.read_entry(i) for i in archive.used_entry_indices()}
    entries[0] = b"my replacement entry"
    Path("BOOKS-EN.FLX").write_bytes(build_flx(entries, count=archive.num_entries))
"""

from __future__ import annotations

__all__ = [
    "COMMENT_FILL",
    "MAX_ENTRIES",
    "U9FlxWriteError",
    "build_flx",
    "repack",
    "repack_equivalent",
    "write_flx",
]

import os
import struct
from collections.abc import Mapping, Sequence

from titan.u9.flx_archive import (
    COMMENT_SIZE,
    COUNT_OFFSET,
    DIR_ENTRY_SIZE,
    DIR_OFFSET,
    SIZE2_OFFSET,
    SIZE_OFFSET,
    U9FlxArchive,
    U9FlxArchiveError,
)

COMMENT_FILL = 0x20
"""Shipped archives pad the comment field with spaces, not NULs."""

UNKNOWN1_OFFSET = 0x4C
UNKNOWN2_OFFSET = 0x54
RESERVED_OFFSET = 0x60
RESERVED_SIZE = 0x20

UNKNOWN1_VALUE = 0
UNKNOWN2_VALUE = 2
RESERVED_ONE_AT = 0x08
"""Byte offset within the reserved block that holds a 1 in every shipped file."""

MAX_ENTRIES = 65536
"""Sanity ceiling; the largest shipped archive declares 10,000 slots."""


class U9FlxWriteError(Exception):
    """Raised when archive contents cannot be packed into a valid FLX."""


def _normalise(
    entries: Mapping[int, bytes] | Sequence[bytes], count: int | None
) -> tuple[dict[int, bytes], int]:
    """Accept either a sparse index->blob mapping or a dense sequence."""
    if isinstance(entries, Mapping):
        table = {int(i): bytes(b) for i, b in entries.items()}
    else:
        table = {i: bytes(b) for i, b in enumerate(entries)}

    for index in table:
        if index < 0:
            raise U9FlxWriteError(f"negative entry index {index}")

    needed = (max(table) + 1) if table else 0
    if count is None:
        count = needed
    elif count < needed:
        raise U9FlxWriteError(
            f"count {count} is too small for an entry at index {max(table)}"
        )
    if not (0 <= count <= MAX_ENTRIES):
        raise U9FlxWriteError(f"implausible entry count {count} (0..{MAX_ENTRIES})")
    return table, count


def build_flx(
    entries: Mapping[int, bytes] | Sequence[bytes],
    *,
    count: int | None = None,
    comment: str | None = None,
) -> bytes:
    """Build a complete FLX archive.

    ``entries`` is either a sparse ``{index: blob}`` mapping or a dense
    sequence of blobs. An empty blob writes an unused slot, matching how the
    reader reports one. ``count`` sets the number of directory slots and
    defaults to the smallest that fits; shipped archives over-allocate heavily
    (``sappear.flx`` declares 8,000 slots for 3,764 entries), so pass the
    original count when repacking.

    ``comment`` is written into the 76-byte comment field and space-padded, as
    shipped archives are. It must be ASCII and fit the field.
    """
    table, count = _normalise(entries, count)

    if comment is None:
        header_comment = bytes([COMMENT_FILL]) * COMMENT_SIZE
    else:
        try:
            raw = comment.encode("ascii")
        except UnicodeEncodeError as e:
            raise U9FlxWriteError(f"comment must be ASCII: {e}") from e
        if len(raw) > COMMENT_SIZE:
            raise U9FlxWriteError(
                f"comment is {len(raw)} bytes, field holds {COMMENT_SIZE}"
            )
        header_comment = raw + bytes([COMMENT_FILL]) * (COMMENT_SIZE - len(raw))

    directory_size = count * DIR_ENTRY_SIZE
    payload_start = DIR_OFFSET + directory_size

    directory = bytearray(directory_size)
    payload = bytearray()
    for index in range(count):
        blob = table.get(index, b"")
        if not blob:
            continue  # (0, 0) -- an unused slot
        offset = payload_start + len(payload)
        struct.pack_into(
            "<II", directory, index * DIR_ENTRY_SIZE, offset, len(blob)
        )
        payload += blob

    total = payload_start + len(payload)
    header = bytearray(DIR_OFFSET)
    header[0:COMMENT_SIZE] = header_comment
    struct.pack_into("<I", header, UNKNOWN1_OFFSET, UNKNOWN1_VALUE)
    struct.pack_into("<I", header, COUNT_OFFSET, count)
    struct.pack_into("<I", header, UNKNOWN2_OFFSET, UNKNOWN2_VALUE)
    struct.pack_into("<I", header, SIZE_OFFSET, total)
    struct.pack_into("<I", header, SIZE2_OFFSET, total)
    struct.pack_into("<I", header, RESERVED_OFFSET + RESERVED_ONE_AT, 1)

    return bytes(header) + bytes(directory) + bytes(payload)


def write_flx(
    filepath: str | os.PathLike[str],
    entries: Mapping[int, bytes] | Sequence[bytes],
    *,
    count: int | None = None,
    comment: str | None = None,
) -> int:
    """Build an archive and write it. Returns the byte count written."""
    data = build_flx(entries, count=count, comment=comment)
    with open(filepath, "wb") as f:
        f.write(data)
    return len(data)


def repack(archive: U9FlxArchive, replacements: Mapping[int, bytes] | None = None) -> bytes:
    """Rebuild ``archive``, optionally swapping some entries.

    Slot count is preserved. A replacement of ``b""`` clears a slot.
    """
    entries: dict[int, bytes] = {
        index: archive.read_entry(index) for index in archive.used_entry_indices()
    }
    if replacements:
        for index, blob in replacements.items():
            if not (0 <= index < archive.num_entries):
                raise U9FlxWriteError(
                    f"replacement index {index} out of range "
                    f"(0..{archive.num_entries - 1})"
                )
            entries[index] = bytes(blob)
    return build_flx(entries, count=archive.num_entries)


def repack_equivalent(original: bytes, rebuilt: bytes) -> bool:
    """True when two archives declare the same slots and identical entry bytes.

    The correct round-trip check. Byte equality is too strong: payload order is
    not fixed by the format, and 6 of the 25 shipped archives store payloads out
    of directory-index order, so rebuilding them yields a different file holding
    the same content.
    """
    try:
        left, right = U9FlxArchive(original), U9FlxArchive(rebuilt)
    except U9FlxArchiveError:
        return False
    if left.num_entries != right.num_entries:
        return False
    if left.used_entry_indices() != right.used_entry_indices():
        return False
    return all(
        left.read_entry(i) == right.read_entry(i) for i in left.used_entry_indices()
    )
