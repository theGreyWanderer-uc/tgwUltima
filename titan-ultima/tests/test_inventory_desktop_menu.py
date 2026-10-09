"""Actual Questionary arrows/hotkeys preserve browser identities and labels."""

import pytest
import questionary
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from titan import _wizard_ui as ui
from titan._inventory_browser import inventory_menu, InventoryBrowser
from titan.u7.container_browser import parse_u7_inventory_id


@pytest.fixture
def desktop_prompt(monkeypatch):
    original = questionary.select
    monkeypatch.setattr(ui, "menus_enabled", lambda: True)
    prompts = []
    with create_pipe_input() as pipe:

        def select(*args, **kwargs):
            prompts.append(kwargs)
            return original(*args, input=pipe, output=DummyOutput(), **kwargs)

        monkeypatch.setattr(questionary, "select", select)
        yield pipe, prompts


def test_arrow_selection_returns_exact_ireg_id_and_friendly_title(desktop_prompt):
    pipe, prompts = desktop_prompt
    key = "IREG:0:5:24:root"
    label = "Locked chest; map 0; 4 direct / 4 total"
    # Q starts selected; up + Enter opens the inventory through Questionary.
    pipe.send_text("\x1b[A\r")
    assert inventory_menu("Choose container:", {key: label, "Q": "Quit"}, "Q") == key
    assert prompts[0]["choices"][0].title == label
    assert prompts[0]["choices"][0].value == key


@pytest.mark.parametrize("key", ["b", "B"])
def test_inventory_hotkeys_still_work_without_enter(desktop_prompt, key):
    pipe, _ = desktop_prompt
    pipe.send_text(key)
    assert (
        inventory_menu(
            "Inventory:", {"IREG:0:5:24:0": "Coins", "B": "Back"}, "IREG:0:5:24:0"
        )
        == "B"
    )


def test_lowercase_filter_tokens_keep_their_value_and_label(desktop_prompt):
    pipe, prompts = desktop_prompt
    pipe.send_text("\x1b[B\r")
    assert (
        inventory_menu(
            "Kind:",
            {"all": "All inventories", "npc": "NPC inventories", "B": "Back"},
            "all",
        )
        == "npc"
    )
    assert prompts[0]["choices"][1].title == "NPC inventories"


def test_legacy_single_key_aliases_collapse_and_lowercase_default_works(desktop_prompt):
    pipe, prompts = desktop_prompt
    pipe.send_text("\r")
    assert ui.choice("> ", ["1", "m", "M"], "m", labels={"M": "Manual"}) == "M"
    assert len(prompts[0]["choices"]) == 2
    assert prompts[0]["choices"][1].title == "[M] Manual"


def test_real_desktop_browser_selection_enters_inventory_then_returns(
    desktop_prompt, capsys
):
    pipe, _ = desktop_prompt
    key = "IREG:0:4:10:root"
    item = {
        "item_id": key,
        "shape": 400,
        "frame": 0,
        "shape_name": "Corpse",
        "child_count": 0,
    }
    browser = InventoryBrowser(
        "U7",
        {key: item},
        {},
        [key],
        lambda *a: None,
        lambda key: {},
        lambda *a: None,
        parse_u7_inventory_id,
    )
    # Default Q is six entries below the first inventory in the results list.
    pipe.send_text("\x1b[A" * 6 + "\r" + "b" + "q")
    browser.browse()
    output = capsys.readouterr().out
    assert f"Corpse [{key}]" in output
    assert "View/export unavailable" not in output


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("IREG:0:5:24:ROOT", "IREG:0:5:24:root"),
        (" ireg:0:4:10:root ", "IREG:0:4:10:root"),
        ("ireg:0:4:10:0.2", "IREG:0:4:10:0.2"),
    ],
)
def test_pasted_uppercase_or_lowercase_u7_ids_resolve(raw, expected):
    assert parse_u7_inventory_id(raw) == expected


def test_redirected_input_returns_canonical_id_and_case_insensitive_action(monkeypatch):
    monkeypatch.setattr(ui, "menus_enabled", lambda: False)
    answers = iter(["IREG:0:5:24:ROOT", "q"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    choices = ["IREG:0:5:24:root", "Q"]
    assert ui.choice("> ", choices) == choices[0]
    assert ui.choice("> ", choices) == "Q"
