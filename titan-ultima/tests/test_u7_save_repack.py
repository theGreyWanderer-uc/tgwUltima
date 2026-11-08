"""Lossless save repacking preserves physical metadata and guards exact occurrences."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import warnings
import zipfile
import zlib
from collections.abc import Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner

from titan.u7.cli import u7_app
from titan.u7.save import U7Save
from titan.u7.save_repack import U7SaveReplacement, repack_u7_save
from titan.u7.ireg_rewrite import U7IregEdit, rewrite_ireg_stream


def _flex_save(entries: Sequence[tuple[str, bytes] | None]) -> bytes:
    header = bytearray(128 + 8 * len(entries))
    header[:80] = b"\x80Native title".ljust(80, b"\0")
    header[88:128] = bytes(range(40))
    struct.pack_into("<II", header, 80, 0xFFFF1A00, len(entries))
    body = bytearray(b"before\xff")
    for index, entry in enumerate(entries):
        if entry is None:
            struct.pack_into("<II", header, 128 + 8 * index, 0xABCD, 0)
            continue
        name, payload = entry
        raw_name = name.encode("latin-1").ljust(13, b"\0")
        blob = raw_name + payload
        struct.pack_into(
            "<II", header, 128 + 8 * index, len(header) + len(body), len(blob)
        )
        body.extend(blob + b"gap\xfe")
    return bytes(header + body + b"trailer\xfd")


def _level2_group(entries: list[tuple[str, bytes]], tail: bytes = bytes(12)) -> bytes:
    return (
        b"".join(
            name.encode("latin-1").ljust(12, b"\0")
            + struct.pack("<I", len(payload))
            + payload
            for name, payload in entries
        )
        + tail
    )


class _NonSeekableZip(io.BytesIO):
    def seek(self, *args: object, **kwargs: object) -> int:
        raise OSError("nonseekable output")


def _zip_save(
    entries: list[tuple[str, bytes]],
    *,
    method: int = zipfile.ZIP_DEFLATED,
    prefix: bool = False,
    absolute_offsets: bool = False,
    descriptor: bool = False,
) -> bytes:
    stream = _NonSeekableZip() if descriptor else io.BytesIO()
    title = b"\x80Title".ljust(80, b"\0") if prefix else b""
    if absolute_offsets:
        stream.write(title)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(stream, "w") as archive:
            archive.comment = b"global\0comment\xff"
            for name, payload in entries:
                info = zipfile.ZipInfo(name, (2003, 4, 5, 6, 7, 8))
                info.compress_type = method
                info.create_system = 3
                info.external_attr = 0o100640 << 16
                info.internal_attr = 1
                info.extra = struct.pack("<HH", 0xCAFE, 5) + b"\x80meta"
                info.comment = b"entry\xff"
                archive.writestr(info, payload)
    raw = stream.getvalue()
    return raw if absolute_offsets else title + raw


def _zip_parts(raw: bytes):
    start = 0 if raw.startswith(b"PK") else 80
    with zipfile.ZipFile(io.BytesIO(raw[start:])) as archive:
        infos = archive.infolist()
        central_start = archive.start_dir + start
        comment = archive.comment
    offsets = sorted(
        (info.header_offset + start, index) for index, info in enumerate(infos)
    )
    local = {}
    for position, (offset, index) in enumerate(offsets):
        end = offsets[position + 1][0] if position + 1 < len(offsets) else central_start
        local[index] = raw[offset:end]
    central = []
    pos = central_start
    for info in infos:
        name, extra, note = struct.unpack_from("<3H", raw, pos + 28)
        length = 46 + name + extra + note
        central.append(raw[pos : pos + length])
        pos += length
    return infos, local, central, central_start, comment


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize(
    "prefix,absolute", [(False, False), (True, False), (True, True)]
)
@pytest.mark.parametrize("descriptor", [False, True])
def test_zip_noop_and_replacement_preserve_raw_unedited_entries(
    method: int, prefix: bool, absolute: bool, descriptor: bool
) -> None:
    raw = _zip_save(
        [
            ("NPC.DAT", b"one" * 30),
            ("NPC.DAT", b"two" * 20),
            ("empty", b""),
            ("folder/", b""),
        ],
        method=method,
        prefix=prefix,
        absolute_offsets=absolute,
        descriptor=descriptor,
    )
    assert repack_u7_save(raw).data == raw
    assert repack_u7_save(raw, [U7SaveReplacement((1,), b"two" * 20)]).data == raw
    result = repack_u7_save(
        raw,
        [
            U7SaveReplacement((1,), b"replacement" * 100),
            U7SaveReplacement((2,), b"now filled"),
        ],
    )
    save = U7Save.from_bytes(result.data, strict=True)
    assert [row.name for row in save.members] == [
        "NPC.DAT",
        "NPC.DAT",
        "empty",
        "folder/",
    ]
    assert [row.data for row in save.members] == [
        b"one" * 30,
        b"replacement" * 100,
        b"now filled",
        b"",
    ]
    a, a_local, a_central, _, comment = _zip_parts(raw)
    b, b_local, b_central, _, new_comment = _zip_parts(result.data)
    assert comment == new_comment
    assert a_local[0] == b_local[0] and a_local[3] == b_local[3]
    if prefix:
        assert raw[:80] == result.data[:80]
    for index, (old, new) in enumerate(zip(a_central, b_central)):
        old_masked, new_masked = bytearray(old), bytearray(new)
        old_masked[42:46] = new_masked[42:46] = bytes(4)
        if index in (1, 2):
            old_masked[16:28] = new_masked[16:28] = bytes(12)
        assert old_masked == new_masked
        assert a[index].flag_bits == b[index].flag_bits


def test_flex_preserves_sparse_slots_raw_names_gaps_header_and_trailer() -> None:
    raw = _flex_save([("NPC.DAT.", b"one"), None, ("NPC.DAT.", b"two"), ("empty", b"")])
    assert repack_u7_save(raw).data == raw
    result = repack_u7_save(
        raw,
        [U7SaveReplacement((1,), b"longer replacement"), U7SaveReplacement((2,), b"")],
    )
    before, after = (
        U7Save.from_bytes(raw, strict=True),
        U7Save.from_bytes(result.data, strict=True),
    )
    assert [row.data for row in after.members] == [b"one", b"longer replacement", b""]
    assert [row.name_raw for row in before.members] == [
        row.name_raw for row in after.members
    ]
    assert raw[:128] == result.data[:128]
    assert raw[136:144] == result.data[136:144]  # unusual sparse offset stays unchanged
    assert raw.count(b"gap\xfe") == result.data.count(b"gap\xfe") == 3
    assert result.data.endswith(b"trailer\xfd")


def test_flex_named_empty_members_can_grow_and_nonempty_members_can_become_empty() -> (
    None
):
    raw = _flex_save([("one", b"old"), None, ("empty", b"")])
    result = repack_u7_save(
        raw, [U7SaveReplacement((0,), b""), U7SaveReplacement((1,), b"filled")]
    )
    parsed = U7Save.from_bytes(result.data, strict=True)
    assert [(row.name, row.data) for row in parsed.members] == [
        ("one", b""),
        ("empty", b"filled"),
    ]
    assert parsed.flex_directory[0][1] == 13 and parsed.flex_directory[1][1] == 0


def test_zip_unknown_trailing_bytes_survive_repacking() -> None:
    raw = _zip_save([("file", b"old")], prefix=True) + b"opaque archive tail\xff"
    result = repack_u7_save(raw, [U7SaveReplacement((0,), b"new and longer")])
    assert result.data.endswith(b"opaque archive tail\xff")
    assert (
        U7Save.from_bytes(result.data, strict=True).members[0].data == b"new and longer"
    )


def test_empty_archives_round_trip_without_creating_members() -> None:
    for raw in (_flex_save([]), _zip_save([]), _zip_save([], prefix=True)):
        assert repack_u7_save(raw).data == raw
        with pytest.raises(ValueError, match="out of range"):
            repack_u7_save(raw, [U7SaveReplacement((0,), b"new")])


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_grouped_occurrences_preserve_terminator_tail_duplicate_order_and_maps(
    method: int,
) -> None:
    tail = b"\0" + b"\xff" * 11 + b"opaque tail"
    one = _level2_group([("NPC.DAT", b"first"), ("empty", b"")], tail)
    two = _level2_group([("NPC.DAT", b"second"), ("empty", b"")], bytes(16))
    world = _level2_group([("u7ireg00", b"map")])
    raw = _zip_save(
        [("GAMEDAT", one), ("GAMEDAT", two), ("MAP0A", world)],
        method=method,
        prefix=True,
    )
    result = repack_u7_save(
        raw,
        [U7SaveReplacement((0,), b"new first"), U7SaveReplacement((4,), b"new map")],
    )
    assert [
        row.data for row in U7Save.from_bytes(result.data, strict=True).members
    ] == [b"new first", b"", b"second", b"", b"new map"]
    _, old_local, _, _, _ = _zip_parts(raw)
    _, new_local, _, _, _ = _zip_parts(result.data)
    assert old_local[1] == new_local[1]
    with zipfile.ZipFile(io.BytesIO(result.data[80:])) as archive:
        assert archive.read(archive.infolist()[0]).endswith(tail)


@pytest.mark.parametrize("outer_zip", [False, True])
def test_nested_flex_map_paths_replace_one_occurrence_without_flattening(
    outer_zip: bool,
) -> None:
    nested = _flex_save([("u7ireg00", b"first"), None, ("u7ireg00", b"second")])
    raw = (
        _zip_save(
            [("GAMEDAT", _level2_group([("map01", nested)])), ("unknown", b"keep")]
        )
        if outer_zip
        else _flex_save([("map01", nested), ("unknown", b"keep")])
    )
    result = repack_u7_save(
        raw,
        [U7SaveReplacement((0, 1), b"edited", hashlib.sha256(b"second").hexdigest())],
    )
    outer = U7Save.from_bytes(result.data, strict=True)
    inner = U7Save.from_bytes(outer.members[0].data, strict=True)
    assert [member.data for member in inner.members] == [b"first", b"edited"]
    assert outer.members[1].data == b"keep" and inner.flex_directory[1][1] == 0
    assert result.changes[0]["member_path"] == [0, 1]


def test_central_order_can_differ_from_physical_local_order() -> None:
    raw = _zip_save([("one", b"1"), ("two", b"2"), ("three", b"3")])
    _, _, central, start, _ = _zip_parts(raw)
    shuffled = (
        raw[:start]
        + b"".join(reversed(central))
        + raw[start + sum(map(len, central)) :]
    )
    result = repack_u7_save(shuffled, [U7SaveReplacement((0,), b"THREE")])
    assert [
        (row.name, row.data)
        for row in U7Save.from_bytes(result.data, strict=True).members
    ] == [("three", b"THREE"), ("two", b"2"), ("one", b"1")]
    _, before, _, _, _ = _zip_parts(shuffled)
    _, after, _, _, _ = _zip_parts(result.data)
    assert before[2] == after[2] and before[1] == after[1]


def test_unsigned_zip_data_descriptor_is_preserved() -> None:
    payload, name = b"original" * 10, b"npc.dat"
    compressed = zlib.compress(payload)[2:-4]
    crc = zlib.crc32(payload)
    local = (
        struct.pack("<4s5H3I2H", b"PK\x03\x04", 20, 8, 8, 0, 0, 0, 0, 0, len(name), 0)
        + name
        + compressed
        + struct.pack("<3I", crc, len(compressed), len(payload))
    )
    central = bytearray(46)
    central[:4] = b"PK\x01\x02"
    struct.pack_into("<4H", central, 4, 20, 20, 8, 8)
    struct.pack_into("<3I", central, 16, crc, len(compressed), len(payload))
    struct.pack_into("<H", central, 28, len(name))
    directory = bytes(central) + name
    raw = (
        local
        + directory
        + struct.pack(
            "<4s4H2IH", b"PK\x05\x06", 0, 0, 1, 1, len(directory), len(local), 0
        )
    )
    result = repack_u7_save(raw, [U7SaveReplacement((0,), b"new")])
    assert U7Save.from_bytes(result.data, strict=True).members[0].data == b"new"
    assert b"PK\x07\x08" not in result.data


def test_zip64_is_preserved_on_noop_and_rejected_before_mutation() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        with archive.open("npc.dat", "w", force_zip64=True) as target:
            target.write(b"original")
    raw = stream.getvalue()
    assert repack_u7_save(raw).data == raw
    with pytest.raises(ValueError, match="ZIP64"):
        repack_u7_save(raw, [U7SaveReplacement((0,), b"new")])


def test_invalid_source_or_aliased_flex_is_not_silently_repaired() -> None:
    raw = _flex_save([("one", b"1"), ("two", b"2")])
    truncated = raw[:-20]
    with pytest.raises(ValueError):
        repack_u7_save(truncated)
    aliased = bytearray(raw)
    aliased[136:144] = aliased[128:136]
    with pytest.raises(ValueError, match="overlapping/aliased"):
        repack_u7_save(bytes(aliased), [U7SaveReplacement((0,), b"new")])


@pytest.mark.parametrize("paths", [(), (-1,), (True,), (0,) * 17, (99,), (0, 0)])
def test_invalid_or_noncontainer_member_path_is_rejected(
    paths: tuple[int, ...],
) -> None:
    with pytest.raises(ValueError):
        repack_u7_save(
            _flex_save([("file", b"not a container")]),
            [U7SaveReplacement(paths, b"new")],
        )


def test_hash_guards_and_overlapping_paths_reject_stale_plans() -> None:
    raw = _flex_save([("file", b"old")])
    with pytest.raises(ValueError, match="source.*SHA-256"):
        repack_u7_save(raw, expected_sha256="0" * 64)
    with pytest.raises(ValueError, match="member.*SHA-256"):
        repack_u7_save(raw, [U7SaveReplacement((0,), b"new", "0" * 64)])
    for paths in [((0,), (0,)), ((0,), (0, 1)), ((0, 1), (0,))]:
        with pytest.raises(ValueError, match="overlapping"):
            repack_u7_save(raw, [U7SaveReplacement(path, b"new") for path in paths])
    with pytest.raises(ValueError, match="directory"):
        repack_u7_save(_zip_save([("folder/", b"")]), [U7SaveReplacement((0,), b"new")])


def _write_repack_plan(path: Path, raw: bytes, *, expected: bytes = b"old") -> None:
    path.write_text(
        json.dumps(
            {
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "replacements": [
                    {
                        "member_path": [0],
                        "expected_sha256": hashlib.sha256(expected).hexdigest(),
                        "file": "new.bin",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_cli_list_json_dry_run_and_new_output_preserve_source(tmp_path: Path) -> None:
    source, plan, output = (
        tmp_path / name for name in ("save.sav", "plan.json", "out/new.sav")
    )
    raw = _flex_save([("u7ireg00", b"old"), None, ("unknown", b"keep")])
    source.write_bytes(raw)
    (tmp_path / "new.bin").write_bytes(b"edited IREG")
    _write_repack_plan(plan, raw)
    listed = CliRunner().invoke(
        u7_app, ["save-list", str(source), "--json", "--strict"]
    )
    assert listed.exit_code == 0, listed.output
    report = json.loads(listed.stdout)
    assert report["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert report["members"][0]["member_path"] == [0]
    args = ["save-repack", str(source), "--plan", str(plan), "-o", str(output)]
    checked = CliRunner().invoke(u7_app, args + ["--dry-run"])
    assert checked.exit_code == 0, checked.output
    assert not output.parent.exists() and json.loads(checked.stdout)["dry_run"]
    written = CliRunner().invoke(u7_app, args)
    assert written.exit_code == 0, written.output
    assert source.read_bytes() == raw
    assert [row.data for row in U7Save.from_file(str(output), strict=True).members] == [
        b"edited IREG",
        b"keep",
    ]
    saved = output.read_bytes()
    assert (
        CliRunner().invoke(u7_app, args).exit_code == 1 and output.read_bytes() == saved
    )
    args[-1] = str(source)
    assert (
        CliRunner().invoke(u7_app, args).exit_code == 1 and source.read_bytes() == raw
    )


def test_cli_stale_member_plan_creates_no_output(tmp_path: Path) -> None:
    source, plan, output = (
        tmp_path / name for name in ("save.sav", "plan.json", "out/new.sav")
    )
    raw = _zip_save([("file", b"old")])
    source.write_bytes(raw)
    (tmp_path / "new.bin").write_bytes(b"new")
    _write_repack_plan(plan, raw, expected=b"stale")
    result = CliRunner().invoke(
        u7_app, ["save-repack", str(source), "--plan", str(plan), "-o", str(output)]
    )
    assert result.exit_code == 1 and "SHA-256" in result.output
    assert not output.exists() and not output.parent.exists()


@pytest.mark.parametrize("kind", ["flex", "zip", "group", "nested"])
def test_ireg_rewrite_can_be_embedded_without_changing_other_save_members(
    kind: str,
) -> None:
    ireg = b"\x06\0\0\x64\0\x50\x2a\0\0"
    changed = rewrite_ireg_stream(ireg, [U7IregEdit(0, {"lift": 6})]).data
    entries = [("flaginit", b"flags"), ("u7ireg00", ireg)]
    path: tuple[int, ...]
    if kind == "nested":
        raw = _flex_save([entries[0], ("map01", _flex_save([entries[1]]))])
        path = (1, 0)
    else:
        raw = (
            _flex_save(entries)
            if kind == "flex"
            else _zip_save(
                entries if kind == "zip" else [("GAMEDAT", _level2_group(entries))]
            )
        )
        path = (1,)
    result = repack_u7_save(
        raw,
        [U7SaveReplacement(path, changed, hashlib.sha256(ireg).hexdigest())],
        expected_sha256=hashlib.sha256(raw).hexdigest(),
    )
    outer = U7Save.from_bytes(result.data, strict=True)
    assert outer.members[0].data == b"flags"
    leaf = (
        U7Save.from_bytes(outer.members[1].data, strict=True).members[0].data
        if kind == "nested"
        else outer.members[1].data
    )
    assert leaf == changed and leaf[5] == 0x60


def test_modified_compression_boundaries_do_not_recompress_unsupported_unmodified_entries() -> (
    None
):
    pytest.importorskip("bz2")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("first", b"old", compress_type=zipfile.ZIP_STORED)
        archive.writestr("second", b"untouched" * 50, compress_type=zipfile.ZIP_BZIP2)
    raw = stream.getvalue()
    result = repack_u7_save(raw, [U7SaveReplacement((0,), b"new and longer")])
    assert _zip_parts(raw)[1][1] == _zip_parts(result.data)[1][1]
    with pytest.raises(ValueError, match="stored or deflated"):
        repack_u7_save(raw, [U7SaveReplacement((1,), b"new")])


def test_crc_corruption_and_bad_local_descriptor_fail_before_repacking() -> None:
    raw = _zip_save([("file", b"old")], method=zipfile.ZIP_STORED)
    corrupted = bytearray(raw)
    name_size, extra_size = struct.unpack_from("<HH", raw, 26)
    corrupted[30 + name_size + extra_size] ^= 1
    with pytest.raises(ValueError, match="CRC"):
        repack_u7_save(bytes(corrupted), [U7SaveReplacement((0,), b"new")])
    raw = _zip_save([("file", b"old")], descriptor=True)
    corrupted = bytearray(raw)
    offset = raw.index(b"PK\x07\x08")
    corrupted[offset + 4] ^= 1
    with pytest.raises(ValueError, match="descriptor"):
        repack_u7_save(bytes(corrupted), [U7SaveReplacement((0,), b"new")])


@pytest.mark.parametrize(
    "bad_plan",
    [
        None,
        {},
        {"source_sha256": "x", "replacements": []},
        {"source_sha256": None, "replacements": []},
    ],
)
def test_cli_invalid_plan_does_not_create_files(
    tmp_path: Path, bad_plan: object
) -> None:
    source, plan, output = (
        tmp_path / name for name in ("save.sav", "plan.json", "out/new.sav")
    )
    source.write_bytes(_flex_save([("file", b"old")]))
    plan.write_text(json.dumps(bad_plan), encoding="utf-8")
    result = CliRunner().invoke(
        u7_app, ["save-repack", str(source), "--plan", str(plan), "-o", str(output)]
    )
    assert result.exit_code == 1 and not output.parent.exists()


def test_cli_removes_new_partial_output_if_writing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, plan, output = (
        tmp_path / name for name in ("save.sav", "plan.json", "out/new.sav")
    )
    raw = _flex_save([("file", b"old")])
    source.write_bytes(raw)
    (tmp_path / "new.bin").write_bytes(b"new")
    _write_repack_plan(plan, raw)
    original_open = Path.open

    class FailingOutput:
        def __enter__(self):
            self.stream = original_open(output, "xb")
            return self

        def write(self, data: bytes) -> None:
            self.stream.write(data[:3])
            raise OSError("injected write failure")

        def __exit__(self, *args: object) -> None:
            self.stream.close()

    def injected_open(path: Path, *args, **kwargs):
        if path == output and args and args[0] == "xb":
            return FailingOutput()
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", injected_open)
    result = CliRunner().invoke(
        u7_app, ["save-repack", str(source), "--plan", str(plan), "-o", str(output)]
    )
    assert result.exit_code == 1 and "injected write failure" in result.output
    assert not output.exists() and source.read_bytes() == raw
