"""Container signed IDs, resource ownership, framing and section-aware gump metadata."""

from __future__ import annotations

import csv
import io
import struct

import pytest
from typer.testing import CliRunner

from titan.u7.archive_targets import ArchiveTarget
from titan.u7.cli import u7_app
from titan.u7.container_gump import load_u7_container_gumps
from titan.u7.flex import U7FlexArchive
from titan.u7.gump_metadata import (
    U7GumpMetadata,
    load_u7_gump_sources,
    read_u7_gump_metadata,
)
from titan.u7.shapeinfo import U7ContainerRecord, U7Containers


def table(rows=((800, 22, -1),), *, version=2, extended=False):
    count = b"\xff" + struct.pack("<H", len(rows)) if extended else bytes([len(rows)])
    return (
        bytes([version])
        + count
        + b"".join(
            struct.pack("<Hhh", *row) if version >= 2 else struct.pack("<Hh", *row[:2])
            for row in rows
        )
    )


def text(section, *rows):
    return (
        f"%%section {section}\n"
        + "\n".join(":" + row for row in rows)
        + "\n%%endsection\n"
    ).encode()


def bundle(path, game="bg", *, binary=None, gumps=b"", flags=b""):
    archive = U7FlexArchive()
    archive.records = [b""] * (17 if game == "bg" else 21)
    archive.records[11 if game == "bg" else 8] = table() if binary is None else binary
    archive.records[16 if game == "bg" else 20] = gumps
    archive.records[7 if game == "bg" else 4] = flags
    path.write_bytes(archive.to_bytes())
    return path


@pytest.mark.parametrize("version", [0, 1, 2, 3])
def test_container_signed_words_zero_and_raw_records(version):
    raw = table(((522, -1, -1), (801, -2, -3), (800, 0, 7)), version=version)
    parsed = U7Containers.from_bytes(raw, source="sample", strict=True)
    assert [row.gump_shape for row in parsed.records] == [-1, -2, 0]
    assert [row.gump_font for row in parsed.records] == (
        [-1, -3, 7] if version >= 2 else [-1] * 3
    )
    assert parsed.table.raw == raw and not parsed.warnings
    rows = list(csv.DictReader(io.StringIO(parsed.dump_csv())))
    assert rows[0]["gump_shape"] == "-1" and rows[0]["gump_shape_hex"] == "0xFFFF"
    assert rows[0]["gump_shape_raw"] == "65535" and rows[0]["source"] == "sample"
    assert b"".join(row.raw for row in parsed.records) == raw[2:]
    assert parsed.records[0].offset == 2
    manual = U7Containers(version, [U7ContainerRecord(800, 0, -1)])
    assert next(csv.DictReader(io.StringIO(manual.dump_csv())))["version"] == str(
        version
    )


@pytest.mark.parametrize("count", [254, 255, 256])
def test_container_extended_count_begins_after_version(count):
    raw = table([(number, 9, -1) for number in range(count)], extended=count >= 255)
    parsed = U7Containers.from_bytes(raw, strict=True)
    assert parsed.declared_count == count and len(parsed.records) == count
    assert parsed.records[0].offset == (4 if count >= 255 else 2)
    assert parsed.table.consumed_bytes == len(raw)


@pytest.mark.parametrize(
    "raw", [b"", b"\x02", b"\x02\xff", b"\x02\xff\x01", b"\x02\x01abc"]
)
def test_container_partial_inputs_are_retained_and_strict_mode_rejects(raw):
    partial = U7Containers.from_bytes(raw)
    assert partial.table.raw == raw and partial.warnings
    with pytest.raises(ValueError, match="Incomplete container table"):
        U7Containers.from_bytes(raw, strict=True)


def test_container_trailing_bytes_and_full_source_streams_are_retained():
    raw = table(((800, 22, 5), (800, -1, -1), (800, 0, 8))) + b"\xaa\xbb"
    base = U7Containers.from_bytes(raw, source="base", strict=True)
    patch = U7Containers.from_bytes(table(((801, 9, 3),), version=1), source="patch")
    merged = U7Containers.merge(base, patch)
    assert len(base.records) == 3 and base.table.trailing_data == b"\xaa\xbb"
    assert len(merged.records) == 2 and merged.records[0].gump_shape == 0
    assert merged.warnings and [t.raw for t in merged.source_tables] == [
        raw,
        patch.table.raw,
    ]
    rows = list(csv.DictReader(io.StringIO(merged.dump_csv())))
    assert [(row["shape"], row["version"], row["gump_font"]) for row in rows] == [
        ("800", "2", "8"),
        ("801", "1", "-1"),
    ]
    assert (
        U7Containers.merge(base, U7Containers.from_bytes(table(((800, -1, -1),))))
        .records[0]
        .gump_shape
        == -1
    )


@pytest.mark.parametrize("game", ["bg", "si"])
def test_engine_bundle_ignores_static_binary_text_and_lock_flags(tmp_path, game):
    static, patch = tmp_path / "STATIC", tmp_path / "patch"
    static.mkdir()
    patch.mkdir()
    (static / "container.dat").write_bytes(table(((800, 10, -1),)))
    (static / "gump_info.txt").write_bytes(text("container_area", "22/1/2/3/4"))
    (static / "shape_info.txt").write_bytes(text("locked_containers", "522/0"))
    path = bundle(
        tmp_path / "bundle.flx",
        game,
        binary=table(((800, 22, 5), (801, 9, 3))),
        gumps=text("container_area", "22/40/18/60/37"),
        flags=text("locked_containers", "522/1"),
    )
    owner = ArchiveTarget("Game", static, patch)
    catalog = load_u7_container_gumps(owner, game, exult_flx=str(path))
    assert catalog.resolve(800)[0] == 22 and catalog.resolve(801)[0] == 9
    assert catalog.resolve(800)[1].width == 60 and catalog.locked[522]
    assert static / "container.dat" not in catalog.source_files
    (patch / "container.dat").write_bytes(table(((800, -1, 2),)))
    (patch / "gump_info.txt").write_bytes(text("checkmark_pos", "22/5/6/2"))
    patched = load_u7_container_gumps(owner, game, exult_flx=str(path))
    assert patched.mappings[800][0] == -1 and patched.resolve(801)[0] == 9
    assert patched.metadata.checkmarks[22].x == 5 and patched.areas[22].width == 60
    assert "#record=" in catalog.mappings[800][1]


def test_static_alias_is_not_reapplied_as_a_bg_patch(tmp_path):
    (tmp_path / "container.dat").write_bytes(table(((800, 10, -1),)))
    path = bundle(tmp_path / "bundle.flx")
    catalog = load_u7_container_gumps(
        ArchiveTarget("BG", tmp_path, tmp_path), "bg", exult_flx=str(path)
    )
    assert catalog.resolve(800)[0] == 22


def test_explicit_custom_game_static_and_loose_file_inspection(tmp_path):
    (tmp_path / "container.dat").write_bytes(table(((800, 10, 4),)))
    path = bundle(tmp_path / "bundle.flx")
    custom = load_u7_container_gumps(
        ArchiveTarget("Custom", tmp_path, tmp_path, standalone=True),
        "si",
        exult_flx=str(path),
    )
    assert custom.resolve(800)[0] == 10
    assert not custom.locked
    assert (
        U7Containers.from_file(str(tmp_path / "container.dat")).records[0].gump_font
        == 4
    )
    assert (
        U7Containers.from_dir(str(tmp_path), "bg", str(path)).records[0].gump_shape
        == 22
    )
    assert (
        U7Containers.from_dir(str(tmp_path), custom_game=True).records[0].gump_shape
        == 10
    )


def test_unavailable_bundle_never_substitutes_static(tmp_path, monkeypatch):
    monkeypatch.setattr("titan.u7.install.resolve_u7_exult_flx", lambda game: None)
    (tmp_path / "container.dat").write_bytes(table())
    result = U7Containers.from_dir(str(tmp_path))
    assert not result.records and any(
        "unknown" in warning for warning in result.warnings
    )
    with pytest.raises(FileNotFoundError):
        load_u7_gump_sources(tmp_path, exult_flx=tmp_path / "missing.flx")


def test_broken_patch_does_not_fall_back_to_bundle(tmp_path):
    patch = tmp_path / "patch"
    patch.mkdir()
    (patch / "container.dat").write_bytes(b"\x02\x01short")
    path = bundle(tmp_path / "bundle.flx")
    with pytest.raises(ValueError, match="Incomplete container"):
        U7Containers.from_dir(str(tmp_path), exult_flx_path=str(path), patch_dir=patch)


def test_metadata_sections_replace_independently_and_retain_raw_provenance():
    metadata = U7GumpMetadata()
    base = (
        text("container_area", "22/-4/5/60/37/63")
        + text("checkmark_pos", "22/24/34/2")
        + text("special", "9")
    )
    metadata.apply_text(base, "base")
    metadata.apply_text(
        text("container_area", "22/0/0/20/30") + text("special", "9/0"), "patch"
    )
    assert metadata.areas[22].width == 20 and metadata.checkmarks[22].x == 24
    assert (
        metadata.debug_flags[22] == 63
        and "base#container_area" in metadata.debug_sources[22]
    )
    assert 9 in metadata.special and metadata.raw_sources["base"] == base
    metadata.apply_text(text("container_area", "22/0/0/20/30/0"), "clear-debug")
    assert metadata.debug_flags[22] == 0
    row = metadata.as_row(22)
    assert row["checkmark"]["source"].startswith("base#checkmark_pos")
    assert metadata.as_row(999)["checkmark"] is None
    exported = list(csv.DictReader(io.StringIO(metadata.dump_csv())))
    assert (
        next(r for r in exported if r["gump_shape"] == "22")["checkmark_shape"] == "2"
    )
    assert next(r for r in exported if r["gump_shape"] == "9")["checkmark_shape"] == ""


def test_omitted_initial_debug_is_zero_and_checkmark_patch_preserves_area(tmp_path):
    path = bundle(tmp_path / "bundle.flx", gumps=text("container_area", "22/1/2/3/4"))
    patch = tmp_path / "patch"
    patch.mkdir()
    (patch / "gump_info.txt").write_bytes(text("checkmark_pos", "22/0/-3/7"))
    metadata = read_u7_gump_metadata(
        load_u7_gump_sources(tmp_path, patch_dir=patch, exult_flx=path)
    )
    assert metadata.debug_flags[22] == 0 and metadata.areas[22].x == 1
    assert metadata.checkmarks[22].y == -3 and metadata.checkmarks[22].shape == 7


@pytest.mark.parametrize(
    "section,row",
    [
        ("container_area", "22/0x10/0/3/4"),
        ("container_area", "22/1_0/0/3/4"),
        ("container_area", "22/1/2"),
        ("container_area", "22/1/2/3/4/bad"),
        ("checkmark_pos", "22/1/2"),
        ("special", "invalid"),
    ],
)
def test_gump_decimal_grammar_and_malformed_sections_are_diagnosed(section, row):
    with pytest.raises(ValueError, match="malformed"):
        U7GumpMetadata().apply_text(text(section, row), "invalid.txt")


def test_cli_help_exposes_custom_and_explicit_source_options():
    result = CliRunner().invoke(u7_app, ["static-data-dump", "--help"])
    assert result.exit_code == 0
    assert all(
        flag in result.stdout
        for flag in ("gumps", "--file", "--custom-game", "--patch-dir")
    )
    result = CliRunner().invoke(u7_app, ["container-browse", "--help"])
    assert result.exit_code == 0 and "--custom-game" in result.stdout


def test_cli_binding_and_text_exports_and_explicit_file_diagnostics(tmp_path):
    path = bundle(
        tmp_path / "bundle.flx",
        binary=table(((800, -1, -1),)),
        gumps=text("checkmark_pos", "22/24/34/2")
        + text("container_area", "22/1/2/3/4/0"),
    )
    args = [str(tmp_path), "--exult-flx", str(path)]
    result = CliRunner().invoke(u7_app, ["static-data-dump", "container", *args])
    assert result.exit_code == 0, result.output
    row = next(csv.DictReader(io.StringIO(result.stdout)))
    assert row["gump_shape"] == "-1" and row["gump_shape_raw"] == "65535"
    result = CliRunner().invoke(u7_app, ["static-data-dump", "gumps", *args])
    assert result.exit_code == 0, result.output
    row = next(csv.DictReader(io.StringIO(result.stdout)))
    assert row["checkmark_shape"] == "2" and row["debug_flags"] == "0"
    explicit = tmp_path / "foreign.dat"
    explicit.write_bytes(table(((800, 0, -1),)) + b"tail")
    result = CliRunner().invoke(
        u7_app, ["static-data-dump", "container", "--file", str(explicit)]
    )
    assert result.exit_code == 0 and "trailing bytes" in result.stderr
    assert next(csv.DictReader(io.StringIO(result.stdout)))["gump_shape"] == "0"
