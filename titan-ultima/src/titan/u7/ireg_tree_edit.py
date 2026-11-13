"""Guarded Exult world IREG authoring and validated save-member embedding."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from titan.u7.ireg_authoring import U7IregCreate, U7IregConvert

from titan.u7.ireg import U7ObjectFlags, decode_ireg_payload
from titan.u7.ireg_metadata import U7IregContext
from titan.u7.ireg_rewrite import U7IregEdit, U7IregWireRecord, rewrite_ireg_stream
from titan.u7.ireg_tree import (
    IREG_TREE_MAX_DEPTH,
    U7IregTree,
    U7IregTreeObject,
    U7IregTreeScope,
    read_ireg_tree,
)
from titan.u7.save_container import read_u7_save_container
from titan.u7.save_repack import (
    U7SaveReplacement,
    U7SaveRepackResult,
    check_u7_save_hash,
    repack_u7_save,
)


@dataclass(frozen=True)
class U7IregDelete:
    """Delete a guarded object and its owned specials; nonempty contents require explicit cascade."""

    offset: int
    expected_sha256: str
    cascade: bool = False


@dataclass(frozen=True)
class U7IregReparent:
    """Move a guarded subtree with explicit coordinates, saved index and inherited-flag policy."""

    offset: int
    expected_sha256: str
    parent_offset: int | None
    parent_sha256: str | None
    x: int
    y: int
    lift: int
    index_word: int
    flag_policy: Literal["preserve", "inherit"]


@dataclass(frozen=True)
class U7IregTreeEditResult:
    """Validated rewritten bytes with source-to-output object identities and effective-flag changes."""

    data: bytes = field(repr=False)
    source_sha256: str
    context_sha256: str
    changes: tuple[dict[str, object], ...]
    offset_map: dict[int, int]
    record_changes: tuple[dict[str, object], ...]
    flag_changes: tuple[dict[str, object], ...]
    created_offsets: dict[str, int] = field(default_factory=dict)

    def as_row(self) -> dict[str, object]:
        return {
            "source_sha256": self.source_sha256,
            "context_sha256": self.context_sha256,
            "output_sha256": hashlib.sha256(self.data).hexdigest(),
            "output_bytes": len(self.data),
            "changes": list(self.changes),
            "object_offsets": self.offset_map,
            "record_changes": list(self.record_changes),
            "flag_changes": list(self.flag_changes),
            "created_offsets": self.created_offsets,
        }


@dataclass(frozen=True)
class U7IregSaveTreeResult:
    """A hierarchy-validated IREG edit embedded in an occurrence-preserving new save archive."""

    tree_edit: U7IregTreeEditResult
    save_repack: U7SaveRepackResult

    @property
    def data(self) -> bytes:
        return self.save_repack.data

    def as_row(self) -> dict[str, object]:
        return {
            "tree_edit": self.tree_edit.as_row(),
            "save_repack": self.save_repack.as_row(),
        }


@dataclass
class _TreeNode:
    original: U7IregTreeObject
    record: U7IregWireRecord
    parent: int | None
    children: _TreeScope | None = None
    policy: Literal["preserve", "inherit"] | None = None


@dataclass
class _TreeScope:
    owner: int | None
    events: list[_TreeNode | U7IregWireRecord]
    terminator: U7IregWireRecord | None


def _guard_hash(expected: object, actual: str, label: str) -> None:
    if (
        not isinstance(expected, str)
        or re.fullmatch(r"[0-9a-fA-F]{64}", expected) is None
        or expected.lower() != actual
    ):
        raise ValueError(f"IREG tree edit: {label} SHA-256 does not match")


def _integer(value: object, label: str, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= maximum
    ):
        raise ValueError(f"IREG tree edit: {label} must be an integer in 0..{maximum}")
    return value


def _descendants(tree: U7IregTree, offset: int) -> set[int]:
    result = {offset}
    pending = [tree.objects[offset]]
    while pending:
        node = pending.pop()
        if node.children:
            for event in node.children.events:
                if isinstance(event, U7IregTreeObject):
                    result.add(event.offset)
                    pending.append(event)
    return result


def _owned_offsets(tree: U7IregTree, node: U7IregTreeObject) -> set[int]:
    result = {node.offset}

    def visit(scope: U7IregTreeScope) -> None:
        for event in scope.events:
            result.add(event.offset)
            if isinstance(event, U7IregTreeObject) and event.children:
                visit(event.children)
        if scope.terminator:
            result.add(scope.terminator.offset)

    if node.children:
        visit(node.children)
    result.update(
        offset for offset, owner in tree.special_owners.items() if owner == node.offset
    )
    return result


def edit_ireg_tree(
    data: bytes,
    operations: Iterable[U7IregDelete | U7IregReparent | U7IregCreate | U7IregConvert],
    *,
    context: U7IregContext,
    superchunk: int,
    expected_sha256: str,
    expected_context_sha256: str,
) -> U7IregTreeEditResult:
    """Apply simultaneous original-offset edits; validate ownership, indices, flags and untouched wire."""
    all_requests = list(operations)
    if any(isinstance(op, (U7IregCreate, U7IregConvert)) for op in all_requests):
        from titan.u7.ireg_authoring import author_ireg_tree

        return author_ireg_tree(
            data,
            all_requests,
            context=context,
            superchunk=superchunk,
            expected_sha256=expected_sha256,
            expected_context_sha256=expected_context_sha256,
        )
    requests: list[U7IregDelete | U7IregReparent] = []
    for request in all_requests:
        if not isinstance(request, (U7IregDelete, U7IregReparent)):
            raise ValueError("IREG tree edit: unsupported operation")
        requests.append(request)
    source_hash = hashlib.sha256(data).hexdigest()
    _guard_hash(expected_sha256, source_hash, "source")
    tree = read_ireg_tree(data, context=context, superchunk=superchunk)
    _guard_hash(expected_context_sha256, tree.context_sha256, "dispatch context")
    targeted: set[int] = set()
    deleted: set[int] = set()
    deleted_records: set[int] = set()
    moves: dict[int, U7IregReparent] = {}
    for operation in requests:
        if not isinstance(operation, (U7IregDelete, U7IregReparent)):
            raise ValueError("IREG tree edit: unsupported operation")
        offset = _integer(operation.offset, "offset", len(data))
        if offset not in tree.objects or offset in targeted:
            raise ValueError("IREG tree edit: missing or duplicate source object")
        original_node = tree.objects[offset]
        _guard_hash(
            operation.expected_sha256,
            hashlib.sha256(tree.owned_bytes(offset)).hexdigest(),
            f"object {offset}",
        )
        targeted.add(offset)
        if isinstance(operation, U7IregDelete):
            if not isinstance(operation.cascade, bool):
                raise ValueError("IREG tree edit: cascade must be boolean")
            if (
                original_node.children
                and original_node.children.events
                and not operation.cascade
            ):
                raise ValueError(
                    "IREG tree edit: nonempty contents require cascade=true"
                )
            deleted.update(_descendants(tree, offset))
            deleted_records.update(_owned_offsets(tree, original_node))
        else:
            if original_node.kind in ("egg", "barge"):
                raise ValueError(
                    "IREG tree edit: egg/barge reparenting needs a class-specific model"
                )
            if operation.flag_policy not in ("preserve", "inherit"):
                raise ValueError(
                    "IREG tree edit: flag_policy must be preserve or inherit"
                )
            _integer(operation.index_word, "index_word", 65535)
            low = operation.index_word & 255
            if low != 255 and not 0 <= low < 18:
                raise ValueError(
                    "IREG tree edit: index_word must request slot 0..17 or explicit no-slot"
                )
            _integer(
                operation.lift,
                "lift",
                255 if original_node.record.extended_lift else 15,
            )
            if operation.parent_offset is None:
                if operation.parent_sha256 is not None:
                    raise ValueError(
                        "IREG tree edit: root destination has no parent hash"
                    )
                x = _integer(operation.x, "world x", 3071)
                y = _integer(operation.y, "world y", 3071)
                if x // 256 != superchunk % 12 or y // 256 != superchunk // 12:
                    raise ValueError(
                        "IREG tree edit: cross-superchunk moves are not supported"
                    )
            else:
                requested_parent = tree.objects.get(
                    _integer(operation.parent_offset, "parent_offset", len(data))
                )
                if requested_parent is None or requested_parent.kind not in (
                    "container",
                    "body",
                ):
                    raise ValueError(
                        "IREG tree edit: destination must be an ordinary container or body"
                    )
                _guard_hash(
                    operation.parent_sha256,
                    hashlib.sha256(requested_parent.record.raw).hexdigest(),
                    "destination parent",
                )
                _integer(operation.x, "gump x", 255)
                _integer(operation.y, "gump y", 255)
            if operation.parent_offset == original_node.parent_offset:
                raise ValueError(
                    "IREG tree edit: object already has that parent; use field edits for placement"
                )
            moves[offset] = operation
    for offset in targeted:
        ancestor = tree.objects[offset].parent_offset
        while ancestor is not None:
            if ancestor in targeted:
                raise ValueError(
                    "IREG tree edit: source subtrees overlap; use separate guarded transactions"
                )
            ancestor = tree.objects[ancestor].parent_offset
    parents = {
        offset: moves[offset].parent_offset if offset in moves else node.parent_offset
        for offset, node in tree.objects.items()
        if offset not in deleted
    }
    for offset in parents:
        current: int | None = offset
        seen: set[int] = set()
        while current is not None:
            if current in seen or current not in parents:
                raise ValueError(
                    "IREG tree edit: cycle or deleted destination in resulting hierarchy"
                )
            seen.add(current)
            if len(seen) > IREG_TREE_MAX_DEPTH + 1:
                raise ValueError(
                    "IREG tree edit: resulting hierarchy exceeds depth limit"
                )
            current = parents[current]

    nodes: dict[int, _TreeNode] = {}
    scopes: dict[int | None, _TreeScope] = {}

    def clone(scope: U7IregTreeScope) -> _TreeScope:
        copied = _TreeScope(scope.owner_offset, [], scope.terminator)
        scopes[scope.owner_offset] = copied
        for event in scope.events:
            if isinstance(event, U7IregTreeObject):
                node = _TreeNode(event, event.record, event.parent_offset)
                nodes[event.offset] = node
                node.children = clone(event.children) if event.children else None
                copied.events.append(node)
            else:
                copied.events.append(event)
        return copied

    root = clone(tree.root)
    specials = {
        offset: list(tree.owned_specials.get(offset, ())) for offset in targeted
    }
    for operation in requests:
        node = nodes[operation.offset]
        old_scope = scopes[node.original.parent_offset]
        owned_specials = {record.offset for record in specials[operation.offset]}
        old_scope.events = [
            event
            for event in old_scope.events
            if event is not node
            and not (
                isinstance(event, U7IregWireRecord) and event.offset in owned_specials
            )
        ]

    def patch_record(
        record: U7IregWireRecord, fields: dict[str, int | bool]
    ) -> U7IregWireRecord:
        rewritten = rewrite_ireg_stream(
            record.raw, [U7IregEdit(0, fields)], context=context
        ).data
        return U7IregWireRecord(
            record.offset, record.kind, rewritten, record.header_size
        )

    changes: list[dict[str, object]] = []
    for operation in requests:
        node = nodes[operation.offset]
        if isinstance(operation, U7IregDelete):
            changes.append(
                {
                    "action": "delete",
                    "offset": operation.offset,
                    "cascade": operation.cascade,
                    "removed_objects": sorted(_descendants(tree, operation.offset)),
                }
            )
            continue
        if operation.parent_offset is None:
            destination = root
            x, y = operation.x % 256, operation.y % 256
        else:
            parent = nodes[operation.parent_offset]
            if parent.children is None:
                parent.children = _TreeScope(
                    operation.parent_offset,
                    [],
                    U7IregWireRecord(-1, "control", b"\1", 1),
                )
                scopes[operation.parent_offset] = parent.children
                raw = bytearray(parent.record.raw)
                start = (
                    parent.record.header_size + 4 + int(parent.record.extended_shape)
                )
                raw[start : start + 2] = b"\1\0"
                parent.record = U7IregWireRecord(
                    parent.record.offset,
                    parent.record.kind,
                    bytes(raw),
                    parent.record.header_size,
                )
            destination = parent.children
            x, y = operation.x, operation.y
        node.record = patch_record(
            node.record, {"x_byte": x, "y_byte": y, "lift": operation.lift}
        )
        node.parent, node.policy = operation.parent_offset, operation.flag_policy
        destination.events.extend(
            [
                U7IregWireRecord(
                    -1, "index", b"\2" + operation.index_word.to_bytes(2, "little"), 1
                ),
                node,
                *specials[operation.offset],
            ]
        )
        changes.append(
            {
                "action": "reparent",
                "offset": operation.offset,
                "old_parent": node.original.parent_offset,
                "new_parent": operation.parent_offset,
                "x": operation.x,
                "y": operation.y,
                "lift": operation.lift,
                "index_word": operation.index_word,
                "flag_policy": operation.flag_policy,
            }
        )

    output = bytearray()
    positions: dict[int, int] = {}
    wire_positions: dict[int, int] = {}
    expected_flags: dict[int, U7ObjectFlags] = {}

    def emit_record(record: U7IregWireRecord) -> None:
        if record.offset >= 0:
            if record.offset in wire_positions:
                raise ValueError(
                    "IREG tree edit: original record emitted more than once"
                )
            wire_positions[record.offset] = len(output)
        output.extend(record.raw)

    def emit_scope(
        scope: _TreeScope, inherited: U7ObjectFlags, policy: str | None
    ) -> None:
        for event in scope.events:
            if isinstance(event, U7IregWireRecord):
                emit_record(event)
                continue
            node = event
            active = node.policy or policy

            def decode():
                return decode_ireg_payload(
                    node.record.payload,
                    entlen=len(node.record.payload),
                    extended=node.record.extended_shape,
                    extended_lift=node.record.extended_lift,
                    inherited_flags=inherited,
                    context=context,
                )

            state = decode()
            if state is None or state.context_warnings:
                raise ValueError(
                    "IREG tree edit: rewritten object layout is not resolved"
                )
            if state.object_flags != node.original.flags and active != "inherit":
                if active is None:
                    raise ValueError("IREG tree edit: unplanned inherited-flag change")
                fields: dict[str, int | bool] = {}
                for flag, name in (
                    (U7ObjectFlags.INVISIBLE, "invisible"),
                    (U7ObjectFlags.OKAY_TO_TAKE, "okay_to_take"),
                    (U7ObjectFlags.TEMPORARY, "temporary"),
                ):
                    if bool(state.object_flags & flag) != bool(
                        node.original.flags & flag
                    ):
                        fields[name] = bool(node.original.flags & flag)
                try:
                    node.record = patch_record(node.record, fields)
                except ValueError as error:
                    raise ValueError(
                        "IREG tree edit: preserved inherited flags cannot be encoded; choose inherit explicitly"
                    ) from error
                state = decode()
                if state is None or state.object_flags != node.original.flags:
                    raise ValueError(
                        "IREG tree edit: preserved inherited flags cannot be represented"
                    )
            if state.has_children_marker != (node.children is not None):
                raise ValueError(
                    "IREG tree edit: child marker does not match serialized list"
                )
            positions[node.original.offset] = len(output)
            expected_flags[node.original.offset] = state.object_flags
            emit_record(node.record)
            if node.children is not None:
                emit_scope(node.children, state.child_inherit_flags, active)
        if scope.terminator:
            emit_record(scope.terminator)

    emit_scope(root, U7ObjectFlags.NONE, None)
    if (
        set(wire_positions)
        != {record.offset for record in tree.records} - deleted_records
    ):
        raise ValueError("IREG tree edit: unexpected record loss or retention")
    result = bytes(output)
    reread = read_ireg_tree(result, context=context, superchunk=superchunk)
    if set(positions) != set(parents) or set(positions.values()) != set(reread.objects):
        raise ValueError("IREG tree edit: output object identity set changed")
    record_changes: list[dict[str, object]] = []
    flag_changes: list[dict[str, object]] = []
    for offset, location in positions.items():
        before, after = tree.objects[offset], reread.objects[location]
        if after.record.raw != nodes[offset].record.raw:
            raise ValueError(
                "IREG tree edit: serialized object bytes differ from the prepared record"
            )
        parent_id = parents[offset]
        expected_parent = positions[parent_id] if parent_id is not None else None
        expected_index = (
            moves[offset].index_word if offset in moves else before.saved_index_word
        )
        if (
            after.parent_offset != expected_parent
            or after.saved_index_word != expected_index
            or after.flags != expected_flags[offset]
        ):
            raise ValueError(
                "IREG tree edit: output ownership/index/flags validation failed"
            )
        if (after.shape, after.frame, after.kind) != (
            before.shape,
            before.frame,
            before.kind,
        ):
            raise ValueError("IREG tree edit: output changed shape/class/frame")
        expected_position = (
            (moves[offset].x, moves[offset].y, moves[offset].lift)
            if offset in moves
            else (before.x, before.y, before.lift)
        )
        if (after.x, after.y, after.lift) != expected_position:
            raise ValueError("IREG tree edit: output coordinates do not match the edit")
        if before.record.raw != after.record.raw:
            record_changes.append(
                {
                    "offset": offset,
                    "output_offset": location,
                    "before_hex": before.record.raw.hex(),
                    "after_hex": after.record.raw.hex(),
                }
            )
        if before.flags != after.flags:
            flag_changes.append(
                {
                    "offset": offset,
                    "before": int(before.flags),
                    "after": int(after.flags),
                }
            )
    new_records = {record.offset: record for record in reread.records}
    for old in tree.records:
        if old.offset not in wire_positions:
            continue
        location = wire_positions[old.offset]
        if old.offset not in tree.objects and new_records[location].raw != old.raw:
            raise ValueError(
                "IREG tree edit: changed an untouched control/special/opaque record"
            )
        if old.offset in tree.special_owners:
            owner = tree.special_owners[old.offset]
            if reread.special_owners.get(location, -1) != (
                positions[owner] if owner is not None else None
            ):
                raise ValueError(
                    "IREG tree edit: special ownership changed unexpectedly"
                )
    return U7IregTreeEditResult(
        result,
        source_hash,
        tree.context_sha256,
        tuple(changes),
        positions,
        tuple(record_changes),
        tuple(flag_changes),
    )


def read_ireg_save_member(
    data: bytes,
    member_path: tuple[int, ...],
    *,
    superchunk: int,
    expected_sha256: str | None = None,
) -> bytes:
    """Resolve an explicit standalone U7IREG member; reject actor data and mismatched superchunks."""
    if expected_sha256 is not None:
        check_u7_save_hash(expected_sha256, data, "source")
    if not isinstance(member_path, tuple) or not 1 <= len(member_path) <= 16:
        raise ValueError("IREG tree edit: save member path must contain 1..16 indices")
    raw = data
    for index in member_path:
        _integer(index, "member index", 0xFFFFFFFF)
        archive = read_u7_save_container(raw, strict=True)
        if index >= len(archive.members) or archive.members[index].is_directory:
            raise ValueError(
                "IREG tree edit: save member path is out of range or a directory"
            )
        member = archive.members[index]
        raw = member.data
    match = re.fullmatch(
        r"u7ireg([0-9a-f]{2})",
        member.name.replace("\\", "/").split("/")[-1],
        re.IGNORECASE,
    )
    if match is None or int(match[1], 16) != superchunk:
        raise ValueError(
            "IREG tree edit: save leaf must be a standalone U7IREG member matching superchunk"
        )
    return raw


def edit_ireg_save_member(
    data: bytes,
    member_path: tuple[int, ...],
    operations: Iterable[U7IregDelete | U7IregReparent | U7IregCreate | U7IregConvert],
    *,
    context: U7IregContext,
    superchunk: int,
    expected_save_sha256: str,
    expected_member_sha256: str,
    expected_context_sha256: str,
) -> U7IregSaveTreeResult:
    """Validate a structural IREG edit before embedding it in a guarded occurrence-preserving save."""
    raw = read_ireg_save_member(
        data, member_path, superchunk=superchunk, expected_sha256=expected_save_sha256
    )
    edited = edit_ireg_tree(
        raw,
        operations,
        context=context,
        superchunk=superchunk,
        expected_sha256=expected_member_sha256,
        expected_context_sha256=expected_context_sha256,
    )
    packed = repack_u7_save(
        data,
        [U7SaveReplacement(member_path, edited.data, expected_member_sha256)],
        expected_sha256=expected_save_sha256,
    )
    return U7IregSaveTreeResult(edited, packed)
