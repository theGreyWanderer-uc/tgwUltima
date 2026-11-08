"""Preserve Exult IREG special records and saved inventory index IDs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from titan.u7.saved_values import U7SavedValueReader, saved_value_row

SPECIAL_NAMES = {1: "usecode_script", 2: "endmark", 3: "attributes", 4: "string"}


@dataclass
class U7IregSpecial:
    """One wire record, retaining malformed/unknown payloads without executing them."""

    offset: int
    type_id: int | None
    kind: str
    declared_length: int | None
    payload_hex: str
    raw_hex: str
    complete: bool
    decoded_complete: bool = False
    decoded: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    owner_offset: int | None = None

    @property
    def raw(self) -> bytes:
        return bytes.fromhex(self.raw_hex)

    @property
    def payload(self) -> bytes:
        return bytes.fromhex(self.payload_hex)

    def as_row(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class U7IregIndexId:
    """Stored u16 word and Exult's persistent signed-low-byte interpretation."""

    offset: int
    scope_offset: int
    raw_word: int | None
    index: int | None
    slot_name: str
    raw_hex: str
    complete: bool


@dataclass
class U7IregExtras:
    """Stream-level evidence includes orphan specials and otherwise unowned index IDs."""

    raw_hex: str = ""
    specials: list[U7IregSpecial] = field(default_factory=list)
    indices: list[U7IregIndexId] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_special(self, record: U7IregSpecial, owner_offset: int | None) -> None:
        record.owner_offset = owner_offset
        self.specials.append(record)
        self.warnings.extend(
            f"IREG offset {record.offset}: {w}" for w in record.warnings
        )
        if owner_offset is None and record.type_id != 2:
            self.warnings.append(
                f"IREG offset {record.offset}: special has no preceding object"
            )


def read_ireg_index(
    data: bytes, offset: int, scope_offset: int = 0, *, offset_base: int = 0
) -> tuple[U7IregIndexId, int]:
    """Read 02/u16; only the low byte is sign-extended by Exult, including 00FF."""
    from titan.u7.save import _READY_SLOT_NAMES

    if not 0 <= offset < len(data) or data[offset] != 2:
        raise ValueError(f"IREG index marker missing at offset {offset}")

    end = min(offset + 3, len(data))
    complete = end == offset + 3
    word = int.from_bytes(data[offset + 1 : end], "little") if complete else None
    index = (
        ((word & 255) - 256 if word & 128 else word & 255) if word is not None else None
    )
    name = (
        _READY_SLOT_NAMES.get(index, "")
        if index is not None and 0 <= index < 18
        else ""
    )
    return U7IregIndexId(
        offset + offset_base,
        scope_offset + offset_base,
        word,
        index,
        name,
        data[offset:end].hex(),
        complete,
    ), end


def saved_slot_row(index: U7IregIndexId | None) -> dict[str, object]:
    """Saved requests are distinct from READY preferences and runtime slot acceptance."""
    return {
        "saved_index_word": index.raw_word if index is not None else None,
        "saved_index_id": index.index if index is not None else None,
        "saved_slot_name": index.slot_name if index is not None else "",
        "saved_slot_state": "unrecorded"
        if index is None
        else "slot"
        if index.slot_name
        else "unreadied"
        if index.index == -1
        else "invalid",
    }


def _decode_script(record: U7IregSpecial, payload: bytes) -> None:
    reader = U7SavedValueReader(payload, "IREG script")
    values: list[dict[str, object]] = []
    record.decoded["values"] = values
    count = reader.word(2)
    record.decoded["value_count"] = count
    current = reader.word(2)
    record.decoded["current_index"] = current
    for _ in range(count):
        values.append(saved_value_row(reader.values(1)[0], payload))
    record.decoded["frame_index"] = reader.word(2)
    no_halt = reader.word(2)
    record.decoded["no_halt_raw"] = no_halt
    record.decoded["no_halt"] = bool(no_halt)
    record.decoded["delay_ms"] = reader.word(4)
    record.decoded["trailing_hex"] = payload[reader.pos :].hex()
    if current > count:
        record.warnings.append("script current index exceeds value count")
    if reader.pos < len(payload):
        record.warnings.append("script has trailing bytes; retained")


def _decode_attributes(record: U7IregSpecial, payload: bytes) -> None:
    pairs: list[dict[str, object]] = []
    effective: dict[str, int] = {}
    record.decoded.update(pairs=pairs, effective=effective)
    pos = 0
    while pos < len(payload):
        start = pos
        end = payload.find(b"\0", pos)
        if end < 0:
            raise ValueError("attribute name has no NUL terminator")
        if end + 3 > len(payload):
            raise ValueError("attribute value is truncated")
        name = payload[pos:end]
        value = int.from_bytes(payload[end + 1 : end + 3], "little")
        pos = end + 3
        text = name.decode("latin-1")
        pairs.append(
            {
                "name": text,
                "name_hex": name.hex(),
                "value": value,
                "offset": start,
                "raw_hex": payload[start:pos].hex(),
            }
        )
        effective[text] = value


def read_ireg_special(
    data: bytes, offset: int, *, offset_base: int = 0
) -> tuple[U7IregSpecial, int]:
    """Read FF/type/u16/payload, with the no-length FF02 terminator as a special case."""
    if not 0 <= offset < len(data) or data[offset] != 255:
        raise ValueError(f"IREG special marker missing at offset {offset}")
    type_id = data[offset + 1] if offset + 1 < len(data) else None
    kind = SPECIAL_NAMES.get(type_id, "unknown") if type_id is not None else "unknown"
    if type_id == 2:
        return U7IregSpecial(
            offset + offset_base, 2, kind, None, "", "ff02", True, True
        ), offset + 2
    header_end = offset + 4
    length = (
        int.from_bytes(data[offset + 2 : header_end], "little")
        if header_end <= len(data)
        else None
    )
    end = min(header_end + length, len(data)) if length is not None else len(data)
    payload = data[header_end:end] if length is not None else b""
    complete = length is not None and len(payload) == length
    record = U7IregSpecial(
        offset + offset_base,
        type_id,
        kind,
        length,
        payload.hex(),
        data[offset:end].hex(),
        complete,
    )
    if length is None:
        record.warnings.append("special header is truncated")
        return record, end
    if not complete:
        record.warnings.append(
            f"special payload is truncated: declared {length}, available {len(payload)}"
        )
    try:
        if type_id == 1:
            _decode_script(record, payload)
        elif type_id == 3:
            _decode_attributes(record, payload)
        elif type_id == 4:
            text, nul, trailing = payload.partition(b"\0")
            record.decoded = {
                "text": text.decode("latin-1"),
                "bytes_hex": text.hex(),
                "nul_terminated": bool(nul),
                "trailing_hex": trailing.hex(),
            }
            if not nul:
                raise ValueError("string has no NUL terminator")
            if trailing:
                record.warnings.append("string has bytes after NUL; retained")
        else:
            record.warnings.append(f"unknown special type {type_id}; payload retained")
            return record, end
        record.decoded_complete = complete
    except ValueError as error:
        record.warnings.append(str(error))
    return record, end


def read_ireg_specials(
    data: bytes, pos: int, *, owner_offset: int | None = None, offset_base: int = 0
) -> tuple[list[U7IregSpecial], int]:
    """Read an actor's adjacent special list, stopping at FF02 or the first non-FF byte."""
    records = []
    while pos < len(data) and data[pos] == 255:
        record, pos = read_ireg_special(data, pos, offset_base=offset_base)
        record.owner_offset = owner_offset
        records.append(record)
        if record.type_id == 2 or not record.complete:
            break
    return records, pos
