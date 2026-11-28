"""U8 save folder config and ``--nonfixed`` slot/name/path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from titan.u8.install import (
    expand_u8_paths,
    prune_stale_u8_save_default,
    resolve_u8_save,
    u8_save_dir,
    u8_setup_lines,
)

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


def _section(base: Path, lang: str = "ENGLISH", **paths: str) -> dict:
    return expand_u8_paths(
        {"game": {"base": base.as_posix(), "language": lang}, "paths": dict(paths)}
    )


def test_savegame_expands_against_base(tmp_path: Path) -> None:
    section = _section(tmp_path, savegame="cloud_saves/SAVEGAME")
    assert Path(section["paths"]["savegame"]) == tmp_path / "cloud_saves" / "SAVEGAME"
    assert u8_save_dir(section) == tmp_path / "cloud_saves" / "SAVEGAME"


def test_absolute_savegame_is_kept(tmp_path: Path) -> None:
    engine = tmp_path / "Pentagram" / "u8-save"
    section = _section(tmp_path, savegame=engine.as_posix())
    assert u8_save_dir(section) == engine


def test_config_nonfixed_slot_and_name_resolve_in_save_folder(tmp_path: Path) -> None:
    saves = tmp_path / "saves"
    by_slot = _section(tmp_path, savegame=saves.as_posix(), nonfixed="3")
    by_name = _section(tmp_path, savegame=saves.as_posix(), nonfixed="U8SAVE.002")
    assert resolve_u8_save(None, by_slot) == saves / "U8SAVE.003"
    assert resolve_u8_save(None, by_name) == saves / "U8SAVE.002"


def test_old_setups_default_save_counts_only_when_it_exists(tmp_path: Path) -> None:
    saves = tmp_path / "saves"
    section = _section(tmp_path, savegame=saves.as_posix(), nonfixed="U8SAVE.000")
    assert (
        resolve_u8_save(None, section) is None
    )  # missing: the base world, as it meant
    saves.mkdir()
    (saves / "U8SAVE.000").write_bytes(b"")
    assert resolve_u8_save(None, section) == saves / "U8SAVE.000"
    assert resolve_u8_save("0", section) == saves / "U8SAVE.000"  # asked for: as given


def test_flag_wins_over_config_default(tmp_path: Path) -> None:
    saves = tmp_path / "saves"
    section = _section(tmp_path, savegame=saves.as_posix(), nonfixed="3")
    assert resolve_u8_save("1", section) == saves / "U8SAVE.001"
    assert resolve_u8_save("U8SAVE.004", section) == saves / "U8SAVE.004"


def test_no_flag_and_no_default_is_base_world(tmp_path: Path) -> None:
    section = _section(tmp_path, savegame="cloud_saves/SAVEGAME")
    assert resolve_u8_save(None, section) is None
    assert resolve_u8_save("", section) is None


def test_flag_paths_are_used_as_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    section = _section(tmp_path, savegame=(tmp_path / "saves").as_posix())
    absolute = tmp_path / "elsewhere" / "U8SAVE.009"
    assert resolve_u8_save(str(absolute), section) == absolute

    monkeypatch.chdir(tmp_path)
    (tmp_path / "NONFIXED.DAT").write_bytes(b"")
    assert resolve_u8_save("NONFIXED.DAT", section) == Path("NONFIXED.DAT")
    assert resolve_u8_save("sub/U8SAVE.000", section) == Path("sub/U8SAVE.000")


def test_missing_savegame_falls_back_to_nonfixed_folder_then_base(
    tmp_path: Path,
) -> None:
    engine = tmp_path / "engine"
    from_nonfixed = _section(tmp_path, nonfixed=(engine / "U8SAVE.000").as_posix())
    assert resolve_u8_save("2", from_nonfixed) == engine / "U8SAVE.002"

    gog = _section(tmp_path)
    assert resolve_u8_save("2", gog) == tmp_path / "cloud_saves" / "SAVEGAME" / (
        "U8SAVE.002"
    )
    flat = _section(tmp_path, lang="")
    assert resolve_u8_save("2", flat) == tmp_path / "U8SAVE.002"


def test_slot_without_any_save_folder_is_an_error() -> None:
    with pytest.raises(ValueError, match="save folder"):
        resolve_u8_save("3", {"paths": {}})


def test_setup_lines_write_save_folder_not_a_save(tmp_path: Path) -> None:
    usecode = tmp_path / "USECODE" / "EUSECODE.FLX"
    gog = tomllib.loads(
        "\n".join(u8_setup_lines("base", "ENGLISH", "cloud_saves/SAVEGAME", usecode))
    )
    assert gog["u8"]["paths"]["savegame"] == "cloud_saves/SAVEGAME"
    assert "nonfixed" not in gog["u8"]["paths"]

    flat = tomllib.loads("\n".join(u8_setup_lines("base", "", "", usecode)))
    assert "savegame" not in flat["u8"]["paths"]
    assert "nonfixed" not in flat["u8"]["paths"]


def _raw(base: Path, **paths: str) -> dict:
    return {
        "u8": {
            "game": {"base": base.as_posix(), "language": "ENGLISH"},
            "paths": dict(paths),
        }
    }


def test_prune_removes_only_missing_generated_default(tmp_path: Path) -> None:
    stale = _raw(tmp_path, nonfixed="U8SAVE.000")
    assert prune_stale_u8_save_default(stale) is True
    assert "nonfixed" not in stale["u8"]["paths"]

    saves = tmp_path / "cloud_saves" / "SAVEGAME"
    saves.mkdir(parents=True)
    (saves / "U8SAVE.000").write_bytes(b"")
    present = _raw(tmp_path, nonfixed="U8SAVE.000")
    assert prune_stale_u8_save_default(present) is False
    assert present["u8"]["paths"]["nonfixed"] == "U8SAVE.000"


@pytest.mark.parametrize("value", ["3", "U8SAVE.001", "/abs/U8SAVE.000"])
def test_prune_keeps_user_chosen_defaults(tmp_path: Path, value: str) -> None:
    data = _raw(tmp_path, nonfixed=value)
    assert prune_stale_u8_save_default(data) is False
    assert data["u8"]["paths"]["nonfixed"] == value


def test_prune_ignores_configs_without_u8_section() -> None:
    legacy = {"paths": {"nonfixed": "U8SAVE.000"}}
    assert prune_stale_u8_save_default(legacy) is False
    assert legacy["paths"]["nonfixed"] == "U8SAVE.000"
