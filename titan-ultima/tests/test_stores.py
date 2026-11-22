"""Store and launcher records (titan._stores) and what _meta makes of them."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from titan import _meta, _stores
from titan._meta import InstallSource

# conftest stubs the readers that look at this machine; keep the real ones here.
REAL = {
    name: getattr(_stores, name)
    for name in (
        "gog_registry_records",
        "steam_roots",
        "heroic_config_dirs",
        "lutris_databases",
    )
}


def test_parse_vdf_reads_both_library_formats_escapes_and_comments() -> None:
    new = _stores.parse_vdf(
        '"libraryfolders"\n{\n  "0"\n  {\n    "path"  "C:\\\\Program Files (x86)\\\\Steam"\n'
        '    "apps" { "3067560" "123" }\n  }\n  // a comment\n  "1" { "path" "D:\\\\SteamLibrary" }\n}\n'
    )
    folders = new["libraryfolders"]
    assert folders["0"]["path"] == "C:\\Program Files (x86)\\Steam"
    assert folders["0"]["apps"] == {"3067560": "123"}
    assert folders["1"]["path"] == "D:\\SteamLibrary"
    old = _stores.parse_vdf(
        '"LibraryFolders" { "TimeNextStatsReport" "1" "1" "E:\\\\Games" }'
    )
    assert old["LibraryFolders"]["1"] == "E:\\Games"


def _manifest(library: Path, appid: str, name: str, installdir: str) -> None:
    steamapps = library / "steamapps"
    steamapps.mkdir(parents=True, exist_ok=True)
    (steamapps / f"appmanifest_{appid}.acf").write_text(
        f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n'
        f'\t"installdir"\t\t"{installdir}"\n}}\n',
        encoding="utf-8",
    )


def test_steam_records_follow_every_library(tmp_path: Path) -> None:
    root, second = tmp_path / "Steam", tmp_path / "SteamLibrary"
    _manifest(root, "3067560", "Ultima™ IX: Ascension", "Ultima IX")
    _manifest(second, "999", "Some Other Game", "Other")
    (root / "steamapps/libraryfolders.vdf").write_text(
        '"libraryfolders" { "0" { "path" "%s" } "1" { "path" "%s" } }'
        % (str(root).replace("\\", "\\\\"), str(second).replace("\\", "\\\\")),
        encoding="utf-8",
    )
    records = _stores.steam_records([root])
    by_id = {record.store_id: record for record in records}
    assert set(by_id) == {"3067560", "999"}
    u9 = by_id["3067560"]
    assert u9.title == "Ultima™ IX: Ascension" and u9.found_by == "steam-manifest"
    assert u9.path == root / "steamapps" / "common" / "Ultima IX"
    assert by_id["999"].path == second / "steamapps" / "common" / "Other"
    assert _stores.matches("u9", u9) and not _stores.matches("u9", by_id["999"])


def test_heroic_records_use_library_titles_and_gog_info(tmp_path: Path) -> None:
    store = tmp_path / "heroic/gog_store"
    store.mkdir(parents=True)
    u7 = tmp_path / "Games/Ultima 7"
    u7.mkdir(parents=True)
    (u7 / "goggame-1207658910.info").write_text(
        json.dumps({"gameId": "1207658910", "name": "Ultima™ 7: The Complete Edition"}),
        encoding="utf-8",
    )
    uw = tmp_path / "Games/UW"
    (store / "installed.json").write_text(
        json.dumps(
            {
                "installed": [
                    {
                        "appName": "1207658910",
                        "install_path": str(u7),
                        "platform": "windows",
                    },
                    {
                        "appName": "1207661093",
                        "install_path": str(uw),
                        "platform": "windows",
                    },
                    {"appName": "broken"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (store / "library.json").write_text(
        json.dumps(
            {"games": [{"app_name": "1207661093", "title": "Ultima Underworld 1+2"}]}
        ),
        encoding="utf-8",
    )
    records = {r.store_id: r for r in _stores.heroic_records([tmp_path / "heroic"])}
    assert set(records) == {"1207658910", "1207661093"}
    assert records["1207658910"].title == "Ultima™ 7: The Complete Edition"
    assert records["1207661093"].title == "Ultima Underworld 1+2"
    assert records["1207661093"].found_by == "heroic-manifest"
    assert records["1207661093"].label == "GOG (Heroic)"
    for game in ("u7bg", "u7si"):
        assert _stores.matches(game, records["1207658910"])
    for game in ("uw1", "uw2"):
        assert _stores.matches(game, records["1207661093"])


def test_lutris_records_read_installed_games_read_only(tmp_path: Path) -> None:
    database = tmp_path / "pga.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE games (name TEXT, slug TEXT, directory TEXT, installed INTEGER,"
            " service TEXT, service_id TEXT)"
        )
        connection.executemany(
            "INSERT INTO games VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("Ultima VIII: Pagan", "ultima-8", "/games/u8", 1, "gog", "1207658904"),
                ("Old Game", "old", "/games/old", 0, "", ""),
            ],
        )
    connection.close()
    records = _stores.lutris_records([database])
    assert [(r.store, r.store_id, r.title, r.found_by) for r in records] == [
        ("gog", "1207658904", "Ultima VIII: Pagan", "lutris-db")
    ]
    assert records[0].label == "GOG (Lutris)"
    assert _stores.lutris_records([tmp_path / "missing.db"]) == []


def test_gog_registry_records_prefer_the_games_own_info(tmp_path, monkeypatch) -> None:
    folder = tmp_path / "GOG Galaxy/Games/Ultima 8"
    folder.mkdir(parents=True)
    (folder / "goggame-1207658904.info").write_text(
        json.dumps({"gameId": "1207658904", "name": "Ultima™ 8 Gold Edition"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(_stores, "_registry_subkeys", lambda path: ["1207658904"])
    monkeypatch.setattr(
        _stores,
        "_registry_values",
        lambda path: (
            [{"path": str(folder), "gameName": "Ultima 8", "gameID": "1207658904"}]
            if path.endswith("1207658904")
            else []
        ),
    )
    [record] = REAL["gog_registry_records"]()
    assert (record.store, record.store_id, record.found_by) == (
        "gog",
        "1207658904",
        "gog-registry",
    )
    assert record.title == "Ultima™ 8 Gold Edition" and record.path == folder
    assert record.label == "GOG" and _stores.matches("u8", record)


def test_every_game_with_installs_is_in_the_catalogue() -> None:
    games = {game.id for game in _meta.GAMES if _meta.has_install_support(game.id)}
    assert games == set(_stores.CATALOGUE)


@pytest.mark.parametrize(
    "title, games",
    [
        ("Ultima™ IX: Ascension", {"u9"}),
        ("Ultima VII Part Two: Serpent Isle", {"u7si"}),
        ("Ultima VII: The Black Gate", {"u7bg"}),
        ("Ultima™ 7: The Complete Edition", {"u7bg", "u7si"}),
        ("Ultima Underworld 1+2", {"uw1", "uw2"}),
        ("Ultima Underworld: The Stygian Abyss", {"uw1"}),
        ("Ultima Underworld II: Labyrinth of Worlds", {"uw2"}),
        ("Ultima™ 6: The False Prophet", {"u6"}),
        ("Worlds of Ultima: Martian Dreams", {"md"}),
        ("Ultima™ 8 Gold Edition", {"u8"}),
        ("Ultima Online", {"uo"}),
        ("Pagan Online", set()),
        ("Ascension Saga", set()),
    ],
)
def test_catalogue_titles(title: str, games: set[str]) -> None:
    record = InstallSource("gog", "", title, Path("Z:/nowhere/x"), "gog-registry")
    assert {
        game for game in _stores.CATALOGUE if _stores.matches(game, record)
    } == games


def _martian(folder: Path) -> Path:
    data = folder / "MARTIAN"
    data.mkdir(parents=True)
    for name in ("MDPAL", "CHUNKS", "MAPTILES.VGA", "MAP"):
        (data / name).write_bytes(b"\0")
    return data


def test_store_installs_report_verified_registered_and_missing(
    tmp_path, monkeypatch
) -> None:
    good = tmp_path / "steamapps/common/Martian Dreams"
    _martian(good)
    empty = tmp_path / "GOG Games/Martian Dreams"
    empty.mkdir(parents=True)
    records = [
        InstallSource(
            "steam", "1", "Worlds of Ultima: Martian Dreams", good, "steam-manifest"
        ),
        InstallSource("gog", "2", "Martian Dreams", empty, "gog-registry"),
        InstallSource("gog", "3", "Martian Dreams", tmp_path / "gone", "gog-registry"),
        InstallSource("folder", "", "stuff", empty, "search-folder"),
        InstallSource("steam", "4", "Something Else", tmp_path, "steam-manifest"),
    ]
    monkeypatch.setattr(_stores, "store_records", lambda config=None: records)

    found = {(s.source.store_id, s.status) for s in _meta.store_installs("md", {})}
    assert found == {("1", "verified"), ("2", "registered"), ("3", "missing")}
    verified = next(s for s in _meta.store_installs("md", {}) if s.status == "verified")
    assert verified.install is not None and verified.install.source.label == "Steam"

    installs = _meta.find_installs("md", {})
    from_steam = [i for i in installs if i.source is not None]
    assert [i.source.store_id for i in from_steam] == ["1"]
    assert good in from_steam[0].root.parents or from_steam[0].root == good / "MARTIAN"


def test_search_folders_list_each_child_for_every_game(tmp_path) -> None:
    (tmp_path / "Old/U7").mkdir(parents=True)
    (tmp_path / "Old/Misc").mkdir()
    records = _stores.search_folder_records(
        {"search": {"folders": [str(tmp_path / "Old")]}}
    )
    names = sorted(r.path.name for r in records)
    assert names == ["Misc", "Old", "U7"]
    assert all(r.store == "folder" and _stores.matches("u8", r) for r in records)


def test_readers_ignore_missing_launchers(tmp_path) -> None:
    assert _stores.steam_records([tmp_path / "no-steam"]) == []
    assert _stores.heroic_records([tmp_path / "no-heroic"]) == []
    assert (
        _stores.search_folder_records({"search": {"folders": [str(tmp_path / "nope")]}})
        == []
    )


def _fake_registry(monkeypatch, tree: dict) -> None:
    """Serve registry keys from *tree*: ``{path: {"keys": [...], "values": {...}}}``."""
    monkeypatch.setattr(
        _stores, "_registry_subkeys", lambda path: tree.get(path, {}).get("keys", [])
    )
    monkeypatch.setattr(
        _stores,
        "_registry_values",
        lambda path: [tree[path]["values"]] if tree.get(path, {}).get("values") else [],
    )


def test_ea_uo_and_uninstall_registry_records(tmp_path, monkeypatch) -> None:
    ea, uof, gog = tmp_path / "EA UO", tmp_path / "UOForever/UO", tmp_path / "GOG U6"
    uninstall = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    _fake_registry(
        monkeypatch,
        {
            r"SOFTWARE\Electronic Arts\EA Games": {"keys": ["Ultima Online Classic"]},
            r"SOFTWARE\Electronic Arts\EA Games\Ultima Online Classic": {
                "values": {"InstallDir": str(ea), "GameExecutionPath": "UO.exe"}
            },
            r"SOFTWARE\Origin Worlds Online": {"keys": ["Ultima Online"]},
            r"SOFTWARE\Origin Worlds Online\Ultima Online": {"keys": ["1.0"]},
            r"SOFTWARE\Origin Worlds Online\Ultima Online\1.0": {
                "values": {"ExePath": str(uof / "client.exe")}
            },
            uninstall: {"keys": ["GOG U6", "Icon only", "Nameless"]},
            uninstall + r"\GOG U6": {
                "values": {"DisplayName": "Ultima™ 6", "InstallLocation": str(gog)}
            },
            uninstall + r"\Icon only": {
                "values": {
                    "DisplayName": "Ultima Online Classic Client",
                    "DisplayIcon": f'"{ea / "UO.exe"}",0',
                }
            },
            uninstall + r"\Nameless": {"values": {"InstallLocation": str(tmp_path)}},
        },
    )
    [ea_record] = _stores.ea_records()
    assert (ea_record.store, ea_record.title, ea_record.path) == (
        "ea",
        "Ultima Online Classic",
        ea,
    )
    [uo_record] = _stores.uo_registry_records()
    assert (uo_record.store, uo_record.path, uo_record.found_by) == (
        "origin",
        uof,
        "uo-registry",
    )
    records = {r.store_id: r for r in _stores.uninstall_records()}
    assert set(records) == {"GOG U6", "Icon only"}
    assert records["GOG U6"].path == gog and _stores.matches("u6", records["GOG U6"])
    assert records["Icon only"].path == ea  # the icon's folder
    for record in (ea_record, uo_record, records["Icon only"]):
        assert _stores.matches("uo", record)


@pytest.mark.parametrize(
    "value, folder",
    [
        (r'"C:\Games\UO\uninst.exe" /S', r"C:\Games\UO"),
        (r"C:\Games\UO\UO.exe,0", r"C:\Games\UO"),
        (r"C:\Program Files\X\unins000.exe /SILENT", r"C:\Program Files\X"),
        ("", None),
    ],
)
def test_exe_folder_reads_registry_command_values(value, folder) -> None:
    result = _stores._exe_folder(value)
    assert (str(result) if result else None) == (str(Path(folder)) if folder else None)
