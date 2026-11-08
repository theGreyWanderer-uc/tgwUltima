"""Creation, conversion and width promotion retain wire data and guarded object identities."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from titan.u7.cli import u7_app
from titan.u7.ireg_authoring import U7IregCreate, U7IregConvert, create_ireg_record
from titan.u7.ireg_tree import read_ireg_tree
from titan.u7.ireg_tree_edit import U7IregDelete, U7IregReparent, edit_ireg_tree
from titan.u7.ireg_metadata import U7IregContext
from titan.u7.typeflag import U7TypeFlags


def context() -> U7IregContext:
    raw = bytearray(4096 * 3)
    for shape, cls in (
        (100, 2),
        (101, 3),
        (102, 5),
        (200, 6),
        (201, 6),
        (275, 7),
        (300, 8),
        (400, 6),
        (1500, 2),
    ):
        raw[shape * 3 + 1] = cls
    tfa = U7TypeFlags.parse(bytes(raw[:3072]))
    entry = U7TypeFlags.parse(bytes([0, 2, 0])).entries[0]
    entry.shape_num = 1500
    tfa.entries.append(entry)
    tfa._by_num[1500] = entry
    return U7IregContext(
        tfa=tfa, bodies={400: True}, bodies_complete=True, jawbones_complete=True
    )


def tree(raw: bytes):
    return read_ireg_tree(raw, context=context(), superchunk=85)


def record(shape: int = 100, **kwargs):
    return create_ireg_record(shape, context=context(), **kwargs)


def edit(raw: bytes, operations):
    return edit_ireg_tree(
        raw,
        operations,
        context=context(),
        superchunk=85,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expected_context_sha256=tree(raw).context_sha256,
    )


def convert(raw: bytes, offset: int = 0, **kwargs):
    return U7IregConvert(
        offset, hashlib.sha256(tree(raw).owned_bytes(offset)).hexdigest(), **kwargs
    )


def create(name: str, shape: int = 100, parent: int | str | None = None, **kwargs):
    return U7IregCreate(
        name,
        record(shape),
        parent,
        None,
        300 if parent is None else 8,
        1800 if parent is None else 9,
        0,
        255,
        "inherit",
        **kwargs,
    )


@pytest.mark.parametrize(
    "shape,frame,lift,prefix",
    [(100, 0, 0, 10), (100, 0, 80, 253), (1500, 0, 0, 254), (100, 200, 0, 254)],
)
def test_canonical_creation_selects_width_without_truncation(
    shape: int, frame: int, lift: int, prefix: int
) -> None:
    raw = record(shape, frame=frame, lift=lift)
    parsed = tree(raw).objects[0]
    assert (parsed.shape, parsed.frame, parsed.lift) == (shape, frame, lift)
    assert raw[0] == prefix


def test_empty_world_creation_and_nested_forward_referenced_creation_ids() -> None:
    result = edit(
        b"",
        [
            create("item", parent="inner"),
            create("outer", 200),
            create("inner", 201, "outer"),
        ],
    )
    after = tree(result.data)
    assert set(result.created_offsets) == {"item", "inner", "outer"}
    assert (
        after.objects[result.created_offsets["item"]].parent_offset
        == result.created_offsets["inner"]
    )
    assert (
        after.objects[result.created_offsets["inner"]].parent_offset
        == result.created_offsets["outer"]
    )
    assert result.offset_map == {}


def test_create_preserves_existing_opaque_orphans_and_persistent_indices() -> None:
    raw = b"\xff\x4d\3\0old\2\3\xab" + record() + b"\3abc\0\0"
    result = edit(raw, [create("new")])
    assert result.data.startswith(raw)
    assert (
        tree(result.data).objects[result.created_offsets["new"]].saved_index_word == 255
    )
    assert result.offset_map[10] == 10


def test_conversion_preserves_unknown_simple_bytes_and_special_ownership() -> None:
    raw = bytearray(record())
    raw[8:] = b"\xa5\xb6\xc7"
    source = bytes(raw) + b"\xff\x4d\3\0old" + b"\3xyz"
    result = edit(source, [convert(source, shape=101, frame=3)])
    assert result.data[7:] == source[7:]
    assert tree(result.data).objects[0].shape == 101
    assert list(tree(result.data).special_owners.values()) == [0]


@pytest.mark.parametrize(
    "fmt,shape,frame,lift", [("fd", None, None, 200), ("fe", 1500, 240, 255)]
)
def test_promotion_retains_unknown_payload_and_updates_class_lift(
    fmt: str, shape: int | None, frame: int | None, lift: int
) -> None:
    raw = record()
    result = edit(
        raw, [convert(raw, record_format=fmt, shape=shape, frame=frame, lift=lift)]
    )
    after = tree(result.data).objects[0]
    assert after.lift == lift and after.record.raw[0] == (253 if fmt == "fd" else 254)
    assert after.record.payload[-5:] == raw[-5:]


def test_six_to_ten_and_body_npc_word_promotion_preserve_nonfield_bytes() -> None:
    raw = b"\6" + record()[1:7]
    result = edit(raw, [convert(raw, simple_length=10)])
    assert result.data == b"\x0a" + raw[1:] + bytes(4)
    body = bytearray(record(400))
    body[7] = 0xA5
    source = bytes(body)
    promoted = edit(source, [convert(source, body_npc=500)])
    assert tree(promoted.data).objects[0].kind == "body"
    assert promoted.data[9:11] == (500).to_bytes(2, "little")
    assert promoted.data[7] == 0xA5


def test_class_layout_conversion_requires_explicit_replacement_and_loss_consent() -> (
    None
):
    raw = record()
    with pytest.raises(ValueError):
        edit(raw, [convert(raw, shape=200)])
    with pytest.raises(ValueError, match="allow_data_loss"):
        edit(raw, [convert(raw, replacement_record=record(200))])
    result = edit(
        raw, [convert(raw, replacement_record=record(200), allow_data_loss=True)]
    )
    assert tree(result.data).objects[0].kind == "container"
    assert result.record_changes[0]["before_hex"] == raw.hex()


def test_promote_ignored_lift_bits_requires_explicit_loss_consent() -> None:
    source = bytearray(record())
    source[5] = 0x0F
    raw = bytes(source)
    with pytest.raises(ValueError, match="ignored lift bits"):
        edit(raw, [convert(raw, lift=80)])
    result = edit(raw, [convert(raw, lift=80, allow_data_loss=True)])
    assert tree(result.data).objects[0].lift == 80


def test_conversion_and_original_offset_move_can_share_a_transaction() -> None:
    raw = record() + record(200)
    parent = len(record())
    request = U7IregReparent(
        0,
        hashlib.sha256(tree(raw).owned_bytes(0)).hexdigest(),
        parent,
        hashlib.sha256(tree(raw).objects[parent].record.raw).hexdigest(),
        7,
        8,
        0,
        255,
        "inherit",
    )
    result = edit(raw, [convert(raw, shape=1500), request])
    assert (
        tree(result.data).objects[result.offset_map[0]].parent_offset
        == result.offset_map[parent]
    )
    assert tree(result.data).objects[result.offset_map[0]].shape == 1500
    moved = next(row for row in result.changes if row["action"] == "reparent")
    assert moved["offset"] == 0 and moved["new_parent"] == parent


def test_creation_cycle_unknown_parent_duplicate_id_and_deleted_receiver_fail() -> None:
    raw = record(200)
    for operations in (
        [create("x", 200, "y"), create("y", 200, "x")],
        [create("x", parent="missing")],
        [create("x"), create("x")],
    ):
        with pytest.raises(ValueError):
            edit(raw, operations)
    creation = replace(
        create("x", parent=0), parent_sha256=hashlib.sha256(raw).hexdigest()
    )
    with pytest.raises(ValueError):
        edit(raw, [creation, U7IregDelete(0, hashlib.sha256(raw).hexdigest())])


def test_body_word_promotion_from_twelve_bytes_and_container_conversion_with_contents() -> (
    None
):
    body13 = record(400)
    body12 = b"\x0c" + body13[1:10] + body13[11:]
    result = edit(body12, [convert(body12, body_npc=500)])
    assert tree(result.data).objects[0].record.payload[8:10] == (500).to_bytes(
        2, "little"
    )
    parent = bytearray(record(200))
    parent[5] = 1
    raw = bytes(parent) + record() + b"\1"
    with pytest.raises(ValueError, match="contents"):
        edit(raw, [convert(raw, replacement_record=record(), allow_data_loss=True)])
    converted = edit(
        raw, [convert(raw, replacement_record=record(400), allow_data_loss=True)]
    )
    after = tree(converted.data)
    assert after.objects[0].kind == "body"
    assert after.objects[converted.offset_map[len(parent)]].parent_offset == 0


@pytest.mark.parametrize("wide", ["fd", "fe"])
def test_replacement_class_layout_retains_source_width(wide: str) -> None:
    raw = record(record_format=wide)
    result = edit(
        raw, [convert(raw, replacement_record=record(200), allow_data_loss=True)]
    )
    assert result.data[0] == (253 if wide == "fd" else 254)
    with pytest.raises(ValueError, match="demotion"):
        edit(
            raw,
            [
                convert(
                    raw,
                    replacement_record=record(200),
                    allow_data_loss=True,
                    record_format="ordinary",
                )
            ],
        )


def test_fd_to_fe_preserves_reserved_payload_bytes_and_rejects_demotion() -> None:
    raw = record(lift=200)
    result = edit(raw, [convert(raw, shape=1500)])
    assert result.data.startswith(b"\xfe")
    assert tree(result.data).objects[0].lift == 200
    assert result.data[7:] == raw[6:]
    with pytest.raises(ValueError, match="demotion"):
        edit(
            result.data,
            [convert(result.data, shape=100, lift=0, record_format="ordinary")],
        )


@pytest.mark.parametrize("saved", [False, True])
def test_cli_creation_conversion_and_promotion_embed_or_write(
    tmp_path: Path, saved: bool
) -> None:
    runner = CliRunner()
    static = tmp_path / "STATIC"
    static.mkdir()
    metadata = context()
    assert metadata.tfa is not None
    (static / "TFA.DAT").write_bytes(
        b"".join(entry.tfa for entry in metadata.tfa.entries[:1024])
    )
    (static / "bodies.txt").write_text(
        "%%section version\n:2\n%%endsection\n%%section bodyshapes\n:400/1\n%%endsection\n"
    )
    (static / "shape_info.txt").write_text(
        "%%section version\n:7\n%%endsection\n%%section is_jawbone\n%%endsection\n"
    )
    raw = record() + b"\xff\x4d\3\0old\3abc"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("u7ireg55", raw)
        archive.writestr("empty", b"")
    source = tmp_path / "source.dat"
    source.write_bytes(stream.getvalue() if saved else raw)
    common = ["--static", str(static), "--custom-game"]
    inspect = runner.invoke(
        u7_app,
        [
            "ireg-tree",
            str(source),
            *common,
            "--superchunk",
            "85",
            *(["--member-path", "0"] if saved else []),
        ],
    )
    assert inspect.exit_code == 0, inspect.output
    view = json.loads(inspect.stdout)
    plan = {key: view[key] for key in ("source_sha256", "context_sha256", "superchunk")}
    plan["operations"] = [
        {
            "action": "promote",
            "offset": 0,
            "expected_sha256": view["objects"][0]["owned_sha256"],
            "shape": 101,
            "frame": 200,
        },
        {
            "action": "create",
            "object_id": "box",
            "record_hex": record(200).hex(),
            "parent_offset": None,
            "parent_sha256": None,
            "x": 300,
            "y": 1800,
            "lift": 0,
            "index_word": 255,
            "flag_policy": "inherit",
        },
        {
            "action": "create",
            "object_id": "item",
            "record_hex": record().hex(),
            "parent_offset": "box",
            "parent_sha256": None,
            "x": 8,
            "y": 9,
            "lift": 0,
            "index_word": 4,
            "flag_policy": "preserve",
        },
    ]
    if saved:
        plan["save"] = view["save"]
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan))
    destination = tmp_path / "new.dat"
    written = runner.invoke(
        u7_app,
        [
            "ireg-tree-edit",
            str(source),
            *common,
            "--plan",
            str(plan_file),
            "-o",
            str(destination),
        ],
    )
    assert written.exit_code == 0, written.output
    edited = destination.read_bytes()
    if saved:
        with zipfile.ZipFile(io.BytesIO(edited)) as archive:
            edited = archive.read("u7ireg55")
            assert archive.read("empty") == b""
    after = tree(edited)
    assert len(after.objects) == 3 and after.objects[0].frame == 200
    report = json.loads(written.stdout)
    changes = report["tree_edit"] if saved else report
    assert (
        after.objects[changes["created_offsets"]["item"]].parent_offset
        == changes["created_offsets"]["box"]
    )
    assert b"old\3abc" in edited
