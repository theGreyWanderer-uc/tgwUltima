"""Exercise the actual font and shape workflows through Questionary prompts."""

from functools import partial
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from titan.fonts import wizard as fonts
from titan.u7 import shape_wizard as shapes
from titan import _wizard_ui as ui
from titan.u7.cli import u7_app
from titan.u7.palette import U7Palette
from titan.u7.shape import U7Shape
from titan.u7 import container, eggs, target_picker
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.flex import U7FlexArchive
from titan.u7.map import U7MapObject


def scripted_menus(monkeypatch, answers):
    import questionary

    iterator = iter(answers)
    prompts = []

    def factory(message, **kwargs):
        prompts.append((message, kwargs))

        class Prompt:
            def ask(self):
                answer = next(iterator)
                return answer(kwargs) if callable(answer) else answer

        return Prompt()

    for name in ("select", "confirm", "path", "text", "checkbox"):
        monkeypatch.setattr(questionary, name, factory)
    monkeypatch.setattr(ui, "menus_enabled", lambda: True)
    monkeypatch.setattr(
        "builtins.input",
        lambda *args: pytest.fail("used plain input in a menu terminal"),
    )
    return prompts


@pytest.fixture(autouse=True)
def isolate_profile(monkeypatch, tmp_path):
    monkeypatch.setattr("titan._config.get_config", lambda: {})
    monkeypatch.setattr("titan.u7.target_picker.find_exult_cfg", lambda: None)
    monkeypatch.setattr("titan.u7.install.exult_game_paths", lambda game: {})
    monkeypatch.setattr(fonts, "find_exult_cfg", lambda: None)
    monkeypatch.setattr(shapes, "get_config", lambda: {})
    monkeypatch.setattr(shapes, "find_exult_cfg", lambda: None)
    monkeypatch.setattr(shapes, "_exult_paths", lambda game: None)
    monkeypatch.setattr(fonts, "open_preview", lambda path: True)
    monkeypatch.setattr(
        fonts.tempfile,
        "NamedTemporaryFile",
        partial(fonts.tempfile.NamedTemporaryFile, dir=tmp_path),
    )


def test_font_wizard_uses_named_menus_and_can_cancel_preview(tmp_path, monkeypatch):
    output = tmp_path / "font.shp"
    prompts = scripted_menus(
        monkeypatch,
        [
            "1",
            lambda kwargs: kwargs["choices"][0].value,
            "",
            "2",
            "1",
            "1",
            False,
            "0",
            "Q",
        ],
    )
    result = CliRunner().invoke(u7_app, ["font-create", "-o", str(output)])
    assert result.exit_code == 0, result.output
    choices = {message: options for message, options in prompts}
    assert [c.title for c in choices["Game flavour:"]["choices"]] == [
        "[1] Black Gate",
        "[2] Serpent Isle",
    ]
    assert "Hinted mono" in choices["Rendering method:"]["choices"][0].title
    assert "Looks good" in choices["Review the font preview:"]["choices"][0].title
    assert not output.exists()


def test_gradient_menu_displays_swatches_for_every_preset(monkeypatch):
    from titan.fonts.palette import list_gradient_presets, get_gradient_preset

    prompts = scripted_menus(monkeypatch, ["1", False, "1", "6"])
    fonts._step_hollow_gradient(fonts.WizardConfig())
    choices = prompts[0][1]["choices"]
    keys = list_gradient_presets()
    assert len(choices) == len(keys) + 1
    for choice, key in zip(choices, keys):
        preset = get_gradient_preset(key)
        assert isinstance(choice.title, list)
        assert choice.title[0][1].strip() == preset.name
        assert [
            style.removeprefix("bg:")
            for style, _ in choice.title
            if style.startswith("bg:")
        ] == preset.colors
        assert all("\x1b" not in text for _, text in choice.title)
    assert choices[-1].title == "[M] Manual palette indices"


def test_custom_font_preview_reprompts_and_returns_to_review_without_rerendering(
    tmp_path, monkeypatch
):
    output = tmp_path / "font.shp"
    prompts = scripted_menus(
        monkeypatch,
        [
            "1",
            lambda kwargs: kwargs["choices"][0].value,
            "",
            "2",
            "1",
            "1",
            False,
            "0",
            "C",
            "",
            "TOOLONG!!",
            "é",
            "CAPONE12",
            "C",
            "",
            "Q",
        ],
    )
    rendered, reviewed = [], []
    original_render, original_preview = fonts._render, fonts._mapped_preview

    def render(config):
        rendered.append(config)
        return original_render(config)

    def preview(*args, **kwargs):
        reviewed.append(kwargs.get("preview_text"))
        return original_preview(*args, **kwargs)

    monkeypatch.setattr(fonts, "_render", render)
    monkeypatch.setattr(fonts, "_mapped_preview", preview)
    result = CliRunner().invoke(u7_app, ["font-create", "-o", str(output)])
    assert result.exit_code == 0, result.output
    assert "1-8 printable characters" in result.output
    assert "not available in this font" in result.output
    assert "CAPONE12" in result.output
    assert len(rendered) == 1
    assert reviewed == [None, "CAPONE12", "CAPONE12"]
    review_prompts = [
        options for message, options in prompts if message == "Review the font preview:"
    ]
    assert len(review_prompts) == 3
    assert any(choice.value == "C" for choice in review_prompts[0]["choices"])
    assert not output.exists()


def test_shape_wizard_menu_flow_converts_and_saves(tmp_path, monkeypatch):
    source, output, palette = (
        tmp_path / "image.png",
        tmp_path / "image.shp",
        tmp_path / "palette.pal",
    )
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(source)
    palette.write_bytes(bytes(768))
    monkeypatch.setattr(
        shapes, "_palette", lambda config: U7Palette.from_file(str(palette))
    )
    monkeypatch.setattr(shapes, "_open_preview", lambda path: True)
    monkeypatch.setattr(
        shapes.tempfile,
        "NamedTemporaryFile",
        partial(shapes.tempfile.NamedTemporaryFile, dir=tmp_path),
    )
    prompts = scripted_menus(
        monkeypatch,
        [
            "2",
            lambda kwargs: kwargs["choices"][0].value,
            str(source),
            "",
            "0",
            False,
            "1",
            "0",
            "0",
            "Y",
            "1",
            str(output),
            True,
        ],
    )
    result = CliRunner().invoke(u7_app, ["shape-create"])
    assert result.exit_code == 0, result.output
    assert len(U7Shape.from_data(output.read_bytes(), strict=True).frames) == 1
    assert any(message == "Review the image preview:" for message, _ in prompts)
    assert any(message == "Output format:" for message, _ in prompts)


@pytest.mark.parametrize("palette_answers", [[""], ["0", ""]])
def test_shape_menu_accepts_automatic_custom_game_palette(
    tmp_path, monkeypatch, palette_answers
):
    root = tmp_path / "custom"
    static, patch = root / "static", root / "patch"
    static.mkdir(parents=True)
    patch.mkdir()
    palette = U7FlexArchive()
    palette.records = [bytes([10]) * 768]
    palette_path = static / "PALETTES.FLX"
    palette_path.write_bytes(palette.to_bytes())
    palette.records = [b""]
    (patch / "PALETTES.FLX").write_bytes(palette.to_bytes())
    target = ArchiveTarget("Custom SI game", static, patch, True, root)
    monkeypatch.setattr(shapes, "discover_targets", lambda *args: [target])
    monkeypatch.setattr(
        shapes,
        "resolve_game_palette",
        lambda *args: pytest.fail("used retail palette for a standalone game"),
    )
    source = tmp_path / "image.png"
    Image.new("RGBA", (8, 8), (40, 40, 40, 255)).save(source)
    reviewed = []
    monkeypatch.setattr(
        shapes, "show_preview", lambda converted, **kwargs: reviewed.append(converted)
    )
    prompts = scripted_menus(
        monkeypatch,
        ["2", target, str(source), *palette_answers, "0", False, "1", "0", "0", "Q"],
    )
    result = CliRunner().invoke(u7_app, ["shape-create"])
    assert result.exit_code == 0, result.output
    assert str(palette_path) in result.output
    assert len(reviewed) == 1
    assert reviewed[0].palette.source == str(palette_path)
    assert reviewed[0].palette.colors[1] == (40, 40, 40)
    file_prompts = [
        (message, kwargs)
        for message, kwargs in prompts
        if message.startswith("Palette file")
    ]
    assert len(file_prompts) == len(palette_answers)
    assert all(
        "Enter = automatic" in message and kwargs["default"] == ""
        for message, kwargs in file_prompts
    )
    if "0" in palette_answers:
        assert "record numbers such as 0 belong in the next prompt" in result.output


@pytest.mark.parametrize("wizard", [fonts.run_wizard, shapes.run_wizard])
def test_menu_cancel_is_clean_and_writes_nothing(monkeypatch, tmp_path, wizard):
    scripted_menus(monkeypatch, [None])
    assert wizard(output_override=str(tmp_path / "out.shp")) == 0
    assert not (tmp_path / "out.shp").exists()


def test_numeric_menu_prompt_retries_invalid_and_out_of_range(monkeypatch):
    prompts = scripted_menus(monkeypatch, ["oops", "300", "12"])
    assert shapes._integer("Palette record [0]:", 0, 0, 20) == 12
    assert len(prompts) == 3
    assert prompts[0][1]["default"] == "0"


@pytest.mark.parametrize("default, moved", [("bg", "si"), ("si", "bg")])
def test_real_menu_arrow_moves_highlight_and_preserves_initial_default(default, moved):
    import questionary
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from questionary.prompts.common import InquirerControl

    titles = {"bg": "Black Gate", "si": "Serpent Isle"}
    with create_pipe_input() as pipe:
        prompt = ui.select(
            "Game flavour:",
            choices=[
                questionary.Choice(title, value=value)
                for value, title in titles.items()
            ],
            default=default,
            input=pipe,
            output=DummyOutput(),
        )
        control = next(
            item
            for item in prompt.application.layout.find_all_controls()
            if isinstance(item, InquirerControl)
        )
        assert control.get_pointed_at().value == default
        assert (
            "class:highlighted",
            f"[{default[0].upper()}] {titles[default]}",
        ) in control._get_choice_tokens()
        pipe.send_text("\x1b[B\r")
        assert prompt.unsafe_ask() == moved
        tokens = control._get_choice_tokens()
        assert ("class:highlighted", f"[{moved[0].upper()}] {titles[moved]}") in tokens
        assert ("class:text", f"[{default[0].upper()}] {titles[default]}") in tokens
        assert not any(style == "class:selected" for style, _ in tokens)


def test_path_prompts_show_tab_hint_and_keep_default(monkeypatch, tmp_path):
    prompts = scripted_menus(monkeypatch, [str(tmp_path), str(tmp_path)])
    assert ui.path("PNG file or frame directory [enter path]:", str(tmp_path)) == str(
        tmp_path
    )
    assert ui.path_prompt("GAMEDAT directory:", only_directories=True).ask() == str(
        tmp_path
    )
    assert "Tab: show file/folder choices" in prompts[0][0]
    assert prompts[0][1]["default"] == str(tmp_path)
    assert "Tab: show folders" in prompts[1][0]
    assert prompts[1][1]["only_directories"] is True


@pytest.mark.parametrize(
    "key,expected", [("f", "F"), ("F", "F"), ("s", "S"), ("j", "J"), ("k", "K")]
)
def test_real_menu_hotkeys_act_without_enter_and_display_selected_action(key, expected):
    import questionary
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from questionary.prompts.common import InquirerControl

    with create_pipe_input() as pipe:
        prompt = ui.select(
            "Browse shape:",
            choices=[
                questionary.Choice(f"[{value}] {title}", value=value)
                for value, title in {
                    "F": "Next frame",
                    "S": "Different shape",
                    "J": "Next shape",
                    "K": "Previous shape",
                }.items()
            ],
            default="S",
            hotkeys={value: value for value in "FSJK"},
            input=pipe,
            output=DummyOutput(),
        )
        control = next(
            item
            for item in prompt.application.layout.find_all_controls()
            if isinstance(item, InquirerControl)
        )
        pipe.send_text(key)
        assert prompt.unsafe_ask() == expected
        assert control.get_pointed_at().value == expected
        assert control.is_answered


@pytest.mark.parametrize(
    "key,expected", [("n", "N"), ("N", "N"), ("b", "B"), ("s", "S")]
)
def test_paged_choice_actions_work_without_enter_with_long_numeric_ids(
    monkeypatch, key, expected
):
    import questionary
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    original_select = questionary.select
    monkeypatch.setattr(ui, "menus_enabled", lambda: True)
    with create_pipe_input() as pipe:
        monkeypatch.setattr(
            questionary,
            "select",
            lambda *args, **kwargs: original_select(
                *args, input=pipe, output=DummyOutput(), **kwargs
            ),
        )
        pipe.send_text(key)
        assert (
            ui.choice(
                "Choose NPC:",
                ["234", "235", "N", "B", "S"],
                "234",
                labels={
                    "234": "Devon",
                    "235": "Malchir",
                    "N": "Next page",
                    "B": "Previous page",
                    "S": "Search",
                },
            )
            == expected
        )


def test_long_numeric_ids_do_not_bind_the_first_digit_or_break_arrows(monkeypatch):
    import questionary
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    original_select = questionary.select
    monkeypatch.setattr(ui, "menus_enabled", lambda: True)
    with create_pipe_input() as pipe:
        monkeypatch.setattr(
            questionary,
            "select",
            lambda *args, **kwargs: original_select(
                *args, input=pipe, output=DummyOutput(), **kwargs
            ),
        )
        # '1' must not select ID 1 before someone finishes typing 15.
        pipe.send_text("1\x1b[B\r")
        assert ui.choice("Choose NPC:", ["1", "15", "N"], "1") == "15"


def test_short_numeric_menu_has_visible_immediate_keys(monkeypatch):
    import questionary
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from questionary.prompts.common import InquirerControl

    original_select = questionary.select
    captured = []
    monkeypatch.setattr(ui, "menus_enabled", lambda: True)
    with create_pipe_input() as pipe:

        def select(*args, **kwargs):
            prompt = original_select(*args, input=pipe, output=DummyOutput(), **kwargs)
            captured.append(prompt)
            return prompt

        monkeypatch.setattr(questionary, "select", select)
        pipe.send_text("2")
        assert (
            ui.choice(
                "Game:",
                ["1", "2"],
                "1",
                labels={"1": "Black Gate", "2": "Serpent Isle"},
            )
            == "2"
        )
    control = next(
        c
        for c in captured[0].application.layout.find_all_controls()
        if isinstance(c, InquirerControl)
    )
    assert control.get_pointed_at().title == "[2] Serpent Isle"


def test_shape_tokens_do_not_become_invalid_multicharacter_keys(monkeypatch):
    import questionary
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    original_select = questionary.select
    monkeypatch.setattr(ui, "menus_enabled", lambda: True)
    with create_pipe_input() as pipe:
        monkeypatch.setattr(
            questionary,
            "select",
            lambda *args, **kwargs: original_select(
                *args, input=pipe, output=DummyOutput(), **kwargs
            ),
        )
        pipe.send_text("n")
        assert ui.choice("Shapes:", ["S150", "S151", "N"], "S150") == "N"


def test_owner_selector_assigns_keys_without_mutating_choices():
    import questionary
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    owner = ArchiveTarget("Mod", None, Path("patch"))
    choices = [
        questionary.Choice("Mod", value=owner),
        questionary.Choice("Other world", value="manual"),
    ]
    with create_pipe_input() as pipe:
        prompt = ui.select("World:", choices=choices, input=pipe, output=DummyOutput())
        pipe.send_text("m")
        assert prompt.unsafe_ask() == "manual"
    assert choices[0].title == "Mod" and choices[1].title == "Other world"


def test_hotkey_menu_preserves_arrow_keys_and_enter():
    import questionary
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    with create_pipe_input() as pipe:
        prompt = ui.select(
            "Browse shape:",
            choices=[
                questionary.Choice("Next frame", value="F"),
                questionary.Choice("Different shape", value="S"),
            ],
            default="F",
            hotkeys={"F": "F", "S": "S"},
            input=pipe,
            output=DummyOutput(),
        )
        pipe.send_text("\x1b[B\r")
        assert prompt.unsafe_ask() == "S"


def test_formatted_menu_keeps_swatches_and_moves_name_highlight():
    import questionary
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from questionary.prompts.common import InquirerControl

    with create_pipe_input() as pipe:
        prompt = ui.select(
            "Gradient preset:",
            choices=[
                questionary.Choice(
                    fonts._swatch_fragments(
                        "Red", ["#ff0000"], label_style="class:choice-label"
                    ),
                    value="red",
                ),
                questionary.Choice(
                    fonts._swatch_fragments(
                        "Blue", ["#0000ff"], label_style="class:choice-label"
                    ),
                    value="blue",
                ),
            ],
            default="red",
            input=pipe,
            output=DummyOutput(),
        )
        control = next(
            item
            for item in prompt.application.layout.find_all_controls()
            if isinstance(item, InquirerControl)
        )
        assert ("class:choice-label class:highlighted", "Red") in control.text()
        pipe.send_text("\x1b[B\r")
        assert prompt.unsafe_ask() == "blue"
        tokens = control.text()
        assert ("class:choice-label class:highlighted", "Blue") in tokens
        assert ("class:choice-label class:text", "Red") in tokens
        assert ("bg:#ff0000", "  ") in tokens
        assert ("bg:#0000ff", "  ") in tokens


@pytest.fixture
def owned_world(tmp_path, monkeypatch):
    root = tmp_path / "custom"
    static, patch, gamedat = root / "STATIC", root / "patch", root / "gamedat"
    for path in (static, patch, gamedat / "MAP01"):
        path.mkdir(parents=True)
    (static / "TFA.DAT").write_bytes(bytes(3584))
    tfa = bytearray(3072)
    tfa[522 * 3 + 1] = 6
    (patch / "TFA.DAT").write_bytes(tfa)
    names = U7FlexArchive()
    names.records = [b""] * 523
    names.records[522] = b"custom chest\0"
    (patch / "TEXT.FLX").write_bytes(names.to_bytes())
    (gamedat / "MAP01/U7IREG00").write_bytes(b"dummy")
    target = ArchiveTarget("Custom game", static, patch, True, root, gamedat)
    monkeypatch.setattr(target_picker, "game_targets", lambda game: (target, [target]))
    parsed = []

    def parser(path, sc, flags):
        parsed.append(path)
        assert flags.get(522).shape_class == 6
        return [U7MapObject(1, 2, 0, 522, 0)]

    monkeypatch.setattr(container.U7MapRenderer, "parse_ireg_deep", parser)
    return target, parsed


def test_container_wizard_uses_selected_mod_metadata_gamedat_and_map(
    owned_world, monkeypatch, capsys
):
    target, parsed = owned_world
    scripted_menus(
        monkeypatch,
        ["si", target, str(target.gamedat), 1, "", "", "", "", True, "tree", False],
    )
    assert container.run_wizard() == 0
    assert parsed == [str(target.gamedat / "MAP01/U7IREG00")]
    assert "custom chest" in capsys.readouterr().out


def test_egg_wizard_uses_selected_mod_metadata_gamedat_and_map(
    owned_world, monkeypatch
):
    target, parsed = owned_world
    scripted_menus(
        monkeypatch,
        ["si", target, str(target.gamedat), 1, [], "", True, "table", False],
    )
    assert eggs.run_wizard() == 0
    assert parsed == [str(target.gamedat / "MAP01/U7IREG00")]


def test_u8_extraction_uses_default_no_confirmation(tmp_path, monkeypatch):
    from titan.u8.cli import _ensure_asset_dir

    prompts = scripted_menus(monkeypatch, [False])
    assert not _ensure_asset_dir(
        str(tmp_path / "shapes"), ".shp", "Shapes", "U8SHAPES.FLX"
    )
    assert prompts[0][1]["default"] is False
    assert not (tmp_path / "shapes").exists()
