"""Static monster categories, resistance labels and effective actor-flag composition."""

from __future__ import annotations

import csv
import io
import struct

import pytest
from typer.testing import CliRunner

from titan.u7.actor_flags import U7ActorFlags, load_u7_actor_flags
from titan.u7.cli import u7_app
from titan.u7.flex import U7FlexArchive
from titan.u7.monster import U7MonsterDefinitions, monster_report
from titan.u7.save import U7NPC


def record(shape=700, *, category=3, legacy=0, immune=0, equipment=0, deleted=False):
    data = bytearray(25)
    struct.pack_into("<H", data, 0, shape)
    data[2], data[13], data[14], data[15], data[11] = (
        53 << 2,
        category,
        equipment,
        legacy,
        immune,
    )
    data[24] = 255 if deleted else 0
    return bytes(data)


def definitions(*rows):
    return U7MonsterDefinitions.from_bytes(bytes([len(rows)]) + b"".join(rows))


def flags(rows="", *, source="flags", defaults=True):
    return U7ActorFlags.from_text(
        "%%section actor_flags\n" + rows + "\n%%endsection",
        source=source,
        defaults=defaults,
    )


def bundle(path, *, game="si", rows=""):
    data = U7FlexArchive()
    data.records = [b""] * 8
    data.records[7 if game == "bg" else 4] = (
        "%%section actor_flags\n" + rows + "\n%%endsection"
    ).encode()
    path.write_bytes(data.to_bytes())
    return path


@pytest.mark.parametrize(
    ("code", "category", "name"),
    [
        (0, 2, "unpredictable"),
        (1, 0, "noncombatant"),
        (2, 1, "opportunist"),
        (3, 2, "unpredictable"),
        (4, 3, "tactician"),
        (5, 4, "berserker"),
        (6, 5, "unknown_category_5"),
        (7, 6, "unknown_category_6"),
    ],
)
def test_static_category_is_not_live_actor_mode(code, category, name):
    parsed = definitions(record(category=code))
    definition = parsed.records[0]
    assert (definition.behavior_category, definition.behavior_category_name) == (
        category,
        name,
    )
    assert definition.attack_mode == category and definition.attack_mode_name == name
    row = next(csv.DictReader(io.StringIO(parsed.dump_csv())))
    assert row["behavior_category_name"] == row["attack_mode_name"] == name
    assert (
        U7NPC(npc_num=0, name="", shape=0, frame=0, attack_mode=2).attack_mode_name
        == "strongest"
    )
    assert bool(parsed.validate_semantics()) == (code >= 6)


@pytest.mark.parametrize(
    ("bit", "label"),
    [
        (0, "normal"),
        (1, "fire"),
        (2, "magic"),
        (3, "lightning"),
        (4, "ethereal"),
        (5, "sonic"),
        (6, "unknown_6"),
        (7, "unknown_7"),
    ],
)
def test_damage_labels_keep_unknown_bits_and_raw_bytes(bit, label):
    raw = bytearray(record(immune=1 << bit))
    raw[10] = 1 << bit
    raw[7], raw[16], raw[19], raw[12], raw[13] = 0xA5, 0xC1, 0xE2, 0x9F, 0xFB
    parsed = definitions(bytes(raw)).records[0]
    assert parsed.immune_names == parsed.vulnerable_names == label
    assert parsed.immune == parsed.vulnerable == 1 << bit
    assert parsed.raw_hex == raw.hex() and parsed.strength == 53


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([record(), record(deleted=True)], {}),
        ([record(deleted=True), record(category=5)], {700: "berserker"}),
        ([record(category=1), record(category=4)], {700: "tactician"}),
        ([record(), record(deleted=True), record(category=2)], {700: "opportunist"}),
        ([record(deleted=True)], {}),
    ],
)
def test_single_stream_removals_and_reinstatements_preserve_raw_records(rows, expected):
    parsed = definitions(*rows)
    assert {
        shape: r.behavior_category_name for shape, r in parsed.by_shape().items()
    } == expected
    assert len(parsed.records) == len(rows) and parsed.table.raw == bytes(
        [len(rows)]
    ) + b"".join(rows)
    assert {
        shape: r.behavior_category_name
        for shape, r in U7MonsterDefinitions.merge(parsed).by_shape().items()
    } == expected


def test_semantic_bounds_are_optional_and_do_not_rewrite_unknown_data():
    raw = record(category=7, equipment=3)
    parsed = definitions(raw)
    assert len(parsed.validate_semantics()) == 1
    warnings = parsed.validate_semantics(equipment_count=2, shape_count=700)
    assert len(warnings) == 3 and any("equipment reference 3" in w for w in warnings)
    assert parsed.records[0].raw_hex == raw.hex() and not parsed.warnings
    assert not definitions(record(deleted=True)).validate_semantics(
        equipment_count=0, shape_count=0
    )


def test_summary_counts_resolved_shapes_when_raw_records_are_superseded():
    parsed = definitions(*([record()] * 22), record(deleted=True))
    summary = parsed.dump_summary()
    assert "22 active, 1 deleted, 23 total; 0 effective shapes" in summary
    assert "more" not in summary and "STR=" not in summary


def test_actor_flag_rows_replace_whole_byte_and_missing_sections_preserve_it():
    base = flags(":700/1/1/1/1/1/1/1/1", source="base")
    cleared = base.overlay(
        flags(":700/0/0/0/0/0/0/0/0", source="patch", defaults=False)
    )
    assert cleared.resolve(700).flags == 0 and cleared.resolve(700).known_mask == 255
    short = base.overlay(flags(":700/0/1", source="short", defaults=False))
    assert short.resolve(700).flags == 2
    assert base.resolve(700).flags == 255
    missing = U7ActorFlags.from_text(
        "%%section framenames\n:700/0/-1/-1\n%%endsection", source="unrelated"
    )
    assert base.overlay(missing).resolve(700).flags == 255
    assert "short#actor_flags:" in short.resolve(700).text_source
    assert flags(":700/-2/0/1").resolve(700).flags == 5


def test_migration_happens_after_text_and_preserves_raw_binary_flags():
    definition = definitions(record(legacy=7)).records[0]
    text = flags(":700/0/0/0/0/0/0/0/0", source="clear-all")
    resolved = text.resolve(
        700, legacy_flags=definition.legacy_actor_flags, legacy_source="binary"
    )
    assert resolved.flags == 0x1C and resolved.legacy_mask == 0x1C
    assert resolved.legacy_source == "binary"
    assert (
        definition.can_teleport
        and definition.can_summon
        and definition.can_be_invisible
    )
    row = definition.as_row(text)
    assert row["can_teleport"] == row["effective_can_teleport"] == 1
    assert row["effective_actor_flags"] == 0x1C
    assert definition.raw_hex == record(legacy=7).hex()


def test_missing_defaults_do_not_fabricate_negative_abilities():
    table = U7ActorFlags()
    unknown = table.resolve(700)
    assert unknown.flag_value(2) is None and unknown.known_mask == 0
    assert unknown.as_row()["effective_can_teleport"] == ""
    partial = table.resolve(700, legacy_flags=1)
    assert partial.flag_value(2) is True and partial.flag_value(3) is None
    assert partial.known_mask == 4 and "unknown" in partial.summary()
    explicit = flags(":700/0/0/0", defaults=False).resolve(700)
    assert explicit.flag_value(2) is False and explicit.known_mask == 255
    assert flags().resolve(701).flag_value(2) is False
    with pytest.raises(ValueError, match="between 0 and 7"):
        explicit.flag_value(8)


@pytest.mark.parametrize(("game", "index"), [("bg", 7), ("si", 4)])
def test_loader_uses_matching_bundle_and_ordered_patches(tmp_path, game, index):
    resource = bundle(tmp_path / "game.flx", game=game, rows=":700/1/0/1")
    patch = tmp_path / "patch"
    patch.mkdir()
    (patch / "shape_info.txt").write_text(
        "%%section actor_flags\n:700/0/1\n%%endsection"
    )
    extra = tmp_path / "later.txt"
    extra.write_text("%%section actor_flags\n:700/0/0/0/1\n%%endsection")
    parsed = load_u7_actor_flags(
        game=game, exult_flx_path=resource, patch_dirs=[patch], patch_files=[extra]
    )
    assert parsed.resolve(700).flags == 8 and parsed.defaults_available
    assert f"record={index}" in parsed.sources[0]
    assert len(parsed.sources) == 3 and str(extra) in parsed.resolve(700).text_source


def test_loader_explicit_default_file_and_no_default_mode(tmp_path):
    default = tmp_path / "baseline.txt"
    default.write_text("%%section actor_flags\n:700/1/0/0\n%%endsection")
    loaded = load_u7_actor_flags(default_shape_info_path=default)
    assert loaded.resolve(700).flag_value(0) is True
    assert load_u7_actor_flags(discover_defaults=False).resolve(700).known_mask == 0
    with pytest.raises(ValueError, match="select one"):
        load_u7_actor_flags(default_shape_info_path=default, exult_flx_path="bad")
    with pytest.raises(ValueError, match="must be bg or si"):
        load_u7_actor_flags(game="other", discover_defaults=False)


@pytest.mark.parametrize("row", [":bad/1", ":65536/1", ":700/0x1"])
def test_actor_flag_invalid_fields_are_diagnosed(row):
    with pytest.raises(ValueError, match="U7 actor_flags"):
        flags(row)


def test_reports_show_effective_and_raw_abilities_separately(tmp_path):
    static = tmp_path / "STATIC"
    static.mkdir()
    (static / "MONSTERS.DAT").write_bytes(b"\1" + record())
    (static / "EQUIP.DAT").write_bytes(b"\0")
    resource = bundle(tmp_path / "defaults.flx", rows=":700/0/0/1/1/0")
    output = tmp_path / "defs.csv"
    result = CliRunner().invoke(
        u7_app,
        [
            "monster-defs",
            str(static),
            "--game",
            "si",
            "--exult-flx",
            str(resource),
            "--format",
            "csv",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    row = next(csv.DictReader(io.StringIO(output.read_text())))
    assert row["can_teleport"] == "0" and row["effective_can_teleport"] == "1"
    assert row["behavior_category_name"] == "unpredictable"
    assert "record=4" in row["actor_flags_source"]
    outputs = monster_report(
        str(static), None, None, game="si", exult_flx_path=str(resource)
    )
    joined = next(
        csv.DictReader(io.StringIO(outputs["monster_definitions_merged.csv"]))
    )
    assert (
        joined["effective_can_summon"] == "1"
        and "actor_flag_sources=" in outputs["manifest.txt"]
    )


def test_cli_explicit_shape_patch_clears_defaults_and_reports_semantic_warnings(
    tmp_path,
):
    source = tmp_path / "MONSTERS.DAT"
    source.write_bytes(b"\1" + record(category=7))
    resource = bundle(tmp_path / "game.flx", rows=":700/0/0/1")
    patch = tmp_path / "flags.txt"
    patch.write_text("%%section actor_flags\n:700/0/0/0\n%%endsection")
    output = tmp_path / "out.csv"
    result = CliRunner().invoke(
        u7_app,
        [
            "monster-defs",
            str(source),
            "--exult-flx",
            str(resource),
            "--game",
            "si",
            "--shape-info",
            str(patch),
            "--format",
            "csv",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0 and "unsupported behavior category 6" in result.output
    row = next(csv.DictReader(io.StringIO(output.read_text())))
    assert row["effective_can_teleport"] == "0"
