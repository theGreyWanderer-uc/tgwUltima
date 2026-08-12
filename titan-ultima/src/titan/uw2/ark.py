"""UU2 ARK archive reader."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import struct

from .compression import decode_uw2_block


@dataclass(frozen=True)
class ArkBlock:
    index: int
    offset: int
    flags: int
    data_size: int
    available_size: int

    @property
    def available(self) -> bool:
        return self.offset != 0 and self.data_size > 0

    @property
    def is_compressed(self) -> bool:
        return bool(self.flags & 0x02)

    @property
    def should_be_compressed(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def has_extra_space(self) -> bool:
        return bool(self.flags & 0x04)

    def to_json(self) -> dict:
        data = asdict(self)
        data.update(
            {
                "available": self.available,
                "is_compressed": self.is_compressed,
                "should_be_compressed": self.should_be_compressed,
                "has_extra_space": self.has_extra_space,
            }
        )
        return data


class ArkArchive:
    """Read UU2 ARK files with the practical six-byte table base."""

    def __init__(
        self, path: Path, data: bytes, blocks: list[ArkBlock], header_prefix: bytes
    ):
        self.path = path
        self.data = data
        self.blocks = blocks
        self.header_prefix = header_prefix
        self.count16 = struct.unpack_from("<H", header_prefix, 0)[0]
        self.count32 = struct.unpack_from("<I", header_prefix, 0)[0]

    @classmethod
    def from_file(cls, path: str | Path) -> "ArkArchive":
        path = Path(path)
        data = path.read_bytes()
        if len(data) < 6:
            raise ValueError(f"{path} is too small to be a UU2 ARK archive")

        prefix = data[:6]
        count16 = struct.unpack_from("<H", prefix, 0)[0]
        count32 = struct.unpack_from("<I", prefix, 0)[0]
        count = count16 if count16 > 0 else count32

        table_base = 6
        table_bytes = count * 4
        required = table_base + table_bytes * 4
        if required > len(data):
            raise ValueError(
                f"{path} header expects {required} bytes for {count} blocks, "
                f"but file is only {len(data)} bytes"
            )

        offsets = _read_u32_table(data, table_base, count)
        flags = _read_u32_table(data, table_base + table_bytes, count)
        sizes = _read_u32_table(data, table_base + table_bytes * 2, count)
        available_sizes = _read_u32_table(data, table_base + table_bytes * 3, count)

        blocks = [
            ArkBlock(i, offsets[i], flags[i], sizes[i], available_sizes[i])
            for i in range(count)
        ]
        return cls(path, data, blocks, prefix)

    def is_available(self, index: int) -> bool:
        return 0 <= index < len(self.blocks) and self.blocks[index].available

    def get_raw_block(self, index: int) -> bytes:
        block = self.blocks[index]
        if not block.available:
            raise KeyError(f"ARK block {index} is unavailable")
        end = block.offset + block.data_size
        if end > len(self.data):
            raise ValueError(
                f"ARK block {index} extends past EOF: {end} > {len(self.data)}"
            )
        return self.data[block.offset : end]

    def get_decoded_block(self, index: int) -> bytes:
        block = self.blocks[index]
        raw = self.get_raw_block(index)
        if block.is_compressed:
            return decode_uw2_block(raw)
        return raw

    def summary(self) -> dict:
        return {
            "path": str(self.path),
            "file_size": len(self.data),
            "header_prefix_hex": self.header_prefix.hex(),
            "count16": self.count16,
            "count32": self.count32,
            "block_count": len(self.blocks),
            "available_blocks": sum(1 for block in self.blocks if block.available),
            "compressed_blocks": sum(1 for block in self.blocks if block.is_compressed),
            "blocks": [block.to_json() for block in self.blocks],
        }


def _read_u32_table(data: bytes, offset: int, count: int) -> list[int]:
    return list(struct.unpack_from(f"<{count}I", data, offset))
