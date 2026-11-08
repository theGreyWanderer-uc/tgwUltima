"""Structural IREG edits preserve ownership, opaque data, saved indices and flag policies."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import warnings
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest
from typer.testing import CliRunner

from titan.u7.cli import u7_app
from titan.u7.ireg_metadata import U7IregContext
from titan.u7.ireg_tree import read_ireg_tree
from titan.u7.ireg_tree_edit import (
    U7IregDelete,
    U7IregReparent,
    edit_ireg_tree,
    edit_ireg_save_member,
    read_ireg_save_member,
)
from titan.u7.ireg_tree_cli import read_ireg_tree_plan
from titan.u7.save import U7Save
from titan.u7.typeflag import U7TypeFlags


def metadata() -> U7IregContext:
    raw = bytearray(3072)
    for shape, kind in (
        (100, 2),
        (101, 3),
        (102, 5),
        (200, 6),
        (201, 6),
        (300, 8),
        (400, 6),
        (275, 7),
    ):
        raw[shape * 3 + 1] = kind
    return U7IregContext(
        U7TypeFlags.parse(bytes(raw)),
        bodies={400: True},
        bodies_complete=True,
        jawbones_complete=True,
    )


def obj(
    shape: int = 100, *, contents: bool = False, flags: int = 0, quality: int = 0
) -> bytes:
    length = 12 if shape in (200, 201, 400) else 18 if shape == 300 else 6
    raw = bytearray(length)
    raw[2], raw[3] = shape & 255, shape >> 8
    if length == 12:
        raw[4], raw[11] = int(contents), flags
    elif length == 6:
        raw[5] = quality
    return bytes([length]) + raw


def special(kind: int, payload: bytes) -> bytes:
    return bytes([255, kind]) + struct.pack("<H", len(payload)) + payload


def model(raw: bytes):
    return read_ireg_tree(raw, context=metadata(), superchunk=85)


def delete(raw: bytes, offset: int, cascade: bool = False):
    tree = model(raw)
    return U7IregDelete(
        offset, hashlib.sha256(tree.owned_bytes(offset)).hexdigest(), cascade
    )


def move(
    raw: bytes,
    offset: int,
    parent: int | None,
    *,
    policy: Literal["preserve", "inherit"] = "preserve",
    index: int = 255,
    x: int = 9,
    y: int = 11,
    lift: int = 0,
):
    tree = model(raw)
    return U7IregReparent(
        offset,
        hashlib.sha256(tree.owned_bytes(offset)).hexdigest(),
        parent,
        hashlib.sha256(tree.objects[parent].record.raw).hexdigest()
        if parent is not None
        else None,
        x,
        y,
        lift,
        index,
        policy,
    )


def edit(raw: bytes, operations):
    tree = model(raw)
    return edit_ireg_tree(
        raw,
        operations,
        context=metadata(),
        superchunk=85,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expected_context_sha256=tree.context_sha256,
    )


def test_lossless_tree_retains_padding_opaque_records_and_noncontiguous_special_owners() -> (
    None
):
    child = obj(101)
    raw = (
        special(77, b"orphan")
        + b"\2\3\xab"
        + obj(200, contents=True)
        + child
        + special(4, b"child\0")
        + b"\1\0\0"
        + b"\3abc"
        + special(77, b"parent\xff")
        + obj()
    )
    tree = model(raw)
    assert tree.to_bytes() == raw and edit(raw, []).data == raw
    parent = next(node for node in tree.objects.values() if node.shape == 200)
    descendant = next(node for node in tree.objects.values() if node.shape == 101)
    assert (
        descendant.parent_offset == parent.offset
        and descendant.saved_index_word is None
    )
    assert parent.saved_index_word == 0xAB03
    assert len(tree.opaque_offsets) == 1
    assert list(tree.special_owners.values()) == [
        None,
        descendant.offset,
        parent.offset,
    ]


def test_delete_removes_owned_specials_but_keeps_opaque_records_and_persistent_index() -> (
    None
):
    first = obj()
    opaque = b"\3xyz"
    raw = b"\2\3\xab" + first + opaque + special(77, b"owned") + obj(101) + b"\0\0"
    result = edit(raw, [delete(raw, 3)])
    after = model(result.data)
    assert result.data == b"\2\3\xab" + opaque + obj(101) + b"\0\0"
    assert next(iter(after.objects.values())).saved_index_word == 0xAB03


def test_cascade_is_required_and_removes_only_the_selected_subtree() -> None:
    raw = (
        obj(200, contents=True)
        + obj()
        + special(4, b"child\0")
        + b"\1"
        + special(77, b"container")
        + obj(201)
    )
    with pytest.raises(ValueError, match="cascade"):
        edit(raw, [delete(raw, 0)])
    result = edit(raw, [delete(raw, 0, True)])
    assert result.data == obj(201)
    assert len(result.offset_map) == 1


def test_reparent_opens_empty_destination_and_keeps_source_empty_list_and_unknown_data() -> (
    None
):
    raw = (
        obj(200, contents=True)
        + obj()
        + special(77, b"move me")
        + b"\3xyz\1"
        + obj(201)
        + special(4, b"destination\0")
        + b"\0\0"
    )
    tree = model(raw)
    child = next(node for node in tree.objects.values() if node.shape == 100)
    destination = next(node for node in tree.objects.values() if node.shape == 201)
    result = edit(raw, [move(raw, child.offset, destination.offset, index=0xABFF)])
    after = model(result.data)
    moved = after.objects[result.offset_map[child.offset]]
    assert moved.parent_offset == result.offset_map[destination.offset]
    assert (moved.x, moved.y, moved.lift, moved.saved_index_word) == (9, 11, 0, 0xABFF)
    assert (
        b"\3xyz" in result.data
        and b"move me" in result.data
        and b"destination\0" in result.data
    )
    assert all(
        owner in after.objects
        for owner in after.special_owners.values()
        if owner is not None
    )
    assert after.objects[result.offset_map[0]].children is not None


def test_preserve_inherited_flags_fails_if_no_stored_bit_but_inherit_is_explicit() -> (
    None
):
    raw = obj(200, contents=True, flags=8) + obj() + b"\1" + obj(201)
    tree = model(raw)
    child = next(node for node in tree.objects.values() if node.shape == 100)
    parent = next(node for node in tree.objects.values() if node.shape == 201)
    with pytest.raises(ValueError, match="cannot be encoded"):
        edit(raw, [move(raw, child.offset, parent.offset)])
    result = edit(raw, [move(raw, child.offset, parent.offset, policy="inherit")])
    assert result.flag_changes == ({"offset": child.offset, "before": 2, "after": 0},)


def test_moving_container_preserves_descendant_flags_and_saved_requests() -> None:
    raw = obj(200, contents=True, flags=8) + b"\2\3\0" + obj() + b"\1" + obj(201)
    tree = model(raw)
    parent = next(node for node in tree.objects.values() if node.shape == 201)
    child = next(node for node in tree.objects.values() if node.shape == 100)
    result = edit(raw, [move(raw, 0, parent.offset)])
    after = model(result.data)
    assert after.objects[result.offset_map[child.offset]].saved_index_word == 3
    assert result.flag_changes == ()


def test_container_to_world_requires_same_superchunk_and_world_coordinates() -> None:
    raw = obj(200, contents=True) + obj(101) + b"\1\0\0"
    offset = len(obj(200, contents=True))
    result = edit(raw, [move(raw, offset, None, x=300, y=1800, lift=4)])
    moved = model(result.data).objects[result.offset_map[offset]]
    assert moved.parent_offset is None and (moved.x, moved.y, moved.lift) == (
        300,
        1800,
        4,
    )
    with pytest.raises(ValueError, match="cross-superchunk"):
        edit(raw, [move(raw, offset, None, x=0, y=0)])


def test_cycles_and_overlapping_sources_are_rejected() -> None:
    raw = obj(200) + obj(201)
    second = len(obj(200))
    with pytest.raises(ValueError, match="cycle"):
        edit(raw, [move(raw, 0, second), move(raw, second, 0)])
    with pytest.raises(ValueError, match="cycle"):
        edit(raw, [move(raw, 0, 0)])
    nested = obj(200, contents=True) + obj(201) + b"\1"
    with pytest.raises(ValueError, match="overlap"):
        edit(nested, [delete(nested, 0, True), delete(nested, len(obj(200)))])


@pytest.mark.parametrize(
    "raw", [obj(200, contents=True), obj() + b"\xff\2", b"\xfd", b"\6abc"]
)
def test_malformed_or_actor_only_streams_are_rejected(raw: bytes) -> None:
    with pytest.raises(ValueError):
        model(raw)


def test_class_context_and_source_hash_are_guarded() -> None:
    raw = obj()
    with pytest.raises(ValueError, match="source"):
        edit_ireg_tree(
            raw,
            [],
            context=metadata(),
            superchunk=85,
            expected_sha256="0" * 64,
            expected_context_sha256=model(raw).context_sha256,
        )
    changed = metadata()
    assert changed.tfa is not None
    changed.tfa.entries[100].shape_class = 3
    with pytest.raises(ValueError, match="context"):
        edit_ireg_tree(
            raw,
            [],
            context=changed,
            superchunk=85,
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            expected_context_sha256=model(raw).context_sha256,
        )
    with pytest.raises(ValueError, match="TFA"):
        read_ireg_tree(raw, context=U7IregContext(), superchunk=85)


def test_batch_moves_keep_original_sibling_indices_and_owned_specials() -> None:
    raw = (
        obj(200, contents=True)
        + b"\2\3\0"
        + obj(101)
        + b"\1"
        + obj(100)
        + special(77, b"first")
        + obj(102)
        + special(77, b"second")
    )
    before = model(raw)
    first, second = [
        node.offset for node in before.objects.values() if node.shape in (100, 102)
    ]
    sibling = next(node.offset for node in before.objects.values() if node.shape == 101)
    result = edit(
        raw, [move(raw, first, 0, index=4), move(raw, second, 0, index=0xABFF)]
    )
    after = model(result.data)
    assert after.objects[result.offset_map[sibling]].saved_index_word == 3
    assert after.objects[result.offset_map[first]].saved_index_word == 4
    assert after.objects[result.offset_map[second]].saved_index_word == 0xABFF
    assert list(after.special_owners.values()) == [
        result.offset_map[first],
        result.offset_map[second],
    ]


@pytest.mark.parametrize("reverse", [False, True])
def test_move_into_a_destination_that_is_itself_moved(reverse: bool) -> None:
    raw = obj(100) + obj(200) + obj(201)
    parent, grandparent = len(obj()), len(obj()) + len(obj(200))
    operations = [move(raw, 0, parent), move(raw, parent, grandparent)]
    result = edit(raw, reversed(operations) if reverse else operations)
    after = model(result.data)
    assert (
        after.objects[result.offset_map[0]].parent_offset == result.offset_map[parent]
    )
    assert (
        after.objects[result.offset_map[parent]].parent_offset
        == result.offset_map[grandparent]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("index_word", 18),
        ("index_word", 254),
        ("x", True),
        ("lift", 16),
        ("parent_sha256", "0" * 64),
        ("expected_sha256", "0" * 64),
    ],
)
def test_invalid_move_or_stale_identity_is_rejected(field: str, value: object) -> None:
    raw = obj() + obj(200)
    operation = move(raw, 0, len(obj()))
    with pytest.raises(ValueError):
        edit(raw, [replace(operation, **{field: value})])


def test_deleted_destination_duplicate_source_and_unsupported_receiver_are_rejected() -> (
    None
):
    raw = obj() + obj(200) + obj(101)
    destination = len(obj())
    for operations in (
        [move(raw, 0, destination), delete(raw, destination)],
        [delete(raw, 0), delete(raw, 0)],
        [move(raw, 0, destination + len(obj(200)))],
    ):
        with pytest.raises(ValueError):
            edit(raw, operations)


@pytest.mark.parametrize("extended", [False, True])
def test_body_destination_preserves_reserved_fields_and_extended_identity(
    extended: bool,
) -> None:
    payload = bytearray(obj(400)[1:])
    payload.insert(9, 0xAB)
    if extended:
        payload.insert(4, 0)
    body = (b"\xfe" if extended else b"") + bytes([len(payload)]) + payload
    raw = obj(101) + body
    destination = len(obj(101))
    result = edit(raw, [move(raw, 0, destination)])
    after = model(result.data)
    parent = after.objects[result.offset_map[destination]]
    assert parent.kind == "body" and parent.children is not None
    expected = bytearray(body)
    start = parent.record.header_size + 4 + int(extended)
    expected[start : start + 2] = b"\1\0"
    assert parent.record.raw == bytes(expected)


def test_depth_bound_and_opaque_only_cascade() -> None:
    raw = obj(200, contents=True) * 128 + obj() + b"\1" * 128
    assert len(model(raw).objects) == 129
    with pytest.raises(ValueError, match="nesting"):
        model(obj(200, contents=True) + raw + b"\1")
    opaque = obj(200, contents=True) + b"\3abc\1"
    with pytest.raises(ValueError, match="cascade"):
        edit(opaque, [delete(opaque, 0)])
    assert edit(opaque, [delete(opaque, 0, True)]).data == b""


def saved(raw: bytes, kind: str = "zip", name: str = "u7ireg55") -> bytes:
    if kind == "flex":
        entries = [(name, raw), ("empty", b""), (name, b"untouched")]
        header = bytearray(128 + 8 * len(entries))
        struct.pack_into("<II", header, 80, 0xFFFF1A00, len(entries))
        body = bytearray()
        for index, (member_name, payload) in enumerate(entries):
            blob = member_name.encode().ljust(13, b"\0") + payload
            struct.pack_into(
                "<II", header, 128 + 8 * index, len(header) + len(body), len(blob)
            )
            body.extend(blob)
        return bytes(header + body)
    stream = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if kind == "grouped":
                group = b"".join(
                    n.encode().ljust(12, b"\0") + struct.pack("<I", len(p)) + p
                    for n, p in [(name, raw), ("empty", b""), (name, b"untouched")]
                ) + bytes(12)
                archive.writestr("GAMEDAT", group)
            elif kind == "nested":
                archive.writestr("nested.sav", saved(raw, "flex", name))
            else:
                archive.writestr(name, raw)
                archive.writestr("empty", b"")
                archive.writestr(name, b"untouched")
    return stream.getvalue()


@pytest.mark.parametrize(
    "kind,path", [("zip", (0,)), ("flex", (0,)), ("grouped", (0,)), ("nested", (0, 0))]
)
def test_validated_tree_is_embedded_in_the_exact_save_occurrence(
    kind: str, path: tuple[int, ...]
) -> None:
    raw = obj() + obj(200)
    archive = saved(raw, kind)
    result = edit_ireg_save_member(
        archive,
        path,
        [delete(raw, 0)],
        context=metadata(),
        superchunk=85,
        expected_save_sha256=hashlib.sha256(archive).hexdigest(),
        expected_member_sha256=hashlib.sha256(raw).hexdigest(),
        expected_context_sha256=model(raw).context_sha256,
    )
    assert read_ireg_save_member(result.data, path, superchunk=85) == obj(200)
    before, after = (
        U7Save.from_bytes(archive, strict=True),
        U7Save.from_bytes(result.data, strict=True),
    )
    assert [(m.name, m.data) for m in before.members[1:]] == [
        (m.name, m.data) for m in after.members[1:]
    ]
    assert archive == saved(raw, kind)


@pytest.mark.parametrize("name", ["NPC.DAT", "u7ireg54"])
def test_save_world_selection_rejects_actor_members_and_wrong_superchunks(
    name: str,
) -> None:
    with pytest.raises(ValueError):
        read_ireg_save_member(saved(obj(), name=name), (0,), superchunk=85)


def cli_static(tmp_path: Path) -> Path:
    static = tmp_path / "STATIC"
    static.mkdir()
    context = metadata()
    assert context.tfa is not None
    (static / "TFA.DAT").write_bytes(
        b"".join(entry.tfa for entry in context.tfa.entries)
    )
    (static / "bodies.txt").write_text(
        "%%section version\n:2\n%%endsection\n%%section bodyshapes\n:400/1\n%%endsection\n"
    )
    (static / "shape_info.txt").write_text(
        "%%section version\n:7\n%%endsection\n%%section is_jawbone\n%%endsection\n"
    )
    return static


@pytest.mark.parametrize("archive", [False, True])
@pytest.mark.parametrize("action", ["delete", "reparent"])
def test_cli_inspection_plan_dry_run_and_new_file_write(
    tmp_path: Path, archive: bool, action: str
) -> None:
    runner = CliRunner()
    static = cli_static(tmp_path)
    raw = obj() + obj(200)
    source = tmp_path / "source.dat"
    original = saved(raw) if archive else raw
    source.write_bytes(original)
    common = ["--static", str(static), "--custom-game"]
    inspection = runner.invoke(
        u7_app,
        [
            "ireg-tree",
            str(source),
            *common,
            "--superchunk",
            "85",
            *(["--member-path", "0"] if archive else []),
        ],
    )
    assert inspection.exit_code == 0, inspection.output
    report = json.loads(inspection.stdout)
    operation = {
        "action": "delete",
        "offset": 0,
        "expected_sha256": report["objects"][0]["owned_sha256"],
        "cascade": False,
    }
    if action == "reparent":
        operation = {
            "action": "reparent",
            "offset": 0,
            "expected_sha256": report["objects"][0]["owned_sha256"],
            "parent_offset": report["objects"][1]["offset"],
            "parent_sha256": report["objects"][1]["record_sha256"],
            "x": 8,
            "y": 9,
            "lift": 0,
            "index_word": 255,
            "flag_policy": "preserve",
        }
    plan = {
        key: report[key] for key in ("source_sha256", "context_sha256", "superchunk")
    }
    plan["operations"] = [operation]
    if archive:
        plan["save"] = report["save"]
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))
    output = tmp_path / "edited.dat"
    arguments = [
        "ireg-tree-edit",
        str(source),
        "--plan",
        str(plan_path),
        *common,
        "-o",
        str(output),
    ]
    preview = runner.invoke(u7_app, [*arguments, "--dry-run"])
    assert preview.exit_code == 0, preview.output
    assert not output.exists()
    write = runner.invoke(u7_app, arguments)
    assert write.exit_code == 0, write.output
    edited = (
        read_ireg_save_member(output.read_bytes(), (0,), superchunk=85)
        if archive
        else output.read_bytes()
    )
    if action == "delete":
        assert edited == obj(200)
    else:
        after = model(edited)
        moved = next(node for node in after.objects.values() if node.shape == 100)
        assert moved.parent_offset == 0 and (
            moved.x,
            moved.y,
            moved.saved_index_word,
        ) == (8, 9, 255)
    assert runner.invoke(u7_app, arguments).exit_code == 1
    assert source.read_bytes() == original
    output.unlink()
    plan["source_sha256"] = "0" * 64
    plan_path.write_text(json.dumps(plan))
    assert runner.invoke(u7_app, arguments).exit_code == 1
    assert not output.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("superchunk", True),
        ("source_sha256", "bad"),
        ("operations", [{}]),
        ("save", {"source_sha256": "0" * 64, "member_path": []}),
        ("unknown", 0),
    ],
)
def test_plan_rejects_ambiguous_or_incomplete_fields(field: str, value: object) -> None:
    plan: dict[str, object] = {
        "source_sha256": "0" * 64,
        "context_sha256": "0" * 64,
        "superchunk": 85,
        "operations": [],
    }
    plan[field] = value
    with pytest.raises(ValueError):
        read_ireg_tree_plan(plan)
