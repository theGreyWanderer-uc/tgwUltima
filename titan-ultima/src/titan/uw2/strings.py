"""STRINGS.PAK Huffman string decoder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct


@dataclass(frozen=True)
class HuffmanNode:
    symbol: int
    parent: int
    left: int
    right: int


class GameStrings:
    def __init__(self, blocks: dict[int, list[str]]):
        self.blocks = blocks

    @classmethod
    def from_file(cls, path: str | Path) -> "GameStrings":
        data = Path(path).read_bytes()
        offset = 0
        node_count = struct.unpack_from("<H", data, offset)[0]
        offset += 2

        nodes = []
        for _ in range(node_count):
            symbol, parent, left, right = struct.unpack_from("<BBBB", data, offset)
            nodes.append(HuffmanNode(symbol, parent, left, right))
            offset += 4

        block_count = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        block_infos = []
        for _ in range(block_count):
            block_id, block_offset = struct.unpack_from("<HI", data, offset)
            block_infos.append((block_id, block_offset))
            offset += 6

        blocks: dict[int, list[str]] = {}
        for block_id, block_offset in block_infos:
            blocks[block_id] = decode_block(data, block_offset, nodes)

        return cls(blocks)

    def get(self, block_id: int, string_index: int, default: str = "") -> str:
        block = self.blocks.get(block_id)
        if block is None or string_index < 0 or string_index >= len(block):
            return default
        return block[string_index]

    def summary(self) -> dict:
        return {
            "block_count": len(self.blocks),
            "blocks": [
                {"block_id": block_id, "string_count": len(strings)}
                for block_id, strings in sorted(self.blocks.items())
            ],
        }


def decode_block(data: bytes, block_offset: int, nodes: list[HuffmanNode]) -> list[str]:
    string_count = struct.unpack_from("<H", data, block_offset)[0]
    offsets = [
        struct.unpack_from("<H", data, block_offset + 2 + index * 2)[0]
        for index in range(string_count)
    ]
    strings_base = block_offset + (string_count + 1) * 2
    return [
        decode_string(data, strings_base + string_offset, nodes)
        for string_offset in offsets
    ]


def decode_string(data: bytes, offset: int, nodes: list[HuffmanNode]) -> str:
    root = len(nodes) - 1
    bit_count = 0
    raw = 0
    cursor = offset
    output = bytearray()

    while cursor <= len(data):
        node_index = root
        while nodes[node_index].left != 0xFF and nodes[node_index].right != 0xFF:
            if bit_count == 0:
                if cursor >= len(data):
                    return output.decode("cp437", errors="replace")
                raw = data[cursor]
                cursor += 1
                bit_count = 8

            if raw & 0x80:
                node_index = nodes[node_index].right
            else:
                node_index = nodes[node_index].left
            raw = (raw << 1) & 0xFF
            bit_count -= 1

        symbol = nodes[node_index].symbol
        if symbol == ord("|"):
            break
        output.append(symbol)

    return output.decode("cp437", errors="replace")


def clean_display_name(
    value: str, *, title_case: bool = True, remove_space: bool = False
) -> str:
    value = value.strip()
    if not value:
        return value

    if "_" in value:
        value = value.split("_", 1)[1]
    if "&" in value:
        value = value.split("&", 1)[0]
    value = value.strip()

    lower = value.lower()
    if lower.startswith("a "):
        value = value[2:]
    elif lower.startswith("an ") and lower != "an stone":
        value = value[3:]

    value = value.strip()
    if title_case:
        value = " ".join(word[:1].upper() + word[1:] for word in value.split(" "))
        value = value.replace(" Of ", " of ").replace(" The ", " the ")
    if remove_space:
        value = "".join(value.split())
    return value
