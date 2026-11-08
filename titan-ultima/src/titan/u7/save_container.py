"""Bounded U7 named Flex/ZIP save inspection with ordered members and strict diagnostics."""

from __future__ import annotations

import io
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass, field

FLEX_SAVE_MAGIC = 0xFFFF1A00


@dataclass(frozen=True)
class U7SaveMember:
    """One physical named occurrence; incomplete payloads never masquerade as complete members."""

    name: str
    data: bytes = field(repr=False)
    index: int
    source: str
    declared_size: int
    offset: int
    complete: bool = True
    is_directory: bool = False
    name_raw: bytes | None = field(default=None, repr=False)


@dataclass
class U7SaveContainer:
    """Raw archive plus logical member occurrences; sparse Flex slots and group tails stay separate."""

    raw: bytes = field(repr=False)
    title: str = ""
    container_format: str = ""
    members: list[U7SaveMember] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    complete: bool = True
    declared_count: int | None = None
    flex_directory: list[tuple[int, int]] = field(default_factory=list)
    zip_comment: bytes = b""
    group_trailing_data: dict[str, bytes] = field(default_factory=dict)
    _names: dict[str, int] = field(default_factory=dict, repr=False)

    def issue(self, message: str, *, strict: bool, structural: bool = True) -> None:
        """Strict mode rejects structural errors; duplicate-name observations remain readable."""
        message = "U7 save container: " + message
        if structural:
            self.complete = False
            if strict:
                raise ValueError(message)
        self.warnings.append(message)

    def add_member(
        self,
        name: str,
        data: bytes,
        source: str,
        declared_size: int,
        offset: int,
        *,
        complete: bool = True,
        is_directory: bool = False,
        name_raw: bytes | None = None,
    ) -> None:
        """Append an occurrence, retaining case collisions and exact duplicates with provenance."""
        key = name.casefold()
        if key in self._names:
            self.issue(
                f"duplicate name {name!r} at member {len(self.members)} (first member {self._names[key]}); all occurrences retained.",
                strict=False,
                structural=False,
            )
        else:
            self._names[key] = len(self.members)
        self.members.append(
            U7SaveMember(
                name,
                data,
                len(self.members),
                source,
                declared_size,
                offset,
                complete,
                is_directory,
                name_raw,
            )
        )


def _member_name(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("latin-1").rstrip(".")


def _read_named_flex(data: bytes, *, strict: bool) -> U7SaveContainer:
    if len(data) < 128:
        raise ValueError("U7 save container: truncated Flex header")
    result = U7SaveContainer(
        data, data[:80].split(b"\0", 1)[0].decode("latin-1"), "flex"
    )
    count = struct.unpack_from("<I", data, 84)[0]
    result.declared_count = count
    directory_end = 128 + 8 * count
    if directory_end > len(data):
        result.issue(
            f"truncated Flex directory: declares {count} slots, only {(len(data) - 128) // 8} complete directory rows available.",
            strict=strict,
        )
    for index in range(min(count, (len(data) - 128) // 8)):
        offset, size = struct.unpack_from("<II", data, 128 + index * 8)
        result.flex_directory.append((offset, size))
        if size == 0:
            continue  # Sparse slot, distinct from a named member with an empty payload.
        source = f"flex#record={index}"
        if offset < directory_end or offset >= len(data):
            result.issue(
                f"{source} offset {offset} lies outside the member-data region.",
                strict=strict,
            )
            continue
        end = offset + size
        available = data[offset : min(end, len(data))]
        complete = end <= len(data) and size >= 13
        if size < 13:
            result.issue(
                f"{source} has {size} bytes, shorter than the 13-byte filename field.",
                strict=strict,
            )
            continue
        if end > len(data):
            result.issue(
                f"{source} payload is truncated: declares {size} stored bytes, only {len(available)} available.",
                strict=strict,
            )
        if len(available) < 13:
            result.issue(
                f"{source} has a truncated 13-byte filename field.", strict=strict
            )
            continue
        name_raw = available[:13]
        name = _member_name(name_raw)
        if not name:
            result.issue(f"{source} has an empty filename.", strict=strict)
            complete = False
        result.add_member(
            name,
            available[13:],
            source,
            size - 13,
            offset + 13,
            complete=complete,
            name_raw=name_raw,
        )
    return result


def _read_level2_group(
    result: U7SaveContainer, blob: bytes, source: str, prefix: str, *, strict: bool
) -> None:
    """Honor Exult's twelve-byte terminal name before attempting to read a size word."""
    pos, ordinal = 0, 0
    while pos < len(blob):
        start = pos
        if len(blob) - pos < 12:
            result.issue(
                f"{source} has a truncated level-2 filename at offset {pos}.",
                strict=strict,
            )
            result.group_trailing_data[source] = blob[pos:]
            return
        name_raw = blob[pos : pos + 12]
        pos += 12
        if name_raw[0] == 0:
            result.group_trailing_data[source] = blob[pos:]
            if any(name_raw) or any(blob[pos:]):
                result.issue(
                    f"{source} has nonzero bytes in/after its level-2 terminator; retained.",
                    strict=False,
                    structural=False,
                )
            return
        if len(blob) - pos < 4:
            result.issue(
                f"{source} has a truncated level-2 size word at offset {pos}.",
                strict=strict,
            )
            result.group_trailing_data[source] = blob[start:]
            return
        size = struct.unpack_from("<I", blob, pos)[0]
        pos += 4
        end = pos + size
        complete = end <= len(blob)
        if not complete:
            result.issue(
                f"{source} member {ordinal} payload is truncated: declares {size} bytes, only {len(blob) - pos} available.",
                strict=strict,
            )
        name = _member_name(name_raw)
        if not name:
            result.issue(
                f"{source} member {ordinal} has an empty filename.", strict=strict
            )
            complete = False
        result.add_member(
            prefix + name,
            blob[pos : min(end, len(blob))],
            f"{source}#member={ordinal}",
            size,
            pos,
            complete=complete,
            name_raw=name_raw,
        )
        if end > len(blob):
            return
        pos, ordinal = end, ordinal + 1
    result.issue(f"{source} is missing its 12-byte level-2 terminator.", strict=strict)


def _read_named_zip(data: bytes, start: int, *, strict: bool) -> U7SaveContainer:
    title = data[:80].split(b"\0", 1)[0].decode("latin-1") if start else ""
    result = U7SaveContainer(data, title, "zip")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data[start:]))
    except (zipfile.BadZipFile, OSError, EOFError, ValueError) as error:
        raise ValueError(
            f"U7 save container: invalid or truncated ZIP archive: {error}"
        ) from error
    with archive:
        result.zip_comment = archive.comment
        infos = archive.infolist()
        result.declared_count = len(infos)
        for index, info in enumerate(infos):
            source = f"zip#entry={index}:{info.filename}"
            try:
                # ZipInfo identifies this exact occurrence; read(name) would select the last duplicate.
                blob = archive.read(info)
            except (
                zipfile.BadZipFile,
                RuntimeError,
                OSError,
                EOFError,
                ValueError,
                zlib.error,
            ) as error:
                result.issue(
                    f"{source} cannot be read completely: {error}", strict=strict
                )
                result.add_member(
                    info.filename,
                    b"",
                    source,
                    info.file_size,
                    info.header_offset + start,
                    complete=False,
                    is_directory=info.is_dir(),
                )
                continue
            lower = info.filename.lower()
            if lower == "gamedat" or re.fullmatch(r"map[0-9a-f]{2}", lower):
                _read_level2_group(
                    result,
                    blob,
                    source,
                    "" if lower == "gamedat" else lower + "/",
                    strict=strict,
                )
            else:
                result.add_member(
                    info.filename,
                    blob,
                    source,
                    info.file_size,
                    info.header_offset + start,
                    is_directory=info.is_dir(),
                )
    return result


def read_u7_save_container(data: bytes, *, strict: bool = False) -> U7SaveContainer:
    """Inspect known Flex or raw/title-prefixed ZIP; valid small ZIPs need no Flex-sized header."""
    if len(data) >= 84 and struct.unpack_from("<I", data, 80)[0] == FLEX_SAVE_MAGIC:
        return _read_named_flex(data, strict=strict)
    signatures = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
    if data[:4] in signatures:
        return _read_named_zip(data, 0, strict=strict)
    if data[80:84] in signatures:
        return _read_named_zip(data, 80, strict=strict)
    raise ValueError("Unrecognised U7 savegame format (not FLEX, not ZIP)")
