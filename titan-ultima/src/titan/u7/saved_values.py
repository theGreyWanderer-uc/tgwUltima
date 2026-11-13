"""Bounded Exult serialized values shared by statics and scheduled IREG scripts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class U7UsecodeValue:
    """One saved value; strings/names and integer bit patterns stay raw."""

    type_tag: int
    value: int | bytes | tuple[U7UsecodeValue, ...]
    offset: int
    end_offset: int


class U7SavedValueReader:
    """Read bounded value trees without resolving classes or dereferencing pointers."""

    def __init__(self, data: bytes, label: str = "usecode.var") -> None:
        self.data = data
        self.pos = 0
        self.label = label

    def take(self, size: int) -> bytes:
        if size < 0 or size > len(self.data) - self.pos:
            raise ValueError(
                f"{self.label} truncated at offset {self.pos}: need {size} bytes"
            )
        result = self.data[self.pos : self.pos + size]
        self.pos += size
        return result

    def word(self, size: int) -> int:
        return int.from_bytes(self.take(size), "little")

    def values(self, count: int, depth: int = 0) -> list[U7UsecodeValue]:
        if depth > 128:
            raise ValueError(f"{self.label} nesting exceeds 128 levels")
        if count > len(self.data) - self.pos:
            raise ValueError(f"{self.label} value count exceeds remaining bytes")
        values = []
        for _ in range(count):
            start = self.pos
            tag = self.word(1)
            value: int | bytes | tuple[U7UsecodeValue, ...]
            if tag in (0, 3):
                value = self.word(4)
            elif tag in (1, 4):
                value = self.take(self.word(2))
            elif tag in (2, 5):
                value = tuple(self.values(self.word(2), depth + 1))
            else:
                raise ValueError(
                    f"{self.label} unknown value tag {tag} at offset {start}"
                )
            values.append(U7UsecodeValue(tag, value, start, self.pos))
        return values


def saved_value_row(value: U7UsecodeValue, data: bytes) -> dict[str, object]:
    """Export signed script integers and raw bytes in a JSON-safe structural view."""
    tag = value.type_tag
    row: dict[str, object] = {
        "type_tag": tag,
        "type": (
            "integer",
            "string",
            "array",
            "pointer",
            "class_symbol",
            "class_object",
        )[tag],
        "offset": value.offset,
        "end_offset": value.end_offset,
        "raw_hex": data[value.offset : value.end_offset].hex(),
    }
    if isinstance(value.value, int):
        row["raw_integer"] = value.value
        row["value"] = (
            value.value - 0x100000000
            if tag == 0 and value.value & 0x80000000
            else value.value
        )
        if tag == 3:
            row["resolved"] = False
    elif isinstance(value.value, bytes):
        row["value"] = value.value.decode("latin-1")
        row["bytes_hex"] = value.value.hex()
    else:
        row["value"] = [saved_value_row(child, data) for child in value.value]
    return row
