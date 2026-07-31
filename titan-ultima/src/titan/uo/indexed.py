"""Ultima Online legacy IDX/MUL and UOP-backed indexed resources."""

from __future__ import annotations

__all__ = ["UOIndexEntry", "UOIndexedFile"]

from dataclasses import dataclass
from pathlib import Path
import struct

from titan.uo.uop import UOPArchive, hash_uop_path


@dataclass(frozen=True)
class UOIndexEntry:
    """A legacy-style indexed resource entry."""

    index: int
    data: bytes
    extra: int = 0


class UOIndexedFile:
    """Indexed UO resources loaded from either IDX/MUL or UOP."""

    def __init__(self, entries: dict[int, UOIndexEntry]) -> None:
        self.entries = entries

    @classmethod
    def from_mul_idx(cls, mul_path: str | Path, idx_path: str | Path) -> UOIndexedFile:
        mul = Path(mul_path)
        idx = Path(idx_path)
        mul_size = mul.stat().st_size
        entries: dict[int, UOIndexEntry] = {}

        with idx.open("rb") as index_stream, mul.open("rb") as data_stream:
            index_data = index_stream.read()
            for entry_id in range(len(index_data) // 12):
                lookup, length, extra = struct.unpack_from(
                    "<III", index_data, entry_id * 12
                )
                if (
                    lookup == 0xFFFFFFFF
                    or length == 0
                    or lookup > mul_size
                    or length > mul_size - lookup
                ):
                    continue
                data_stream.seek(lookup)
                entries[entry_id] = UOIndexEntry(
                    entry_id, data_stream.read(length), extra
                )

        return cls(entries)

    @classmethod
    def from_uop(
        cls,
        uop_path: str | Path,
        *,
        extension: str = ".tga",
        entry_count: int,
        has_extra_header: bool = False,
        range_start: int | None = None,
        range_end: int | None = None,
        max_entries: int | None = None,
    ) -> UOIndexedFile:
        archive = UOPArchive(uop_path)
        stem = Path(uop_path).stem.lower()
        entries: dict[int, UOIndexEntry] = {}
        start = 0 if range_start is None else range_start
        end = entry_count if range_end is None else min(range_end, entry_count)

        for entry_id in range(start, end):
            if max_entries is not None and len(entries) >= max_entries:
                break
            virtual_path = f"build/{stem}/{entry_id:08d}{extension}"
            entry = archive.entries_by_hash.get(hash_uop_path(virtual_path))
            if entry is None:
                continue

            data = archive.read_entry(entry)
            extra = 0
            if has_extra_header:
                if len(data) < 8:
                    continue
                width, height = struct.unpack_from("<II", data, 0)
                if width <= 0 or height <= 0 or width > 4096 or height > 4096:
                    continue
                extra = ((width & 0xFFFF) << 16) | (height & 0xFFFF)
                data = data[8:]

            entries[entry_id] = UOIndexEntry(entry_id, data, extra)

        return cls(entries)
