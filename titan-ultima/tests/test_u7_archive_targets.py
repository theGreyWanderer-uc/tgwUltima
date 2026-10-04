"""Discover actual Exult archive owners independently of BG/SI flavour."""

import pytest

from titan.fonts.exult_cfg import ExultGamePaths
from titan.u7.archive_targets import (
    _read_config_xml,
    discover_targets,
    target_from_folder,
)


def test_mod_descriptions_macros_and_folder_discovery(tmp_path):
    static = tmp_path / "STATIC"
    mods = tmp_path / "mods"
    (mods / "pagan/patch").mkdir(parents=True)
    (mods / "other/patch").mkdir(parents=True)
    (mods / "pagan.cfg").write_bytes(
        b"<modinfo><display_string>Pagan\x00 Edition</display_string>"
        b"<patch>__MOD_PATH__/patch</patch></modinfo>"
    )
    (mods / "remapped.cfg").write_text(
        "<modinfo><mod_title>other</mod_title><display_string>Other Title</display_string>"
        "<patch>__MODS__/other/patch</patch></modinfo>"
    )
    (mods / "invalid.cfg").write_text("invalid XML")
    targets = discover_targets(
        "SI", {}, static, ExultGamePaths("SI", mods_path=str(mods)), None
    )
    assert [(target.name, target.patch) for target in targets] == [
        ("Other Title", mods / "other/patch"),
        ("Pagan Edition", mods / "pagan/patch"),
    ]
    assert all(target.static == static and not target.standalone for target in targets)


def test_titan_settings_and_custom_exult_game_paths(tmp_path):
    custom = tmp_path / "custom"
    custom.mkdir()
    cfg = tmp_path / "exult.cfg"
    cfg.write_text(
        f"<config><disk><game><serpentisle><path>{tmp_path}</path></serpentisle>"
        f"<mygame><path>{custom}</path><title> My SI Game </title>"
        "<static_path>assets</static_path><patch>edits</patch></mygame>"
        "<missing><path>missing</path></missing></game></disk></config>"
    )
    config = {
        "u7si": {
            "game": {"base": str(tmp_path)},
            "mods": {
                "configured": {"paths": {"patch": "mods/configured/patch"}},
                "runtime_only": {"paths": {"root": "SAVE/profile"}},
                "custom_library": {
                    "paths": {"static": "own/static", "patch": "own/patch"}
                },
            },
        }
    }
    targets = {
        target.name: target
        for target in discover_targets("SI", config, tmp_path / "STATIC", None, cfg)
    }
    assert set(targets) == {"configured", "custom_library", "My SI Game (Exult game)"}
    assert targets["configured"].patch == tmp_path / "mods/configured/patch"
    assert not targets["configured"].standalone
    assert targets["custom_library"].standalone
    assert targets["My SI Game (Exult game)"].static == custom / "assets"
    assert targets["My SI Game (Exult game)"].patch == custom / "edits"
    assert targets["My SI Game (Exult game)"].standalone


@pytest.mark.parametrize("own_static", [False, True])
@pytest.mark.parametrize("select_patch", [False, True])
def test_manual_target_root_or_patch(tmp_path, own_static, select_patch):
    root = tmp_path / "my-mod"
    (root / "patch").mkdir(parents=True)
    if own_static:
        (root / "STATIC").mkdir()
    retail = tmp_path / "retail/STATIC"
    target = target_from_folder(root / "patch" if select_patch else root, retail)
    assert target.name == "my-mod"
    assert target.static == (root / "STATIC" if own_static else retail)
    assert target.patch == root / "patch"
    assert target.standalone is own_static


def test_manual_missing_folder_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="folder not found"):
        target_from_folder(tmp_path / "missing", None)


def test_config_rejects_dtd_and_entity_expansion(tmp_path):
    cfg = tmp_path / "entities.cfg"
    cfg.write_text(
        '<!DOCTYPE modinfo [<!ENTITY title "bad">]><modinfo><display_string>&title;</display_string></modinfo>'
    )
    with pytest.raises(ValueError, match="must not contain a DTD"):
        _read_config_xml(cfg)


def test_mod_runtime_paths_follow_exult_savegame_macros(tmp_path):
    mods = tmp_path / "retail/mods"
    mods.mkdir(parents=True)
    (mods / "pagan.cfg").write_text(
        "<modinfo><gamedat_path>__MOD_PATH__/current</gamedat_path></modinfo>"
    )
    cfg = tmp_path / "exult.cfg"
    cfg.write_text(
        f"<config><disk><game><serpentisle><savegame_path>{tmp_path}/saves</savegame_path></serpentisle></game></disk></config>"
    )
    target = discover_targets(
        "SI",
        {},
        tmp_path / "retail/STATIC",
        ExultGamePaths("SI", mods_path=str(mods)),
        cfg,
    )[0]
    assert target.gamedat == tmp_path / "saves/mods/pagan/current"
    assert target.root == mods / "pagan"
