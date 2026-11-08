"""U7 ZIP32 repacking that copies unedited local records and opaque metadata verbatim."""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class _ZipSaveEntry:
    index: int
    info: zipfile.ZipInfo
    local_offset: int
    central: bytes


@dataclass(frozen=True)
class _ZipSaveLayout:
    entries: tuple[_ZipSaveEntry, ...]
    central_offset: int
    offset_base: int
    end_record: bytes


def u7_save_zip_start(data: bytes) -> int:
    """Return the supported ZIP payload start, retaining an optional 80-byte title."""
    return 0 if data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08") else 80


def _zip_u32(value: int) -> int:
    if not 0 <= value < 0xFFFFFFFF:
        raise ValueError("U7 save repack: ZIP32 size/offset exceeds supported range")
    return value


def _check_zip_extra(extra: bytes) -> None:
    pos = 0
    while pos < len(extra):
        if pos + 4 > len(extra):
            raise ValueError("U7 save repack: malformed ZIP extra field")
        tag, size = struct.unpack_from("<HH", extra, pos)
        pos += 4
        if tag == 1:
            raise ValueError("U7 save repack: editing ZIP64 archives is not supported")
        if pos + size > len(extra):
            raise ValueError("U7 save repack: truncated ZIP extra field")
        pos += size


def _zip_save_layout(data: bytes) -> _ZipSaveLayout:
    start = u7_save_zip_start(data)
    with zipfile.ZipFile(io.BytesIO(data[start:])) as archive:
        infos = archive.infolist()
        comment = archive.comment
    # Match zipfile's final EOCD choice; comments and any following bytes are copied.
    end = data.rfind(b"PK\x05\x06", max(0, len(data) - 65558))
    if end < 0 or end + 22 > len(data):
        raise ValueError("U7 save repack: missing ZIP end record")
    disk, cd_disk, disk_count, count, cd_size, cd_relative, comment_size = (
        struct.unpack_from("<4H2IH", data, end + 4)
    )
    if disk or cd_disk or disk_count != count:
        raise ValueError("U7 save repack: multidisk ZIP archives are not supported")
    if (
        count == 65535
        or cd_size == 0xFFFFFFFF
        or cd_relative == 0xFFFFFFFF
        or data[max(0, end - 20) : end - 16] == b"PK\x06\x07"
    ):
        raise ValueError("U7 save repack: editing ZIP64 archives is not supported")
    if (
        count != len(infos)
        or end + 22 + comment_size > len(data)
        or data[end + 22 : end + 22 + comment_size] != comment
    ):
        raise ValueError("U7 save repack: inconsistent ZIP end record")
    central = end - cd_size
    if central < start:
        raise ValueError("U7 save repack: invalid ZIP central-directory bounds")
    offset_base = central - cd_relative
    entries: list[_ZipSaveEntry] = []
    pos = central
    for index, info in enumerate(infos):
        if pos + 46 > end or data[pos : pos + 4] != b"PK\x01\x02":
            raise ValueError("U7 save repack: invalid ZIP central-directory entry")
        name_size, extra_size, entry_comment_size, disk_start = struct.unpack_from(
            "<4H", data, pos + 28
        )
        length = 46 + name_size + extra_size + entry_comment_size
        if pos + length > end or disk_start:
            raise ValueError("U7 save repack: truncated or multidisk ZIP entry")
        raw = data[pos : pos + length]
        _check_zip_extra(raw[46 + name_size : 46 + name_size + extra_size])
        crc, compressed, uncompressed = struct.unpack_from("<3I", raw, 16)
        relative = struct.unpack_from("<I", raw, 42)[0]
        if 0xFFFFFFFF in (compressed, uncompressed, relative):
            raise ValueError("U7 save repack: editing ZIP64 entries is not supported")
        local = start + info.header_offset
        if relative + offset_base != local or not start <= local < central:
            raise ValueError("U7 save repack: inconsistent ZIP local-header offset")
        if (crc, compressed, uncompressed) != (
            info.CRC,
            info.compress_size,
            info.file_size,
        ):
            raise ValueError("U7 save repack: inconsistent ZIP central metadata")
        entries.append(_ZipSaveEntry(index, info, local, raw))
        pos += length
    if pos != end:
        raise ValueError("U7 save repack: unsupported ZIP central-directory trailer")
    ordered = sorted(entry.local_offset for entry in entries)
    if len(set(ordered)) != len(ordered):
        raise ValueError("U7 save repack: aliased ZIP local records are not supported")
    return _ZipSaveLayout(tuple(entries), central, offset_base, data[end:])


def _replace_zip_local(
    segment: bytes, entry: _ZipSaveEntry, payload: bytes
) -> tuple[bytes, int, int]:
    if len(segment) < 30 or segment[:4] != b"PK\x03\x04":
        raise ValueError("U7 save repack: missing ZIP local header")
    flags, method = struct.unpack_from("<HH", segment, 6)
    if flags != entry.info.flag_bits or method != entry.info.compress_type:
        raise ValueError("U7 save repack: local/central ZIP flags or method disagree")
    if flags & ~0x080E:
        raise ValueError("U7 save repack: unsupported ZIP flags on modified entry")
    if method not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise ValueError(
            "U7 save repack: modified ZIP entries must be stored or deflated"
        )
    name_size, extra_size = struct.unpack_from("<HH", segment, 26)
    payload_start = 30 + name_size + extra_size
    payload_end = payload_start + entry.info.compress_size
    if payload_end > len(segment):
        raise ValueError("U7 save repack: overlapping or truncated ZIP local record")
    _check_zip_extra(segment[30 + name_size : payload_start])
    suffix_start = payload_end
    signed_descriptor = False
    if flags & 8:
        expected_descriptor = (
            entry.info.CRC,
            entry.info.compress_size,
            entry.info.file_size,
        )
        candidates = []
        for signed in (False, True):
            if signed and segment[payload_end : payload_end + 4] != b"PK\x07\x08":
                continue
            descriptor_start = payload_end + (4 if signed else 0)
            if (
                descriptor_start + 12 <= len(segment)
                and struct.unpack_from("<3I", segment, descriptor_start)
                == expected_descriptor
            ):
                candidates.append((signed, descriptor_start + 12))
        if len(candidates) != 1:
            raise ValueError("U7 save repack: invalid ZIP data descriptor")
        signed_descriptor, suffix_start = candidates[0]
    old_fields = struct.unpack_from("<3I", segment, 14)
    expected = (entry.info.CRC, entry.info.compress_size, entry.info.file_size)
    if any(
        old != value and not (flags & 8 and old == 0)
        for old, value in zip(old_fields, expected)
    ):
        raise ValueError("U7 save repack: local/central ZIP sizes or CRC disagree")
    size = _zip_u32(len(payload))
    crc = zlib.crc32(payload)
    if method == zipfile.ZIP_DEFLATED:
        level = (6, 9, 3, 1)[(flags >> 1) & 3]
        encoder = zlib.compressobj(level, zlib.DEFLATED, -15)
        compressed = encoder.compress(payload) + encoder.flush()
    else:
        compressed = payload
    packed_size = _zip_u32(len(compressed))
    header = bytearray(segment[:payload_start])
    for index, value in enumerate((crc, packed_size, size)):
        if not flags & 8 or old_fields[index] != 0:
            struct.pack_into("<I", header, 14 + 4 * index, value)
    descriptor = (
        (b"PK\x07\x08" if signed_descriptor else b"")
        + struct.pack("<3I", crc, packed_size, size)
        if flags & 8
        else b""
    )
    return (
        bytes(header) + compressed + descriptor + segment[suffix_start:],
        crc,
        packed_size,
    )


def repack_u7_zip_entries(data: bytes, replacements: Mapping[int, bytes]) -> bytes:
    """Replace physical ZIP32 occurrences; preserve unmodified compressed records and metadata."""
    if not replacements:
        return data
    layout = _zip_save_layout(data)
    if set(replacements) - {entry.index for entry in layout.entries}:
        raise ValueError("U7 save repack: ZIP replacement index is out of range")
    physical = sorted(layout.entries, key=lambda entry: entry.local_offset)
    if not physical:
        raise ValueError("U7 save repack: cannot replace a member of an empty ZIP")
    output = bytearray(data[: physical[0].local_offset])
    central_records: dict[int, bytes] = {}
    for index, entry in enumerate(physical):
        end = (
            physical[index + 1].local_offset
            if index + 1 < len(physical)
            else layout.central_offset
        )
        raw = data[entry.local_offset : end]
        central = bytearray(entry.central)
        struct.pack_into("<I", central, 42, _zip_u32(len(output) - layout.offset_base))
        if entry.index in replacements:
            payload = replacements[entry.index]
            raw, crc, compressed_size = _replace_zip_local(raw, entry, payload)
            struct.pack_into(
                "<3I", central, 16, crc, compressed_size, _zip_u32(len(payload))
            )
        else:
            if len(raw) < 30 or raw[:4] != b"PK\x03\x04":
                raise ValueError("U7 save repack: invalid unmodified ZIP local record")
            name_size, extra_size = struct.unpack_from("<HH", raw, 26)
            if 30 + name_size + extra_size + entry.info.compress_size > len(raw):
                raise ValueError("U7 save repack: overlapping ZIP local records")
            _check_zip_extra(raw[30 + name_size : 30 + name_size + extra_size])
        central_records[entry.index] = bytes(central)
        output.extend(raw)
    central_start = len(output)
    for entry in layout.entries:
        output.extend(central_records[entry.index])
    end_record = bytearray(layout.end_record)
    struct.pack_into(
        "<II",
        end_record,
        12,
        _zip_u32(len(output) - central_start),
        _zip_u32(central_start - layout.offset_base),
    )
    output.extend(end_record)
    _zip_u32(len(output))
    return bytes(output)
