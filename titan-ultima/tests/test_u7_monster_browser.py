"""Monster source ownership, UI navigation, equipment and safe reports."""

from __future__ import annotations

import csv
import io
import json
import struct
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from typer.testing import CliRunner

from titan import _wizard_ui as ui
from titan.u7 import monster_browser as browser
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.cli import u7_app
from titan.u7.flex import U7FlexArchive
from titan.u7.monster import U7WeaponInfos, monster_equipment_rows
from titan.u7.npc_browser import Source
from titan.u7.shape import U7Shape


def write_flex(path, entries, magic=0xCC):
    archive = U7FlexArchive()
    archive.records, archive.magic2 = list(entries), magic
    path.write_bytes(archive.to_bytes())


def definition(shape, strength=10, *, equip=1, deleted=False):
    raw = bytearray(25)
    struct.pack_into("<H", raw, 0, shape)
    raw[2:7] = bytes([strength << 2, 12 << 2, 8 << 2, (9 << 2) | 2, 0x20])
    raw[8:12] = bytes([0x31, 4, 2, 4])
    raw[13:16] = bytes([1, equip, 3])
    raw[24] = 255 if deleted else 0
    return bytes(raw)


def weapon(shape, ammo, *, deleted=False):
    payload = bytearray(19)
    struct.pack_into("<h", payload, 0, ammo)
    payload[-1] = 255 if deleted else 0
    return struct.pack("<H", shape) + payload


def equipment(item=160):
    raw = bytearray(60)
    struct.pack_into("<HBB", raw, 0, item, 50, 4)
    struct.pack_into("<HBB", raw, 6, 161, 100, 1)
    return b"\x01" + bytes(raw)


def actor(shape=150, *, health=25, dead=False):
    raw = bytearray(117)
    struct.pack_into("<H", raw, 2, shape)
    raw[6:8] = bytes([13, 2])
    struct.pack_into("<H", raw, 8, 3 << 12)
    raw[10] = health
    struct.pack_into("<H", raw, 14, 1)
    struct.pack_into("<H", raw, 16, (1 << 15) if dead else 0)
    raw[18:24] = bytes([22, 21, 20, 19, 6, 1])
    return bytes(raw)


def actors():
    return (
        struct.pack("<H", 3)
        + actor(150)
        + actor(150, health=12)
        + actor(151, dead=True)
    )


def sprite(frames=17):
    shape = U7Shape()
    for i in range(frames):
        frame = U7Shape.Frame()
        frame.width, frame.height = 3, 2
        frame.pixels = np.full((2, 3), 5 if i == 16 else 6, dtype=np.uint8)
        frame.pixels[0, 0] = 255
        shape.frames.append(frame)
    return shape.to_bytes()


def write_save(path, entries, kind="zip"):
    if kind == "flex":
        write_flex(
            path,
            [name.encode().ljust(13, b"\x00") + blob for name, blob in entries.items()],
        )
        return
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        if kind == "level2":
            grouped = b"".join(
                name.encode().ljust(12, b"\x00") + struct.pack("<I", len(blob)) + blob
                for name, blob in entries.items()
            )
            archive.writestr("gamedat", grouped + bytes(16))
        else:
            for name, blob in entries.items():
                archive.writestr(name, blob)
    path.write_bytes(
        (b"" if kind == "raw" else b"A monster save".ljust(80, b"\x00"))
        + output.getvalue()
    )


@pytest.fixture
def owner(tmp_path, monkeypatch):
    static, patch, gamedat, saves = [
        tmp_path / n for n in ("STATIC", "patch", "gamedat", "saves")
    ]
    for path in (static, patch, gamedat, saves):
        path.mkdir()
    (static / "MONSTERS.DAT").write_bytes(
        definition(150) + definition(151, 20) + definition(152, 30, equip=0)
    )
    (static / "EQUIP.DAT").write_bytes(equipment())
    (static / "WEAPONS.DAT").write_bytes(b"\x01" + weapon(161, 162))
    tfa = bytearray(164 * 3)
    for number in (150, 151, 152):
        tfa[number * 3 + 1] = 12
    tfa[160 * 3 + 1], tfa[163 * 3 + 1] = 3, 6
    (static / "TFA.DAT").write_bytes(tfa)
    names = [b""] * 164
    for number, name in [
        (150, "goblin"),
        (151, "troll"),
        (152, "golem"),
        (160, "coins"),
        (161, "bow"),
        (162, "arrows"),
        (163, "bag"),
    ]:
        names[number] = name.encode() + b"\x00"
    write_flex(static / "TEXT.FLX", names)
    write_flex(
        static / "SHAPES.VGA",
        [bytes(64)] * 150 + [sprite(), sprite(2), sprite(1)] + [b""] * 11,
    )
    palette = bytearray(768)
    palette[15:18], palette[18:21] = bytes([63, 0, 0]), bytes([0, 0, 63])
    write_flex(static / "PALETTES.FLX", [bytes(palette)])
    (gamedat / "MONSNPCS.DAT").write_bytes(actors())
    target = ArchiveTarget(
        "Test SI mod", static, patch, root=tmp_path, gamedat=gamedat, save_root=saves
    )
    monkeypatch.setattr(browser, "game_targets", lambda game: (target, []))
    monkeypatch.setattr(ui, "menus_enabled", lambda: False)
    return target


def answers(monkeypatch, sequence):
    pending = iter(sequence)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(pending))


def definitions(owner):
    return browser.load_session(
        owner, Source(owner.static / "MONSTERS.DAT", "definitions"), "si"
    )


def live(owner):
    return browser.load_session(owner, Source(owner.gamedat, "live"), "si")


def test_base_plus_sparse_patch_definitions_and_deletions(owner):
    (owner.patch / "monsters.dat").write_bytes(
        b"\x01"
        + definition(150, 40)
        + definition(151, deleted=True)
        + definition(155, 15)
    )
    session = definitions(owner)
    assert [e.shape for e in session.records] == [150, 152, 155]
    assert session.records[0].definition.strength == 40
    assert session.records[0].definition.source_file == str(
        owner.patch / "monsters.dat"
    )
    assert session.records[1].definition.source_file == str(
        owner.static / "MONSTERS.DAT"
    )


def test_foreign_definition_file_does_not_inherit_owner_definitions(owner, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    path = other / "MONSTERS.DAT"
    path.write_bytes(definition(190))
    session = browser.load_session(owner, Source(path, "definitions"), "si")
    assert [e.shape for e in session.records] == [190]


def test_missing_explicit_source_is_rejected(owner, tmp_path):
    with pytest.raises(ValueError, match="Source not found"):
        browser.load_session(
            owner, Source(tmp_path / "missing" / "MONSTERS.DAT", "definitions"), "si"
        )


def test_standalone_world_without_retail_base(owner):
    target = replace(owner, static=None)
    for name in ("MONSTERS.DAT", "EQUIP.DAT"):
        (owner.patch / name).write_bytes((owner.static / name).read_bytes())
    session = browser.load_session(
        target, Source(owner.patch / "MONSTERS.DAT", "definitions"), "si"
    )
    assert [e.shape for e in session.records] == [150, 151, 152]


def test_equipment_chances_quantity_and_generated_ammo_reuse_existing_rules(owner):
    session = definitions(owner)
    rows = browser.possible_equipment(session, session.records[0])
    coins = next(row for row in rows if row["item_shape"] == 160)
    assert coins["min_quantity_if_created"] == 1
    assert coins["max_quantity_if_created"] == 4
    assert coins["probability"] == 50
    ammunition = next(row for row in rows if row["generated"])
    assert ammunition["item_shape"] == 162
    assert ammunition["quantity"] == "2d10"
    assert rows == [
        r
        for r in monster_equipment_rows(str(owner.static), "si")
        if r["monster_shape"] == 150
    ]


def test_owner_patch_equipment_and_sparse_weapon_deletions(owner):
    (owner.patch / "equip.dat").write_bytes(equipment(162))
    (owner.patch / "weapons.dat").write_bytes(b"\x01" + weapon(161, -1, deleted=True))
    session = definitions(owner)
    rows = browser.possible_equipment(session, session.records[0])
    assert session.equipment.source_file == str(owner.patch / "equip.dat")
    assert rows[0]["item_shape"] == 162
    assert not any(row["generated"] for row in rows)


def test_sparse_weapon_patch_preserves_other_base_weapons():
    base = U7WeaponInfos.from_bytes(b"\x02" + weapon(100, 200) + weapon(101, 201))
    patch = U7WeaponInfos.from_bytes(b"\x01" + weapon(100, 202))
    merged = U7WeaponInfos.merge(base, patch)
    assert merged.ammo_for_weapon(100) == 202
    assert merged.ammo_for_weapon(101) == 201
    assert base.ammo_for_weapon(100) == 200


@pytest.mark.parametrize(
    "name,data",
    [
        ("MONSTERS.DAT", bytes(24)),
        ("EQUIP.DAT", b"\x01" + bytes(59)),
        ("WEAPONS.DAT", b"\xff\x01"),
    ],
)
def test_incomplete_owner_tables_are_visible(owner, name, data):
    (owner.patch / name).write_bytes(data)
    session = definitions(owner)
    assert "incomplete" in session.overview().lower()
    if name == "MONSTERS.DAT":
        assert not session.records
    if name == "EQUIP.DAT":
        assert session.equipment is None


@pytest.mark.parametrize("kind", ["flex", "zip", "raw", "level2"])
def test_saved_monsters_use_only_selected_save_and_keep_source_indices(owner, kind):
    path = owner.save_root / "monsters.sav"
    write_save(path, {"MONSNPCS.DAT": actors(), "identity": b"MYMOD"}, kind)
    original = path.read_bytes()
    session = browser.load_session(owner, Source(path, "save"), "si")
    assert len(session.records) == 3
    assert [e.number for e in session.records] == [0, 1, 2]
    assert session.records[1].actor.health == 12
    assert session.records[2].actor.is_dead
    assert session.identity == "MYMOD"
    assert path.read_bytes() == original


def test_missing_saved_monsters_do_not_inherit_live_data(owner):
    path = owner.save_root / "empty.sav"
    write_save(path, {"identity": b"MYMOD"})
    session = browser.load_session(owner, Source(path, "save"), "si")
    assert not session.records
    assert "monsnpcs.dat is not present" in session.overview()
    assert "no monsters are inherited" in session.overview()


def test_case_insensitive_live_and_loose_monster_sources(owner):
    session = live(owner)
    assert [e.actor.health for e in session.records] == [25, 12, 25]
    loose = browser.load_session(owner, Source(owner.gamedat / "MONSNPCS.DAT"), "si")
    assert [e.shape for e in loose.records] == [150, 150, 151]


def test_partial_monster_records_produce_diagnostic(owner):
    (owner.gamedat / "MONSNPCS.DAT").write_bytes(struct.pack("<H", 3) + actor())
    session = live(owner)
    assert len(session.records) == 1
    assert "parsed 1 of 3" in session.overview()


def test_valid_empty_monster_table_is_not_reported_as_missing(owner):
    (owner.gamedat / "MONSNPCS.DAT").write_bytes(bytes(2))
    session = live(owner)
    assert session.records == []
    assert "monsnpcs.dat is not present" not in session.overview()


def test_expansion_identity_is_checked_against_selected_game_flavour(owner):
    (owner.gamedat / "identity").write_bytes(b"SILVER SEED")
    session = browser.load_session(owner, Source(owner.gamedat, "live"), "bg")
    assert not session.world_matches
    assert all(e.definition is None for e in session.records)


def test_world_identity_mismatch_disables_foreign_definitions_and_preview(owner):
    (owner.gamedat / "identity").write_bytes(b"BLACKGATE")
    session = live(owner)
    assert len(session.records) == 3
    assert all(e.definition is None for e in session.records)
    assert not session.equipment_rows
    assert not session.world_matches
    assert session.preview_error
    with pytest.raises(ValueError, match="identity"):
        browser.spawn_rows(session, 150)


def test_search_by_shape_hex_name_and_live_instance(owner):
    session = live(owner)
    assert [e.number for e in browser.filter_entries(session, "150")] == [0, 1]
    assert [e.number for e in browser.filter_entries(session, "0x96")] == [0, 1]
    assert [e.number for e in browser.filter_entries(session, "gObLiN")] == [0, 1]
    assert [e.number for e in browser.filter_entries(session, "#1")] == [1]
    assert [e.number for e in browser.filter_entries(session, mode="dead")] == [2]
    assert [e.number for e in browser.filter_entries(session, mode="alive")] == [0, 1]


def test_cli_definition_navigation_after_single_search_is_not_trapped(
    owner, monkeypatch
):
    answers(monkeypatch, ["2", "1", "D", "S", "goblin", "150", "N", "B", "Q"])
    result = CliRunner().invoke(u7_app, ["monster-browse"])
    assert result.exit_code == 0, result.output
    assert "shape 151" in result.output
    assert result.output.count("definition: goblin") == 2
    assert "Next monster (151: troll)" in result.output


def test_cli_live_next_monster_distinguishes_same_shape_instances(owner, monkeypatch):
    answers(monkeypatch, ["2", "1", "G", "0", "N", "N", "Q"])
    result = CliRunner().invoke(u7_app, ["monster-browse"])
    assert result.exit_code == 0, result.output
    assert "instance #0: goblin" in result.output
    assert "instance #1: goblin" in result.output
    assert "instance #2: troll" in result.output


def test_cli_paging_and_filter_hotkeys(owner, monkeypatch):
    monkeypatch.setattr(browser, "PAGE_SIZE", 1)
    answers(monkeypatch, ["2", "1", "G", "N", "B", "F", "D", "2", "N", "Q"])
    result = CliRunner().invoke(u7_app, ["monster-browse"])
    assert result.exit_code == 0, result.output
    assert "Next page" in result.output and "Previous page" in result.output
    assert "Only one monster matches this filter" in result.output


def test_cli_source_switch_from_definitions_to_save(owner, monkeypatch):
    path = owner.save_root / "test.sav"
    write_save(path, {"monsnpcs.dat": actors()})
    answers(monkeypatch, ["2", "1", "D", "D", "S", "1", "0", "Q"])
    result = CliRunner().invoke(u7_app, ["monster-browse"])
    assert result.exit_code == 0, result.output
    assert "saved/live monster instances" in result.output
    assert "Actor source:" in result.output


def test_unavailable_spawn_data_keeps_current_monster_and_navigation(
    owner, monkeypatch, capsys
):
    session = definitions(replace(owner, gamedat=None))
    answers(monkeypatch, ["G", "0", "N", "Q"])
    assert browser.browse(session, 150) == "Q"
    output = capsys.readouterr().out
    assert "No live GAMEDAT" in output
    assert "definition: troll" in output


def test_cli_initial_source_and_shape_and_help(owner, monkeypatch):
    answers(monkeypatch, ["2", "1", "Q"])
    result = CliRunner().invoke(
        u7_app,
        [
            "monster-browse",
            str(owner.static / "MONSTERS.DAT"),
            "--game",
            "si",
            "--shape",
            "151",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "definition: troll" in result.output
    help_result = CliRunner().invoke(u7_app, ["monster-browse", "--help"])
    assert help_result.exit_code == 0
    assert "--shape" in help_result.output
    assert "monsnpcs.dat" in help_result.output


def test_possible_equipment_is_separate_from_actual_inventory(owner, monkeypatch):
    answers(monkeypatch, ["2", "1", "G", "0", "T", "Q", "I", "Q", "Q"])
    result = CliRunner().invoke(u7_app, ["monster-browse"])
    assert result.exit_code == 0, result.output
    assert "chances do not describe this actor's actual inventory" in result.output
    assert "coins: 50% chance; quantity 1-4" in result.output
    assert "Actual inventory: 0" in result.output
    assert "Back to monster" in result.output


@pytest.fixture
def art(owner, monkeypatch):
    images = []
    monkeypatch.setattr(
        browser, "sys", SimpleNamespace(stdout=SimpleNamespace(isatty=lambda: True))
    )
    monkeypatch.setattr(
        browser, "terminal_image", lambda image, **kwargs: images.append(image)
    )
    return definitions(owner), images


def test_preview_standing_pose_transparency_and_short_shape_fallback(art):
    session, images = art
    assert browser.preview(session, session.records[0]) == 16
    assert images[0].getpixel((1, 0)) == (255, 0, 0, 255)
    assert images[0].getpixel((0, 0))[3] == 0
    assert browser.preview(session, session.records[1]) == 0
    assert images[1].getpixel((1, 0)) == (0, 0, 255, 255)


def test_preview_owner_sparse_patch_and_cache(art):
    session, images = art
    write_flex(session.target.patch / "shapes.vga", [b""] * 150 + [sprite(2)], 0xCC01)
    write_flex(session.target.patch / "palettes.flx", [b""])
    assert browser.preview(session, session.records[0]) == 0
    first = session.preview_library
    assert browser.preview(session, session.records[1]) == 0
    assert session.preview_library is first
    assert images[0].getpixel((1, 0)) == (0, 0, 255, 255)


def test_preview_missing_palette_keeps_details_available(art, capsys):
    session, images = art
    (session.target.static / "PALETTES.FLX").unlink()
    assert browser.preview(session, session.records[0]) is None
    assert not images
    assert "preview unavailable" in capsys.readouterr().out
    assert "Base stats: STR 10" in browser.detail(session, session.records[0])


def test_redirected_preview_does_not_load_art(owner, monkeypatch):
    session = definitions(owner)
    monkeypatch.setattr(
        browser, "sys", SimpleNamespace(stdout=SimpleNamespace(isatty=lambda: False))
    )
    monkeypatch.setattr(
        browser, "load_library", lambda *_: pytest.fail("loaded redirected artwork")
    )
    assert browser.preview(session, session.records[0]) is None


def test_cli_frame_hotkeys_and_playback_use_same_shape_provider(
    art, monkeypatch, capsys
):
    session, images = art
    playback = []
    monkeypatch.setattr(
        browser,
        "play_terminal",
        lambda provider, **kwargs: playback.append(provider(0, 0)[0]),
    )
    answers(monkeypatch, ["F", "P", "Q"])
    assert browser.browse(session, 151) == "Q"
    assert len(playback) == 1
    assert "frame 0" in capsys.readouterr().out
    assert len(images) == 3


def test_related_eggs_use_selected_save_maps_without_extracting_other_entries(
    owner, monkeypatch, tmp_path
):
    from titan.u7.eggs import EggResult
    from titan.u7.map import EggMeta, U7MapObject

    path = owner.save_root / "eggs.sav"
    write_save(
        path,
        {
            "monsnpcs.dat": actors(),
            "map01/U7IREG00": b"saved-map",
            "U7IREG00": b"saved-zero",
            "../../escape": b"bad",
        },
    )
    session = browser.load_session(owner, Source(path, "save"), "si")
    calls = []

    def query(params):
        root = Path(params.gamedat_dir)
        calls.append(root)
        assert params.map_num == 1
        assert (root / "map01" / "u7ireg00").read_bytes() == b"saved-map"
        assert not (root / "u7ireg00").exists()
        assert params.patch_dir == str(owner.patch)
        meta = EggMeta(
            egg_type=1,
            probability=50,
            criteria=0,
            distance=2,
            data1=4,
            data2=150,
            nocturnal=False,
            once=False,
            hatched=False,
            auto_reset=False,
        )
        return [EggResult(U7MapObject(12, 13, 0, 275, 0, egg_meta=meta), 0)]

    monkeypatch.setattr(browser, "query_eggs", query)
    rows = browser.spawn_rows(session, 150, 1)
    assert rows[0]["source"] == str(path)
    assert rows[0]["map_num"] == 1
    assert rows[0]["monster_shape"] == 150
    assert browser.spawn_rows(session, 151, 1) == []
    assert len(calls) == 1
    assert not calls[0].exists()


def test_save_without_ireg_does_not_scan_owner_gamedat(owner, monkeypatch):
    path = owner.save_root / "no-eggs.sav"
    write_save(path, {"monsnpcs.dat": actors()})
    session = browser.load_session(owner, Source(path, "save"), "si")

    def query(params):
        assert Path(params.gamedat_dir) != owner.gamedat
        assert list(Path(params.gamedat_dir).rglob("*")) == []
        return []

    monkeypatch.setattr(browser, "query_eggs", query)
    assert browser.spawn_rows(session, 150) == []


def test_spawn_map_menu_includes_stored_extra_maps(owner, monkeypatch):
    path = owner.save_root / "map.sav"
    write_save(path, {"monsnpcs.dat": actors(), "map01/u7ireg00": b""})
    session = browser.load_session(owner, Source(path, "save"), "si")
    answers(monkeypatch, ["1"])
    assert browser._spawn_map(session, session.records[0]) == 1


@pytest.mark.parametrize(
    "monster_shape,frame,extended,wire_extended",
    [(150, 5, False, False), (1078, 17, True, False), (4095, 200, True, True)],
)
def test_related_eggs_decode_real_retail_and_exult_monster_records(
    owner, monster_shape, frame, extended, wire_extended
):
    adj = int(wire_extended)
    payload = bytearray((14 if extended else 12) + adj)
    payload[0:4] = bytes([1, 2, 275 & 255, 275 >> 8])
    struct.pack_into("<H", payload, 4 + adj, 1)
    payload[6 + adj] = 60
    struct.pack_into("<H", payload, 7 + adj, (6 << 8) | (3 << 2) | 2)
    struct.pack_into(
        "<H", payload, 10 + adj, frame if extended else monster_shape | (frame << 10)
    )
    if extended:
        struct.pack_into("<H", payload, 12 + adj, monster_shape)
    prefix = (b"\xfe" if wire_extended else b"") + bytes([len(payload)])
    (owner.gamedat / "U7IREG00").write_bytes(prefix + payload)
    rows = browser.spawn_rows(live(owner), monster_shape)
    assert len(rows) == 1
    assert rows[0]["monster_shape"] == monster_shape
    assert rows[0]["monster_frame"] == frame
    assert rows[0]["count"] == 3
    assert rows[0]["schedule"] == 6
    assert rows[0]["alignment"] == 2
    assert rows[0]["probability"] == 60


def test_json_export_separates_base_stats_possible_equipment_and_actual_actor(
    owner, monkeypatch, tmp_path
):
    session = live(owner)
    path = tmp_path / "reports" / "goblin.json"
    answers(monkeypatch, ["J", str(path)])
    browser._export(session, session.records, session.records[1])
    data = json.loads(path.read_text())
    assert data["record_number"] == 1
    assert data["definition"]["strength"] == 10
    assert data["actual_actor"]["strength"] == 22
    assert data["actual_inventory"] == []
    assert data["possible_spawn_equipment"]


def test_filtered_actor_csv_keeps_original_instance_number(
    owner, monkeypatch, tmp_path
):
    session = live(owner)
    path = tmp_path / "filtered.csv"
    answers(monkeypatch, ["C", str(path)])
    browser._export(session, browser.filter_entries(session, "#1"))
    rows = list(csv.DictReader(io.StringIO(path.read_text())))
    assert len(rows) == 1
    assert rows[0]["live_index"] == "1"
    assert rows[0]["name"] == "goblin"


@pytest.mark.parametrize(
    "location", ["static", "patch", "gamedat", "source", "existing"]
)
def test_report_exports_cannot_change_game_data_or_existing_files(
    owner, tmp_path, location
):
    session = live(owner)
    path = (
        tmp_path / "existing.json"
        if location == "existing"
        else session.source.path / "MONSNPCS.DAT"
        if location == "source"
        else getattr(owner, location) / "report.json"
    )
    if location == "existing":
        path.write_text("original")
    original = path.read_bytes() if path.exists() else None
    with pytest.raises((ValueError, FileExistsError)):
        browser.write_report(session, path, "changed")
    assert (path.read_bytes() if path.exists() else None) == original


def test_eof_cancel_is_clean(owner, monkeypatch):
    def cancel(*_):
        raise EOFError

    monkeypatch.setattr("builtins.input", cancel)
    assert browser.run_browser() == 0
