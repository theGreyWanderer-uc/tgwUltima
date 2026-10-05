"""NPC/save ownership, provenance, navigation, diagnostics and report safety."""

from __future__ import annotations

import io
import json
import struct
import zipfile
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from typer.testing import CliRunner

from titan import _wizard_ui as ui
from titan.fonts.exult_cfg import ExultGamePaths
from titan.u7 import npc_browser as browser
from titan.u7.archive_targets import ArchiveTarget, base_target, discover_targets
from titan.u7.cli import u7_app
from titan.u7.flex import U7FlexArchive
from titan.u7.save import U7NPCInventoryItem, U7ReadyTypes
from titan.u7.shape import U7Shape


def npc_bytes(name="Avatar", *, flags=0, inventory=b"", unused=False):
    record = bytearray(117)
    struct.pack_into("<H", record, 2, 150)
    struct.pack_into("<H", record, 4, bool(inventory))
    record[6:8] = bytes([13, 2])
    struct.pack_into("<H", record, 8, 3 << 12)
    record[10] = 23
    struct.pack_into("<H", record, 14, not unused)
    struct.pack_into("<H", record, 16, flags)
    record[18:24] = bytes([22, 21, 20, 19, 6, 1])
    struct.pack_into("<H", record, 29, 17)
    struct.pack_into("<H", record, 51, 1 << 9)
    record[93] = 24
    encoded = name.encode("ascii")[:16]
    record[101 : 101 + len(encoded)] = encoded
    return bytes(record) + inventory


def npcs_bytes():
    return struct.pack("<HH", 5, 0) + b"".join(
        [
            npc_bytes("Avatar", flags=1 << 11),
            npc_bytes("Iolo", flags=1 << 11),
            npc_bytes("Iolo Junior"),
            npc_bytes("Mortis", flags=1 << 15),
            npc_bytes("", unused=True),
        ]
    )


def schedules_bytes():
    return struct.pack("<iI5H", -1, 5, 0, 1, 1, 1, 1) + struct.pack(
        "<HHBBBB", 301, 402, 3, 2, 6, 0x7F
    )


def write_flex(path, entries):
    archive = U7FlexArchive()
    archive.records = list(entries)
    path.write_bytes(archive.to_bytes())


def write_save(path, entries, *, format="zip", title="A save"):
    if format == "flex":
        write_flex(
            path,
            [name.encode().ljust(13, b"\x00") + blob for name, blob in entries.items()],
        )
        return
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        if format == "level2":
            group = b"".join(
                name.encode().ljust(12, b"\x00") + struct.pack("<I", len(blob)) + blob
                for name, blob in entries.items()
            )
            archive.writestr("gamedat", group + bytes(16))
        else:
            for name, blob in entries.items():
                archive.writestr(name, blob)
    prefix = b"" if format == "raw" else title.encode().ljust(80, b"\x00")
    path.write_bytes(prefix + stream.getvalue())


@pytest.fixture
def owner(tmp_path, monkeypatch):
    static, patch, gamedat, saves = [
        tmp_path / name for name in ("STATIC", "patch", "gamedat", "saves")
    ]
    for path in (static, patch, gamedat, saves):
        path.mkdir()
    write_flex(static / "SHAPES.VGA", [b"\x00" * 64] * 32)
    write_flex(
        static / "TEXT.FLX", [b"" if i != 6 else b"a/sword//s" for i in range(32)]
    )
    tfa = bytearray(32 * 3)
    tfa[5 * 3 + 1] = 6
    (static / "TFA.DAT").write_bytes(tfa)
    (static / "SCHEDULE.DAT").write_bytes(schedules_bytes())
    (gamedat / "NPC.DAT").write_bytes(npcs_bytes())
    (gamedat / "SCHEDULE.DAT").write_bytes(schedules_bytes())
    target = ArchiveTarget(
        "SI mod", static, patch, root=tmp_path, gamedat=gamedat, save_root=saves
    )
    monkeypatch.setattr(browser, "game_targets", lambda game: (target, []))
    monkeypatch.setattr(ui, "menus_enabled", lambda: False)
    return target


def answers(monkeypatch, values):
    pending = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(pending))


@pytest.mark.parametrize("format", ["flex", "zip", "level2", "raw"])
def test_saved_npcs_use_runtime_flavour_in_all_archive_formats(owner, format):
    path = owner.save_root / "test.sav"
    write_save(
        path,
        {
            "NPC.DAT": npcs_bytes(),
            "schedule.dat": schedules_bytes(),
            "identity": b"MYCUSTOMGAME\x1a",
        },
        format=format,
    )
    original = path.read_bytes()
    session = browser.load_session(owner, browser.Source(path, "save"), "si")
    assert session.npcs.npc_flavor == "runtime"
    assert len(session.npcs.npcs) == 5
    assert session.npcs.npcs[0].is_female is True
    assert session.npcs.npcs[0].map_num == 2
    assert session.npcs.npcs[0].face_num == 17
    assert session.schedules.entries[1][0].tx == 301
    assert session.identity == "MYCUSTOMGAME"
    assert not session.warnings
    assert path.read_bytes() == original


@pytest.mark.parametrize("format", ["flex", "raw"])
def test_patch_initgame_provenance_and_owner_new_game_schedules(owner, format):
    path = owner.patch / "INITGAME.DAT"
    write_save(path, {"npc.dat": npcs_bytes()}, format=format)
    schedule = bytearray(schedules_bytes())
    struct.pack_into("<H", schedule, 18, 444)
    (owner.patch / "schedule.dat").write_bytes(schedule)
    assert browser.owner_file(owner, "INITGAME.DAT") == path
    session = browser.load_session(owner, browser.Source(path, "initial"), "si")
    assert session.schedules.entries[1][0].tx == 444
    assert session.npcs.npc_flavor == (
        "original-new-game" if format == "flex" else "runtime"
    )
    npc = session.npcs.npcs[0]
    assert npc.is_female == (format != "flex")
    assert npc.face_num == (0 if format == "flex" else 17)
    assert npc.map_num == (0 if format == "flex" else 2)


def test_saved_or_live_missing_files_do_not_inherit_initial_data(owner):
    path = owner.save_root / "missing.sav"
    write_save(path, {"identity": b"MYGAME"})
    session = browser.load_session(owner, browser.Source(path, "save"), "si")
    assert session.npcs is None and session.schedules is None
    assert "npc.dat is not present" in session.overview()
    (owner.gamedat / "SCHEDULE.DAT").unlink()
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    assert session.npcs.npc_flavor == "runtime"
    assert session.schedules is None


def test_loose_npc_file_uses_only_its_own_siblings(owner, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    path = other / "npc.dat"
    path.write_bytes(npcs_bytes())
    session = browser.load_session(owner, browser.Source(path), "si")
    assert session.npcs is not None
    assert session.schedules is None
    assert session.source.path == path


def test_truncated_records_and_malformed_schedules_are_visible(owner):
    (owner.gamedat / "NPC.DAT").write_bytes(struct.pack("<HH", 2, 0) + npc_bytes())
    (owner.gamedat / "SCHEDULE.DAT").write_bytes(schedules_bytes()[:-1])
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    assert len(session.npcs.npcs) == 1
    assert "parsed 1 of 2" in session.overview()
    assert "schedule.dat entries are incomplete" in session.overview()
    assert session.schedules is None


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\xff" * 4,
        struct.pack("<i", -3),
        struct.pack("<iI", -1, 2),
        struct.pack("<iHH", 2, 2, 1),
    ],
)
def test_schedule_validation_does_not_misreport_partial_as_empty(data):
    with pytest.raises((ValueError, struct.error)):
        browser._schedule_checks(data)


def test_last_npc_short_name_record_is_reported(owner):
    (owner.gamedat / "NPC.DAT").write_bytes(struct.pack("<HH", 1, 0) + npc_bytes()[:-8])
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    assert "last NPC record is incomplete" in session.overview()


def test_identity_mismatch_and_incomplete_party_roster_are_reported(owner):
    info = bytearray(64)
    info[12] = 1
    path = owner.save_root / "wrong.sav"
    write_save(
        path,
        {
            "identity": b"BLACKGATE",
            "saveinfo.dat": bytes(info),
            "npc.dat": npcs_bytes(),
        },
    )
    session = browser.load_session(owner, browser.Source(path, "save"), "si")
    assert "identity differs" in session.overview()
    assert "party roster is incomplete" in session.overview()


def test_owner_save_directory_is_not_recursively_mixed_with_mods(owner):
    write_save(owner.save_root / "EXULT00.SAV", {"npc.dat": npcs_bytes()})
    other = owner.save_root / "mods" / "other"
    other.mkdir(parents=True)
    write_save(other / "exult01.sav", {"npc.dat": npcs_bytes()})
    assert browser.save_paths(owner) == [owner.save_root / "EXULT00.SAV"]
    assert browser.save_paths(replace(owner, save_root=None)) == []


def test_discovery_honours_mod_savegame_path_separately_from_gamedat(tmp_path):
    mods = tmp_path / "install" / "mods"
    mods.mkdir(parents=True)
    (mods / "pagan.cfg").write_text(
        "<mod_info><gamedat_path>__MOD_PATH__/current</gamedat_path><savegame_path>__MOD_PATH__/saves</savegame_path></mod_info>"
    )
    cfg = tmp_path / "exult.cfg"
    cfg.write_text(
        f"<config><disk><game><serpentisle><savegame_path>{tmp_path}/profile</savegame_path></serpentisle></game></disk></config>"
    )
    target = discover_targets(
        "SI", {}, tmp_path / "STATIC", ExultGamePaths("SI", mods_path=str(mods)), cfg
    )[0]
    assert target.gamedat == tmp_path / "profile/mods/pagan/current"
    assert target.save_root == tmp_path / "profile/mods/pagan/saves"


def test_titan_archive_override_still_discovers_matching_exult_runtime_paths(tmp_path):
    mods = tmp_path / "install" / "mods"
    mods.mkdir(parents=True)
    (mods / "pagan.cfg").write_text(
        "<mod_info><savegame_path>__MOD_PATH__/saves</savegame_path></mod_info>"
    )
    cfg = tmp_path / "exult.cfg"
    cfg.write_text(
        f"<config><disk><game><serpentisle><savegame_path>{tmp_path}/profile</savegame_path></serpentisle></game></disk></config>"
    )
    config = {
        "u7si": {"mods": {"My Pagan": {"paths": {"patch": str(mods / "pagan/patch")}}}}
    }
    target = discover_targets(
        "SI",
        config,
        tmp_path / "STATIC",
        ExultGamePaths("SI", mods_path=str(mods)),
        cfg,
    )[0]
    assert target.name == "My Pagan"
    assert target.save_root == tmp_path / "profile/mods/pagan/saves"
    assert target.gamedat == tmp_path / "profile/mods/pagan/gamedat"
    config["u7si"]["mods"]["My Pagan"]["paths"]["savegame"] = str(
        tmp_path / "explicit-saves"
    )
    target = discover_targets(
        "SI",
        config,
        tmp_path / "STATIC",
        ExultGamePaths("SI", mods_path=str(mods)),
        cfg,
    )[0]
    assert target.save_root == tmp_path / "explicit-saves"


def test_base_and_custom_game_save_roots_follow_configured_paths(tmp_path):
    custom = tmp_path / "custom"
    custom.mkdir()
    cfg = tmp_path / "exult.cfg"
    cfg.write_text(
        f"<config><disk><game><serpentisle><savegame_path>{tmp_path}/si-saves</savegame_path></serpentisle><mine><path>{custom}</path><savegame_path>profiles</savegame_path><gamedat_path>working</gamedat_path></mine></game></disk></config>"
    )
    retail = base_target("SI", {}, tmp_path / "STATIC", None, cfg)
    assert retail.save_root == tmp_path / "si-saves"
    own = discover_targets("SI", {}, tmp_path / "STATIC", None, cfg)[0]
    assert own.save_root == custom / "profiles"
    assert own.gamedat == custom / "working"


def test_search_filters_keep_original_npc_ids(owner):
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    npcs = session.npcs.npcs
    assert [n.npc_num for n in browser.filter_npcs(npcs, "IOLO")] == [1, 2]
    assert [n.npc_num for n in browser.filter_npcs(npcs, "2")] == [2]
    assert [n.npc_num for n in browser.filter_npcs(npcs, mode="party")] == [0, 1]
    assert [n.npc_num for n in browser.filter_npcs(npcs, mode="alive")] == [0, 1, 2]
    assert [n.npc_num for n in browser.filter_npcs(npcs, mode="dead")] == [3]
    assert [n.npc_num for n in browser.filter_npcs(npcs, mode="unused")] == [4]
    numbered_name = replace(npcs[1], npc_num=20, name="NPC 2")
    assert [n.npc_num for n in browser.filter_npcs([*npcs, numbered_name], "2")] == [2]


def test_real_nested_inventory_parse_and_preferred_slot_are_preserved(owner):
    container = bytes([0, 0, 5, 0, 1, 0, 0, 0, 0, 0, 0, 0])
    sword = bytes([0, 0, 6, 0, 0, 2])
    inventory = bytes([12]) + container + bytes([6]) + sword + bytes([1, 1])
    (owner.gamedat / "NPC.DAT").write_bytes(
        struct.pack("<HH", 1, 0) + npc_bytes(inventory=inventory)
    )
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    npc = session.npcs.npcs[0]
    assert [(item.shape, item.depth, item.path) for item in npc.inventory] == [
        (5, 0, "5:0"),
        (6, 1, "5:0/6:0"),
    ]
    session.ready = U7ReadyTypes({6: 3})
    rows = browser.inventory_rows(session, npc)
    assert rows[1]["name"] == "sword"
    assert rows[1]["preferred_slot"] == "left_hand"
    assert rows[1]["location"] == "inside 5:0/6:0"


def test_no_metadata_still_browses_and_warns(owner):
    target = replace(owner, static=None, patch=owner.patch / "missing")
    session = browser.load_session(target, browser.Source(owner.gamedat, "live"), "si")
    assert len(session.npcs.npcs) == 5
    assert "nesting uses the reader's heuristics" in session.overview()
    assert "numeric shape IDs" in session.overview()


def test_inventory_browser_distinguishes_identical_container_paths(
    owner, monkeypatch, capsys
):
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    npc = session.npcs.npcs[0]
    npc.inventory = [
        U7NPCInventoryItem(5, 0, 0, 0, 0, 0, 0, "5:0"),
        U7NPCInventoryItem(6, 0, 0, 0, 0, 1, 1, "5:0/6:0"),
        U7NPCInventoryItem(5, 0, 0, 0, 0, 0, 0, "5:0"),
        U7NPCInventoryItem(7, 0, 0, 0, 0, 2, 1, "5:0/7:0"),
    ]
    answers(monkeypatch, ["0", "C", "1", "B", "U", "2", "C", "3", "Q"])
    browser._inventory(session, npc)
    output = capsys.readouterr().out
    first_scope = output.split("Contents of item 0:")[1].split(
        "Inventory and nested contents"
    )[0]
    assert "sword" in first_scope and "shape 7" not in first_scope
    assert "Contents of item 2" in output and "Item 3: shape 7" in output


@pytest.mark.parametrize("marker", [2, -1, -2])
def test_schedule_formats_validate_and_read(marker):
    offsets = struct.pack("<HH", 0, 1)
    if marker == 2:
        raw = struct.pack("<i", marker) + offsets + bytes([6 << 3 | 2, 1, 2, 13])
    else:
        raw = struct.pack("<iI", marker, 2)
        if marker == -2:
            raw += struct.pack("<H", 1)
        raw += offsets
        if marker == -2:
            raw += struct.pack("<H", 4) + b"abc\x00"
        raw += struct.pack("<HHBBBB", 301, 402, 3, 2, 6, 0x7F)
    browser._schedule_checks(raw)
    schedules = browser.U7Schedules.from_bytes(raw)
    assert schedules.entries[1][0].time == 2
    assert schedules.entries[1][0].type == 6


def test_paged_search_can_have_no_results_and_return_to_all(owner, monkeypatch, capsys):
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    session.npcs.npcs += [
        replace(session.npcs.npcs[2], npc_num=i, name=f"Npc {i}") for i in range(5, 33)
    ]
    answers(monkeypatch, ["N", "B", "S", "missing", "S", "", "Q"])
    assert browser._browse_npcs(session) == "Q"
    output = capsys.readouterr().out
    assert "page 2/3" in output and "NPCs: 0 matches" in output


def test_change_world_resets_source_and_npc_selection(owner, monkeypatch, capsys):
    games = []

    def targets(game):
        games.append(game)
        return owner, []

    monkeypatch.setattr(browser, "game_targets", targets)
    answers(monkeypatch, ["2", "1", "W", "1", "1", "G", "Q"])
    assert browser.run_browser(source=str(owner.gamedat), npc=1) == 0
    assert games == ["si", "bg"]
    assert capsys.readouterr().out.count("NPC 1: Iolo") == 1


@pytest.mark.parametrize("query", ["Devon", "234"])
def test_next_npc_after_single_search_result_moves_to_adjacent_record(
    owner, monkeypatch, capsys, query
):
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    template = session.npcs.npcs[0]
    session.npcs.npcs = [
        replace(template, npc_num=i, name=name)
        for i, name in [(233, "Total"), (234, "Devon"), (235, "Malchir"), (236, "Kith")]
    ]
    answers(monkeypatch, ["S", query, "234", "N", "B", "B", "Q"])
    assert browser._browse_npcs(session) == "Q"
    output = capsys.readouterr().out
    assert "NPC 235: Malchir" in output
    assert "NPC 233: Total" in output
    assert "Next NPC (#235 Malchir)" in output
    assert "Previous NPC (#233 Total)" in output
    assert "Search applies to the selection list" in output


def test_next_npc_respects_filter_but_not_the_search(owner, monkeypatch, capsys):
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    # ID 2 matches the text search, but is not in the party.
    session.npcs.npcs[1].name = "Chosen"
    session.npcs.npcs[2].name = "Chosen Other"
    answers(monkeypatch, ["F", "P", "S", "Chosen", "1", "N", "Q"])
    assert browser._browse_npcs(session) == "Q"
    output = capsys.readouterr().out
    assert "NPC 0: Avatar" in output and "NPC 2: Chosen Other" not in output


def test_single_npc_filter_explains_why_next_cannot_move(owner, monkeypatch, capsys):
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    answers(monkeypatch, ["F", "D", "3", "N", "Q"])
    assert browser._browse_npcs(session) == "Q"
    assert "Only one NPC matches the current filter" in capsys.readouterr().out


def test_all_npc_selection_menus_request_hotkeys(owner, monkeypatch):
    seen = []

    def choose(prompt, choices, default, **kwargs):
        seen.append(kwargs)
        return default

    monkeypatch.setattr(ui, "choice", choose)
    for prompt, labels in [
        ("NPC page", {"234": "Devon", "N": "Next page", "S": "Search"}),
        ("Save page", {"10": "save", "N": "Next page"}),
        ("Source", {"I": "Initial", "G": "GAMEDAT"}),
        ("Filter", {"A": "All", "P": "Party"}),
        ("Inventory", {"10": "bag", "U": "Up", "N": "Next page"}),
        ("Export", {"J": "JSON", "T": "Text"}),
    ]:
        browser._menu(prompt, labels, next(iter(labels)))
    assert all(item["hotkeys"] for item in seen)


def test_details_schedules_and_terminal_controls(owner):
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    npc = session.npcs.npcs[1]
    npc.name = "Iolo\x1b[31m"
    assert "\x1b" not in browser.npc_detail(session, npc)
    assert "tile" in browser.npc_detail(session, npc)
    assert "06:00-08:59" in browser.schedules_text(session, npc)
    assert "301, 402, 3" in browser.schedules_text(session, npc)
    assert "No daily schedule entries" in browser.schedules_text(
        session, session.npcs.npcs[0]
    )


def sprite_bytes(frame16=5, frames=18):
    shape = U7Shape()
    for number in range(frames):
        frame = U7Shape.Frame()
        frame.width, frame.height = 3, 2
        frame.pixels = np.full((2, 3), frame16 if number == 16 else 6, dtype=np.uint8)
        frame.pixels[0, 0] = 255
        shape.frames.append(frame)
    return shape.to_bytes()


@pytest.fixture
def npc_art(owner, monkeypatch):
    write_flex(
        owner.static / "SHAPES.VGA",
        [bytes(64)] * 150 + [sprite_bytes(5), sprite_bytes(7)],
    )
    palette = bytearray(768)
    palette[5 * 3 : 5 * 3 + 3] = bytes([63, 0, 0])
    palette[6 * 3 : 6 * 3 + 3] = bytes([0, 0, 63])
    palette[7 * 3 : 7 * 3 + 3] = bytes([0, 63, 0])
    write_flex(owner.static / "PALETTES.FLX", [bytes(palette)])
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    images = []
    # Scope the TTY stub to this module; capsys may replace global stdout.
    monkeypatch.setattr(
        browser, "sys", SimpleNamespace(stdout=SimpleNamespace(isatty=lambda: True))
    )
    monkeypatch.setattr(
        browser,
        "terminal_image",
        lambda image, **kwargs: images.append((image, kwargs)),
    )
    return session, images


def test_npc_preview_uses_shape_frame_16_and_main_palette_with_transparency(
    npc_art, capsys
):
    session, images = npc_art
    npc = session.npcs.npcs[0]
    npc.frame = 3  # The requested pose is frame 16, independent of saved frame.
    browser.npc_preview(session, npc)
    image, kwargs = images[0]
    assert image.mode == "RGBA"
    assert image.getpixel((1, 0)) == (255, 0, 0, 255)
    assert image.getpixel((0, 0))[3] == 0
    assert kwargs == {"reserved_rows": 20}
    assert "shape 150, frame 16" in capsys.readouterr().out


def test_npc_preview_inherits_empty_exult_patch_shapes_and_palette_slots(npc_art):
    session, images = npc_art
    write_flex(session.target.patch / "shapes.vga", [b""] * 151 + [sprite_bytes(6)])
    write_flex(session.target.patch / "PALETTES.FLX", [b""])
    before = {
        path: path.read_bytes()
        for directory in (session.target.static, session.target.patch)
        for path in directory.iterdir()
    }
    npc = session.npcs.npcs[0]
    browser.npc_preview(session, npc)
    browser.npc_preview(session, replace(npc, shape=151))
    assert images[0][0].getpixel((1, 0)) == (255, 0, 0, 255)
    assert images[1][0].getpixel((1, 0)) == (0, 0, 255, 255)
    assert (
        session.preview_library.palette_path == session.target.static / "PALETTES.FLX"
    )
    assert all(path.read_bytes() == data for path, data in before.items())


def test_npc_preview_reuses_world_library_when_moving_to_another_npc(
    npc_art, monkeypatch
):
    session, images = npc_art
    calls = []
    load = browser.load_library

    def counted(*args, **kwargs):
        calls.append(args)
        return load(*args, **kwargs)

    monkeypatch.setattr(browser, "load_library", counted)
    session.npcs.npcs[1].shape = 151
    answers(monkeypatch, ["N", "Q"])
    assert browser._browse_npcs(session, 0) == "Q"
    assert len(calls) == 1 and len(images) == 2
    assert images[0][0].getpixel((1, 0)) == (255, 0, 0, 255)
    assert images[1][0].getpixel((1, 0)) == (0, 255, 0, 255)


@pytest.mark.parametrize(
    "problem",
    [
        "missing_frame",
        "empty_shape",
        "corrupt_shape",
        "missing_palette",
        "missing_archive",
        "identity_mismatch",
    ],
)
def test_unavailable_npc_art_keeps_details_and_navigation_working(
    npc_art, monkeypatch, capsys, problem
):
    session, images = npc_art
    if problem == "missing_frame":
        write_flex(
            session.target.static / "SHAPES.VGA", [b""] * 150 + [sprite_bytes(frames=2)]
        )
    elif problem == "empty_shape":
        session.npcs.npcs[0].shape = 149
        write_flex(session.target.static / "SHAPES.VGA", [b""] * 152)
    elif problem == "corrupt_shape":
        write_flex(
            session.target.static / "SHAPES.VGA", [b""] * 150 + [b"invalid shape"]
        )
    elif problem == "missing_palette":
        (session.target.static / "PALETTES.FLX").unlink()
    elif problem == "missing_archive":
        (session.target.static / "SHAPES.VGA").unlink()
    else:
        session.preview_error = "Choose the world matching this save's game identity."
    answers(monkeypatch, ["Q"])
    assert browser._browse_npcs(session, 0) == "Q"
    output = capsys.readouterr().out
    assert "NPC 0: Avatar" in output and "NPC preview unavailable:" in output
    assert not images
    if problem == "missing_frame":
        assert "frame 16 is unavailable" in output


def test_redirected_output_never_loads_preview_art(npc_art, monkeypatch):
    session, images = npc_art
    monkeypatch.setattr(browser.sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(
        browser,
        "load_library",
        lambda *args, **kwargs: pytest.fail("redirected output loaded art"),
    )
    browser.npc_preview(session, session.npcs.npcs[0])
    assert not images and session.preview_library is None


def test_failed_world_art_load_is_not_retried_for_each_npc(npc_art, monkeypatch):
    session, images = npc_art
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(args)
        raise ValueError("Missing palette")

    monkeypatch.setattr(browser, "load_library", unavailable)
    browser.npc_preview(session, session.npcs.npcs[0])
    browser.npc_preview(session, session.npcs.npcs[1])
    assert len(calls) == 1 and not images


def test_plain_npc_flow_search_details_inventory_schedules_back(
    owner, monkeypatch, capsys
):
    answers(
        monkeypatch,
        [
            "2",
            "1",
            "G",
            "S",
            "Iolo",
            "1",
            "T",
            "Q",
            "I",
            "Q",
            "N",
            "B",
            "S",
            "F",
            "P",
            "0",
            "O",
            "Q",
        ],
    )
    assert browser.run_browser() == 0
    output = capsys.readouterr().out
    assert "NPC 1: Iolo" in output and "NPC 2: Iolo Junior" in output
    assert "Daily schedules" in output and "Inventory and nested contents" in output
    assert "preferred slot" not in output or "not proof" in output


def test_plain_save_flow_selects_owner_save_and_lists_files(owner, monkeypatch, capsys):
    write_save(
        owner.save_root / "exult00.sav",
        {"npc.dat": npcs_bytes(), "schedule.dat": schedules_bytes()},
        title="My mod save",
    )
    answers(monkeypatch, ["2", "1", "S", "1", "F", "Q", "N", "0", "Q"])
    assert browser.run_browser(saves=True) == 0
    output = capsys.readouterr().out
    assert "My mod save" in output and "Source files" in output
    assert "NPC 0: Avatar" in output


def test_cli_help_and_initial_source_npc_number(owner, monkeypatch):
    runner = CliRunner()
    for command in ("npc-browse", "save-browse"):
        result = runner.invoke(u7_app, [command, "--help"])
        assert result.exit_code == 0
        assert "--game" in result.output
    answers(monkeypatch, ["2", "1", "Q"])
    result = runner.invoke(
        u7_app, ["npc-browse", str(owner.gamedat), "--game", "si", "--npc", "1"]
    )
    assert result.exit_code == 0
    assert "NPC 1: Iolo" in result.output


def test_bad_source_retries_and_cancel_returns_success(
    owner, monkeypatch, tmp_path, capsys
):
    path = tmp_path / "corrupt.sav"
    path.write_bytes(b"wrong")
    answers(monkeypatch, ["2", "1", "G", "Q"])
    assert browser.run_browser(source=str(path)) == 0
    assert "ERROR:" in capsys.readouterr().out
    monkeypatch.setattr(
        "builtins.input", lambda prompt="": (_ for _ in ()).throw(EOFError())
    )
    assert browser.run_browser() == 0


def test_exports_nested_json_and_never_overwrites_sources(owner, monkeypatch, tmp_path):
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    npc = session.npcs.npcs[1]
    npc.inventory = [U7NPCInventoryItem(6, 0, 0, 0, 0, 2, 1, "5:0/6:0")]
    output = tmp_path / "reports" / "iolo.json"
    answers(monkeypatch, ["J", str(output)])
    browser._export(session, [npc], npc)
    report = json.loads(output.read_text())
    assert report["npc"]["npc_num"] == 1
    assert report["inventory"][0]["path"] == "5:0/6:0"
    assert report["schedules"][0]["tx"] == 301
    answers(monkeypatch, ["J", str(output)])
    with pytest.raises(FileExistsError):
        browser._export(session, [npc], npc)
    for path in (
        owner.gamedat / "NPC.DAT",
        owner.patch / "report.json",
        owner.static / "report.json",
    ):
        answers(monkeypatch, ["J", str(path)])
        with pytest.raises(ValueError, match="outside the game archives"):
            browser._export(session, [npc], npc)


@pytest.mark.parametrize(
    "action,suffix", [("N", ".csv"), ("I", ".csv"), ("S", ".csv"), ("T", ".txt")]
)
def test_other_report_formats(owner, monkeypatch, tmp_path, action, suffix):
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    output = tmp_path / f"report_{action}{suffix}"
    answers(monkeypatch, [action, str(output)])
    browser._export(session, [session.npcs.npcs[1]], session.npcs.npcs[1])
    content = output.read_text()
    assert content
    if action in {"N", "S"}:
        assert "Iolo" in content and "Avatar" not in content


def test_detail_actions_use_native_immediate_hotkeys(owner, monkeypatch):
    session = browser.load_session(owner, browser.Source(owner.gamedat, "live"), "si")
    seen = []

    def choose(prompt, choices, default, **kwargs):
        seen.append(kwargs)
        return "Q"

    monkeypatch.setattr(ui, "choice", choose)
    assert browser._browse_npcs(session, 1) == "Q"
    assert seen[0]["hotkeys"] is True
    assert {"N", "B", "S", "I", "T", "E", "D", "W", "Q"} <= set(seen[0]["labels"])
