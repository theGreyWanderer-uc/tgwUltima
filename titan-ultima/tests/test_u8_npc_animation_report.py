"""Native slot joins, complete animation rows, offline links and report preservation."""

from __future__ import annotations

import csv
import json
import struct
from html.parser import HTMLParser
from pathlib import Path

import pytest
from typer.testing import CliRunner

from titan.u8.cli import u8_app
from titan.u8.itemcach import U8ItemCache
from titan.u8.npcdata import U8NpcData
from titan.u8.npc_animation_report import (
    ANIMATION_FIELDS,
    describe_u8_npc_animations,
    export_u8_npc_animation_report,
    load_u8_npc_labels,
    u8_npc_animation_rows,
)
from titan.u8.shape_browser import U8ShapeLibrary, load_u8_shape_library
from tests.test_u8_cached_state import item_blocks, save_bytes, state_flex
from tests.test_u8_shape_browser import anim_bytes, shape_bytes


@pytest.fixture
def case(tmp_path: Path):
    static = tmp_path / "STATIC"
    static.mkdir()
    sprites = shape_bytes(
        [(bytes((5, 6, 255)), 0, 0), (bytes((7, 8)), 0, 1), (bytes((9,)), 0, 0)]
    )
    (static / "U8SHAPES.FLX").write_bytes(state_flex([b"", sprites]))
    (static / "U8PAL.PAL").write_bytes(
        bytes(4) + bytes(index % 64 for index in range(768))
    )
    (static / "ANIM.DAT").write_bytes(anim_bytes())
    gamedat = tmp_path / "GAMEDAT"
    gamedat.mkdir()
    blocks = item_blocks()
    arrays = bytearray(blocks[0])
    struct.pack_into("<H", arrays, 46080 + 7 * 2, 1)
    arrays[64512 + 1] = 1
    (gamedat / "itemcach.dat").write_bytes(state_flex([bytes(arrays), blocks[1]]))
    raw = bytearray(256 * 49)
    struct.pack_into("<bbbBBH", raw, 49, 7, 8, 9, 60, 2, 7)
    raw[49 + 8] = 1
    (gamedat / "npcdata.dat").write_bytes(state_flex([bytes(raw)]))
    return static, gamedat


def parsed(case: tuple[Path, Path]) -> tuple[U8ShapeLibrary, U8NpcData, U8ItemCache]:
    static, gamedat = case
    return (
        load_u8_shape_library(static / "U8SHAPES.FLX"),
        U8NpcData.from_file(gamedat / "npcdata.dat"),
        U8ItemCache.from_file(gamedat / "itemcach.dat"),
    )


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value is not None and key in {"href", "src"}:
                self.urls.append(value)
            if value is not None and key == "id":
                self.ids.add(value)


def test_native_slot_shape_join_keeps_names_context_and_unreferenced_frames(case):
    data = describe_u8_npc_animations(*parsed(case))
    assert [npc["npc_id"] for npc in data["npcs"]] == [1, 7]
    assert (
        len(data["shapes"]) == 1
    )  # NPC IDs 1/7 share shape 1; NPCnum 42 is not the join.
    assert data["npcs"][0]["item_npc_num"] == 42
    shape = data["shapes"][1]
    assert len(shape["rows"]) == 33
    assert shape["rows"][-1]["row_kind"] == "unreferenced"
    assert shape["rows"][-1]["frame"] == 2 and shape["rows"][-1]["animation_name"] == ""
    rows = u8_npc_animation_rows(data["npcs"][0], shape)
    matching = [row for row in rows if row["matches_saved_context"]]
    assert len(matching) == 1 and matching[0]["frame"] == 1
    assert (
        matching[0]["animation_name"] == "attack" and matching[0]["matches_saved_frame"]
    )
    assert matching[0]["direction_name"] == "E" and matching[0]["step"] == 1
    assert matching[0]["delta_dir"] == -4 and matching[0]["movement_world_units"] == -16
    assert matching[0]["flipped"] and matching[0]["node_raw"]
    assert ANIMATION_FIELDS[ANIMATION_FIELDS.index("frame") + 1] == "animation_name"


def test_bundle_contains_master_csv_per_npc_html_and_shared_image_links(
    case, tmp_path: Path
):
    output = tmp_path / "report"
    manifest = export_u8_npc_animation_report(*parsed(case), output)
    assert manifest["npc_count"] == 2 and manifest["shape_count"] == 1
    assert manifest["row_count"] == 66 and manifest["contact_sheet_count"] == 17
    with (output / "master.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert {row["npc_id"] for row in rows} == {"1", "7"}
    assert {row["label_source"] for row in rows} == {
        "native_avatar_slot",
        "bundled_npc_usecode_class",
    }
    mordea = next(row for row in rows if row["npc_id"] == "7")
    assert mordea["npc_name"] == "Mordea"
    assert (
        mordea["npc_usecode_class"] == "1031" and mordea["npc_usecode_name"] == "MORDEA"
    )
    assert "Mordea" in (output / "npcs/npc_007.html").read_text()
    assert len({row["contact_sheet"] for row in rows}) == 17
    for page in [output / "index.html", *sorted((output / "npcs").glob("*.html"))]:
        links = Links()
        links.feed(page.read_text())
        for url in links.urls:
            assert not url.startswith(("http:", "https:", "file:"))
            assert (page.parent / url.split("#", 1)[0]).resolve().is_file()
    for row in rows:
        assert (output / row["contact_sheet"]).exists()
        page_name, anchor = row["npc_report"].split("#")
        links = Links()
        links.feed((output / page_name).read_text())
        assert anchor in links.ids
    state = json.loads((output / "npc_state.json").read_text())
    assert state[0]["strength"] == 7 and state[0]["raw"]


def test_report_names_are_explicit_and_html_escaped(case, tmp_path: Path):
    names = tmp_path / "names.csv"
    names.write_text(
        'npc_id,name\n7,"Devon <script>alert(1)</script> & friend"\n', encoding="utf-8"
    )
    labels = load_u8_npc_labels(names)
    output = tmp_path / "report"
    export_u8_npc_animation_report(
        *parsed(case), output, npc_id=7, labels=labels, sources=(names,)
    )
    page = (output / "npcs/npc_007.html").read_text()
    assert (
        "&lt;script&gt;" in page and "<script>" not in page and "&amp; friend" in page
    )
    with (output / "master.csv").open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["npc_label"] == labels[7] and row["label_source"] == "names_csv"
    assert row["class_label"] == ""


def test_resolved_animation_flags_reach_html_csv_and_saved_npc_state(
    case, tmp_path: Path
):
    static, gamedat = case
    raw = bytearray(256 * 49)
    struct.pack_into("<H", raw, 7 * 49 + 0x1B, 0x0010)
    struct.pack_into("<H", raw, 7 * 49 + 0x2F, 0x0020)
    npc_bytes = state_flex([bytes(raw)])
    (gamedat / "npcdata.dat").write_bytes(npc_bytes)
    animation = bytearray(anim_bytes())
    table = struct.unpack_from("<I", animation, 4)[0]
    action = struct.unpack_from("<I", animation, table + 7 * 4)[0]
    animation[action + 1] |= 0x60
    (static / "ANIM.DAT").write_bytes(animation)
    output = tmp_path / "flags_report"
    export_u8_npc_animation_report(*parsed(case), output, npc_id=7)
    page = (output / "npcs/npc_007.html").read_text()
    for name in (
        "animation_failed",
        "weapon_hit",
        "hit_on_collision",
        "repeat_after_completion",
    ):
        assert name in page
    assert "unknown_flag1b_4" not in page and "unknown_flag2f_5" not in page
    state = json.loads((output / "npc_state.json").read_text())[0]
    assert state["flag_names"] == ["animation_failed", "weapon_hit"]
    with (output / "master.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row["action"] == "7"]
    assert rows and all(
        {"hit_on_collision", "repeat_after_completion"}
        <= set(row["action_flag_names"].split("|"))
        for row in rows
    )
    assert all(row["npc_flag_names"] == "animation_failed|weapon_hit" for row in rows)
    assert (gamedat / "npcdata.dat").read_bytes() == npc_bytes


@pytest.mark.parametrize(
    "text",
    [
        "id,name\n7,Devon\n",
        "npc_id,name\n7,Devon\n7,Bentic\n",
        "npc_id,name\n256,Devon\n",
        "npc_id,name\n7,\n",
    ],
)
def test_invalid_name_csv_is_rejected(tmp_path: Path, text: str):
    path = tmp_path / "names.csv"
    path.write_text(text)
    with pytest.raises(ValueError):
        load_u8_npc_labels(path)


def test_missing_node_frames_are_retained_and_only_bad_sheets_are_omitted(
    case, tmp_path: Path
):
    static, _ = case
    (static / "ANIM.DAT").write_bytes(anim_bytes(missing=True))
    output = tmp_path / "report"
    manifest = export_u8_npc_animation_report(*parsed(case), output, npc_id=1)
    assert manifest["npc_count"] == 1 and manifest["contact_sheet_count"] == 1
    assert manifest["shapes"][0]["diagnostics"]
    with (output / "master.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    bad = next(row for row in rows if row["frame"] == "99")
    assert bad["valid_frame"] == "False" and bad["animation_name"] == "walk"
    assert bad["contact_sheet"] == "" and bad["width"] == ""
    assert "missing sprite frame 99" in (output / "npcs/npc_001.html").read_text()


def test_unknown_action_ids_keep_numeric_labels(case):
    lib, npcs, cache = parsed(case)
    from dataclasses import replace

    assert lib.animations is not None
    action = lib.animations.actions.pop((1, 7))
    lib.animations.actions[(1, 36)] = replace(action, action_num=36)
    data = describe_u8_npc_animations(lib, npcs, cache)
    assert {
        row["animation_name"]
        for row in data["shapes"][1]["rows"]
        if row.get("action") == 36
    } == {"action_36"}


def test_report_cannot_replace_sources_or_existing_exports(case, tmp_path: Path):
    static, gamedat = case
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "index.html").write_bytes(b"keep")
    with pytest.raises(ValueError, match="new or empty"):
        export_u8_npc_animation_report(*parsed(case), existing)
    assert (existing / "index.html").read_bytes() == b"keep"
    with pytest.raises(ValueError, match="input files"):
        export_u8_npc_animation_report(
            *parsed(case), tmp_path, sources=(gamedat / "npcdata.dat",)
        )
    assert (static / "ANIM.DAT").read_bytes() == anim_bytes()


def test_report_publishes_to_empty_directory_and_removes_staging(case, tmp_path: Path):
    output = tmp_path / "report"
    output.mkdir()
    manifest = export_u8_npc_animation_report(*parsed(case), output, npc_id=7)
    assert manifest["npc_count"] == 1
    assert (output / "index.html").is_file()
    assert not list(tmp_path.glob(".report-*"))


def test_report_preserves_files_created_during_rendering(case, tmp_path: Path):
    output = tmp_path / "report"

    def concurrent_write(message: str) -> None:
        output.mkdir(exist_ok=True)
        (output / "user.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="became nonempty"):
        export_u8_npc_animation_report(
            *parsed(case), output, npc_id=7, progress=concurrent_write
        )
    assert (output / "user.txt").read_text() == "keep"
    assert not (output / "index.html").exists()
    assert not list(tmp_path.glob(".report-*"))


@pytest.mark.parametrize("kind", ["gamedat", "save", "loose"])
def test_command_help_and_reports_from_each_native_source_kind(
    case, tmp_path: Path, kind: str
):
    static, gamedat = case
    help_result = CliRunner().invoke(u8_app, ["npc-animation-report", "--help"])
    assert help_result.exit_code == 0
    for option in (
        "--shapes",
        "--anim",
        "--palette",
        "--itemcach",
        "--npc",
        "--names",
        "--output",
    ):
        assert option in help_result.output
    if kind == "save":
        source = tmp_path / "U8SAVE.001"
        source.write_bytes(
            save_bytes(
                [
                    ("NPCDATA.DAT", (gamedat / "npcdata.dat").read_bytes()),
                    ("ITEMCACH.DAT", (gamedat / "itemcach.dat").read_bytes()),
                ]
            )
        )
    else:
        source = gamedat if kind == "gamedat" else gamedat / "npcdata.dat"
    output = tmp_path / f"{kind}_report"
    result = CliRunner().invoke(
        u8_app,
        [
            "npc-animation-report",
            str(source),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "--npc",
            "7",
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Saved 1 NPC reports" in result.output
    assert (output / "npcs/npc_007.html").exists() and not (
        output / "npcs/npc_001.html"
    ).exists()
    manifest = json.loads((output / "manifest.json").read_text())
    assert {Path(row["path"]).name for row in manifest["sources"]} >= {
        "npcdata.dat" if kind == "gamedat" else source.name,
        "ANIM.DAT",
        "U8SHAPES.FLX",
    }


def test_missing_state_or_anim_aborts_without_report_outputs(case, tmp_path: Path):
    static, gamedat = case
    (gamedat / "itemcach.dat").unlink()
    output = tmp_path / "report"
    result = CliRunner().invoke(
        u8_app,
        [
            "npc-animation-report",
            str(gamedat),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 1 and "paired NPCDATA" in result.output
    assert not output.exists()
