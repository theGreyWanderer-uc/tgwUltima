"""Guarded Exult object creation, class conversion and loss-aware record promotion."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal, cast

from titan.u7.ireg import U7ObjectFlags, decode_ireg_payload, nibble_swap
from titan.u7.ireg_metadata import U7IregContext
from titan.u7.ireg_rewrite import (
    U7IregEdit,
    U7IregWireRecord,
    read_ireg_wire_records,
    rewrite_ireg_stream,
)
from titan.u7.ireg_tree import U7IregTreeObject, U7IregTreeScope, read_ireg_tree

if TYPE_CHECKING:
    from titan.u7.ireg_tree_edit import (
        U7IregDelete,
        U7IregReparent,
        U7IregTreeEditResult,
    )

IregRecordFormat = Literal["auto", "ordinary", "fd", "fe"]


@dataclass(frozen=True)
class U7IregCreate:
    """Create one empty object from an explicit record; string parent IDs refer to other creations."""

    object_id: str
    record: bytes = field(repr=False)
    parent_offset: int | str | None
    parent_sha256: str | None
    x: int
    y: int
    lift: int
    index_word: int
    flag_policy: Literal["preserve", "inherit"]


@dataclass(frozen=True)
class U7IregConvert:
    """Convert a guarded record; different class layouts require an explicit replacement and loss consent."""

    offset: int
    expected_sha256: str
    shape: int | None = None
    frame: int | None = None
    lift: int | None = None
    record_format: IregRecordFormat = "auto"
    simple_length: Literal[6, 10] | None = None
    body_npc: int | None = None
    replacement_record: bytes | None = field(default=None, repr=False)
    allow_data_loss: bool = False
    flag_policy: Literal["preserve", "inherit"] = "preserve"


def _number(value: object, name: str, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= maximum
    ):
        raise ValueError(f"IREG authoring: {name} must be an integer in 0..{maximum}")
    return value


def _hash(expected: object, raw: bytes, name: str) -> None:
    if (
        not isinstance(expected, str)
        or expected.lower() != hashlib.sha256(raw).hexdigest()
    ):
        raise ValueError(f"IREG authoring: {name} SHA-256 does not match")


def _record(raw: bytes) -> U7IregWireRecord:
    records = read_ireg_wire_records(raw)
    if len(records) != 1 or records[0].kind != "object":
        raise ValueError("IREG authoring: expected exactly one complete object record")
    return records[0]


def _decoded(record: U7IregWireRecord, context: U7IregContext):
    result = decode_ireg_payload(
        record.payload,
        entlen=len(record.payload),
        extended=record.extended_shape,
        extended_lift=record.extended_lift,
        context=context,
    )
    if result is None or result.context_warnings:
        raise ValueError("IREG authoring: unresolved class or invalid object layout")
    return result


def _shape_family(shape: int, context: U7IregContext) -> str:
    info = context.tfa.get(shape) if context.tfa else None
    if info is None:
        raise ValueError("IREG authoring: target shape class is unavailable")
    if context.bodies.get(shape):
        return "body"
    if context.jawbones.get(shape):
        return "jawbone"
    return {
        6: "container",
        7: "egg",
        8: "spellbook",
        9: "barge",
        11: "virtue_stone",
    }.get(info.shape_class, "simple")


def create_ireg_record(
    shape: int,
    *,
    context: U7IregContext,
    frame: int = 0,
    lift: int = 0,
    record_format: IregRecordFormat = "auto",
) -> bytes:
    """Build a zero-initialized empty object of the metadata-selected class; extra payload state stays explicit."""
    shape = _number(shape, "shape", 65535)
    info = context.tfa.get(shape) if context.tfa else None
    if info is None:
        raise ValueError("IREG authoring: matching TFA is required for creation")
    length = (
        13
        if context.bodies.get(shape)
        else 12
        if info.shape_class in (6, 7, 9, 11) or context.jawbones.get(shape)
        else 18
        if info.shape_class == 8
        else 10
    )
    frame, lift = _number(frame, "frame", 255), _number(lift, "lift", 255)
    required = "fe" if shape > 1023 or frame > 63 else "fd" if lift > 15 else "ordinary"
    chosen = required if record_format == "auto" else record_format
    if (
        chosen not in ("ordinary", "fd", "fe")
        or required == "fe"
        and chosen != "fe"
        or required == "fd"
        and chosen == "ordinary"
    ):
        raise ValueError(
            "IREG authoring: creation format cannot represent identity/lift"
        )
    payload = bytearray(length)
    payload[2:4] = bytes([shape & 255, (shape >> 8 & 3) | (frame & 63) << 2])
    payload[4 if length in (6, 10) else 10 if length == 13 else 9] = nibble_swap(lift)
    if chosen == "fe":
        payload[2:4] = shape.to_bytes(2, "little") + bytes([frame])
    result = (
        (b"\xfe" if chosen == "fe" else b"\xfd" if chosen == "fd" else b"")
        + bytes([len(payload)])
        + payload
    )
    _decoded(_record(result), context)
    return result


def _format_record(
    record: U7IregWireRecord,
    *,
    context: U7IregContext,
    shape: int | None = None,
    frame: int | None = None,
    lift: int | None = None,
    record_format: IregRecordFormat = "auto",
    simple_length: int | None = None,
    body_npc: int | None = None,
    allow_data_loss: bool = False,
    minimum_format: Literal["ordinary", "fd", "fe"] = "ordinary",
) -> bytes:
    # Normalized payload has the ordinary four-byte identity, followed by untouched class bytes.
    payload = bytearray(record.payload)
    old = _decoded(record, context)
    if record.extended_shape:
        payload[2:5] = bytes(
            [old.shape & 255, (old.shape >> 8 & 3) | (old.frame & 63) << 2]
        )
    length = len(payload)
    old_lift_index = 4 if length in (6, 10) else 10 if length == 13 else 9
    ignored_lift_bits = payload[old_lift_index] & 15 if not record.extended_lift else 0
    shape = old.shape if shape is None else _number(shape, "shape", 65535)
    frame = old.frame if frame is None else _number(frame, "frame", 255)
    lift = old.lift if lift is None else _number(lift, "lift", 255)
    if simple_length is not None:
        simple_length = _number(simple_length, "simple_length", 10)
        if (
            old.kind != "simple"
            or simple_length not in (6, 10)
            or simple_length < length
        ):
            raise ValueError(
                "IREG authoring: simple promotion only supports 6 to 10 bytes"
            )
        payload.extend(bytes(simple_length - length))
    if body_npc is not None:
        if old.kind != "body":
            raise ValueError("IREG authoring: body_npc requires a body record")
        npc = _number(body_npc, "body_npc", 65535)
        if len(payload) == 12:
            payload.insert(9, 0)
        if len(payload) != 13:
            raise ValueError(
                "IREG authoring: body NPC promotion requires a 12/13-byte body"
            )
        payload[7] = 1
        payload[8:10] = npc.to_bytes(2, "little")
    required = "fe" if shape > 1023 or frame > 63 else "fd" if lift > 15 else "ordinary"
    if record_format == "auto":
        chosen = (
            "fe"
            if record.extended_shape or required == "fe" or minimum_format == "fe"
            else "fd"
            if record.extended_lift or required == "fd" or minimum_format == "fd"
            else "ordinary"
        )
    else:
        chosen = record_format
    if (
        chosen not in ("ordinary", "fd", "fe")
        or (required == "fe" and chosen != "fe")
        or (required == "fd" and chosen == "ordinary")
    ):
        raise ValueError(
            "IREG authoring: requested record format cannot represent the identity/lift"
        )
    if (
        (record.extended_shape or minimum_format == "fe")
        and chosen != "fe"
        or (record.extended_lift or minimum_format == "fd")
        and chosen == "ordinary"
    ):
        raise ValueError("IREG authoring: implicit record demotion is not supported")
    if chosen != "ordinary" and ignored_lift_bits and not allow_data_loss:
        raise ValueError(
            "IREG authoring: promotion would discard ignored lift bits; explicit allow_data_loss required"
        )
    payload[2:4] = bytes([shape & 255, (shape >> 8 & 3) | (frame & 63) << 2])
    index = 4 if len(payload) in (6, 10) else 10 if len(payload) == 13 else 9
    payload[index] = (
        nibble_swap(lift) if chosen != "ordinary" else (lift << 4) | ignored_lift_bits
    )
    if chosen == "fe":
        payload[2:4] = shape.to_bytes(2, "little") + bytes([frame])
    prefix = b"\xfe" if chosen == "fe" else b"\xfd" if chosen == "fd" else b""
    result = prefix + bytes([len(payload)]) + payload
    _decoded(_record(result), context)
    return result


def author_ireg_tree(
    data: bytes,
    operations: Iterable[U7IregDelete | U7IregReparent | U7IregCreate | U7IregConvert],
    *,
    context: U7IregContext,
    superchunk: int,
    expected_sha256: str,
    expected_context_sha256: str,
) -> U7IregTreeEditResult:
    """Stage original-offset conversions/creations, then use the validated hierarchy editor for placement."""
    from titan.u7.ireg_tree_edit import (
        U7IregDelete,
        U7IregReparent,
        U7IregTreeEditResult,
        edit_ireg_tree,
    )

    _hash(expected_sha256, data, "source")
    original = read_ireg_tree(data, context=context, superchunk=superchunk)
    if (
        not isinstance(expected_context_sha256, str)
        or expected_context_sha256.lower() != original.context_sha256
    ):
        raise ValueError("IREG authoring: dispatch context SHA-256 does not match")
    requests = list(operations)
    conversions: dict[int, U7IregConvert] = {}
    creations: dict[str, U7IregCreate] = {}
    moves: list[U7IregDelete | U7IregReparent] = []
    for op in requests:
        if isinstance(op, U7IregCreate):
            if (
                not isinstance(op.object_id, str)
                or not op.object_id
                or op.object_id in creations
            ):
                raise ValueError(
                    "IREG authoring: creation IDs must be nonempty unique strings"
                )
            creations[op.object_id] = op
        elif isinstance(op, (U7IregConvert, U7IregDelete, U7IregReparent)):
            _number(op.offset, "offset", len(data))
            if op.offset not in original.objects:
                raise ValueError("IREG authoring: source object not found")
            _hash(op.expected_sha256, original.owned_bytes(op.offset), "object")
            if isinstance(op, U7IregConvert):
                if (
                    op.offset in conversions
                    or not isinstance(op.allow_data_loss, bool)
                    or op.flag_policy not in ("preserve", "inherit")
                ):
                    raise ValueError(
                        "IREG authoring: duplicate conversion or invalid loss/flag policy"
                    )
                conversions[op.offset] = op
            else:
                moves.append(op)
            if isinstance(op, U7IregReparent) and op.parent_offset is not None:
                _number(op.parent_offset, "parent_offset", len(data))
                if op.parent_offset not in original.objects:
                    raise ValueError("IREG authoring: destination not found")
                _hash(
                    op.parent_sha256,
                    original.objects[op.parent_offset].record.raw,
                    "parent",
                )
            elif isinstance(op, U7IregReparent) and op.parent_sha256 is not None:
                raise ValueError("IREG authoring: root destination has no parent hash")
        else:
            raise ValueError("IREG authoring: unsupported operation")
    replacements: dict[int, bytes] = {}
    for offset, op in conversions.items():
        before = original.objects[offset]
        base = (
            _record(op.replacement_record)
            if op.replacement_record is not None
            else before.record
        )
        if op.replacement_record is not None and not op.allow_data_loss:
            raise ValueError(
                "IREG authoring: replacement payload requires explicit allow_data_loss"
            )
        raw = _format_record(
            base,
            context=context,
            shape=op.shape,
            frame=op.frame,
            lift=before.lift if op.lift is None else op.lift,
            record_format=op.record_format,
            simple_length=op.simple_length,
            body_npc=op.body_npc,
            allow_data_loss=op.allow_data_loss,
            minimum_format="fe"
            if before.record.extended_shape
            else "fd"
            if before.record.extended_lift
            else "ordinary",
        )
        after = _decoded(_record(raw), context)
        if (
            after.kind != before.kind
            or _shape_family(after.shape, context)
            != _shape_family(before.shape, context)
        ) and op.replacement_record is None:
            raise ValueError(
                "IREG authoring: class layout conversion requires an explicit replacement record"
            )
        payload = bytearray(raw)
        target = _record(raw)
        payload[target.header_size : target.header_size + 2] = before.record.payload[:2]
        if before.children is not None:
            if after.kind not in ("container", "body"):
                raise ValueError(
                    "IREG authoring: reparent/delete contents before converting to a non-container"
                )
            start = target.header_size + 4 + int(target.extended_shape)
            payload[start : start + 2] = before.record.payload[
                4 + int(before.record.extended_shape) : 6
                + int(before.record.extended_shape)
            ]
        elif after.has_children_marker:
            raise ValueError(
                "IREG authoring: replacement record cannot introduce an unprovided child list"
            )
        replacements[offset] = bytes(payload)

    staged = bytearray()
    offsets: dict[int, int] = {}
    policies: dict[int, str] = {}

    def emit(scope: U7IregTreeScope, policy: str = "preserve") -> None:
        for event in scope.events:
            offsets[event.offset] = len(staged)
            if isinstance(event, U7IregTreeObject):
                active = (
                    conversions[event.offset].flag_policy
                    if event.offset in conversions
                    else policy
                )
                policies[event.offset] = active
                staged.extend(replacements.get(event.offset, event.record.raw))
                if event.children:
                    emit(event.children, active)
            else:
                staged.extend(event.raw)
        if scope.terminator:
            offsets[scope.terminator.offset] = len(staged)
            staged.extend(scope.terminator.raw)

    emit(original.root)
    # Preserve decoded flags after class changes where an existing field can represent them.
    parsed = read_ireg_tree(bytes(staged), context=context, superchunk=superchunk)
    flag_edits: list[U7IregEdit] = []
    for offset, before in original.objects.items():
        after = parsed.objects[offsets[offset]]
        if policies[offset] == "preserve" and before.flags != after.flags:
            fields = {
                name: bool(before.flags & flag)
                for flag, name in (
                    (U7ObjectFlags.INVISIBLE, "invisible"),
                    (U7ObjectFlags.OKAY_TO_TAKE, "okay_to_take"),
                    (U7ObjectFlags.TEMPORARY, "temporary"),
                )
                if bool(before.flags & flag) != bool(after.flags & flag)
            }
            flag_edits.append(U7IregEdit(after.offset, fields))
    staged = bytearray(
        rewrite_ireg_stream(bytes(staged), flag_edits, context=context).data
    )
    converted = read_ireg_tree(bytes(staged), context=context, superchunk=superchunk)
    for offset, before in original.objects.items():
        if (
            policies[offset] == "preserve"
            and converted.objects[offsets[offset]].flags != before.flags
        ):
            raise ValueError("IREG authoring: preserved flags cannot be represented")
    created: dict[str, int] = {}
    for name, op in creations.items():
        record = _record(op.record)
        decoded = _decoded(record, context)
        if decoded.has_children_marker:
            raise ValueError(
                "IREG authoring: creation record must start empty; use creation IDs to build nested lists"
            )
        _number(op.index_word, "index_word", 65535)
        if op.index_word & 255 not in (*range(18), 255) or op.flag_policy not in (
            "preserve",
            "inherit",
        ):
            raise ValueError("IREG authoring: invalid creation index or flag policy")
        if op.parent_offset is None:
            x, y = _number(op.x, "world x", 3071), _number(op.y, "world y", 3071)
            if (
                x // 256 != superchunk % 12
                or y // 256 != superchunk // 12
                or op.parent_sha256 is not None
            ):
                raise ValueError("IREG authoring: invalid world creation destination")
        else:
            x, y = superchunk % 12 * 256, superchunk // 12 * 256
        raw = _format_record(record, context=context, lift=op.lift)
        raw = rewrite_ireg_stream(
            raw,
            [U7IregEdit(0, {"x_byte": x % 256, "y_byte": y % 256})],
            context=context,
        ).data
        staged.extend(b"\2" + op.index_word.to_bytes(2, "little"))
        created[name] = len(staged)
        staged.extend(raw)
    prepared = bytes(staged)
    ready = read_ireg_tree(prepared, context=context, superchunk=superchunk)
    translated: list[U7IregDelete | U7IregReparent] = []
    for op in moves:
        mapped = offsets[op.offset]
        if isinstance(op, U7IregDelete):
            translated.append(
                replace(
                    op,
                    offset=mapped,
                    expected_sha256=hashlib.sha256(
                        ready.owned_bytes(mapped)
                    ).hexdigest(),
                )
            )
        else:
            parent = offsets[op.parent_offset] if op.parent_offset is not None else None
            translated.append(
                replace(
                    op,
                    offset=mapped,
                    expected_sha256=hashlib.sha256(
                        ready.owned_bytes(mapped)
                    ).hexdigest(),
                    parent_offset=parent,
                    parent_sha256=hashlib.sha256(
                        ready.objects[parent].record.raw
                    ).hexdigest()
                    if parent is not None
                    else None,
                )
            )
    for name, op in creations.items():
        if op.parent_offset is None:
            continue
        if isinstance(op.parent_offset, str):
            if op.parent_offset not in created or op.parent_sha256 is not None:
                raise ValueError(
                    "IREG authoring: unknown creation parent ID or unexpected parent hash"
                )
            parent = created[op.parent_offset]
        else:
            _number(op.parent_offset, "parent_offset", len(data))
            if op.parent_offset not in original.objects:
                raise ValueError("IREG authoring: creation destination not found")
            _hash(
                op.parent_sha256,
                original.objects[op.parent_offset].record.raw,
                "creation parent",
            )
            parent = offsets[op.parent_offset]
        mapped = created[name]
        translated.append(
            U7IregReparent(
                mapped,
                hashlib.sha256(ready.owned_bytes(mapped)).hexdigest(),
                parent,
                hashlib.sha256(ready.objects[parent].record.raw).hexdigest(),
                op.x,
                op.y,
                op.lift,
                op.index_word,
                op.flag_policy,
            )
        )
    result = edit_ireg_tree(
        prepared,
        translated,
        context=context,
        superchunk=superchunk,
        expected_sha256=hashlib.sha256(prepared).hexdigest(),
        expected_context_sha256=ready.context_sha256,
    )
    final = read_ireg_tree(result.data, context=context, superchunk=superchunk)
    mapping = {
        old: result.offset_map[new]
        for old, new in offsets.items()
        if old in original.objects and new in result.offset_map
    }
    deleted = set(original.objects) - set(mapping)
    if any(offset in deleted for offset in conversions):
        raise ValueError(
            "IREG authoring: cannot convert an object deleted by the same transaction"
        )
    if any(value not in result.offset_map for value in created.values()):
        raise ValueError("IREG authoring: creation destination is deleted")
    # Conversion emission retains every non-object event verbatim; the core checks
    # retained special ownership and controls against that staged tree after moves.
    changes = [
        {
            "action": "convert",
            "offset": offset,
            "allow_data_loss": op.allow_data_loss,
            "before_hex": original.objects[offset].record.raw.hex(),
            "after_hex": final.objects[mapping[offset]].record.raw.hex(),
        }
        for offset, op in conversions.items()
    ]
    changes += [
        {
            "action": "create",
            "object_id": name,
            "output_offset": result.offset_map[offset],
            "parent_offset": creations[name].parent_offset,
            "x": creations[name].x,
            "y": creations[name].y,
            "lift": creations[name].lift,
            "index_word": creations[name].index_word,
            "flag_policy": creations[name].flag_policy,
            "flags": int(final.objects[result.offset_map[offset]].flags),
            "record_hex": final.objects[result.offset_map[offset]].record.raw.hex(),
        }
        for name, offset in created.items()
    ]
    reverse_offsets = {
        new: old for old, new in offsets.items() if old in original.objects
    }
    for row in result.changes:
        if row["offset"] in created.values():
            continue
        report = dict(row)
        for key in ("offset", "old_parent", "new_parent"):
            value = report.get(key)
            if isinstance(value, int):
                report[key] = reverse_offsets[value]
        if row["action"] == "delete":
            report["removed_objects"] = [
                reverse_offsets[value]
                for value in cast(list[int], row["removed_objects"])
            ]
        changes.append(report)
    records = tuple(
        {
            "offset": old,
            "output_offset": new,
            "before_hex": original.objects[old].record.raw.hex(),
            "after_hex": final.objects[new].record.raw.hex(),
        }
        for old, new in mapping.items()
        if original.objects[old].record.raw != final.objects[new].record.raw
    )
    flags: tuple[dict[str, object], ...] = tuple(
        {
            "offset": old,
            "before": int(original.objects[old].flags),
            "after": int(final.objects[new].flags),
        }
        for old, new in mapping.items()
        if original.objects[old].flags != final.objects[new].flags
    )
    return U7IregTreeEditResult(
        result.data,
        hashlib.sha256(data).hexdigest(),
        original.context_sha256,
        tuple(changes),
        mapping,
        records,
        flags,
        {name: result.offset_map[offset] for name, offset in created.items()},
    )
