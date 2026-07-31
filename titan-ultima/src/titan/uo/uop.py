"""Ultima Online UOP archive reader."""

from __future__ import annotations

__all__ = ["UOPArchive", "UOPEntry", "hash_uop_path"]

from dataclasses import dataclass
from pathlib import Path
import struct
import zlib

_U32_MASK = 0xFFFFFFFF
_UOP_MAGIC = 0x0050594D


@dataclass(frozen=True)
class UOPEntry:
    """A single UOP table entry."""

    offset: int
    header_length: int
    compressed_length: int
    decompressed_length: int
    path_hash: int
    data_hash: int
    compression: int

    @property
    def payload_offset(self) -> int:
        return self.offset + self.header_length


def _u32(value: int) -> int:
    return value & _U32_MASK


def _rot(value: int, count: int) -> int:
    return _u32((value << count) | (value >> (32 - count)))


def hash_uop_path(path: str) -> int:
    """Return the UOP path hash used by Mythic/EA UOP archives."""
    data = path.lower()
    length = len(data)
    a = b = c = _u32(0xDEADBEEF + length)
    k = 0

    while length > 12:
        a = _u32(
            a
            + ord(data[k])
            + (ord(data[k + 1]) << 8)
            + (ord(data[k + 2]) << 16)
            + (ord(data[k + 3]) << 24)
        )
        b = _u32(
            b
            + ord(data[k + 4])
            + (ord(data[k + 5]) << 8)
            + (ord(data[k + 6]) << 16)
            + (ord(data[k + 7]) << 24)
        )
        c = _u32(
            c
            + ord(data[k + 8])
            + (ord(data[k + 9]) << 8)
            + (ord(data[k + 10]) << 16)
            + (ord(data[k + 11]) << 24)
        )

        a = _u32(a - c)
        a ^= _rot(c, 4)
        c = _u32(c + b)
        b = _u32(b - a)
        b ^= _rot(a, 6)
        a = _u32(a + c)
        c = _u32(c - b)
        c ^= _rot(b, 8)
        b = _u32(b + a)
        a = _u32(a - c)
        a ^= _rot(c, 16)
        c = _u32(c + b)
        b = _u32(b - a)
        b ^= _rot(a, 19)
        a = _u32(a + c)
        c = _u32(c - b)
        c ^= _rot(b, 4)
        b = _u32(b + a)

        length -= 12
        k += 12

    if length:
        tail = data[k:]
        if length >= 12:
            c = _u32(c + (ord(tail[11]) << 24))
        if length >= 11:
            c = _u32(c + (ord(tail[10]) << 16))
        if length >= 10:
            c = _u32(c + (ord(tail[9]) << 8))
        if length >= 9:
            c = _u32(c + ord(tail[8]))
        if length >= 8:
            b = _u32(b + (ord(tail[7]) << 24))
        if length >= 7:
            b = _u32(b + (ord(tail[6]) << 16))
        if length >= 6:
            b = _u32(b + (ord(tail[5]) << 8))
        if length >= 5:
            b = _u32(b + ord(tail[4]))
        if length >= 4:
            a = _u32(a + (ord(tail[3]) << 24))
        if length >= 3:
            a = _u32(a + (ord(tail[2]) << 16))
        if length >= 2:
            a = _u32(a + (ord(tail[1]) << 8))
        if length >= 1:
            a = _u32(a + ord(tail[0]))

        c ^= b
        c = _u32(c - _rot(b, 14))
        a ^= c
        a = _u32(a - _rot(c, 11))
        b ^= a
        b = _u32(b - _rot(a, 25))
        c ^= b
        c = _u32(c - _rot(b, 16))
        a ^= c
        a = _u32(a - _rot(c, 4))
        b ^= a
        b = _u32(b - _rot(a, 14))
        c ^= b
        c = _u32(c - _rot(b, 24))

    return ((b & _U32_MASK) << 32) | (c & _U32_MASK)


def _bwt_decompress(buffer: bytes) -> bytes:
    if len(buffer) < 1029:
        return b""

    first_char = buffer[4]
    table = sorted(((first_char + i) & 0xFFFF) for i in range(256 * 256))
    decoded = bytearray()
    pos = 5

    while pos < len(buffer):
        current = first_char
        value = table[current]
        if current > 0:
            table[1 : current + 1] = table[0:current]
        table[0] = value
        decoded.append(value & 0xFF)
        first_char = buffer[pos]
        pos += 1

    if len(decoded) < 1024:
        return b""

    counts = list(struct.unpack_from("<256I", decoded, 0))
    out_len = sum(counts)
    if out_len <= 0:
        return b""

    payload = decoded[1024:]
    symbols = list(range(256))
    frequency = sorted(
        (idx for idx, count in enumerate(counts) if count),
        key=lambda idx: counts[idx],
        reverse=True,
    )
    non_zero_count = len(frequency)
    starts = [0] * 256
    ends = [0] * 256
    cursor = 0

    for rank, freq in enumerate(frequency):
        if cursor >= len(payload):
            return b""
        symbols[payload[cursor]] = freq
        starts[freq] = cursor + 1
        cursor += counts[freq]
        ends[freq] = cursor

    value = symbols[0] & 0xFF
    output = bytearray()
    while len(output) < out_len:
        output.append(value)
        if starts[value] >= ends[value]:
            if non_zero_count > 0:
                non_zero_count -= 1
            for i in range(non_zero_count):
                symbols[i] = symbols[i + 1]
            value = symbols[0] & 0xFF
            continue

        idx = payload[starts[value]]
        starts[value] += 1
        if idx != 0:
            old_value = value
            for i in range(idx):
                symbols[i] = symbols[i + 1]
            symbols[idx] = old_value
            value = symbols[0] & 0xFF

    return bytes(output)


class UOPArchive:
    """Read entries from a UOP archive."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.entries = self._read_entries()
        self.entries_by_hash = {entry.path_hash: entry for entry in self.entries}

    def read_entry(self, entry: UOPEntry) -> bytes:
        """Read and decompress an entry payload."""
        with self.path.open("rb") as stream:
            stream.seek(entry.payload_offset)
            data = stream.read(entry.compressed_length)

        if len(data) != entry.compressed_length:
            raise ValueError("short UOP payload read")

        if entry.compression == 0:
            if len(data) != entry.decompressed_length:
                raise ValueError("uncompressed UOP length mismatch")
            return data

        if entry.compression in (1, 3):
            out = zlib.decompress(data)
            if len(out) != entry.decompressed_length:
                raise ValueError("decompressed UOP length mismatch")
            if entry.compression == 3:
                return _bwt_decompress(out)
            return out

        raise ValueError(f"unsupported UOP compression flag: {entry.compression}")

    def read_hashed_path(self, path: str) -> bytes | None:
        """Read an entry by generated virtual UOP path."""
        entry = self.entries_by_hash.get(hash_uop_path(path))
        return None if entry is None else self.read_entry(entry)

    def _read_entries(self) -> list[UOPEntry]:
        size = self.path.stat().st_size
        entries: list[UOPEntry] = []

        with self.path.open("rb") as stream:
            header = stream.read(28)
            if len(header) != 28:
                raise ValueError("short UOP header")
            magic, _version, _signature, next_block, _capacity, _count = struct.unpack(
                "<IIIQII", header
            )
            if magic != _UOP_MAGIC:
                raise ValueError(f"not a UOP archive: {self.path}")

            seen_blocks: set[int] = set()
            while next_block:
                if next_block in seen_blocks:
                    raise ValueError("loop detected in UOP block chain")
                if next_block < 0 or next_block + 12 > size:
                    raise ValueError("UOP block offset outside archive")
                seen_blocks.add(next_block)

                stream.seek(next_block)
                block_header = stream.read(12)
                if len(block_header) != 12:
                    raise ValueError("short UOP block header")
                files_in_block, next_block = struct.unpack("<IQ", block_header)

                for _ in range(files_in_block):
                    raw = stream.read(34)
                    if len(raw) != 34:
                        raise ValueError("short UOP file record")
                    values = struct.unpack("<QIIIQIh", raw)
                    entry = UOPEntry(*values)
                    if entry.offset == 0:
                        continue
                    if entry.payload_offset < 0 or entry.payload_offset > size:
                        raise ValueError("UOP payload offset outside archive")
                    if (
                        entry.compressed_length < 0
                        or entry.payload_offset + entry.compressed_length > size
                    ):
                        raise ValueError("UOP payload extent outside archive")
                    entries.append(entry)

        return entries
