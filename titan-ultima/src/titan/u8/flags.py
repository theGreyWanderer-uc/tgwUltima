"""Native FLAG.DAT global usecode variables and optional FLAGSYM.DAT symbols.

Decoded U8/FLAG.C stores 1024 bytes, addressed by bit index and field width.
Symbols supply verified offsets; declaration order is never used to assign them.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from titan.u8.save import U8SaveArchive

FLAG_BYTE_COUNT = 1024
FLAG_BIT_COUNT = FLAG_BYTE_COUNT * 8


def _validate_flag_field(index: int, width: int) -> None:
    if not 1 <= width <= 16:
        raise ValueError("FLAG.DAT: field width must be 1-16 bits")
    if not 0 <= index < FLAG_BIT_COUNT or index + width > FLAG_BIT_COUNT:
        raise ValueError("FLAG.DAT: bit field is outside 0-8191")


@dataclass(frozen=True)
class U8FlagSymbol:
    """A native global flag symbol with its bit offset and DOS int width."""

    name: str
    index: int
    width: int


@dataclass(frozen=True)
class U8FlagSymbols:
    """Verified name/index/width records from native FLAGSYM.DAT, in file order."""

    symbols: tuple[U8FlagSymbol, ...]
    raw_data: bytes

    @classmethod
    def from_file(cls, filepath: str | Path) -> U8FlagSymbols:
        """Read optional native symbol data; reconstructed source is not this format."""
        return cls.from_bytes(Path(filepath).read_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> U8FlagSymbols:
        """Parse NUL-terminated ASCII names followed by two little-endian words."""
        position = 0
        symbols: list[U8FlagSymbol] = []
        names: set[str] = set()
        while position < len(data):
            end = data.find(b"\x00", position)
            if end <= position or end + 5 > len(data):
                raise ValueError("FLAGSYM.DAT: truncated or empty symbol record")
            try:
                name = data[position:end].decode("ascii")
            except UnicodeDecodeError as error:
                raise ValueError("FLAGSYM.DAT: symbol name must be ASCII") from error
            if name in names:
                raise ValueError("FLAGSYM.DAT: duplicate symbol name")
            index, width = struct.unpack_from("<HH", data, end + 1)
            _validate_flag_field(index, width)
            names.add(name)
            symbols.append(U8FlagSymbol(name, index, width))
            position = end + 5
        return cls(tuple(symbols), bytes(data))

    def to_bytes(self) -> bytes:
        """Preserve exact native symbol bytes, including record order."""
        return self.raw_data


@dataclass(frozen=True)
class U8GlobalFlags:
    """Global flag storage; missing native save flags use the engine's zero default."""

    raw_data: bytes
    defaulted: bool = False

    @classmethod
    def from_file(cls, filepath: str | Path) -> U8GlobalFlags:
        """Read loose FLAG.DAT, a GAMEDAT directory, or a native U8 save archive."""
        path = Path(filepath)
        if path.is_dir():
            candidates = [p for p in path.iterdir() if p.name.upper() == "FLAG.DAT"]
            if len(candidates) > 1:
                raise ValueError("FLAG.DAT: duplicate directory entry")
            return (
                cls.from_bytes(candidates[0].read_bytes())
                if candidates
                else cls.zero_default()
            )
        raw = path.read_bytes()
        if U8SaveArchive.is_save_file(raw):
            payload = U8SaveArchive.from_bytes(raw).get_data("FLAG.DAT")
            return cls.zero_default() if payload is None else cls.from_bytes(payload)
        return cls.from_bytes(raw)

    @classmethod
    def from_bytes(cls, data: bytes) -> U8GlobalFlags:
        """Require the native writer's exact 1024-byte buffer; retain every bit."""
        if len(data) != FLAG_BYTE_COUNT:
            raise ValueError(f"FLAG.DAT: expected 1024 bytes, found {len(data)}")
        return cls(bytes(data))

    @classmethod
    def zero_default(cls) -> U8GlobalFlags:
        """Represent absent FLAG.DAT as initialized zero state, with explicit provenance."""
        return cls(bytes(FLAG_BYTE_COUNT), defaulted=True)

    def get_value(self, index: int, width: int = 1) -> int:
        """Read an unsigned packed value, least significant bit first across bytes."""
        _validate_flag_field(index, width)
        start = index // 8
        end = (index + width + 7) // 8
        word = int.from_bytes(self.raw_data[start:end], "little")
        return (word >> (index % 8)) & ((1 << width) - 1)

    def set_bit_indices(self) -> tuple[int, ...]:
        """Return all set bit indices; adjacent bits need not be separate variables."""
        return tuple(
            byte_index * 8 + bit
            for byte_index, value in enumerate(self.raw_data)
            for bit in range(8)
            if value & (1 << bit)
        )

    def to_bytes(self) -> bytes:
        """Return the exact native global flag buffer, without an archive wrapper."""
        return self.raw_data
