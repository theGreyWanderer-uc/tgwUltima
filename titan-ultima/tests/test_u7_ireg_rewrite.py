"""Guarded IREG writes preserve unknown bytes and reject stale/ambiguous operations."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest
from typer.testing import CliRunner

from titan.u7.cli import u7_app
from titan.u7.ireg import U7ObjectFlags, decode_ireg_payload
from titan.u7.ireg_metadata import U7IregContext
from titan.u7.ireg_rewrite import (
    U7IregEdit,
    read_ireg_edit_plan,
    read_ireg_wire_records,
    rewrite_ireg_stream,
)
from titan.u7.typeflag import U7TypeFlags


def object_wire(length: int = 6, prefix: int | None = None) -> bytes:
    payload = bytearray(range(1, length + 1))
    payload[2:4] = b"\x64\x00"
    if prefix == 254:
        payload.insert(4, 7)
    return (
        (bytes([prefix]) if prefix is not None else b"")
        + bytes([len(payload)])
        + payload
    )


def special_wire(kind: int, payload: bytes) -> bytes:
    return bytes([255, kind]) + struct.pack("<H", len(payload)) + payload


def context(shape_class: int, *, body: bool = False) -> U7IregContext:
    data = bytearray(3072)
    data[301] = shape_class
    return U7IregContext(
        U7TypeFlags.parse(bytes(data)),
        bodies={100: body},
        bodies_complete=True,
        jawbones_complete=True,
    )


def decoded(raw: bytes, metadata: U7IregContext | None = None):
    record = read_ireg_wire_records(raw)[0]
    return decode_ireg_payload(
        record.payload,
        entlen=len(record.payload),
        extended=record.extended_shape,
        extended_lift=record.extended_lift,
        context=metadata,
    )


def test_noop_preserves_every_byte_including_unknowns_and_controls() -> None:
    raw = (
        b"\0\x01\x02\x03\xab"
        + object_wire(12)
        + object_wire()
        + b"\x01"
        + special_wire(77, b"\xff\0\xfe\x80")
        + b"\xff\x02\x03abc\0\0"
        + object_wire(6, 254)
    )
    result = rewrite_ireg_stream(raw)
    assert result.data == raw and result.changes == ()
    records = read_ireg_wire_records(raw)
    assert b"".join(row.raw for row in records) == raw
    assert any(row.payload == b"abc" for row in records)
    assert rewrite_ireg_stream(b"").data == b""


@pytest.mark.parametrize("prefix", [None, 253, 254])
@pytest.mark.parametrize("length", [6, 10, 12, 13, 14, 18])
def test_frame_lift_edits_preserve_other_fields(
    length: int, prefix: int | None
) -> None:
    raw = object_wire(length, prefix)
    before = read_ireg_wire_records(raw)[0]
    lift = 239 if prefix else 13
    frame = 211 if prefix == 254 else 37
    result = rewrite_ireg_stream(raw, [U7IregEdit(0, {"frame": frame, "lift": lift})])
    after = read_ireg_wire_records(result.data)[0]
    value = decoded(result.data)
    assert value is not None and value.frame == frame and value.lift == lift
    assert (
        value.shape == 100
        and after.raw[: after.header_size] == before.raw[: before.header_size]
    )
    adj = int(prefix == 254)
    lift_offset = (4 if length in (6, 10) else 10 if length == 13 else 9) + adj
    changed = {4 if adj else 3, lift_offset}
    assert all(
        a == b
        for i, (a, b) in enumerate(zip(before.payload, after.payload))
        if i not in changed
    )
    if prefix is None:
        assert after.payload[lift_offset] & 15 == before.payload[lift_offset] & 15


@pytest.mark.parametrize("prefix", [None, 253, 254])
def test_quality_flags_and_quantity_bits_preserve_unrelated_bits(
    prefix: int | None,
) -> None:
    raw = object_wire(10, prefix)
    record = read_ireg_wire_records(raw)[0]
    quality_offset = 5 + int(prefix == 254)
    for shape_class, fields, mask in [
        (3, {"okay_to_take": True}, 128),
        (5, {"invisible": True, "okay_to_take": True}, 9),
    ]:
        result = rewrite_ireg_stream(
            raw, [U7IregEdit(0, fields)], context=context(shape_class)
        )
        value = decoded(result.data, context(shape_class))
        new = read_ireg_wire_records(result.data)[0].payload
        assert new[quality_offset] == record.payload[quality_offset] | mask
        assert value is not None and value.object_flags & U7ObjectFlags.OKAY_TO_TAKE
        cleared = rewrite_ireg_stream(
            result.data,
            [U7IregEdit(0, {key: False for key in fields})],
            context=context(shape_class),
        )
        assert (
            read_ireg_wire_records(cleared.data)[0].payload[quality_offset] & mask == 0
        )


@pytest.mark.parametrize("length", [12, 13, 14])
@pytest.mark.parametrize("prefix", [None, 254])
def test_body_flag_bytes_are_shifted_without_touching_npc_identity(
    length: int, prefix: int | None
) -> None:
    raw = object_wire(length, prefix)
    metadata = context(6, body=True)
    result = rewrite_ireg_stream(
        raw, [U7IregEdit(0, {"invisible": True})], context=metadata
    )
    a, b = (
        read_ireg_wire_records(raw)[0].payload,
        read_ireg_wire_records(result.data)[0].payload,
    )
    flag_offset = 11 + int(prefix == 254) + int(length == 13)
    assert b[flag_offset] == a[flag_offset] | 1
    assert all(x == y for i, (x, y) in enumerate(zip(a, b)) if i != flag_offset)


def test_temporary_and_raw_quality_edits_require_valid_class_layout() -> None:
    raw = object_wire(10)
    result = rewrite_ireg_stream(
        raw,
        [U7IregEdit(0, {"temporary": True, "quality_byte": 42})],
        context=context(2),
    )
    value = decoded(result.data, context(2))
    assert value is not None and value.quality == 42
    assert value.object_flags & U7ObjectFlags.TEMPORARY
    for metadata, wire in [(context(5), raw), (context(2), object_wire(6))]:
        with pytest.raises(ValueError, match="temporary"):
            rewrite_ireg_stream(
                wire, [U7IregEdit(0, {"temporary": True})], context=metadata
            )


def test_special_growth_and_later_edits_use_original_offsets() -> None:
    first, last = special_wire(4, b"old\0"), object_wire()
    raw = first + b"\xff\x02\x02\xff\xab" + last
    offset = len(raw) - len(last)
    result = rewrite_ireg_stream(
        raw,
        [
            U7IregEdit(
                0, special_payload=b"long\xfflocalized\0tail", expected_raw=first
            ),
            U7IregEdit(offset, {"frame": 33}, expected_raw=last),
        ],
    )
    expected_special = special_wire(4, b"long\xfflocalized\0tail")
    assert result.data.startswith(expected_special + b"\xff\x02\x02\xff\xab")
    assert result.changes[1]["output_offset"] == len(result.data) - len(last)
    assert decoded(result.data[-len(last) :]).frame == 33
    assert result.changes[1]["offset"] == offset


def test_index_word_and_opaque_special_replacement_do_not_reencode_text() -> None:
    raw = b"\x02\x03\xab" + special_wire(77, b"opaque\x80")
    result = rewrite_ireg_stream(
        raw,
        [U7IregEdit(0, index_word=0xCCFF), U7IregEdit(3, special_payload=b"\xff\xfe")],
    )
    assert result.data == b"\x02\xff\xcc" + special_wire(77, b"\xff\xfe")


@pytest.mark.parametrize(
    "wire",
    [
        object_wire(),
        b"\xfd\x06abcdef",
        b"\xfe\x07abcdefg",
        b"\x02\xff\0",
        b"\xff\x02",
        special_wire(4, b"a\0"),
    ],
)
def test_every_truncated_record_is_rejected(wire: bytes) -> None:
    for cut in range(1, len(wire)):
        with pytest.raises(ValueError, match="IREG rewrite:"):
            rewrite_ireg_stream(wire[:cut])


@pytest.mark.parametrize(
    "edit",
    [
        U7IregEdit(1, {"frame": 1}),
        U7IregEdit(0, {"frame": 64}),
        U7IregEdit(0, {"lift": 16}),
        U7IregEdit(0, {"shape": 3}),
        U7IregEdit(0, {"x_byte": -1}),
        U7IregEdit(0, {"y_byte": True}),
        U7IregEdit(0, {"quality_byte": 4}),
        U7IregEdit(0, {"invisible": True}),
        U7IregEdit(0, special_payload=b"abc"),
        U7IregEdit(0, index_word=1),
        U7IregEdit(0),
        U7IregEdit(0, {"frame": 1}, index_word=1),
        U7IregEdit(0, {"frame": 1}, expected_raw=b"stale"),
    ],
)
def test_invalid_or_ambiguous_edits_are_rejected(edit: U7IregEdit) -> None:
    raw = object_wire()
    with pytest.raises(ValueError, match="IREG rewrite:"):
        rewrite_ireg_stream(raw, [edit])
    assert raw == object_wire()


def test_conflicts_bad_specials_and_explicit_format_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        rewrite_ireg_stream(object_wire(), [U7IregEdit(0, {"frame": 1})] * 2)
    with pytest.raises(ValueError, match="SHA-256"):
        rewrite_ireg_stream(object_wire(), expected_sha256="0" * 64)
    with pytest.raises(ValueError, match="quality_byte"):
        rewrite_ireg_stream(
            object_wire(),
            [U7IregEdit(0, {"quality_byte": 1, "okay_to_take": True})],
            context=context(3),
        )
    for kind in (1, 3, 4):
        with pytest.raises(ValueError, match="known-type"):
            rewrite_ireg_stream(
                special_wire(kind, b""), [U7IregEdit(0, special_payload=b"bad")]
            )
    for raw in (b"\xff\x02", b"\x02\xff\0", object_wire(6, 254)):
        with pytest.raises(ValueError, match="retail"):
            rewrite_ireg_stream(raw, data_format="retail")
    assert (
        rewrite_ireg_stream(object_wire(), data_format="retail").data == object_wire()
    )


def plan_for(raw: bytes) -> dict[str, object]:
    return {
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "edits": [{"offset": 0, "expected_hex": raw.hex(), "fields": {"frame": 32}}],
    }


def test_retail_edits_do_not_assume_exult_flags_or_regroup_chunks() -> None:
    raw = object_wire()
    with pytest.raises(ValueError, match="Exult only"):
        rewrite_ireg_stream(raw, [U7IregEdit(0, {"okay_to_take": True})], data_format="retail", context=context(3))
    with pytest.raises(ValueError, match="high nibble"):
        rewrite_ireg_stream(raw, [U7IregEdit(0, {"x_byte": 32})], data_format="retail")
    result = rewrite_ireg_stream(raw, [U7IregEdit(0, {"x_byte": 15})], data_format="retail")
    assert result.data[1] == 15 and result.data[2:] == raw[2:]


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"source_sha256": "xx", "edits": []},
        {"source_sha256": "0" * 64, "edits": [{}]},
    ],
)
def test_plan_rejects_unknown_shape_or_missing_guards(bad: object) -> None:
    with pytest.raises(ValueError, match="IREG rewrite:"):
        read_ireg_edit_plan(bad)


def test_cli_writes_new_output_and_report_without_changing_source(
    tmp_path: Path,
) -> None:
    source, plan, output = (
        tmp_path / name for name in ("u7ireg55", "plan.json", "new/u7ireg55")
    )
    raw = object_wire()
    source.write_bytes(raw)
    plan.write_text(json.dumps(plan_for(raw)), encoding="utf-8")
    args = [
        "ireg-rewrite",
        str(source),
        "--format",
        "exult",
        "--edits",
        str(plan),
        "-o",
        str(output),
    ]
    result = CliRunner().invoke(u7_app, args)
    assert result.exit_code == 0, result.output
    assert source.read_bytes() == raw and decoded(output.read_bytes()).frame == 32
    report = json.loads(result.stdout)
    assert report["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert report["changes"][0]["before_hex"] == raw.hex()
    original_output = output.read_bytes()
    assert CliRunner().invoke(u7_app, args).exit_code == 1
    assert output.read_bytes() == original_output
    args[-1] = str(source)
    assert (
        CliRunner().invoke(u7_app, args).exit_code == 1 and source.read_bytes() == raw
    )


def test_cli_stale_plan_writes_nothing(tmp_path: Path) -> None:
    source, plan, output = (
        tmp_path / name for name in ("ireg", "plan.json", "out/ireg")
    )
    source.write_bytes(object_wire())
    plan.write_text(json.dumps(plan_for(object_wire(10))), encoding="utf-8")
    result = CliRunner().invoke(
        u7_app,
        [
            "ireg-rewrite",
            str(source),
            "--format",
            "exult",
            "--edits",
            str(plan),
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 1 and "SHA-256" in result.output
    assert not output.exists() and not output.parent.exists()
