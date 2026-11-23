"""Flavors: one model for every game (``titan._meta.list_flavors``)."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest

from titan import _config, _meta, _stores
from titan._meta import InstallSource
from titan.u7.flex import U7FlexArchive
from titan.u8.save import U8SaveArchive


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep flavors away from real installs, Exult, Pentagram and ScummVM settings."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(_config, "_config", {})
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("TITAN_DATA", str(tmp_path / "data"))
    monkeypatch.setattr("titan.u7.install.exult_game_paths", lambda game: {})
    monkeypatch.setattr("titan.u7.flavors.exult_game_paths", lambda game: {})
    monkeypatch.setattr("titan.u7.install.find_exult_cfg", lambda *a, **k: None)
    return tmp_path


def test_families_group_u7_and_every_game_once() -> None:
    families = dict(_meta.families())
    assert [g.id for g in families["u7"]] == ["u7bg", "u7si"]
    assert sorted(g.id for games in families.values() for g in games) == sorted(
        g.id for g in _meta.GAMES
    )


def test_every_game_lists_flavors_and_providers_load(workspace: Path) -> None:
    for game in _meta.GAMES:
        assert _meta.list_flavors(game.id, {}) == [], game.id
        if game.flavors:
            assert hasattr(import_module(game.flavors), "list_flavors"), game.flavors


def _martian(folder: Path) -> Path:
    data = folder / "MARTIAN"
    data.mkdir(parents=True)
    for name in ("MDPAL", "CHUNKS", "MAPTILES.VGA", "MAP"):
        (data / name).write_bytes(b"\0")
    return data


def test_default_flavors_cover_configured_and_store_installs(
    workspace, monkeypatch
) -> None:
    mine = _martian(workspace / "Mine")
    steam = workspace / "steamapps/common/Martian Dreams"
    _martian(steam)
    record = InstallSource(
        "steam", "77", "Worlds of Ultima: Martian Dreams", steam, "steam-manifest"
    )
    monkeypatch.setattr(_stores, "store_records", lambda config=None: [record])
    config = {"md": {"game": {"base": str(mine)}}}

    configured, store = _meta.list_flavors("md", config)
    assert (configured.key, configured.default, dict(configured.config)) == (
        "configured",
        True,
        {},
    )
    assert (store.key, store.title, store.default) == ("steam:77", "Steam", False)
    assert (
        Path(_meta.flavor_config(store, config)["md"]["game"]["base"])
        == store.install.root
    )


def test_flavor_config_lays_keys_over_the_users() -> None:
    flavor = _meta.Flavor(
        "u8", "x", "X", "engine", config={"u8": {"paths": {"savegame": "S"}}}
    )
    config = {
        "u8": {"game": {"base": "B"}, "paths": {"fixed": "F", "savegame": "OLD"}},
        "uo": {},
    }
    merged = _meta.flavor_config(flavor, config)
    assert merged["u8"] == {
        "game": {"base": "B"},
        "paths": {"fixed": "F", "savegame": "S"},
    }
    assert config["u8"]["paths"]["savegame"] == "OLD"  # the user's config is untouched


def _u7(root: Path) -> Path:
    static = root / "STATIC"
    static.mkdir(parents=True)
    for name, records in {
        "SHAPES.VGA": [bytes(64)],
        "PALETTES.FLX": [bytes([20, 30, 40]) * 256],
        "TEXT.FLX": [b"test shape\0"],
        "ENDGAME.DAT": [b"x"],
    }.items():
        archive = U7FlexArchive()
        archive.records = records
        archive.save(str(static / name))
    return root


def test_u7_flavors_follow_the_engine_state_in_each_install(
    workspace, monkeypatch
) -> None:
    exult = _u7(workspace / "exult copy")
    (exult / "gamedat").mkdir()
    (exult / "gamedat" / "exult.ver").write_text("1.10")
    (exult / "exult00bg.sav").write_bytes(b"\0")
    dos = _u7(workspace / "dosbox copy")
    (dos / "GAMEDAT").mkdir()
    (dos / "GAMEDAT" / "GAMETIMA.DAT").write_bytes(b"\0")
    (dos / "GAME00.U7").write_bytes(b"\0")
    fresh = _u7(workspace / "fresh copy")
    config = {
        "u7bg": {
            "game": {"base": str(exult)},
            "paths": {"gamedat": str(exult / "gamedat")},
        },
        "search": {"folders": [str(dos), str(fresh)]},
    }
    flavors = {f.key: f for f in _meta.list_flavors("u7bg", config)}
    assert flavors["exult"].default and flavors["exult"].engine == "exult"
    assert flavors["exult"].args == {"game": "bg"}
    dos_key = f"folder:{dos.as_posix()}/dos"
    assert flavors[dos_key].engine == "dos" and not flavors[dos_key].default
    paths = _meta.flavor_config(flavors[dos_key], config)["u7bg"]["paths"]
    assert (
        Path(paths["gamedat"]).name.upper() == "GAMEDAT"
        and Path(paths["gamedat"]).parent == dos
    )
    assert [s.path.name for s in _meta.flavor_saves(flavors[dos_key], config)] == [
        "GAME00.U7"
    ]
    fresh_key = f"folder:{fresh.as_posix()}/install"
    assert flavors[fresh_key].kind == "install" and flavors[fresh_key].engine == ""


def test_u7_mods_sit_under_the_exult_flavor(workspace, monkeypatch) -> None:
    exult = _u7(workspace / "bg")
    (exult / "gamedat").mkdir()
    (exult / "gamedat" / "exult.ver").write_text("1.10")
    mods = [
        _meta.ModInfo("Keyring", "Keyring", "mod", True),
        _meta.ModInfo("straya", "Straya", "exult-game", False),
    ]
    monkeypatch.setattr("titan.u7.mods.list_mods", lambda config, game_id: mods)
    config = {
        "u7bg": {
            "game": {"base": str(exult)},
            "paths": {"gamedat": str(exult / "gamedat")},
        }
    }
    by_key = {f.key: f for f in _meta.list_flavors("u7bg", config)}
    assert by_key["mod:Keyring"].parent == "exult"
    assert by_key["mod:Keyring"].args == {"game": "bg", "mod": "Keyring"}
    assert by_key["exult-game:straya"].notes == ("Not played in Exult yet.",)


def _u8_save(path: Path, *, dos: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((U8SaveArchive.SIGNATURE if dos else b"PentagramSave") + bytes(40))


def test_u8_flavors_per_save_source_with_readability(workspace) -> None:
    base = workspace / "ULTIMA8"
    (base / "ENGLISH" / "STATIC").mkdir(parents=True)
    _u8_save(base / "cloud_saves" / "SAVEGAME" / "U8SAVE.001")
    _u8_save(workspace / "roaming" / "Pentagram" / "u8-save" / "U8SAVE.000", dos=False)
    scummvm = workspace / "roaming" / "ScummVM"
    scummvm.mkdir(parents=True)
    (scummvm / "scummvm.ini").write_text(
        f"[scummvm]\nsavepath={(workspace / 'svm').as_posix()}\n"
        "[ultima8]\ngameid=ultima8\ndescription=Ultima VIII: Pagan\n"
        "[monkey]\ngameid=monkey\n",
        encoding="utf-8",
    )
    _u8_save(workspace / "svm" / "ultima8.002", dos=False)
    config = {"u8": {"game": {"base": str(base), "language": "ENGLISH"}, "paths": {}}}

    flavors = {f.key: f for f in _meta.list_flavors("u8", config)}
    assert set(flavors) == {"dos", "pentagram", "scummvm:ultima8"}
    assert flavors["dos"].default and flavors["dos"].saves_readable
    assert not flavors["pentagram"].saves_readable
    assert "can't read" in flavors["pentagram"].notes[0]
    assert flavors["scummvm:ultima8"].title == "ScummVM (Ultima VIII: Pagan)"
    assert not flavors["scummvm:ultima8"].saves_readable
    assert [
        s.path.name for s in _meta.flavor_saves(flavors["scummvm:ultima8"], config)
    ] == ["ultima8.002"]
    pentagram = _meta.flavor_config(flavors["pentagram"], config)["u8"]["paths"][
        "savegame"
    ]
    assert Path(pentagram) == workspace / "roaming" / "Pentagram" / "u8-save"


def test_uo_flavors_are_the_named_clients(workspace) -> None:
    classic = workspace / "Classic"
    uof = workspace / "UOF"
    for folder in (classic, uof):
        folder.mkdir()
        (folder / "tiledata.mul").write_bytes(b"\0")
    config = {
        "uo": {
            "game": {"install": "classic"},
            "installs": {
                "classic": {"path": str(classic), "label": "EA Classic Client"},
                "uof": {"path": str(uof), "label": "UO Forever", "multis": "mul"},
            },
        }
    }
    classic_flavor, uof_flavor = _meta.list_flavors("uo", config)
    assert (
        classic_flavor.key,
        classic_flavor.default,
        dict(classic_flavor.config),
    ) == ("client:classic", True, {})
    assert (uof_flavor.title, uof_flavor.args) == ("UO Forever", {"client": "uof"})
    assert _meta.flavor_config(uof_flavor, config)["uo"]["game"]["install"] == "uof"
    assert uof_flavor.notes == ("Reads multis from mul, maps from auto.",)


def test_uo_lists_registry_clients_no_entry_names(workspace, monkeypatch) -> None:
    classic = workspace / "Classic"
    uof = workspace / "UOForever" / "UO"
    for folder in (classic, uof):
        folder.mkdir(parents=True)
        (folder / "tiledata.mul").write_bytes(b"\0")
    record = InstallSource("origin", "", "Ultima Online", uof, "uo-registry")
    monkeypatch.setattr(_stores, "store_records", lambda config=None: [record])
    config = {
        "uo": {
            "game": {"install": "classic"},
            "installs": {
                "classic": {"path": str(classic), "label": "EA Classic Client"}
            },
        }
    }
    keys = [(f.key, f.title, f.default) for f in _meta.list_flavors("uo", config)]
    assert keys == [
        ("client:classic", "EA Classic Client", True),
        (f"folder:{uof.as_posix()}", "Ultima Online", False),
    ]


def _map_files(folder: Path, *names: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"\0")
    return folder


def test_u7_maps_come_from_static_and_a_mods_own_folders(
    workspace, monkeypatch
) -> None:
    base = _u7(workspace / "SERPENT")
    _map_files(base / "gamedat", "exult.ver")  # Exult's game, so its mods are listed
    _map_files(base / "STATIC", "U7MAP", "U7CHUNKS")
    _map_files(base / "STATIC" / "map01", "U7IFIX00")
    _map_files(base / "STATIC" / "map7f")  # empty: not a map
    patch = _map_files(workspace / "mymod" / "patch" / "map02", "u7ifix00").parent
    mod = _meta.ModInfo("mymod", "My Mod", "mod", True, {"patch": patch})
    monkeypatch.setattr("titan.u7.mods.list_mods", lambda config, game_id: [mod])
    config = {
        "u7si": {
            "game": {"base": str(base)},
            "paths": {"static": "STATIC", "gamedat": str(base / "gamedat")},
        }
    }
    flavors = {f.key: f for f in _meta.list_flavors("u7si", config)}
    base_flavor = next(f for f in flavors.values() if f.kind != "mod")
    assert [(m.title, dict(m.args)) for m in _meta.list_maps(base_flavor, config)] == [
        ("Main world", {"map_num": "0"}),
        ("Map 01", {"map_num": "1"}),
    ]
    mod_maps = _meta.list_maps(flavors["mod:mymod"], config)
    assert [m.key for m in mod_maps] == ["0", "01", "02"]
    assert mod_maps[2].args == {
        "map_num": "2"
    }  # map-render --mod finds the mod's folder
    assert mod_maps[2].notes == (
        "New map from this mod",
    )  # the base game has no map 02
    assert _meta.map_command("u7si") == ("u7", "map-render")


def test_u7_mod_maps_say_what_the_mod_does_to_the_base_map(tmp_path) -> None:
    import struct

    from titan.u7.map_list import mod_map_note

    static = tmp_path / "STATIC"
    static.mkdir()
    layout = bytearray(144 * 256 * 2)  # every slot uses chunk 0, superchunk 0 chunk 1
    struct.pack_into("<H", layout, 0, 1)
    (static / "U7MAP").write_bytes(layout)
    base_chunks = struct.pack("<256H", *([5] * 256)) * 2  # 2-byte tiles: shape 5
    (static / "U7CHUNKS").write_bytes(base_chunks)

    edited = tmp_path / "edited"
    edited.mkdir()
    (edited / "u7map").write_bytes(layout)  # a copy of the base layout
    (edited / "u7ifix00").write_bytes(b"\0")
    (edited / "u7ifix01").write_bytes(b"\0")
    tile = bytes((5, 0, 0))  # Exult's 3-byte tiles: chunk 0 the same, chunk 1 changed
    exult = b"\xff\xff\xff\xffexlt\x00\x00" + tile * 256 + bytes((6, 0, 0)) * 256
    (edited / "u7chunks").write_bytes(exult)
    assert mod_map_note([edited], static, 0, "u7si") == (
        "Serpent Isle, edited by this mod: 2 superchunks of objects, 1 terrain chunk"
    )

    moved = tmp_path / "moved"
    moved.mkdir()
    changed = bytearray(layout)
    struct.pack_into("<H", changed, 512 * 3, 1)  # one superchunk laid out differently
    (moved / "U7MAP").write_bytes(changed)
    assert mod_map_note([moved], static, 0, "u7bg") == (
        "The Black Gate, edited by this mod: 1 superchunk of layout"
    )

    replaced = tmp_path / "replaced"
    replaced.mkdir()
    (replaced / "U7MAP").write_bytes(bytes([1, 0]) * (144 * 256))
    assert (
        mod_map_note([replaced], static, 0, "u7bg") == "Replaces The Black Gate's world"
    )
    assert mod_map_note([replaced], static, 4, "u7bg") == "New map from this mod"
    assert mod_map_note([tmp_path / "empty"], static, 0, "u7si") == (
        "Serpent Isle, unchanged by this mod"
    )


def _only_flavor(game_id: str, config: dict):
    flavors = _meta.list_flavors(game_id, config)
    assert flavors, f"{game_id}: no flavor for {config}"
    return flavors[0]


def test_u6_and_md_maps_are_the_surface_and_five_levels(workspace) -> None:
    u6 = workspace / "Ultima6"
    u6.mkdir()
    for name in ("U6PAL", "CHUNKS", "MAPTILES.VGA", "MAP"):
        (u6 / name).write_bytes(b"\0")
    config = {"u6": {"game": {"base": str(u6)}}}
    maps = _meta.list_maps(_only_flavor("u6", config), config)
    assert [(m.title, dict(m.args)) for m in maps[:2]] == [
        ("Surface", {"full": "true"}),
        ("Dungeon level 0", {"full": "false", "dungeon": "0"}),
    ]
    assert len(maps) == 6 and _meta.map_command("u6") == ("u6", "map-render")

    md = _martian(workspace / "md")
    config = {"md": {"game": {"base": str(md)}}}
    maps = _meta.list_maps(_only_flavor("md", config), config)
    assert [m.title for m in maps] == ["Surface"] + [
        f"Underground level {n}" for n in range(5)
    ]
    assert maps[3].args == {"full": "false", "dungeon": "2"}


def test_uw2_maps_are_the_populated_lev_ark_slots(workspace) -> None:
    import struct

    data = workspace / "UW2" / "DATA"
    data.mkdir(parents=True)
    for name in ("PALS.DAT", "T64.TR"):
        (data / name).write_bytes(b"\0")
    count = 320  # 80 level slots, then their texture, automap and notes blocks
    tables = [[0] * count for _ in range(4)]  # offsets, flags, sizes, available sizes
    for slot in (0, 9):  # Castle of Lord British, the Prison Tower basement
        tables[0][slot], tables[2][slot], tables[3][slot] = 6 + 16 * count, 4, 4
    ark = struct.pack("<HI", count, 0) + b"".join(
        struct.pack(f"<{count}I", *t) for t in tables
    )
    (data / "LEV.ARK").write_bytes(ark + bytes(4))
    config = {"uw2": {"game": {"base": str(data.parent)}}}
    maps = _meta.list_maps(_only_flavor("uw2", config), config)
    assert [(m.key, m.title, dict(m.args)) for m in maps] == [
        ("slot:0", "Britannia - Castle of Lord British", {"slots": "0"}),
        ("slot:9", "Prison Tower - First Floor", {"slots": "9"}),
    ]


def test_uo_maps_are_the_facets_the_client_ships(workspace) -> None:
    client = workspace / "Classic"
    client.mkdir()
    (client / "tiledata.mul").write_bytes(b"\0")
    for name in ("staidx0.mul", "staidx2.mul", "staidx7.mul", "statics0.mul"):
        (client / name).write_bytes(b"\0")
    config = {"uo": {"game": {"base": str(client)}}}
    maps = _meta.list_maps(_only_flavor("uo", config), config)
    assert [(m.title, dict(m.args)) for m in maps] == [
        ("Felucca", {"facet": "0"}),
        ("Ilshenar", {"facet": "2"}),
        ("Facet 7", {"facet": "7"}),
    ]
    assert _meta.map_command("uo") == ("uo", "map-export")  # the whole facet, no centre


def test_u8_maps_are_the_fixed_slots_with_items(workspace) -> None:
    from titan.flex import FlexArchive

    base = workspace / "ULTIMA8"
    static = base / "ENGLISH" / "STATIC"
    static.mkdir(parents=True)
    archive = FlexArchive()
    archive.records = [b""] * 256
    archive.records[3] = bytes(16)
    archive.records[40] = bytes(32)
    archive.save(str(static / "FIXED.DAT"))
    config = {"u8": {"game": {"base": str(base), "language": "ENGLISH"}, "paths": {}}}
    [flavor] = _meta.list_flavors("u8", config)
    maps = _meta.list_maps(flavor, config)
    assert [(m.title, dict(m.args)) for m in maps] == [
        ("Map 3", {"map_num": "3"}),
        ("Map 40", {"map_num": "40"}),
    ]


def test_u9_maps_are_the_terrain_regions(workspace) -> None:
    base = workspace / "Ultima IX"
    static = _map_files(base / "static", "terrain.0", "terrain.5", "fixed.5")
    flavor = _meta.Flavor("u9", "configured", "X", "install", default=True)
    config = {"u9": {"game": {"base": str(base)}, "paths": {"static": "static"}}}
    maps = _meta.list_maps(flavor, config)
    assert [m.key for m in maps] == ["region:0", "region:5"]
    assert maps[1].args == {
        "terrain": str(static / "terrain.5"),
        "fixed": str(static / "fixed.5"),
    }


def test_map_commands_take_every_map_argument() -> None:
    import typer.main

    from titan.cli import app

    root = typer.main.get_command(app)
    argument_names = {
        "u7bg": {"map_num", "mod"},
        "u8": {"map_num"},
        "u9": {"terrain", "fixed"},
    }
    for game in _meta.GAMES:
        command = _meta.map_command(game.id)
        if command is None:
            continue
        group, name = command
        params = {p.name for p in root.commands[group].commands[name].params}
        assert argument_names.get(game.id, set()) <= params, game.id
        assert set(_meta.map_options(game.id)) <= params, game.id
    assert _meta.has_maps("u7si") and not _meta.has_maps("u3nes")


def test_a_mods_map_folder_is_its_patch_first(tmp_path) -> None:
    from titan.u7.map_list import mod_map_root

    patch = _map_files(tmp_path / "patch" / "map01", "u7ifix00").parent
    static = _map_files(tmp_path / "static", "U7MAP")
    _map_files(static / "map01", "U7IFIX00")
    mod = _meta.ModInfo("m", "M", "mod", True, {"patch": patch, "static": static})
    assert (
        mod_map_root(mod, 1) == patch
    )  # both have map 01: the patch wins, as in Exult
    assert mod_map_root(mod, 0) == static  # only the static has a main world
    assert mod_map_root(mod, 2) is None  # the base game's
