"""Native NPC names, source isolation, interactive navigation and export contracts."""

from __future__ import annotations

import csv
import io
import json
import struct
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from titan import _wizard_ui as ui
from titan.u8.cli import u8_app
from titan.u8.npc_browser import (
    describe_u8_npc_equipment,
    discover_u8_npc_sources,
    filter_u8_npcs,
    format_u8_npc_browser_summary,
    load_u8_npc_session,
)
from titan.u8.npc_browser_ui import run_u8_npc_browser, preview_u8_npc_sprite
from titan.u8.npc_names import describe_u8_npc_identity
from titan.u8.npc_source import load_u8_npc_source
from titan.u8.shape_browser import U8ShapeTarget, load_u8_shape_library
from tests.test_u8_cached_state import save_bytes
from tests.test_u8_npc_animation_report import case as case


def session_for_case(case: tuple[Path, Path]):
    static, gamedat = case
    return load_u8_npc_session(gamedat, load_u8_shape_library(static / "U8SHAPES.FLX"))


def test_npc_names_follow_native_permanent_slots_not_shapes_or_npc_num(case):
    session = session_for_case(case)
    avatar, mordea = session.states[1], session.states[7]
    assert avatar["item_npc_num"] == 42 and avatar["npc_name"] == "Avatar"
    assert avatar["item_shape"] == mordea["item_shape"] == 1
    assert mordea["npc_name"] == "Mordea" and mordea["npc_usecode_class"] == 1031
    assert mordea["npc_usecode_name"] == "MORDEA" and mordea["class_label"] == ""
    assert session.states[5]["item_shape"] == 555  # stale free slot would map to Darion
    assert (
        session.states[5]["npc_name"] == ""
        and session.states[5]["npc_label"] == "NPC 5"
    )
    assert session.states[0]["npc_usecode_class"] is None
    fast = dict(mordea, item_status=0x80)
    assert describe_u8_npc_identity(fast)["npc_name"] == ""
    assert describe_u8_npc_identity(fast)["npc_usecode_class"] == 1
    # A coincidentally equal shape/class ID does not turn a fast-only actor into Mordea.
    assert describe_u8_npc_identity(dict(fast, item_shape=1031))["npc_name"] == ""
    assert (
        describe_u8_npc_identity(mordea, labels={7: "Lady Mordea"})["label_source"]
        == "names_csv"
    )


def test_saved_avatar_name_is_shared_by_browser_and_report_command(
    case, tmp_path: Path
):
    static, gamedat = case
    raw = bytearray(77)
    raw[6:12] = b"Alice\0"
    (gamedat / "AVATAR.DAT").write_bytes(raw)
    session = session_for_case(case)
    assert session.states[1]["npc_name"] == "Alice"
    assert session.states[1]["label_source"] == "native_avatar_name"
    output = tmp_path / "named_report"
    result = CliRunner().invoke(
        u8_app,
        [
            "npc-animation-report",
            str(gamedat),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "--npc",
            "1",
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    rows = list(
        csv.DictReader(
            (output / "master.csv").read_text(encoding="utf-8-sig").splitlines()
        )
    )
    assert {row["npc_name"] for row in rows} == {"Alice"}
    assert "Alice" in (output / "npcs/npc_001.html").read_text()
    manifest = json.loads((output / "manifest.json").read_text())
    assert any(Path(row["path"]).name == "AVATAR.DAT" for row in manifest["sources"])


def test_filters_use_allocation_and_verified_dead_flag_not_initial_in_use_or_hp(case):
    states = session_for_case(case).states
    assert [row["npc_id"] for row in filter_u8_npcs(states)] == [1, 7]
    assert len(filter_u8_npcs(states, mode="all")) == 256
    assert len(filter_u8_npcs(states, mode="unused")) == 254
    assert [row["npc_id"] for row in filter_u8_npcs(states, query="mordea")] == [7]
    assert [row["npc_id"] for row in filter_u8_npcs(states, query="0x7")] == [7]
    assert [row["npc_id"] for row in filter_u8_npcs(states, map_num=3, shape=1)] == [1]
    assert (
        len(filter_u8_npcs(states, mode="alive")) == 2
    )  # NPC 7's zero HP is stored residue
    states[7]["state_flags"] = 0x10
    assert [row["npc_id"] for row in filter_u8_npcs(states, mode="dead")] == [7]
    assert not filter_u8_npcs(states, query="Darion")
    with pytest.raises(ValueError, match="unknown allocation"):
        filter_u8_npcs(states, mode="invented")


def test_equipment_preserves_numbered_slots_invalid_and_free_references(case):
    session = session_for_case(case)
    state = dict(
        session.states[1],
        equipment_items=[
            {"slot": 0, "item_id": 0, "item": None},
            {"slot": 1, "item_id": 65535, "item": None, "issue": "outside cache"},
            {
                "slot": 2,
                "item_id": 5,
                "item": {
                    "item_id": 5,
                    "shape": 555,
                    "frame_low": 2,
                    "slot_membership": "free_npc",
                },
            },
            {
                "slot": 3,
                "item_id": 7,
                "item": {
                    "item_id": 7,
                    "shape": 1,
                    "frame_low": 1,
                    "slot_membership": "allocated",
                },
            },
        ],
    )
    rows = describe_u8_npc_equipment(session, state)
    assert [row["slot"] for row in rows] == [0, 1, 2, 3]
    assert rows[1]["issue"] == "outside cache" and "free/null" in rows[2]["issue"]
    assert rows[3]["frame"] == 1


def test_summary_csv_includes_independent_npc_names_and_classes(case):
    states = filter_u8_npcs(session_for_case(case).states)
    states[1]["flag_names"] = ["animation_failed", "weapon_hit"]
    rows = list(
        csv.DictReader(
            io.StringIO(format_u8_npc_browser_summary(states).lstrip("\ufeff"))
        )
    )
    assert rows[1]["npc_name"] == "Mordea" and rows[1]["npc_usecode_name"] == "MORDEA"
    assert rows[1]["item_shape"] == "1" and rows[1]["class_label"] == ""
    assert json.loads(rows[1]["flag_names"]) == ["animation_failed", "weapon_hit"]


@pytest.mark.parametrize("kind", ["gamedat", "save", "loose"])
def test_browser_handles_all_native_sources_and_exact_npc_details(
    case, tmp_path: Path, kind: str
):
    static, gamedat = case
    source = gamedat if kind == "gamedat" else gamedat / "npcdata.dat"
    if kind == "save":
        source = tmp_path / "U8SAVE.001"
        source.write_bytes(
            save_bytes(
                [
                    (name, (gamedat / name.lower()).read_bytes())
                    for name in ("NPCDATA.DAT", "ITEMCACH.DAT")
                ]
            )
        )
    result = CliRunner().invoke(
        u8_app,
        [
            "npc-browse",
            str(source),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "--npc",
            "7",
        ],
        input="T\nQ\n",
    )
    assert result.exit_code == 0, result.output
    assert (
        "NPC 7: Mordea" in result.output
        and '"npc_usecode_class": 1031' in result.output
    )
    assert "2 allocated NPCs" in result.output


def test_browser_navigation_equipment_embedded_animation_and_exports(
    case, tmp_path: Path
):
    static, gamedat = case
    original = {path: path.read_bytes() for folder in case for path in folder.iterdir()}
    output = tmp_path / "browser_exports"
    result = CliRunner().invoke(
        u8_app,
        [
            "npc-browse",
            str(gamedat),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "--npc",
            "1",
            "-o",
            str(output),
        ],
        input="N\nB\nS\nS\nMordea\n7\nI\n0\nB\nB\nA\nM\nA7\nD\n2\nQ\nE\nJ\nC\nH\nB\nQ\n",
    )
    assert result.exit_code == 0, result.output
    assert (
        "Next: NPC 7 Mordea" in result.output
        and "Previous: NPC 1 Avatar" in result.output
    )
    assert "NPC 7: Mordea" in result.output and "attack; direction E" in result.output
    assert "Back to parent browser" in result.output
    assert json.loads((output / "npc_007.json").read_text())["npc_name"] == "Mordea"
    rows = list(
        csv.DictReader(
            (output / "npc_list.csv").read_text(encoding="utf-8-sig").splitlines()
        )
    )
    assert len(rows) == 1 and rows[0]["npc_name"] == "Mordea"
    assert "Mordea" in (output / "npc_007_report/npcs/npc_007.html").read_text()
    assert all(path.read_bytes() == raw for path, raw in original.items())


def test_discovery_keeps_snapshot_sources_with_selected_installation(
    case, tmp_path: Path, monkeypatch
):
    static, gamedat = case
    saves = static.parent / "cloud_saves/SAVEGAME"
    saves.mkdir(parents=True)
    (saves / "U8SAVE.001").write_bytes(save_bytes())
    (saves / "unrelated.dat").write_bytes(b"unused")
    other = tmp_path.parent / f"{tmp_path.name}_other" / "GAMEDAT"
    other.mkdir(parents=True)
    monkeypatch.setattr("titan.u8.npc_browser.cfg", lambda *args: str(other))
    dirs, files = discover_u8_npc_sources(static)
    assert dirs == [gamedat] and files == [saves / "U8SAVE.001"]


def test_no_source_argument_chooses_discovered_gamedat(case):
    static, _ = case
    result = CliRunner().invoke(
        u8_app,
        ["npc-browse", "--shapes", str(static / "U8SHAPES.FLX"), "--npc", "7"],
        input="1\nQ\n",
    )
    assert result.exit_code == 0, result.output
    assert "Choose NPC snapshot" in result.output and "NPC 7: Mordea" in result.output


def test_unused_exact_slot_is_inspectable_without_a_false_named_identity(case):
    static, gamedat = case
    result = CliRunner().invoke(
        u8_app,
        [
            "npc-browse",
            str(gamedat),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "--npc",
            "5",
        ],
        input="A\nT\nQ\n",
    )
    assert result.exit_code == 0, result.output
    assert "NPC 5: NPC 5" in result.output and "free_npc" in result.output
    assert "Sprite/animation view unavailable" in result.output


def test_line_mode_skips_terminal_sprite_loading(case, monkeypatch):
    session = session_for_case(case)
    monkeypatch.setattr(ui, "menus_enabled", lambda: False)
    monkeypatch.setattr(
        session.library, "image", lambda *args: pytest.fail("redirected artwork loaded")
    )
    preview_u8_npc_sprite(session, session.states[1])


def test_missing_sprite_keeps_npc_details_usable(case, monkeypatch, capsys):
    session = session_for_case(case)
    monkeypatch.setattr(ui, "menus_enabled", lambda: True)
    preview_u8_npc_sprite(session, dict(session.states[1], item_frame=999))
    assert "Artwork unavailable" in capsys.readouterr().out


def test_missing_cache_fails_cleanly_and_optional_bad_avatar_is_diagnostic(case):
    _, gamedat = case
    (gamedat / "AVATAR.DAT").write_bytes(b"bad avatar")
    source = load_u8_npc_source(gamedat)
    assert source.avatar is None and "Avatar name unavailable" in source.diagnostics[0]
    (gamedat / "itemcach.dat").unlink()
    with pytest.raises(ValueError, match="paired NPCDATA"):
        load_u8_npc_source(gamedat)


def test_browser_cancellation_and_help_contract(case, monkeypatch):
    static, _ = case
    monkeypatch.setattr(
        ui,
        "choice",
        lambda *args, **kwargs: (_ for _ in ()).throw(ui.PromptCancelled()),
    )
    assert run_u8_npc_browser(shapes=static / "U8SHAPES.FLX") == 0
    result = CliRunner().invoke(u8_app, ["npc-browse", "--help"])
    assert result.exit_code == 0
    for option in (
        "--game-dir",
        "--shapes",
        "--palette",
        "--anim",
        "--itemcach",
        "--npc",
        "--names",
        "--output",
    ):
        assert option in result.output


def test_explicit_name_overrides_are_used_in_browser_and_export(case, tmp_path: Path):
    static, gamedat = case
    names = tmp_path / "names.csv"
    names.write_text("npc_id,name\n7,Lady Mordea\n", encoding="utf-8")
    output = tmp_path / "custom"
    result = CliRunner().invoke(
        u8_app,
        [
            "npc-browse",
            str(gamedat),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "--npc",
            "7",
            "--names",
            str(names),
            "-o",
            str(output),
        ],
        input="E\nJ\nB\nQ\n",
    )
    assert result.exit_code == 0, result.output
    state = json.loads((output / "npc_007.json").read_text())
    assert state["npc_name"] == "Lady Mordea" and state["label_source"] == "names_csv"


def test_switching_snapshots_clears_initial_cache_override(case, tmp_path: Path):
    static, gamedat = case
    raw_cache = bytearray((gamedat / "itemcach.dat").read_bytes())
    arrays_offset = struct.unpack_from("<I", raw_cache, 128)[0]
    struct.pack_into("<H", raw_cache, arrays_offset + 46080 + 7 * 2, 3)
    save = tmp_path / "U8SAVE.002"
    save.write_bytes(
        save_bytes(
            [
                ("NPCDATA.DAT", (gamedat / "npcdata.dat").read_bytes()),
                ("ITEMCACH.DAT", bytes(raw_cache)),
            ]
        )
    )
    output = tmp_path / "changed_source"
    result = CliRunner().invoke(
        u8_app,
        [
            "npc-browse",
            str(gamedat),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "--itemcach",
            str(gamedat / "itemcach.dat"),
            "--npc",
            "7",
            "-o",
            str(output),
        ],
        input=f"D\nC\n{save}\n7\nE\nJ\nB\nQ\n",
    )
    assert result.exit_code == 0, result.output
    assert json.loads((output / "npc_007.json").read_text())["item_shape"] == 3


def test_switching_graphics_owner_reloads_assets(case, tmp_path: Path, monkeypatch):
    static, gamedat = case
    other = tmp_path / "other/STATIC"
    shutil.copytree(static, other)
    monkeypatch.setattr(
        "titan.u8.npc_browser_ui.choose_u8_shape_target",
        lambda directory: U8ShapeTarget("Other", other),
    )
    selected_owners = []

    def choose_source(library):
        selected_owners.append(library.path)
        return gamedat

    monkeypatch.setattr("titan.u8.npc_browser_ui._choose_npc_source", choose_source)
    result = CliRunner().invoke(
        u8_app,
        [
            "npc-browse",
            str(gamedat),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "--npc",
            "7",
        ],
        input="W\n7\nQ\n",
    )
    assert result.exit_code == 0, result.output
    assert selected_owners == [other / "U8SHAPES.FLX"]


def test_browser_can_start_with_installation_selector(case):
    static, _ = case
    result = CliRunner().invoke(
        u8_app, ["npc-browse", "--game-dir", str(static)], input="1\n1\n7\nQ\n"
    )
    assert result.exit_code == 0, result.output
    assert "U8 data source" in result.output and "NPC 7: Mordea" in result.output


def test_exports_keep_existing_files_and_choose_new_filenames(case, tmp_path: Path):
    static, gamedat = case
    output = tmp_path / "preserved"
    output.mkdir()
    (output / "npc_007.json").write_text("keep", encoding="utf-8")
    result = CliRunner().invoke(
        u8_app,
        [
            "npc-browse",
            str(gamedat),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "--npc",
            "7",
            "-o",
            str(output),
        ],
        input="E\nJ\nB\nQ\n",
    )
    assert result.exit_code == 0, result.output
    assert (output / "npc_007.json").read_text() == "keep"
    assert json.loads((output / "npc_007_002.json").read_text())["npc_name"] == "Mordea"
