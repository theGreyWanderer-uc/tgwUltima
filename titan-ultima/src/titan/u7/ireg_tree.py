"""Lossless Exult world IREG trees with scoped controls, special owners and edit guards."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from titan.u7.ireg import U7ObjectFlags, decode_ireg_payload
from titan.u7.ireg_metadata import U7IregContext
from titan.u7.ireg_rewrite import U7IregWireRecord, read_ireg_wire_records

IREG_TREE_MAX_DEPTH = 128


def ireg_context_sha256(context: U7IregContext) -> str:
    """Fingerprint class/body/jawbone dispatch inputs rather than a mutable installation path."""
    values = {
        "game": context.game,
        "classes": [(row.shape_num, row.shape_class) for row in context.tfa.entries]
        if context.tfa
        else [],
        "bodies": sorted(context.bodies.items()),
        "jawbones": sorted(context.jawbones.items()),
        "bodies_complete": context.bodies_complete,
        "jawbones_complete": context.jawbones_complete,
    }
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


@dataclass(frozen=True)
class U7IregTreeScope:
    """One recursive list; padding/index/opaque/special events retain physical order."""

    owner_offset: int | None
    events: tuple[U7IregTreeObject | U7IregWireRecord, ...]
    terminator: U7IregWireRecord | None = None

    def to_bytes(self) -> bytes:
        return b"".join(
            event.to_bytes() if isinstance(event, U7IregTreeObject) else event.raw
            for event in self.events
        ) + (self.terminator.raw if self.terminator else b"")


@dataclass(frozen=True)
class U7IregTreeObject:
    """An original-offset object identity, with decoded state separate from its untouched wire."""

    record: U7IregWireRecord
    parent_offset: int | None
    shape: int
    frame: int
    kind: str
    x: int
    y: int
    lift: int
    flags: U7ObjectFlags
    saved_index_word: int | None
    children: U7IregTreeScope | None = None

    @property
    def offset(self) -> int:
        return self.record.offset

    def to_bytes(self) -> bytes:
        return self.record.raw + (self.children.to_bytes() if self.children else b"")


@dataclass(frozen=True)
class U7IregTree:
    """A bounded world-stream model; unknown lengths remain opaque, unknown topology is rejected."""

    data: bytes = field(repr=False)
    superchunk: int
    context_sha256: str
    root: U7IregTreeScope
    objects: Mapping[int, U7IregTreeObject]
    records: tuple[U7IregWireRecord, ...]
    special_owners: Mapping[int, int | None]
    opaque_offsets: tuple[int, ...]
    owned_specials: Mapping[int, tuple[U7IregWireRecord, ...]]

    def to_bytes(self) -> bytes:
        return self.root.to_bytes()

    def owned_bytes(self, offset: int) -> bytes:
        """Hashable object/subtree plus its scope-owned specials, excluding persistent index controls."""
        node = self.objects[offset]
        specials = b"".join(
            record.raw for record in self.owned_specials.get(offset, ())
        )
        return node.to_bytes() + specials

    def as_row(self) -> dict[str, object]:
        lists: list[dict[str, object]] = []

        def describe(scope: U7IregTreeScope) -> None:
            lists.append(
                {
                    "owner_offset": scope.owner_offset,
                    "events": [event.offset for event in scope.events],
                    "terminator_offset": scope.terminator.offset
                    if scope.terminator
                    else None,
                }
            )
            for event in scope.events:
                if isinstance(event, U7IregTreeObject) and event.children:
                    describe(event.children)

        describe(self.root)
        return {
            "source_sha256": hashlib.sha256(self.data).hexdigest(),
            "context_sha256": self.context_sha256,
            "superchunk": self.superchunk,
            "opaque_offsets": list(self.opaque_offsets),
            "lists": lists,
            "wire_records": [
                {
                    "offset": record.offset,
                    "kind": record.kind,
                    "raw_hex": record.raw.hex(),
                }
                for record in self.records
                if record.offset not in self.objects
            ],
            "objects": [
                {
                    "offset": node.offset,
                    "parent_offset": node.parent_offset,
                    "shape": node.shape,
                    "frame": node.frame,
                    "kind": node.kind,
                    "x": node.x,
                    "y": node.y,
                    "lift": node.lift,
                    "flags": int(node.flags),
                    "saved_index_word": node.saved_index_word,
                    "record_sha256": hashlib.sha256(node.record.raw).hexdigest(),
                    "owned_sha256": hashlib.sha256(
                        self.owned_bytes(node.offset)
                    ).hexdigest(),
                    "record_hex": node.record.raw.hex(),
                    "children": [
                        event.offset
                        for event in node.children.events
                        if isinstance(event, U7IregTreeObject)
                    ]
                    if node.children
                    else [],
                }
                for _, node in sorted(self.objects.items())
            ],
            "special_owners": [
                {"offset": offset, "owner_offset": owner}
                for offset, owner in self.special_owners.items()
            ],
        }


def read_ireg_tree(
    data: bytes, *, context: U7IregContext, superchunk: int
) -> U7IregTree:
    """Parse Exult standalone world IREG; require known class dispatch and balanced child lists."""
    if (
        isinstance(superchunk, bool)
        or not isinstance(superchunk, int)
        or not 0 <= superchunk < 144
    ):
        raise ValueError("IREG tree: superchunk must be an integer in 0..143")
    if context.game not in ("bg", "si"):
        raise ValueError("IREG tree: game must be bg or si")
    records = read_ireg_wire_records(data, data_format="exult")
    position = 0
    objects: dict[int, U7IregTreeObject] = {}
    owners: dict[int, int | None] = {}
    opaque: list[int] = []

    def scope(
        owner: int | None, inherited: U7ObjectFlags, depth: int
    ) -> U7IregTreeScope:
        nonlocal position
        if depth > IREG_TREE_MAX_DEPTH:
            raise ValueError("IREG tree: nesting exceeds 128 lists")
        events: list[U7IregTreeObject | U7IregWireRecord] = []
        last: int | None = None
        index_word: int | None = None
        while position < len(records):
            record = records[position]
            position += 1
            if record.raw == b"\xff\x02":
                raise ValueError(
                    "IREG tree: FF02 is an actor-only terminator, not a world-stream control"
                )
            if record.kind == "control" and record.raw in (b"\0", b"\1"):
                if owner is not None:
                    return U7IregTreeScope(owner, tuple(events), record)
                events.append(record)
                continue
            if record.kind == "index":
                index_word = int.from_bytes(record.payload, "little")
                events.append(record)
                continue
            if record.kind == "special":
                owners[record.offset] = last
                events.append(record)
                continue
            length = len(record.payload) - int(record.extended_shape)
            if length not in (6, 10, 12, 13, 14, 18):
                opaque.append(record.offset)
                events.append(record)
                continue
            payload = record.payload
            shape = (
                int.from_bytes(payload[2:4], "little")
                if record.extended_shape
                else payload[2] + (payload[3] & 3) * 256
            )
            if context.tfa is None or context.tfa.get(shape) is None:
                raise ValueError(
                    f"IREG tree: TFA class unavailable for shape {shape} at {record.offset}"
                )
            decoded = decode_ireg_payload(
                payload,
                entlen=len(payload),
                extended=record.extended_shape,
                extended_lift=record.extended_lift,
                inherited_flags=inherited,
                context=context,
            )
            if decoded is None or decoded.context_warnings:
                raise ValueError(
                    f"IREG tree: ambiguous/unsupported class layout at {record.offset}"
                )
            if decoded.kind == "egg" and owner is not None:
                raise ValueError(
                    "IREG tree: contained eggs are outside the supported world ownership model"
                )
            child_scope = (
                scope(record.offset, decoded.child_inherit_flags, depth + 1)
                if decoded.has_children_marker
                else None
            )
            x = payload[0] + (256 * (superchunk % 12) if owner is None else 0)
            y = payload[1] + (256 * (superchunk // 12) if owner is None else 0)
            node = U7IregTreeObject(
                record,
                owner,
                decoded.shape,
                decoded.frame,
                decoded.kind,
                x,
                y,
                decoded.lift,
                decoded.object_flags,
                index_word,
                child_scope,
            )
            objects[record.offset] = node
            events.append(node)
            last = record.offset
        if owner is not None:
            raise ValueError(
                f"IREG tree: missing child-list terminator for object {owner}"
            )
        return U7IregTreeScope(None, tuple(events))

    root = scope(None, U7ObjectFlags.NONE, 0)
    owned: dict[int, list[U7IregWireRecord]] = {}
    for record in records:
        special_owner = owners.get(record.offset)
        if special_owner is not None:
            owned.setdefault(special_owner, []).append(record)
    result = U7IregTree(
        data,
        superchunk,
        ireg_context_sha256(context),
        root,
        MappingProxyType(objects),
        records,
        MappingProxyType(owners),
        tuple(opaque),
        MappingProxyType({offset: tuple(rows) for offset, rows in owned.items()}),
    )
    if result.to_bytes() != data:
        raise ValueError("IREG tree: internal lossless reconstruction mismatch")
    return result
