"""Ordered save occurrences, empty payloads, strict boundaries and extraction without name loss."""

import io
import json
import struct
import warnings
import zipfile

import pytest
from typer.testing import CliRunner

from titan.u7.cli import u7_app
from titan.u7.save import U7Save
from titan.u7.save_extraction import extract_u7_save_members


def flex(entries):
    header = bytearray(128 + 8 * len(entries))
    header[:7] = b"Title.."
    struct.pack_into("<II", header, 80, 0xFFFF1A00, len(entries))
    bodies = bytearray()
    for index, entry in enumerate(entries):
        if entry is None:
            continue
        name, data = entry
        blob = name.encode("latin-1").ljust(13, b"\0") + data
        struct.pack_into(
            "<II", header, 128 + index * 8, len(header) + len(bodies), len(blob)
        )
        bodies.extend(blob)
    return bytes(header + bodies)


def zip_save(entries, *, prefix=False, comment=b""):
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter(
            "ignore", UserWarning
        )  # Deliberate duplicate ZIP fixture names.
        with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
            archive.comment = comment
            for name, data in entries:
                archive.writestr(name, data)
    return (b"Title".ljust(80, b"\0") if prefix else b"") + output.getvalue()


def group(entries, terminator=bytes(12)):
    return (
        b"".join(
            name.encode().ljust(12, b"\0") + struct.pack("<I", len(data)) + data
            for name, data in entries
        )
        + terminator
    )


@pytest.mark.parametrize("kind", ["flex", "zip", "group"])
def test_ordered_duplicates_keep_their_own_payloads_and_empty_members(kind):
    entries = [
        ("NPC.DAT", b"first"),
        ("NPC.DAT", b"second"),
        ("empty", b""),
        ("npc.dat", b"third"),
    ]
    raw = (
        flex(entries)
        if kind == "flex"
        else zip_save(entries)
        if kind == "zip"
        else zip_save([("GAMEDAT", group(entries))])
    )
    save = U7Save.from_bytes(raw, strict=True)
    assert save.raw == raw and save.complete and save.warnings
    assert save.entry_names() == [name for name, _ in entries]
    assert [member.data for member in save.members] == [data for _, data in entries]
    assert (
        save.get_data("NPC.DAT") == b"second" and save.get_data("npc.dat") == b"third"
    )
    assert (
        save.get_data("NpC.dAt") == b"second"
    )  # Existing exact-then-first-spelling policy.
    assert save.get_all_data("npc.dat") == [b"first", b"second", b"third"]
    assert save.get_all_data("NPC.DAT", case_sensitive=True) == [b"first", b"second"]
    assert save.get_data("empty") == b"" and save.has_entry("empty")
    assert save.list_entries()[2] == ("empty", 0)
    assert len({member.source for member in save.members}) == 4


def test_flex_sparse_slot_is_distinct_from_a_named_empty_member():
    raw = flex([None, ("empty.", b""), ("data", b"x")])
    save = U7Save.from_bytes(raw, strict=True)
    assert save.title == "Title.." and save.declared_count == 3
    assert len(save.flex_directory) == 3 and save.flex_directory[0] == (0, 0)
    assert save.list_entries() == [("empty", 0), ("data", 1)]


@pytest.mark.parametrize("kind", ["flex", "zip"])
def test_title_starting_with_pk_is_not_mistaken_for_a_raw_zip(kind):
    raw = bytearray(
        flex([("data", b"x")])
        if kind == "flex"
        else zip_save([("data", b"x")], prefix=True)
    )
    raw[:80] = b"PK Title".ljust(80, b"\0")
    parsed = U7Save.from_bytes(bytes(raw), strict=True)
    assert parsed.title == "PK Title" and parsed.get_data("data") == b"x"


def test_truncated_flex_payload_is_marked_partial_and_strict_rejects_it():
    raw = flex([("NPC.DAT", b"abcde")])[:-3]
    partial = U7Save.from_bytes(raw)
    assert (
        not partial.complete
        and partial.raw == raw
        and partial.get_data("npc.dat") == b"ab"
    )
    assert partial.members[0].declared_size == 5 and not partial.members[0].complete
    assert any("payload is truncated" in warning for warning in partial.warnings)
    with pytest.raises(ValueError, match="payload is truncated"):
        U7Save.from_bytes(raw, strict=True)


@pytest.mark.parametrize(
    "corruption,match",
    [("directory", "directory"), ("offset", "offset"), ("short_name", "13-byte")],
)
def test_flex_directory_and_filename_validation(corruption, match):
    raw = bytearray(flex([("data", b"x")]))
    if corruption == "directory":
        struct.pack_into("<I", raw, 84, 100)
    elif corruption == "offset":
        struct.pack_into("<I", raw, 128, 128)
    else:
        struct.pack_into("<I", raw, 132, 12)
    partial = U7Save.from_bytes(bytes(raw))
    assert not partial.complete and partial.warnings and partial.raw == bytes(raw)
    with pytest.raises(ValueError, match=match):
        U7Save.from_bytes(bytes(raw), strict=True)


@pytest.mark.parametrize("prefix", [False, True])
def test_small_valid_zip_and_empty_archive_are_not_subject_to_flex_minimum(prefix):
    raw = zip_save([], prefix=prefix, comment=b"comment")
    assert len(raw) < 128
    save = U7Save.from_bytes(raw, strict=True)
    assert save.complete and save.members == () and save.zip_comment == b"comment"
    assert save.title == ("Title" if prefix else "")


@pytest.mark.parametrize("terminator", [bytes(12), bytes(16)])
def test_group_terminator_and_hexadecimal_map_names(terminator):
    raw = zip_save([("map0A", group([("u7ireg00", b"a"), ("empty", b"")], terminator))])
    save = U7Save.from_bytes(raw, strict=True)
    assert save.complete and save.get_data("map0a/u7ireg00") == b"a"
    assert save.get_data("map0a/empty") == b""
    assert list(save.group_trailing_data.values()) == [terminator[12:]]


@pytest.mark.parametrize(
    "blob,match",
    [
        (b"short", "filename"),
        (b"data".ljust(12, b"\0") + b"\2\0", "size word"),
        (
            b"data".ljust(12, b"\0") + struct.pack("<I", 10) + b"ab",
            "payload is truncated",
        ),
        (group([("data", b"x")], b""), "missing.*terminator"),
        (b"", "missing.*terminator"),
    ],
)
def test_group_short_boundaries_have_diagnostics_and_strict_errors(blob, match):
    raw = zip_save([("GAMEDAT", blob)])
    partial = U7Save.from_bytes(raw)
    assert not partial.complete and partial.warnings
    if "payload" in match:
        assert (
            partial.get_data("data") == b"ab" and partial.members[0].declared_size == 10
        )
        assert not partial.members[0].complete
    with pytest.raises(ValueError, match=match):
        U7Save.from_bytes(raw, strict=True)


def test_zip_crc_failure_is_not_reported_as_a_valid_empty_file():
    raw = bytearray(zip_save([("bad", b"abc"), ("good", b"okay")]))
    payload = 30 + len("bad")
    raw[payload] ^= 1
    save = U7Save.from_bytes(bytes(raw))
    assert not save.complete and not save.members[0].complete
    assert save.members[0].declared_size == 3 and save.get_data("good") == b"okay"
    with pytest.raises(ValueError, match="cannot be read completely"):
        U7Save.from_bytes(bytes(raw), strict=True)


@pytest.mark.parametrize("kind", ["flex", "zip", "group"])
def test_extraction_writes_each_duplicate_and_empty_payload_with_name_mapping(
    tmp_path, kind
):
    entries = [("NPC.DAT", b"one"), ("NPC.DAT", b"two"), ("empty", b"")]
    raw = (
        flex(entries)
        if kind == "flex"
        else zip_save(entries)
        if kind == "zip"
        else zip_save([("GAMEDAT", group(entries))])
    )
    save = U7Save.from_bytes(raw, strict=True)
    written, manifest = extract_u7_save_members(save.members, tmp_path / "out")
    assert [path.read_bytes() for _, path in written] == [b"one", b"two", b""]
    assert len({path for _, path in written}) == 3
    mapping = json.loads(manifest.read_text())
    assert [row["name"] for row in mapping] == ["NPC.DAT", "NPC.DAT", "empty"]


def test_duplicate_suffix_does_not_overwrite_an_original_member_name(tmp_path):
    save = U7Save.from_bytes(
        zip_save(
            [
                ("npc.dat", b"one"),
                ("npc.dat", b"two"),
                ("npc.duplicate-0001.dat", b"three"),
            ]
        )
    )
    written, _ = extract_u7_save_members(save.members, tmp_path)
    assert [path.read_bytes() for _, path in written] == [b"one", b"two", b"three"]


def test_manifest_name_does_not_collide_with_member_parent_directory(tmp_path):
    save = U7Save.from_bytes(
        zip_save(
            [
                ("same", b"one"),
                ("same", b"two"),
                ("titan-save-members.json/child", b"three"),
            ]
        )
    )
    written, manifest = extract_u7_save_members(save.members, tmp_path)
    assert manifest.name == "titan-save-members-1.json"
    assert [path.read_bytes() for _, path in written] == [b"one", b"two", b"three"]


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "C:/escape",
        "C:escape",
        "/escape",
        "a:b",
        "NUL",
        "bad.",
        "bad ",
        "a/../../escape",
    ],
)
def test_extraction_preflights_all_names_before_writing(tmp_path, name):
    save = U7Save.from_bytes(zip_save([("good", b"good"), (name, b"bad")]))
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="unsafe|escapes"):
        extract_u7_save_members(save.members, output)
    assert not output.exists()


def test_extraction_preflights_existing_files_and_parent_conflicts(tmp_path):
    (tmp_path / "existing").write_bytes(b"keep")
    save = U7Save.from_bytes(zip_save([("new", b"new"), ("existing", b"overwrite")]))
    with pytest.raises(ValueError, match="already exists"):
        extract_u7_save_members(save.members, tmp_path)
    assert (
        not (tmp_path / "new").exists()
        and (tmp_path / "existing").read_bytes() == b"keep"
    )
    conflict = U7Save.from_bytes(zip_save([("parent", b"x"), ("parent/child", b"y")]))
    with pytest.raises(ValueError, match="conflicting"):
        extract_u7_save_members(conflict.members, tmp_path / "conflict")
    assert not (tmp_path / "conflict").exists()


def test_directory_payload_is_retained_in_api_and_not_silently_discarded_by_extraction(
    tmp_path,
):
    save = U7Save.from_bytes(zip_save([("folder/", b"payload")]), strict=True)
    assert save.members[0].is_directory and save.members[0].data == b"payload"
    with pytest.raises(ValueError, match="directory member has a payload"):
        extract_u7_save_members(save.members, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_cli_lists_duplicates_and_defaults_extraction_to_strict(tmp_path):
    path = tmp_path / "test.sav"
    path.write_bytes(flex([("NPC.DAT", b"one"), ("NPC.DAT", b"two"), ("empty", b"")]))
    listed = CliRunner().invoke(u7_app, ["save-list", str(path), "--strict"])
    assert (
        listed.exit_code == 0
        and "Entries: 3" in listed.stdout
        and "duplicate name" in listed.stderr
    )
    output = tmp_path / "out"
    extracted = CliRunner().invoke(
        u7_app, ["save-extract", str(path), "-o", str(output), "--entry", "npc.dat"]
    )
    assert extracted.exit_code == 0, extracted.output
    assert (output / "NPC.DAT").read_bytes() == b"one"
    assert (output / "NPC.duplicate-0001.DAT").read_bytes() == b"two"
    partial = tmp_path / "partial.sav"
    partial.write_bytes(flex([("data", b"abc")])[:-2])
    rejected = CliRunner().invoke(
        u7_app, ["save-extract", str(partial), "-o", str(tmp_path / "rejected")]
    )
    assert rejected.exit_code != 0 and not (tmp_path / "rejected").exists()
    permissive = CliRunner().invoke(
        u7_app,
        ["save-extract", str(partial), "-o", str(tmp_path / "partial"), "--permissive"],
    )
    assert (
        permissive.exit_code == 0 and (tmp_path / "partial/data").read_bytes() == b"a"
    )
    assert (
        json.loads((tmp_path / "partial/titan-save-members.json").read_text())[0][
            "complete"
        ]
        is False
    )
