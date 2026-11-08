"""Lossless U7 save repacking by guarded member occurrence, including grouped/nested maps."""

from __future__ import annotations

import hashlib
import io
import re
import struct
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from titan.u7.save_container import U7SaveContainer, read_u7_save_container
from titan.u7.save_repack_zip import repack_u7_zip_entries, u7_save_zip_start


@dataclass(frozen=True)
class U7SaveReplacement:
    """Replace one member occurrence; additional path indices descend into embedded containers."""

    member_path: tuple[int, ...]
    data: bytes = field(repr=False)
    expected_sha256: str | None = None


@dataclass(frozen=True)
class U7SaveRepackResult:
    """Repacked bytes and leaf-change evidence; no source files or game state are modified."""

    data: bytes = field(repr=False)
    source_sha256: str
    changes: tuple[dict[str, object], ...]

    def as_row(self) -> dict[str, object]:
        return {
            "source_sha256": self.source_sha256,
            "output_sha256": hashlib.sha256(self.data).hexdigest(),
            "output_bytes": len(self.data),
            "changes": list(self.changes),
        }


def check_u7_save_hash(expected: object, data: bytes, description: str) -> None:
    """Validate a required SHA-256 guard without treating a filename as member identity."""
    if (
        not isinstance(expected, str)
        or re.fullmatch(r"[0-9a-fA-F]{64}", expected) is None
    ):
        raise ValueError(
            f"U7 save repack: {description} SHA-256 must have 64 hexadecimal digits"
        )
    if hashlib.sha256(data).hexdigest() != expected.lower():
        raise ValueError(f"U7 save repack: {description} SHA-256 does not match")


def _read_repack_layout(data: bytes) -> U7SaveContainer:
    try:
        return read_u7_save_container(data, strict=True)
    except (NotImplementedError, struct.error) as error:
        raise ValueError(
            f"U7 save repack: unsupported or invalid container: {error}"
        ) from error


def _save_u32(value: int) -> int:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("U7 save repack: Flex/group size or offset exceeds u32")
    return value


def _repack_flex_members(
    layout: U7SaveContainer, updates: Mapping[int, bytes]
) -> bytes:
    replacements: dict[int, bytes] = {}
    for index, payload in updates.items():
        match = re.fullmatch(r"flex#record=(\d+)", layout.members[index].source)
        if match is None:
            raise ValueError("U7 save repack: missing Flex member provenance")
        replacements[int(match[1])] = payload
    populated = sorted(
        (offset, size, index)
        for index, (offset, size) in enumerate(layout.flex_directory)
        if size
    )
    if not populated:
        raise ValueError("U7 save repack: no populated Flex member to replace")
    output = bytearray(layout.raw[: populated[0][0]])
    for ordinal, (offset, size, index) in enumerate(populated):
        following = (
            populated[ordinal + 1][0]
            if ordinal + 1 < len(populated)
            else len(layout.raw)
        )
        if offset + size > following:
            raise ValueError(
                "U7 save repack: overlapping/aliased Flex records cannot be edited"
            )
        new_offset = _save_u32(len(output))
        raw = layout.raw[offset : offset + size]
        if index in replacements:
            raw = raw[:13] + replacements[index]
        struct.pack_into(
            "<II", output, 128 + 8 * index, new_offset, _save_u32(len(raw))
        )
        output.extend(raw)
        output.extend(layout.raw[offset + size : following])
    _save_u32(len(output))
    return bytes(output)


def _repack_level2_group(blob: bytes, replacements: Mapping[int, bytes]) -> bytes:
    output = bytearray()
    pos, ordinal = 0, 0
    pending = dict(replacements)
    while pos + 12 <= len(blob):
        start = pos
        name = blob[pos : pos + 12]
        if name[0] == 0:
            if pending:
                raise ValueError("U7 save repack: level-2 member index is out of range")
            output.extend(blob[start:])
            return bytes(output)
        if pos + 16 > len(blob):
            break
        size = struct.unpack_from("<I", blob, pos + 12)[0]
        end = pos + 16 + size
        if end > len(blob):
            break
        if ordinal in pending:
            payload = pending.pop(ordinal)
            output.extend(name + struct.pack("<I", _save_u32(len(payload))) + payload)
        else:
            output.extend(blob[start:end])
        pos, ordinal = end, ordinal + 1
    raise ValueError("U7 save repack: invalid or unterminated level-2 group")


def _repack_zip_members(layout: U7SaveContainer, updates: Mapping[int, bytes]) -> bytes:
    direct: dict[int, bytes] = {}
    groups: dict[int, dict[int, bytes]] = {}
    for index, payload in updates.items():
        source = layout.members[index].source
        grouped = re.fullmatch(
            r"zip#entry=(\d+):(?:gamedat|map[0-9a-f]{2})#member=(\d+)",
            source,
            re.IGNORECASE,
        )
        if grouped:
            groups.setdefault(int(grouped[1]), {})[int(grouped[2])] = payload
        else:
            entry = re.match(r"zip#entry=(\d+):", source)
            if entry is None:
                raise ValueError("U7 save repack: missing ZIP member provenance")
            direct[int(entry[1])] = payload
    if groups:
        with zipfile.ZipFile(
            io.BytesIO(layout.raw[u7_save_zip_start(layout.raw) :])
        ) as archive:
            infos = archive.infolist()
            for index, replacements in groups.items():
                direct[index] = _repack_level2_group(
                    archive.read(infos[index]), replacements
                )
    return repack_u7_zip_entries(layout.raw, direct)


def _validate_repacked_members(
    before: U7SaveContainer, data: bytes, updates: Mapping[int, bytes]
) -> None:
    after = _read_repack_layout(data)
    if (
        before.container_format != after.container_format
        or before.declared_count != after.declared_count
        or len(before.members) != len(after.members)
    ):
        raise ValueError("U7 save repack: output changed the member structure")
    if (
        before.zip_comment != after.zip_comment
        or before.group_trailing_data != after.group_trailing_data
    ):
        raise ValueError(
            "U7 save repack: output changed ZIP comment/group trailing bytes"
        )
    for original, rewritten in zip(before.members, after.members):
        if (
            original.name,
            original.name_raw,
            original.is_directory,
            original.source,
        ) != (
            rewritten.name,
            rewritten.name_raw,
            rewritten.is_directory,
            rewritten.source,
        ):
            raise ValueError("U7 save repack: output changed member identity/order")
        if rewritten.data != updates.get(original.index, original.data):
            raise ValueError(
                "U7 save repack: output member does not match the requested payload"
            )


def _repack_save_level(
    data: bytes,
    replacements: list[U7SaveReplacement],
    prefix: tuple[int, ...],
    changes: list[dict[str, object]],
) -> bytes:
    layout = _read_repack_layout(data)
    selected: dict[int, list[U7SaveReplacement]] = {}
    for replacement in replacements:
        index = replacement.member_path[0]
        if index >= len(layout.members):
            raise ValueError(
                f"U7 save repack: member path {prefix + replacement.member_path} is out of range"
            )
        selected.setdefault(index, []).append(replacement)
    updates: dict[int, bytes] = {}
    for index, requests in selected.items():
        member = layout.members[index]
        if member.is_directory:
            raise ValueError("U7 save repack: directory entries cannot be replaced")
        if len(requests[0].member_path) == 1:
            request = requests[0]
            if request.expected_sha256 is not None:
                check_u7_save_hash(
                    request.expected_sha256, member.data, f"member {prefix + (index,)}"
                )
            replacement_data = request.data
            changes.append(
                {
                    "member_path": list(prefix + (index,)),
                    "name": member.name,
                    "source_bytes": len(member.data),
                    "output_bytes": len(replacement_data),
                    "before_sha256": hashlib.sha256(member.data).hexdigest(),
                    "after_sha256": hashlib.sha256(replacement_data).hexdigest(),
                    "changed": member.data != replacement_data,
                }
            )
        else:
            children = [
                U7SaveReplacement(row.member_path[1:], row.data, row.expected_sha256)
                for row in requests
            ]
            replacement_data = _repack_save_level(
                member.data, children, prefix + (index,), changes
            )
        if replacement_data != member.data:
            updates[index] = replacement_data
    if not updates:
        return data
    result = (
        _repack_flex_members(layout, updates)
        if layout.container_format == "flex"
        else _repack_zip_members(layout, updates)
    )
    _validate_repacked_members(layout, result, updates)
    return result


def repack_u7_save(
    data: bytes,
    replacements: Iterable[U7SaveReplacement] = (),
    *,
    expected_sha256: str | None = None,
) -> U7SaveRepackResult:
    """Replace guarded save occurrences without renaming, dropping or regenerating other members."""
    if expected_sha256 is not None:
        check_u7_save_hash(expected_sha256, data, "source")
    requests = list(replacements)
    paths: list[tuple[int, ...]] = []
    for request in requests:
        path = request.member_path
        if (
            not isinstance(path, tuple)
            or not 1 <= len(path) <= 16
            or any(
                isinstance(index, bool) or not isinstance(index, int) or index < 0
                for index in path
            )
        ):
            raise ValueError(
                "U7 save repack: member_path needs 1..16 nonnegative integer occurrence indices"
            )
        if not isinstance(request.data, bytes):
            raise ValueError("U7 save repack: replacement data must be bytes")
        if any(path[: len(old)] == old or old[: len(path)] == path for old in paths):
            raise ValueError("U7 save repack: duplicate or overlapping member paths")
        paths.append(path)
    changes: list[dict[str, object]] = []
    output = _repack_save_level(data, requests, (), changes)
    return U7SaveRepackResult(output, hashlib.sha256(data).hexdigest(), tuple(changes))
