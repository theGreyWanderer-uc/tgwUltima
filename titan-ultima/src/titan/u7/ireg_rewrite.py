"""Lossless IREG rewriting: bounded wire records and guarded, targeted edits.

Unedited bytes, record order, controls and unknown records remain verbatim.
This edits standalone streams or explicitly extracted inventory streams, not
NPC headers, save containers, object ownership or runtime placement.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from titan.u7.ireg import decode_ireg_payload, nibble_swap
from titan.u7.ireg_metadata import U7IregContext
from titan.u7.ireg_specials import read_ireg_special
from titan.u7.typeflag import U7TypeFlags

U7IregFormat = Literal["retail", "exult"]


@dataclass(frozen=True)
class U7IregWireRecord:
    """One physical IREG record; offsets always address the original input."""

    offset: int
    kind: Literal["object", "index", "special", "control"]
    raw: bytes = field(repr=False)
    header_size: int

    @property
    def payload(self) -> bytes:
        return self.raw[self.header_size :]

    @property
    def extended_shape(self) -> bool:
        return self.kind == "object" and self.raw[0] == 254

    @property
    def extended_lift(self) -> bool:
        return self.kind == "object" and self.raw[0] in (253, 254)


@dataclass(frozen=True)
class U7IregEdit:
    """One guarded edit at an original record offset; exactly one operation is allowed."""

    offset: int
    fields: Mapping[str, int | bool] = field(default_factory=dict)
    special_payload: bytes | None = None
    index_word: int | None = None
    expected_raw: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True)
class U7IregRewriteResult:
    """Rewritten bytes plus before/after evidence; no filesystem or engine side effects."""

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


def read_ireg_wire_records(
    data: bytes, *, data_format: U7IregFormat = "exult"
) -> tuple[U7IregWireRecord, ...]:
    """Scan bounded IREG records without rebuilding trees or interpreting localized text."""
    if data_format not in ("retail", "exult"):
        raise ValueError("IREG rewrite: format must be retail or exult")
    records: list[U7IregWireRecord] = []
    pos = 0
    while pos < len(data):
        start = pos
        marker = data[pos]
        pos += 1
        kind: Literal["object", "index", "special", "control"] = "object"
        header = 1
        if marker in (0, 1):
            kind = "control"
        elif marker in (2, 253, 254, 255) and data_format == "retail":
            raise ValueError(
                f"IREG rewrite: Exult control 0x{marker:02X} in retail stream at {start}"
            )
        elif marker == 2:
            kind, pos = "index", pos + 2
        elif marker == 255:
            special, pos = read_ireg_special(data, start)
            if not special.complete:
                raise ValueError(f"IREG rewrite: truncated special at {start}")
            kind = "control" if special.type_id == 2 else "special"
            header = 2 if special.type_id == 2 else 4
        else:
            if marker in (253, 254):
                if pos == len(data):
                    raise ValueError(
                        f"IREG rewrite: truncated extended prefix at {start}"
                    )
                marker = data[pos]
                pos += 1
                header = 2
                if marker < 4 + int(data[start] == 254):
                    raise ValueError(
                        f"IREG rewrite: invalid extended length at {start}"
                    )
            pos += marker
        if pos > len(data):
            raise ValueError(f"IREG rewrite: truncated {kind} at {start}")
        records.append(U7IregWireRecord(start, kind, data[start:pos], header))
    return tuple(records)


def _integer(name: str, value: object, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= maximum
    ):
        raise ValueError(f"IREG rewrite: {name} must be an integer in 0..{maximum}")
    return value


def _flag(name: str, value: object) -> bool:
    if not isinstance(value, (bool, int)) or value not in (0, 1):
        raise ValueError(f"IREG rewrite: {name} must be boolean or 0/1")
    return bool(value)


def _edit_object_fields(
    record: U7IregWireRecord,
    fields: Mapping[str, int | bool],
    context: U7IregContext | None,
    data_format: U7IregFormat,
) -> bytes:
    allowed = {
        "x_byte",
        "y_byte",
        "frame",
        "lift",
        "quality_byte",
        "invisible",
        "okay_to_take",
        "temporary",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"IREG rewrite: unsupported object fields: {sorted(unknown)}")
    if (
        data_format == "retail"
        and {"invisible", "okay_to_take", "temporary"} & fields.keys()
    ):
        raise ValueError(
            "IREG rewrite: semantic flag edits are verified for Exult only"
        )
    payload = bytearray(record.payload)
    adj = int(record.extended_shape)
    length = len(payload) - adj
    supported = (6, 12, 18) if data_format == "retail" else (6, 10, 12, 13, 14, 18)
    if length not in supported:
        raise ValueError(f"IREG rewrite: cannot edit opaque object at {record.offset}")
    decoded = decode_ireg_payload(
        bytes(payload),
        entlen=len(payload),
        extended=record.extended_shape,
        extended_lift=record.extended_lift,
        context=context,
    )
    if decoded is None:
        raise ValueError(f"IREG rewrite: unsupported class layout at {record.offset}")
    class_fields = {
        "quality_byte",
        "invisible",
        "okay_to_take",
        "temporary",
    } & fields.keys()
    shape_info = context.tfa.get(decoded.shape) if context and context.tfa else None
    if class_fields and shape_info is None:
        raise ValueError(
            "IREG rewrite: quality/flag edits require matching TFA class metadata"
        )
    if "quality_byte" in fields and {"invisible", "okay_to_take"} & fields.keys():
        raise ValueError(
            "IREG rewrite: quality_byte cannot be combined with quality flag edits"
        )
    for name, value in fields.items():
        if name in ("x_byte", "y_byte"):
            index = 0 if name == "x_byte" else 1
            coordinate = _integer(name, value, 255)
            if data_format == "retail" and coordinate >> 4 != payload[index] >> 4:
                raise ValueError(
                    "IREG rewrite: retail coordinate edits must preserve the high nibble; chunk regrouping is not implemented"
                )
            payload[index] = coordinate
        elif name == "frame":
            frame = _integer(name, value, 255 if adj else 63)
            if adj:
                payload[4] = frame
            else:
                payload[3] = (payload[3] & 3) | (frame << 2)
        elif name == "lift":
            lift = _integer(name, value, 255 if record.extended_lift else 15)
            lift_offset = (4 if length in (6, 10) else 10 if length == 13 else 9) + adj
            payload[lift_offset] = (
                nibble_swap(lift)
                if record.extended_lift
                else (payload[lift_offset] & 15) | (lift << 4)
            )
        elif name == "quality_byte":
            if decoded.kind not in ("simple", "container", "body", "jawbone"):
                raise ValueError(
                    f"IREG rewrite: no editable quality byte for {decoded.kind}"
                )
            payload[(5 if decoded.kind == "simple" else 7) + adj] = _integer(
                name, value, 255
            )
        else:
            enabled = _flag(name, value)
            shape_class = shape_info.shape_class if shape_info is not None else None
            if name == "temporary":
                if (
                    decoded.kind != "simple"
                    or length != 10
                    or shape_class == U7TypeFlags.SHAPE_CLASS_QUALITY_FLAGS
                ):
                    raise ValueError(
                        "IREG rewrite: temporary needs a 10-byte simple object without quality flags"
                    )
                offset, mask = 6 + adj, 1
            elif decoded.kind in (
                "container",
                "body",
                "jawbone",
                "barge",
                "virtue_stone",
            ):
                offset, mask = (
                    11 + adj + int(length == 13),
                    1 if name == "invisible" else 8,
                )
            elif (
                decoded.kind == "simple"
                and shape_class == U7TypeFlags.SHAPE_CLASS_QUALITY_FLAGS
            ):
                offset, mask = 5 + adj, 1 if name == "invisible" else 8
            elif (
                decoded.kind == "simple"
                and shape_class == U7TypeFlags.SHAPE_CLASS_QUANTITY
                and name == "okay_to_take"
            ):
                offset, mask = 5 + adj, 128
            else:
                raise ValueError(
                    f"IREG rewrite: {name} has no stored flag in this class/layout"
                )
            payload[offset] = (
                payload[offset] | mask if enabled else payload[offset] & ~mask
            )
    return record.raw[: record.header_size] + payload


def rewrite_ireg_stream(
    data: bytes,
    edits: Iterable[U7IregEdit] = (),
    *,
    data_format: U7IregFormat = "exult",
    context: U7IregContext | None = None,
    expected_sha256: str | None = None,
) -> U7IregRewriteResult:
    """Rewrite targeted IREG records; preserve all other bytes and reject stale edits."""
    source_hash = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and expected_sha256.lower() != source_hash:
        raise ValueError("IREG rewrite: source SHA-256 does not match the edit plan")
    records = read_ireg_wire_records(data, data_format=data_format)
    pending: dict[int, U7IregEdit] = {}
    for requested_edit in edits:
        offset = _integer("offset", requested_edit.offset, len(data))
        if offset in pending:
            raise ValueError(f"IREG rewrite: duplicate edit offset {offset}")
        operations = (
            bool(requested_edit.fields)
            + (requested_edit.special_payload is not None)
            + (requested_edit.index_word is not None)
        )
        if operations != 1:
            raise ValueError("IREG rewrite: each edit requires exactly one operation")
        pending[offset] = requested_edit
    output = bytearray()
    changes: list[dict[str, object]] = []
    for record in records:
        edit = pending.pop(record.offset, None)
        rewritten = record.raw
        if edit is not None:
            if edit.expected_raw is not None and edit.expected_raw != record.raw:
                raise ValueError(
                    f"IREG rewrite: expected record bytes do not match at {record.offset}"
                )
            if edit.fields and record.kind == "object":
                rewritten = _edit_object_fields(
                    record, edit.fields, context, data_format
                )
            elif edit.special_payload is not None and record.kind == "special":
                size = _integer(
                    "special payload size", len(edit.special_payload), 65535
                )
                rewritten = (
                    record.raw[:2] + size.to_bytes(2, "little") + edit.special_payload
                )
                parsed, _ = read_ireg_special(rewritten, 0)
                if parsed.type_id in (1, 3, 4) and not parsed.decoded_complete:
                    raise ValueError(
                        "IREG rewrite: replacement special payload fails known-type validation"
                    )
            elif edit.index_word is not None and record.kind == "index":
                rewritten = b"\x02" + _integer(
                    "index_word", edit.index_word, 65535
                ).to_bytes(2, "little")
            else:
                raise ValueError(
                    f"IREG rewrite: operation does not match record kind at {record.offset}"
                )
            changes.append(
                {
                    "offset": record.offset,
                    "output_offset": len(output),
                    "kind": record.kind,
                    "before_hex": record.raw.hex(),
                    "after_hex": rewritten.hex(),
                }
            )
        output.extend(rewritten)
    if pending:
        raise ValueError(
            f"IREG rewrite: edit offsets are not record boundaries: {sorted(pending)}"
        )
    result = bytes(output)
    read_ireg_wire_records(result, data_format=data_format)
    return U7IregRewriteResult(result, source_hash, tuple(changes))


def read_ireg_edit_plan(plan: object) -> tuple[str, tuple[U7IregEdit, ...]]:
    """Validate JSON edit plans: mandatory source hash and expected original record bytes."""
    if not isinstance(plan, dict) or set(plan) != {"source_sha256", "edits"}:
        raise ValueError("IREG rewrite: plan requires only source_sha256 and edits")
    source_hash, rows = plan["source_sha256"], plan["edits"]
    if not isinstance(source_hash, str) or len(source_hash) != 64:
        raise ValueError(
            "IREG rewrite: source_sha256 must contain 64 hexadecimal digits"
        )
    try:
        if len(bytes.fromhex(source_hash)) != 32:
            raise ValueError
    except ValueError as error:
        raise ValueError(
            "IREG rewrite: source_sha256 must contain 64 hexadecimal digits"
        ) from error
    if not isinstance(rows, list):
        raise ValueError("IREG rewrite: edits must be an array")
    edits: list[U7IregEdit] = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or not {"offset", "expected_hex"} <= row.keys()
            or set(row)
            - {"offset", "expected_hex", "fields", "special_payload_hex", "index_word"}
        ):
            raise ValueError(
                "IREG rewrite: edit requires offset, expected_hex and one known operation"
            )
        if len({"fields", "special_payload_hex", "index_word"} & row.keys()) != 1:
            raise ValueError(
                "IREG rewrite: each JSON edit requires exactly one operation"
            )
        try:
            if not isinstance(row["expected_hex"], str):
                raise ValueError
            expected = bytes.fromhex(row["expected_hex"])
            special = row.get("special_payload_hex")
            if "special_payload_hex" in row and not isinstance(special, str):
                raise ValueError
            payload = bytes.fromhex(special) if isinstance(special, str) else None
        except ValueError as error:
            raise ValueError(
                "IREG rewrite: expected_hex and special_payload_hex must be hex strings"
            ) from error
        fields = row.get("fields", {})
        if not isinstance(fields, dict) or any(
            not isinstance(key, str) or not isinstance(value, (int, bool))
            for key, value in fields.items()
        ):
            raise ValueError("IREG rewrite: fields must map names to integers/booleans")
        if "index_word" in row:
            _integer("index_word", row["index_word"], 65535)
        edits.append(
            U7IregEdit(row["offset"], fields, payload, row.get("index_word"), expected)
        )
    return source_hash, tuple(edits)
