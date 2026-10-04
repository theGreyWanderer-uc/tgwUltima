"""Keep world owners, save data, map selection, and explicit paths together."""

from dataclasses import replace

import pytest
import questionary

from titan.u7 import target_picker as picker
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.world import WorldQueryParams


class Questions:
    Choice = questionary.Choice

    def __init__(self, answers):
        self.answers = iter(answers)
        self.prompts = []

    def select(self, message, **kwargs):
        self.prompts.append((message, kwargs))
        answer = next(self.answers)

        class Prompt:
            def ask(self):
                return answer

        return Prompt()

    path = text = select


@pytest.fixture
def targets(tmp_path, monkeypatch):
    retail, custom = tmp_path / "retail", tmp_path / "custom"
    for root in (retail, custom):
        for folder in ("STATIC", "patch", "gamedat"):
            (root / folder).mkdir(parents=True)
    (custom / "gamedat/MAP01").mkdir()
    base = ArchiveTarget(
        "Base SI game",
        retail / "STATIC",
        retail / "patch",
        root=retail,
        gamedat=retail / "gamedat",
    )
    own = ArchiveTarget(
        "Custom SI world",
        custom / "STATIC",
        custom / "patch",
        True,
        custom,
        custom / "gamedat",
    )
    monkeypatch.setattr(picker, "game_targets", lambda game: (base, [own]))
    return base, own


def test_switch_world_replaces_stale_names_and_save_data(targets):
    base, own = targets
    initial = WorldQueryParams(
        static_dir=str(base.static),
        gamedat_dir=str(base.gamedat),
        text_flx_path="old/TEXT.FLX",
        mod_data_dir="old/names",
        patch_dir=str(base.patch),
        output_path="old.csv",
    )
    q = Questions(["si", own, str(own.gamedat), 1])
    result = picker.select_world(q, initial, require_gamedat=True)
    assert result.game == "si"
    assert result.static_dir == result.base_static == str(own.static)
    assert result.gamedat_dir == str(own.gamedat)
    assert result.patch_dir == result.mod_data_dir == str(own.patch)
    assert result.map_num == 1
    assert result.text_flx_path is None and result.output_path is None
    assert initial.text_flx_path == "old/TEXT.FLX"


def test_mod_never_defaults_to_retail_gamedat(targets, monkeypatch, tmp_path):
    base, own = targets
    mod = replace(own, static=base.static, standalone=False, gamedat=None)
    monkeypatch.setattr(picker, "game_targets", lambda game: (base, [mod]))
    q = Questions(["si", mod, str(own.gamedat), 0])
    initial = WorldQueryParams(
        static_dir=str(base.static), gamedat_dir=str(base.gamedat)
    )
    result = picker.select_world(q, initial, require_gamedat=True)
    assert result.gamedat_dir == str(own.gamedat)
    assert q.prompts[2][1]["default"] == ""


def test_current_world_preserves_explicit_paths_and_map(targets):
    base, _ = targets
    initial = WorldQueryParams(
        static_dir=str(base.static),
        gamedat_dir=str(base.gamedat),
        text_flx_path="chosen/TEXT.FLX",
        map_num=3,
    )
    q = Questions(["si", "current", 3])
    result = picker.select_world(q, initial)
    assert result.text_flx_path == initial.text_flx_path
    assert result.gamedat_dir == initial.gamedat_dir
    assert result.map_num == 3


def test_manual_game_folder_uses_its_static_and_gamedat(targets):
    base, own = targets
    q = Questions(["si", "manual", str(own.root), 1])
    result = picker.select_world(q, WorldQueryParams(static_dir=str(base.static)))
    assert result.base_static == str(own.static)
    assert result.gamedat_dir == str(own.gamedat)
    assert result.map_num == 1


@pytest.mark.parametrize("stage", range(4))
def test_cancel_each_world_selection_stage(targets, stage):
    base, own = targets
    answers = ["si", own, str(own.gamedat), 1]
    q = Questions(answers[:stage] + [None])
    with pytest.raises(picker.SelectionCancelled):
        picker.select_world(
            q, WorldQueryParams(static_dir=str(base.static)), require_gamedat=True
        )


def test_map_picker_discovers_hex_and_uppercase_map_folders(tmp_path):
    for name in ("MAP01", "map0A", "mapZZ", "not_a_map"):
        (tmp_path / name).mkdir()
    q = Questions([10])
    assert picker.select_map(q, [str(tmp_path)], 3) == 10
    assert [choice.value for choice in q.prompts[0][1]["choices"]] == [
        0,
        1,
        3,
        10,
        "manual",
    ]


def test_manual_map_number_reprompts_invalid_values(tmp_path):
    q = Questions(["manual", "oops", "256", "0x0a"])
    assert picker.select_map(q, [str(tmp_path)]) == 10


def test_questionary_accepts_target_objects_as_defaults(targets):
    from prompt_toolkit.input import DummyInput
    from prompt_toolkit.output import DummyOutput

    base, _ = targets
    prompt = questionary.select(
        "World:",
        choices=[questionary.Choice(base.name, value=base)],
        default=base,
        input=DummyInput(),
        output=DummyOutput(),
    )
    assert prompt is not None
