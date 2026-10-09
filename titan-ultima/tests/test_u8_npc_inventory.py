"""NPC detail G/C paths, empty inventories and captured saved-gump precedence."""

from __future__ import annotations

import struct

from PIL import Image
from typer.testing import CliRunner

from titan.u8 import container_browser_ui as containers
from titan.u8.cli import u8_app
from titan.u8.npc_browser import load_u8_npc_session
from titan.u8.npc_inventory import load_u8_npc_inventory
from titan.u8.shape_browser import load_u8_shape_library
from tests.test_u8_container_browser import inventory as inventory
from tests.test_u8_native_runtime_state import container_bytes, gumps_bytes
from tests.test_u8_npc_animation_report import case as case


def npc_session(inventory, **kwargs):
    static, gamedat = inventory
    return load_u8_npc_session(
        gamedat, load_u8_shape_library(static / "U8SHAPES.FLX"), **kwargs
    )


def test_empty_npc_g_and_inventory_c_return_to_same_npc(
    inventory, tmp_path, monkeypatch
):
    static, gamedat = inventory
    opened = []
    monkeypatch.setattr(
        containers, "open_preview", lambda path: opened.append(Image.open(path).size)
    )
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
            str(tmp_path / "exports"),
        ],
        input="G\nC\nG\nB\nT\nQ\n",
    )
    assert result.exit_code == 0, result.stdout
    assert opened == [(4, 1), (4, 1)]
    assert "Backpack preview fallback for NPC inventory" in result.stdout
    assert "no captured inventory items" in result.stdout
    assert "Back to NPC" in result.stdout
    assert '"npc_name": "Mordea"' in result.stdout
    assert len(list((tmp_path / "exports/inventory_previews").glob("*.png"))) == 1


def test_inventory_captures_saved_gumps_and_reuses_original_cache(inventory):
    static, gamedat = inventory
    saved = bytearray(container_bytes(7, frame=0))
    struct.pack_into("<h", saved, 56, 2)
    (gamedat / "GUMPS.DAT").write_bytes(gumps_bytes([bytes(saved)]))
    session = npc_session(inventory)
    (gamedat / "GUMPS.DAT").write_bytes(b"changed after capture")
    (gamedat / "itemcach.dat").write_bytes(b"changed after capture")
    data = load_u8_npc_inventory(session)
    assert data.snapshot is session.snapshot
    assert data.snapshot.item_cache is session.source.cache
    assert data.items[7]["gump_previews"][0]["source"] == "saved_gumps"
    assert data.items[7]["gump_previews"][0]["shape"] == 2
    assert data.npc_session is session


def test_explicit_cache_and_loose_npc_sources_retain_paired_snapshot(inventory):
    _, gamedat = inventory
    for source in (gamedat, gamedat / "npcdata.dat"):
        static = inventory[0]
        session = load_u8_npc_session(
            source,
            load_u8_shape_library(static / "U8SHAPES.FLX"),
            itemcach=gamedat / "itemcach.dat",
        )
        data = load_u8_npc_inventory(session)
        assert data.snapshot.item_cache is session.source.cache
        assert data.snapshot.npc_data is session.source.npcs
        assert data.snapshot.gumps is not None
        assert data.items[7]["gump_previews"][0]["source"] == "npc_backpack_fallback"


def test_captured_name_overrides_are_not_reread_by_inventory(inventory, tmp_path):
    names = tmp_path / "names.csv"
    names.write_text(
        "npc_id,name\n1,Custom Avatar\n7,Custom Mordea\n", encoding="utf-8"
    )
    session = npc_session(inventory, names=names)
    names.write_text("changed after capture", encoding="utf-8")
    data = load_u8_npc_inventory(session)
    assert data.items[7]["npc_label"] == "Custom Mordea"
    assert data.items[301]["owner_name"] == "Custom Avatar"
    assert names in data.sources


def test_viewer_failure_is_reported_and_npc_preview_file_remains(
    inventory, tmp_path, monkeypatch
):
    static, gamedat = inventory
    monkeypatch.setattr(containers, "open_preview", lambda path: False)
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
            str(tmp_path / "exports"),
        ],
        input="G\nQ\n",
    )
    assert result.exit_code == 0, result.stdout
    assert "Image viewer could not open the preview" in result.stdout
    files = list((tmp_path / "exports/inventory_previews").glob("*.png"))
    assert len(files) == 1 and Image.open(files[0]).size == (4, 1)


def test_missing_gump_graphics_keeps_npc_inventory_navigation(inventory, tmp_path):
    static, gamedat = inventory
    (static / "U8GUMPS.FLX").unlink()
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
            str(tmp_path / "exports"),
        ],
        input="G\nC\nB\nQ\n",
    )
    assert result.exit_code == 0, result.stdout
    assert "Gump graphics are unavailable" in result.stdout
    assert "Back to NPC" in result.stdout


def test_free_npc_has_no_gump_action(inventory, tmp_path):
    static, gamedat = inventory
    result = CliRunner().invoke(
        u8_app,
        [
            "npc-browse",
            str(gamedat),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "--npc",
            "5",
            "-o",
            str(tmp_path / "exports"),
        ],
        input="Q\n",
    )
    assert result.exit_code == 0, result.stdout
    assert "Preview inventory gump" not in result.stdout


def test_parent_container_npc_session_keeps_captured_snapshot(inventory):
    from tests.test_u8_container_browser import session

    data = session(inventory)
    assert data.npc_session.snapshot is data.snapshot
    npc_inventory = load_u8_npc_inventory(data.npc_session)
    assert npc_inventory.snapshot is data.snapshot
